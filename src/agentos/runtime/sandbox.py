"""工作区沙箱。

所有本地文件工具都必须经过 :class:`WorkspaceSandbox` 解析路径，
确保 Agent 只能操作 ``workspace_root`` 之内的文件：``..`` 相对逃逸、
指向外部的绝对路径、以及指向外部的符号链接都会被拒绝。

另外维护一份敏感文件黑名单，避免模型把 ``.env``、私钥、
API Key 之类的凭据读进上下文或写出去。

.. warning::

   沙箱只约束**文件工具**。``run_command`` 执行的是真实 shell，
   命令内部可以访问文件系统任意位置，因此该工具默认关闭。
"""

from __future__ import annotations

import re
from pathlib import Path

from agentos.core.exceptions import ValidationError


class SandboxViolation(ValidationError):
    """请求的路径越出了工作区沙箱。"""

    code = "sandbox_violation"
    message = "path escapes the workspace sandbox"


class SensitiveFileError(ValidationError):
    """请求访问的文件被列为敏感文件。"""

    code = "sensitive_file"
    message = "access to sensitive file is denied"


# 敏感**文件名**模式（大小写不敏感，针对最后一段路径）。
_SENSITIVE_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.env$"),
    # 允许 .env.example，拒绝 .env.local / .env.production 等
    re.compile(r"^\.env\.(?!example$)"),
    re.compile(r".*\.(key|pem|p12|pfx|jks|keystore)$"),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)$"),
    re.compile(r".*(apikey|api_key|secret|credential|passwd|password).*\.(csv|json|ya?ml|ini|txt)$"),
)

# 敏感**目录名**：出现在路径任意一段即拒绝。
_SENSITIVE_DIRS = frozenset({"secrets", ".ssh", ".aws", ".gnupg", ".kube"})


class WorkspaceSandbox:
    """把路径解析并约束在工作区根目录之内。"""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise SandboxViolation(
                f"workspace root does not exist: {self.root}",
                details={"workspace_root": str(self.root)},
            )

    def resolve(self, path: str | Path = ".") -> Path:
        """把路径解析为工作区内的绝对路径，越界时抛 :class:`SandboxViolation`。"""
        raw = Path(path)
        candidate = raw if raw.is_absolute() else self.root / raw
        # resolve() 会展开符号链接，因此指向外部的软链接同样会被拦截
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise SandboxViolation(
                f"path escapes the workspace: {path}",
                details={"path": str(path), "workspace_root": str(self.root)},
            )
        return resolved

    def relative(self, path: Path) -> str:
        """返回相对工作区根目录的展示路径（统一用正斜杠）。"""
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:  # pragma: no cover - resolve() 已保证在沙箱内
            return str(path)

    def check_sensitive(self, path: Path) -> None:
        """命中敏感文件规则时抛 :class:`SensitiveFileError`。"""
        try:
            inside = path.relative_to(self.root)
        except ValueError:  # pragma: no cover - 调用前已通过 resolve()
            inside = path

        for part in inside.parts[:-1]:
            if part.lower() in _SENSITIVE_DIRS:
                raise SensitiveFileError(
                    f"access denied: '{part}' is a sensitive directory",
                    details={"path": self.relative(path)},
                )

        name = path.name.lower()
        for pattern in _SENSITIVE_NAME_PATTERNS:
            if pattern.match(name):
                raise SensitiveFileError(
                    "access denied: file matches a sensitive pattern",
                    details={"path": self.relative(path), "pattern": pattern.pattern},
                )
