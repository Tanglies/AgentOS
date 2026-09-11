"""本地文件与命令工具测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentos.core.config import ToolsSettings
from agentos.llm.base import ToolCall
from agentos.runtime import (
    SandboxViolation,
    SensitiveFileError,
    Tool,
    ToolRegistry,
    WorkspaceSandbox,
    create_local_tools,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """构造一个含常见文件类型的工作区。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "token.txt").write_text("SECRET_TOKEN=abc\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_TOKEN=abc\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings(workspace: Path) -> ToolsSettings:
    return ToolsSettings(workspace_root=str(workspace), max_output_chars=500)


def _tool(settings: ToolsSettings, name: str) -> Tool:
    return next(tool for tool in create_local_tools(settings) if tool.name == name)


# --- 沙箱 -----------------------------------------------------------------


def test_sandbox_resolves_path_inside_workspace(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    assert sandbox.resolve("src/main.py") == (workspace / "src" / "main.py").resolve()
    assert sandbox.relative(sandbox.resolve("src/main.py")) == "src/main.py"


def test_sandbox_rejects_parent_escape(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    with pytest.raises(SandboxViolation) as excinfo:
        sandbox.resolve("../outside.txt")

    assert excinfo.value.code == "sandbox_violation"


def test_sandbox_rejects_absolute_path_outside(
    workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside")
    sandbox = WorkspaceSandbox(workspace)

    with pytest.raises(SandboxViolation):
        sandbox.resolve(outside / "x.txt")


def test_sandbox_allows_dot_segments_that_stay_inside(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    assert sandbox.resolve("src/../README.md") == (workspace / "README.md").resolve()


def test_sandbox_blocks_env_file(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    with pytest.raises(SensitiveFileError):
        sandbox.check_sensitive(sandbox.resolve(".env"))


def test_sandbox_allows_env_example(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    # 不抛异常即通过
    sandbox.check_sensitive(sandbox.resolve(".env.example"))


def test_sandbox_blocks_sensitive_directory(workspace: Path) -> None:
    sandbox = WorkspaceSandbox(workspace)

    with pytest.raises(SensitiveFileError):
        sandbox.check_sensitive(sandbox.resolve("secrets/token.txt"))


def test_sandbox_blocks_api_key_like_filename(workspace: Path) -> None:
    (workspace / "apiKey-123.csv").write_text("k\n", encoding="utf-8")
    sandbox = WorkspaceSandbox(workspace)

    with pytest.raises(SensitiveFileError):
        sandbox.check_sensitive(sandbox.resolve("apiKey-123.csv"))


# --- list_directory -------------------------------------------------------


async def test_list_directory_lists_entries(settings: ToolsSettings) -> None:
    output = await _tool(settings, "list_directory").run()

    assert "src/" in output
    assert "README.md" in output


async def test_list_directory_reports_missing_path(settings: ToolsSettings) -> None:
    assert "不存在" in await _tool(settings, "list_directory").run("nope")


async def test_list_directory_rejects_escape(settings: ToolsSettings) -> None:
    with pytest.raises(SandboxViolation):
        await _tool(settings, "list_directory").run("../")


# --- read_file ------------------------------------------------------------


async def test_read_file_returns_content(settings: ToolsSettings) -> None:
    assert "print('hi')" in await _tool(settings, "read_file").run("src/main.py")


async def test_read_file_reports_missing_file(settings: ToolsSettings) -> None:
    assert "不存在" in await _tool(settings, "read_file").run("ghost.py")


async def test_read_file_rejects_sensitive_file(settings: ToolsSettings) -> None:
    with pytest.raises(SensitiveFileError):
        await _tool(settings, "read_file").run(".env")


async def test_read_file_skips_binary(workspace: Path, settings: ToolsSettings) -> None:
    (workspace / "blob.bin").write_bytes(b"\x00\x01\x02\x03")

    assert "二进制" in await _tool(settings, "read_file").run("blob.bin")


async def test_read_file_truncates_large_file(workspace: Path) -> None:
    (workspace / "big.txt").write_text("x" * 200, encoding="utf-8")
    limited = ToolsSettings(
        workspace_root=str(workspace), max_read_bytes=10, max_output_chars=1000
    )

    output = await _tool(limited, "read_file").run("big.txt")

    assert "已截断" in output


# --- search_text ----------------------------------------------------------


async def test_search_text_finds_matches(settings: ToolsSettings) -> None:
    output = await _tool(settings, "search_text").run(pattern="print")

    assert "src/main.py:1" in output


async def test_search_text_honours_glob(settings: ToolsSettings) -> None:
    output = await _tool(settings, "search_text").run(pattern="Demo", glob="*.md")

    assert "README.md" in output


async def test_search_text_reports_no_match(settings: ToolsSettings) -> None:
    assert "未找到匹配" in await _tool(settings, "search_text").run(pattern="zzz-not-here")


async def test_search_text_rejects_invalid_regex(settings: ToolsSettings) -> None:
    assert "正则表达式无效" in await _tool(settings, "search_text").run(pattern="[unclosed")


async def test_search_text_skips_sensitive_files(settings: ToolsSettings) -> None:
    """`.env` 里的内容不应出现在搜索结果中。"""
    output = await _tool(settings, "search_text").run(pattern="SECRET_TOKEN")

    assert "未找到匹配" in output


# --- write_file -----------------------------------------------------------


async def test_write_file_creates_new_file(workspace: Path, settings: ToolsSettings) -> None:
    output = await _tool(settings, "write_file").run(path="src/new.py", content="x = 1\n")

    assert "已写入" in output
    assert (workspace / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


async def test_write_file_refuses_overwrite_by_default(
    workspace: Path, settings: ToolsSettings
) -> None:
    output = await _tool(settings, "write_file").run(path="README.md", content="changed\n")

    assert "已存在" in output
    assert (workspace / "README.md").read_text(encoding="utf-8") == "# Demo\n"


async def test_write_file_overwrites_when_confirmed(
    workspace: Path, settings: ToolsSettings
) -> None:
    output = await _tool(settings, "write_file").run(
        path="README.md", content="changed\n", overwrite=True
    )

    assert "已覆盖" in output
    assert (workspace / "README.md").read_text(encoding="utf-8") == "changed\n"


async def test_write_file_blocks_sensitive_target(settings: ToolsSettings) -> None:
    with pytest.raises(SensitiveFileError):
        await _tool(settings, "write_file").run(path=".env", content="x", overwrite=True)


async def test_write_file_rejects_directory_target(settings: ToolsSettings) -> None:
    output = await _tool(settings, "write_file").run(
        path="src", content="x", overwrite=True
    )

    assert "目录" in output


async def test_write_file_rejects_oversized_content(
    workspace: Path, settings: ToolsSettings
) -> None:
    output = await _tool(settings, "write_file").run(
        path="huge.txt", content="x" * 1_100_000
    )

    assert "内容过大" in output


def test_write_file_absent_when_disabled(workspace: Path) -> None:
    disabled = ToolsSettings(workspace_root=str(workspace), allow_file_write=False)

    assert "write_file" not in {tool.name for tool in create_local_tools(disabled)}


# --- run_command ----------------------------------------------------------


def test_run_command_absent_by_default(workspace: Path) -> None:
    default = ToolsSettings(workspace_root=str(workspace))

    assert "run_command" not in {tool.name for tool in create_local_tools(default)}


async def test_run_command_executes_when_enabled(workspace: Path) -> None:
    enabled = ToolsSettings(workspace_root=str(workspace), allow_shell=True)

    output = await _tool(enabled, "run_command").run(command="echo hello-tools")

    assert "hello-tools" in output
    assert "exit=0" in output


async def test_run_command_reports_nonzero_exit(workspace: Path) -> None:
    enabled = ToolsSettings(workspace_root=str(workspace), allow_shell=True)
    command = "exit 3" if sys.platform == "win32" else "exit 3"

    output = await _tool(enabled, "run_command").run(command=command)

    assert "exit=3" in output


async def test_run_command_times_out(workspace: Path) -> None:
    enabled = ToolsSettings(
        workspace_root=str(workspace), allow_shell=True, shell_timeout_seconds=1
    )
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'

    output = await _tool(enabled, "run_command").run(command=command)

    assert "超时" in output


async def test_run_command_runs_inside_workspace(workspace: Path) -> None:
    enabled = ToolsSettings(workspace_root=str(workspace), allow_shell=True)
    tool = _tool(enabled, "run_command")
    command = "cd" if sys.platform == "win32" else "pwd"

    output = await tool.run(command=command)

    assert str(workspace) in output


# --- 与注册表集成 ---------------------------------------------------------


async def test_registry_turns_sandbox_violation_into_error_result(
    settings: ToolsSettings,
) -> None:
    registry = ToolRegistry(create_local_tools(settings))

    result = await registry.execute(
        ToolCall(id="c1", name="read_file", arguments='{"path": "../../escape.txt"}')
    )

    assert result.is_error is True
    assert "escapes the workspace" in result.content


async def test_registry_turns_sensitive_file_denial_into_error_result(
    settings: ToolsSettings,
) -> None:
    registry = ToolRegistry(create_local_tools(settings))

    result = await registry.execute(
        ToolCall(id="c1", name="read_file", arguments='{"path": ".env"}')
    )

    assert result.is_error is True
    assert "sensitive" in result.content