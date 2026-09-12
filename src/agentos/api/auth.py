"""API Key 认证与调用方身份。

认证来源有两处：

1. **数据库密钥**（``api_keys`` 表）—— 带名称与权限，推荐方式
2. **静态配置密钥**（``AGENTOS_AUTH__API_KEYS``）—— 视为管理员（``*``），
   用于签发第一把数据库密钥，解决「数据库里一把钥匙都没有」的引导问题

安全设计：

- 数据库只存 SHA-256 哈希，明文只在签发时返回一次
- 校验用常量时间比较，避免通过响应时间差反推密钥
- 开启但没有任何可用密钥时**拒绝一切**（fail closed），配置失误不会变成未授权访问
- 认证成功后绑定 ``actor``（密钥名称），日志与审计据此回答「谁」
"""

from __future__ import annotations

import hashlib
import secrets
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agentos.core.config import AuthSettings
from agentos.core.context import bind
from agentos.core.logging import get_logger
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import ApiKeyIdentity, ApiKeyStore, Permission
from agentos.runtime.tools import tool_permission_scope

logger = get_logger(__name__)

UNAUTHORIZED_CODE = "unauthorized"
SECURITY_SCHEME_NAME = "APIKeyHeader"

_identity: ContextVar[ApiKeyIdentity | None] = ContextVar(
    "agentos_identity", default=None
)


def fingerprint(value: str) -> str:
    """返回密钥的短指纹，用于区分静态密钥，不可反推原文。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def get_current_identity() -> ApiKeyIdentity | None:
    """返回当前请求的调用方身份；认证关闭时为 ``None``。"""
    return _identity.get()


class APIKeyMiddleware:
    """基于请求头的 API Key 认证中间件。"""

    def __init__(
        self,
        app: ASGIApp,
        settings: AuthSettings,
        *,
        store: ApiKeyStore | None = None,
    ) -> None:
        self.app = app
        self._settings = settings
        self._header = settings.header_name.lower()
        self._store = store
        # 静态配置密钥视为管理员，用于签发第一把数据库密钥
        self._static_keys = tuple(
            key.get_secret_value().encode("utf-8") for key in settings.api_keys
        )
        self._public_paths = frozenset(_normalize(path) for path in settings.public_paths)

        if settings.enabled and not self._static_keys and not self._has_database_keys():
            logger.error(
                "auth enabled but no api keys available; every request will be rejected",
                extra={"extra_fields": {"header": settings.header_name}},
            )

    def _has_database_keys(self) -> bool:
        return self._store is not None and self._store.count() > 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._settings.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CORS 预检不携带自定义请求头，必须放行，否则浏览器侧全部失败
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if _normalize(scope.get("path", "")) in self._public_paths:
            await self.app(scope, receive, send)
            return

        provided = Headers(scope=scope).get(self._header)
        identity = self._authenticate(provided)
        if identity is not None:
            token = _identity.set(identity)
            try:
                # 把调用方身份绑进上下文，下游日志与审计都会带上它
                with bind(
                    actor=identity.name,
                    user_id=identity.user_id,
                    workspace_id=identity.workspace_id,
                ), tool_permission_scope(
                    lambda permission: identity.can(Permission(permission))
                ):
                    await self.app(scope, receive, send)
            finally:
                _identity.reset(token)
            return

        await self._reject(scope, receive, send)

    def _authenticate(self, provided: str | None) -> ApiKeyIdentity | None:
        """先查数据库密钥，回退到静态配置密钥。"""
        if not provided:
            return None

        if self._store is not None:
            identity = self._store.authenticate(provided)
            if identity is not None:
                return identity

        candidate = provided.encode("utf-8")
        for key in self._static_keys:
            if secrets.compare_digest(candidate, key):
                return ApiKeyIdentity(
                    name=f"config-{fingerprint(key.decode('utf-8'))}",
                    user_id=DEFAULT_USER_ID,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    permissions=frozenset({Permission.ALL.value}),
                    source="config",
                )
        return None

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.warning(
            "request rejected: invalid or missing api key",
            extra={
                "extra_fields": {
                    "path": scope.get("path"),
                    "method": scope.get("method"),
                }
            },
        )
        response = JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": UNAUTHORIZED_CODE,
                    "message": "invalid or missing API key",
                    "details": {"header": self._settings.header_name},
                }
            },
        )
        await response(scope, receive, send)


def install_api_key_security_scheme(app: Any, settings: AuthSettings) -> None:
    """给 OpenAPI 补上 API Key 安全方案，让 Swagger UI 出现 Authorize 按钮。

    认证是用**中间件**实现的，路由上没有声明任何依赖，因此 FastAPI
    不会自动生成 ``securitySchemes`` —— Swagger UI 也就没有地方填 Key，
    浏览器里点任何接口都只能拿到 401。

    这里手动补上方案，浏览器就能先 Authorize 再调接口。
    未开启认证时不注入，避免给免认证的部署造成误导。
    """
    if not settings.enabled:
        return

    original_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        schema = original_openapi()
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        if SECURITY_SCHEME_NAME not in schemes:
            schemes[SECURITY_SCHEME_NAME] = {
                "type": "apiKey",
                "in": "header",
                "name": settings.header_name,
            }
            schema["security"] = [{SECURITY_SCHEME_NAME: []}]
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def _normalize(path: str) -> str:
    """去掉尾部斜杠，让 ``/health/`` 也能匹配 ``/health``。"""
    stripped = path.rstrip("/")
    return stripped or "/"
