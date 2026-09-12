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

import hashlib
import secrets
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agentos.core.config import AuthSettings
from agentos.core.context import bind
from agentos.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

logger = get_logger(__name__)

UNAUTHORIZED_CODE = "unauthorized"
SECURITY_SCHEME_NAME = "APIKeyHeader"


def install_api_key_security_scheme(app: FastAPI, settings: AuthSettings) -> None:
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


class APIKeyMiddleware:
    """基于请求头的 API Key 认证中间件。"""

    def __init__(self, app: ASGIApp, settings: AuthSettings) -> None:
        self.app = app
        self._settings = settings
        self._header = settings.header_name.lower()
        # 预计算密钥字节与指纹：指纹用于审计日志标记「谁」，不泄露密钥本身
        self._keys = tuple(
            (
                key.get_secret_value().encode("utf-8"),
                fingerprint(key.get_secret_value()),
            )
            for key in settings.api_keys
        )
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
        actor = self._match(provided) if provided else None
        if actor is not None:
            # 把调用方身份绑进上下文，下游日志与审计都会带上它
            with bind(actor=actor):
                await self.app(scope, receive, send)
            return

        await self._reject(scope, receive, send)

    def _match(self, provided: str) -> str | None:
        """匹配密钥，成功时返回指纹。

        用 :func:`secrets.compare_digest` 做常量时间比较，
        避免通过响应时间差逐字节反推密钥。
        """
        candidate = provided.encode("utf-8")
        for key, fingerprint_value in self._keys:
            if secrets.compare_digest(candidate, key):
                return fingerprint_value
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


def fingerprint(value: str) -> str:
    """返回密钥的短指纹，用于审计与排查，不可反推原文。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _normalize(path: str) -> str:
    """去掉尾部斜杠，让 ``/health/`` 也能匹配 ``/health``。"""
    stripped = path.rstrip("/")
    return stripped or "/"

