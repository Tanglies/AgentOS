"""API Key 管理与权限模型。

安全设计：

- **数据库只存 SHA-256 哈希**。明文只在签发时返回一次，之后无法还原，
  丢失只能重新签发。
- **用 SHA-256 而不是 bcrypt/argon2**：慢哈希防的是低熵密码的暴力枚举，
  而这里的密钥由 ``secrets.token_urlsafe(32)`` 生成（256 位熵），
  暴力枚举在计算上不可行，快哈希足够且更适合每请求校验的热路径。
- **吊销是软删除**（写 ``revoked_at``），保留审计线索。
- **记录 ``last_used_at``**，便于发现闲置或异常使用的密钥。

引导问题：数据库里一把钥匙都没有时，拿什么来签发第一把？
答案是 ``AGENTOS_AUTH__API_KEYS`` 里配置的静态密钥 —— 它们被视为**管理员**
（拥有全部权限），可用于签发数据库密钥。签发完可以把静态密钥清空。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agentos.core.config import ApiKeySettings
from agentos.core.exceptions import ConflictError, NotFoundError, ValidationError
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.runtime.repositories import (
    API_KEYS_SCHEMA,
    ApiKeyRecord,
    ApiKeyRepository,
)

TOUCH_INTERVAL_SECONDS = 60.0

__all__ = [
    "ApiKeyIdentity",
    "ApiKeyIssueResult",
    "ApiKeyRecord",
    "ApiKeyStore",
    "Permission",
    "hash_key",
]


class Permission(StrEnum):
    """权限标识。

    命名规则 ``资源:动作``，与 API 路由一一对应，便于审查。
    """

    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    RUN_CREATE = "run:create"
    RUN_READ = "run:read"
    TOOL_READ = "tool:read"
    TOOL_EXECUTE = "tool:execute"
    SESSION_READ = "session:read"
    SESSION_WRITE = "session:write"
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    EVALUATION_READ = "evaluation:read"
    DASHBOARD_READ = "dashboard:read"
    AUDIT_READ = "audit:read"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_WRITE = "workspace:write"
    API_KEY_ADMIN = "apikey:admin"

    #: 通配，拥有全部权限（静态配置密钥即属此类）
    ALL = "*"


#: 签发数据库密钥时的默认权限：覆盖日常使用，但不含管理员权限
DEFAULT_PERMISSIONS: tuple[str, ...] = (
    Permission.AGENT_READ.value,
    Permission.AGENT_WRITE.value,
    Permission.RUN_CREATE.value,
    Permission.RUN_READ.value,
    Permission.TOOL_READ.value,
    Permission.TOOL_EXECUTE.value,
    Permission.SESSION_READ.value,
    Permission.SESSION_WRITE.value,
    Permission.MEMORY_READ.value,
    Permission.MEMORY_WRITE.value,
    Permission.EVALUATION_READ.value,
    Permission.DASHBOARD_READ.value,
    Permission.AUDIT_READ.value,
    Permission.USER_READ.value,
    Permission.USER_WRITE.value,
    Permission.WORKSPACE_READ.value,
    Permission.WORKSPACE_WRITE.value,
)


def hash_key(raw_key: str) -> str:
    """返回密钥的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKeyIdentity(BaseModel):
    """一次请求的调用方身份。"""

    name: str
    user_id: int = DEFAULT_USER_ID
    workspace_id: int = DEFAULT_WORKSPACE_ID
    permissions: frozenset[str] = Field(default_factory=frozenset)
    source: Literal["database", "config"] = "database"

    def can(self, permission: Permission) -> bool:
        """是否拥有某个权限；拥有通配 ``*`` 表示全部允许。"""
        return (
            Permission.ALL.value in self.permissions
            or permission.value in self.permissions
        )


class ApiKeyIssueResult(BaseModel):
    """签发结果。

    ``key`` 是**明文密钥，只在这里出现一次**，服务端不保存。
    """

    key: str
    record: ApiKeyRecord


class ApiKeyStore:
    """API Key 存储与校验。"""

    def __init__(self, settings: ApiKeySettings | None = None) -> None:
        self._settings = settings or ApiKeySettings()
        self.path = Path(self._settings.db_path).expanduser()
        self._db = Database(self.path, schema=API_KEYS_SCHEMA)
        self._repo = ApiKeyRepository(self._db)
        self._last_touch: dict[str, float] = {}

    @property
    def repository(self) -> ApiKeyRepository:
        """底层 Repository，供只读查询直接使用。"""
        return self._repo

    # --- 签发与管理 ---------------------------------------------------

    def issue(
        self,
        name: str,
        *,
        user_id: int = DEFAULT_USER_ID,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        permissions: list[str] | None = None,
    ) -> ApiKeyIssueResult:
        """签发一把新密钥，返回明文（仅此一次）。"""
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("api key name must not be empty")
        if self._repo.get_by_name(cleaned) is not None:
            raise ConflictError(
                f"api key name already exists: {cleaned}", details={"name": cleaned}
            )

        resolved = list(permissions) if permissions is not None else list(DEFAULT_PERMISSIONS)
        _validate_permissions(resolved)

        raw_key = f"sk-agentos-{secrets.token_urlsafe(32)}"
        record = ApiKeyRecord(
            key_hash=hash_key(raw_key),
            name=cleaned,
            user_id=user_id,
            workspace_id=workspace_id,
            permissions=resolved,
            created_at=datetime.now(UTC),
        )
        saved = self._repo.add(record)
        return ApiKeyIssueResult(key=raw_key, record=saved)

    def revoke(self, key_id: int, *, workspace_id: int | None = None) -> ApiKeyRecord:
        """吊销密钥（软删除）。"""
        if not self._repo.revoke(
            key_id,
            revoked_at=datetime.now(UTC),
            workspace_id=workspace_id,
        ):
            raise NotFoundError(
                f"api key not found or already revoked: {key_id}",
                details={"key_id": key_id},
            )
        record = self._repo.get(key_id)
        if record is None:  # pragma: no cover - 刚更新过，必然存在
            raise NotFoundError(f"api key not found: {key_id}", details={"key_id": key_id})
        return record

    def list(
        self,
        *,
        include_revoked: bool = False,
        workspace_id: int | None = None,
    ) -> list[ApiKeyRecord]:
        """列出密钥记录（不含明文与哈希）。"""
        return self._repo.list(
            include_revoked=include_revoked,
            workspace_id=workspace_id,
        )

    def count(
        self, *, include_revoked: bool = False, workspace_id: int | None = None
    ) -> int:
        """密钥数量。"""
        return self._repo.count(
            include_revoked=include_revoked,
            workspace_id=workspace_id,
        )

    # --- 校验 ---------------------------------------------------------

    def authenticate(self, raw_key: str) -> ApiKeyIdentity | None:
        """校验密钥，成功时返回身份并刷新 ``last_used_at``。"""
        if not raw_key:
            return None
        digest = hash_key(raw_key)
        record = self._repo.get_by_hash(digest)
        if record is None or record.revoked:
            return None

        self._touch(digest)
        return ApiKeyIdentity(
            name=record.name,
            user_id=record.user_id,
            workspace_id=record.workspace_id,
            permissions=frozenset(record.permissions),
            source="database",
        )

    def _touch(self, digest: str) -> None:
        """刷新最近使用时间；同一密钥 60 秒内只写一次，避免每请求一次写。"""
        now = time.monotonic()
        if now - self._last_touch.get(digest, 0.0) < TOUCH_INTERVAL_SECONDS:
            return
        self._last_touch[digest] = now
        self._repo.touch(digest, used_at=datetime.now(UTC))


def _validate_permissions(permissions: list[str]) -> None:
    """拒绝未知权限，避免拼错后静默无效。"""
    known = {item.value for item in Permission}
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise ValidationError(
            f"unknown permission(s): {', '.join(unknown)}",
            details={"unknown": unknown, "known": sorted(known)},
        )