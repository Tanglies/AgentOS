"""本地文件与命令工具，让 Agent 具备编码助手式的工作能力。

工具清单：

- :class:`ListDirectoryTool` —— 列出目录内容
- :class:`ReadFileTool` —— 读取文本文件
- :class:`SearchTextTool` —— 按正则在工作区内搜索
- :class:`WriteFileTool` —— 写入文本文件（可关闭）
- :class:`RunCommandTool` —— 执行 shell 命令（**默认关闭**）

安全边界：

- 文件类工具全部走 :class:`~agentos.runtime.sandbox.WorkspaceSandbox`，
  路径越界与敏感文件（``.env`` / 私钥 / API Key）会被拒绝
- 读取与搜索都有字节数/条数上限，避免把上下文撑爆
- ``run_command`` 执行真实 shell，**不受沙箱约束**（命令内部可访问任意路径），
  因此默认关闭，必须通过 ``AGENTOS_TOOLS__ALLOW_SHELL=true`` 显式开启
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

from agentos.core.config import ToolsSettings
from agentos.runtime.sandbox import SensitiveFileError, WorkspaceSandbox
from agentos.runtime.tools import Tool, truncate_text

# 搜索时跳过的目录，避免把依赖与缓存噪声带进上下文。
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
    }
)

_MAX_MATCHES = 200
_MAX_SCAN_FILES = 2000
_MAX_WRITE_BYTES = 1_048_576
_MAX_LINE_CHARS = 200


class _SandboxedTool(Tool):
    """持有沙箱与配置的本地工具基类。"""

    def __init__(self, sandbox: WorkspaceSandbox, settings: ToolsSettings) -> None:
        self._sandbox = sandbox
        self._settings = settings


class ListDirectoryTool(_SandboxedTool):
    """列出目录内容（不递归）。"""

    name = "list_directory"
    description = "列出工作区内某个目录下的文件与子目录（不递归）。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的路径，默认为 ."}
        },
    }

    async def run(self, path: str = ".") -> str:
        target = self._sandbox.resolve(path)
        if not target.exists():
            return f"路径不存在：{path}"
        if not target.is_dir():
            return f"不是目录：{path}（读取文件请用 read_file）"

        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        if not entries:
            return f"{self._sandbox.relative(target)} 是空目录"

        lines: list[str] = []
        for entry in entries:
            try:
                if entry.is_dir():
                    lines.append(f"{entry.name}/")
                else:
                    lines.append(f"{entry.name}  ({entry.stat().st_size} B)")
            except OSError:
                continue

        header = f"{self._sandbox.relative(target)} （{len(lines)} 项）"
        return truncate_text("\n".join([header, *lines]), self._settings.max_output_chars)


class ReadFileTool(_SandboxedTool):
    """读取文本文件。"""

    name = "read_file"
    description = "读取工作区内文本文件的内容，超过大小上限会截断。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"}
        },
        "required": ["path"],
    }

    async def run(self, path: str) -> str:
        target = self._sandbox.resolve(path)
        self._sandbox.check_sensitive(target)

        if not target.exists():
            return f"文件不存在：{path}"
        if not target.is_file():
            return f"不是文件：{path}（列出目录请用 list_directory）"

        size = target.stat().st_size
        limit = self._settings.max_read_bytes
        raw = target.read_bytes()[:limit]
        if b"\x00" in raw[:4096]:
            return f"{path} 看起来是二进制文件（{size} B），已跳过"

        text = raw.decode("utf-8", errors="replace")
        if size > limit:
            text += f"\n... [文件共 {size} 字节，已截断到前 {limit} 字节]"
        return truncate_text(text, self._settings.max_output_chars)


class SearchTextTool(_SandboxedTool):
    """在工作区内按正则搜索文本。"""

    name = "search_text"
    description = "在工作区目录内按正则搜索文本，返回 文件:行号:内容。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式，例如 ToolRegistry"},
            "path": {"type": "string", "description": "搜索起始路径，默认为 ."},
            "glob": {"type": "string", "description": "文件名通配符，例如 *.py"},
        },
        "required": ["pattern"],
    }

    def _iter_files(self, target: Path, pattern: str | None) -> Iterator[Path]:
        if target.is_file():
            yield target
            return
        scanned = 0
        for candidate in target.rglob(pattern or "*"):
            if not candidate.is_file():
                continue
            parts = candidate.relative_to(self._sandbox.root).parts
            if any(part.lower() in _SKIP_DIRS for part in parts):
                continue
            scanned += 1
            if scanned > _MAX_SCAN_FILES:
                return
            yield candidate

    async def run(self, pattern: str, path: str = ".", glob: str | None = None) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"正则表达式无效：{exc}"

        target = self._sandbox.resolve(path)
        if not target.exists():
            return f"路径不存在：{path}"

        matches: list[str] = []
        limit = self._settings.max_read_bytes
        for candidate in self._iter_files(target, glob):
            if len(matches) >= _MAX_MATCHES:
                break
            # 敏感文件在搜索时静默跳过，而不是让整次搜索失败
            try:
                self._sandbox.check_sensitive(candidate)
            except SensitiveFileError:
                continue
            try:
                if candidate.stat().st_size > limit:
                    continue
                raw = candidate.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:4096]:
                continue

            rel = self._sandbox.relative(candidate)
            for lineno, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()[:_MAX_LINE_CHARS]}")
                    if len(matches) >= _MAX_MATCHES:
                        break

        if not matches:
            return f"未找到匹配：{pattern}"

        header = f"共 {len(matches)} 条匹配（最多返回 {_MAX_MATCHES} 条）"
        return truncate_text("\n".join([header, *matches]), self._settings.max_output_chars)


class WriteFileTool(_SandboxedTool):
    """写入文本文件。"""

    name = "write_file"
    description = (
        "在工作区内写入文本文件。创建新文件可直接写入；"
        "覆盖已存在的文件必须显式传入 overwrite=true。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
            "content": {"type": "string", "description": "要写入的完整文本内容"},
            "overwrite": {
                "type": "boolean",
                "description": "是否允许覆盖已存在的文件，默认为 false",
            },
        },
        "required": ["path", "content"],
    }

    async def run(self, path: str, content: str, overwrite: bool = False) -> str:
        target = self._sandbox.resolve(path)
        self._sandbox.check_sensitive(target)

        if target.exists() and target.is_dir():
            return f"路径是目录，无法写入：{path}"

        payload = content.encode("utf-8")
        if len(payload) > _MAX_WRITE_BYTES:
            return f"内容过大（{len(payload)} 字节），上限为 {_MAX_WRITE_BYTES} 字节"

        if target.exists() and not overwrite:
            return (
                f"文件已存在：{path}（{target.stat().st_size} B）。"
                "如需覆盖，请显式传入 overwrite=true。"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        action = "已覆盖" if overwrite else "已写入"
        return f"{action} {path}（{len(payload)} 字节）"


class RunCommandTool(_SandboxedTool):
    """在工作区目录下执行 shell 命令。

    该工具默认关闭。开启后执行的命令**不受沙箱约束**，
    命令内部可以读写文件系统任意位置，请只在受信任环境使用。
    """

    name = "run_command"
    description = (
        "在工作区目录下执行 shell 命令并返回 stdout/stderr。"
        "适合运行测试、构建、git 等命令。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout_seconds": {
                "type": "number",
                "description": "超时秒数，默认取服务端配置，最大 600",
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, timeout_seconds: float | None = None) -> str:
        configured = self._settings.shell_timeout_seconds
        timeout = min(timeout_seconds or configured, 600.0)

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                cwd=str(self._sandbox.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"命令超时（>{timeout:g}s）已被终止：{command}"
        except OSError as exc:
            return f"命令无法执行：{exc}"

        chunks: list[str] = []
        if completed.stdout:
            chunks.append(completed.stdout.rstrip())
        if completed.stderr:
            chunks.append(f"[stderr]\n{completed.stderr.rstrip()}")
        body = "\n".join(chunks) if chunks else "(无输出)"
        return truncate_text(
            f"[exit={completed.returncode}]\n{body}", self._settings.max_output_chars
        )


def create_local_tools(
    settings: ToolsSettings, sandbox: WorkspaceSandbox | None = None
) -> list[Tool]:
    """按配置创建本地工具。

    ``write_file`` 与 ``run_command`` 仅在对应开关打开时才会注册，
    未启用的能力不会出现在暴露给模型的工具列表里。
    """
    resolved_sandbox = sandbox or WorkspaceSandbox(settings.workspace_root)
    tools: list[Tool] = [
        ListDirectoryTool(resolved_sandbox, settings),
        ReadFileTool(resolved_sandbox, settings),
        SearchTextTool(resolved_sandbox, settings),
    ]
    if settings.allow_file_write:
        tools.append(WriteFileTool(resolved_sandbox, settings))
    if settings.allow_shell:
        tools.append(RunCommandTool(resolved_sandbox, settings))
    return tools
