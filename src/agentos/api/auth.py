"""API Key 认证。

用一个纯 ASGI 中间件统一拦截所有 HTTP 请求，客户端通过请求头
（默认 ``X-API-Key``）携带密钥。

三条设计原则：

- **默认关闭**：本地开发不受影响；对外暴露时必须显式开启
- **失败关闭**：开启但没配置任何密钥时，拒绝所有请求，而不是退化成不校验
- **常量时间比较**：用 :func:`secrets.compare_digest` 避免通过响应时间反推密钥

放行规则：

- 非 HTTP 请求（如 lifespan）
- ``OPTIONS`` 预检请求 —— 浏览器不会在预检里带自定义请求头
- ``public_paths`` 中列出的路径（健康探针与文档）
"""

from __future__ import annotations

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agentos.core.config import AuthSettings
from agentos.core.logging import get_logger

logger = get_logger(__name__)

UNAUTHORIZED_CODE = "unauthorized"


class APIKeyMiddleware:
    """基于请求头的 API Key 认证中间件。"""

    def __init__(self, app: ASGIApp, settings: AuthSettings) -> None:
        self.app = app
        self._settings = settings
        self._header = settings.header_name.lower()
        self._keys = tuple(key.get_secret_value().encode("utf-8") for key in settings.api_keys)
        self._public_paths = frozenset(_normalize(path) for path in settings.public_paths)

        if settings.enabled and not self._keys:
            logger.error(
                "auth enabled but no api keys configured; every request will be rejected",
                extra={"extra_fields": {"header": settings.header_name}},
            )

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
        if provided and self._matches(provided):
            await self.app(scope, receive, send)
            return

        await self._reject(scope, receive, send)

    def _matches(self, provided: str) -> bool:
        """常量时间比较，避免通过响应时间差反推密钥。"""
        candidate = provided.encode("utf-8")
        return any(secrets.compare_digest(candidate, key) for key in self._keys)

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


def _normalize(path: str) -> str:
    """去掉尾部斜杠，让 ``/health/`` 也能匹配 ``/health``。"""
    stripped = path.rstrip("/")
    return stripped or "/"

