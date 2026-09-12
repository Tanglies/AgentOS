"""请求上下文中间件。

为每个请求生成（或透传）request_id，写入日志上下文与 ``X-Request-ID`` 响应头，
并记录访问日志与耗时。
"""

from __future__ import annotations

import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentos.core.context import new_id, reset_request_id, set_request_id
from agentos.core.logging import get_logger

logger = get_logger(__name__)


class JSONCharsetMiddleware:
    """给 ``application/json`` 响应补上 ``charset=utf-8``。

    为什么需要：Starlette 只在 ``text/*`` 上自动补 charset，
    ``application/json`` 的响应头就是光秃秃的 ``application/json``。
    而 Windows PowerShell 5.1 的 ``Invoke-WebRequest`` 在没有 charset 时
    按 **ISO-8859-1** 解码，中文全变乱码。

    为什么用中间件而不是自定义响应类：FastAPI 内置的 ``/openapi.json``
    直接返回 ``JSONResponse``，绕过 ``default_response_class``；
    只有中间件能统一覆盖所有内层产生的响应。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = headers.get("content-type", "")
                if content_type.startswith("application/json") and (
                    "charset=" not in content_type.lower()
                ):
                    headers["content-type"] = f"{content_type}; charset=utf-8"
            await send(message)

        await self.app(scope, receive, send_wrapper)

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware:
    """纯 ASGI 中间件，避免 BaseHTTPMiddleware 带来的额外任务与流式响应问题。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(REQUEST_ID_HEADER) or new_id("req_")
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "http request",
                extra={
                    "extra_fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status_code": status_code,
                        "duration_ms": round(duration_ms, 3),
                    }
                },
            )
            reset_request_id(token)