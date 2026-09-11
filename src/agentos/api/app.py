"""FastAPI 应用装配。

``create_app`` 负责把配置、日志、LLM 客户端与 Agent Runtime 组装成一个可运行的 ASGI 应用；
资源在 lifespan 中创建与释放，避免模块导入时就建立外部连接。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentos import __version__
from agentos.api.middleware import RequestContextMiddleware
from agentos.api.routes import agents, health, runs, sessions, tools
from agentos.core.config import Settings, get_settings
from agentos.core.exceptions import AgentOSError
from agentos.core.logging import configure_logging, get_logger
from agentos.llm.factory import create_llm_client
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.memory import MemoryStore
from agentos.runtime.registry import create_default_registry
from agentos.runtime.runtime import AgentRuntime

logger = get_logger(__name__)

API_PREFIX = "/api/v1"
DESCRIPTION = "AgentOS —— 企业级大模型 Agent 平台 API"


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.logging)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        llm_client = create_llm_client(resolved.llm)
        tool_registry = create_default_tool_registry(resolved.tools)
        memory = MemoryStore(resolved.memory)
        runtime = AgentRuntime(
            llm_client,
            settings=resolved.runtime,
            registry=create_default_registry(
                resolved.runtime, tools=[tool.name for tool in tool_registry.list()]
            ),
            tools=tool_registry,
            memory=memory,
        )
        app.state.llm_client = llm_client
        app.state.runtime = runtime
        logger.info(
            "application started",
            extra={
                "extra_fields": {
                    "environment": resolved.environment,
                    "llm_provider": llm_client.provider,
                }
            },
        )
        try:
            yield
        finally:
            await runtime.aclose()
            logger.info("application stopped")

    app = FastAPI(
        title=resolved.app_name,
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs" if resolved.api.enable_docs else None,
        redoc_url="/redoc" if resolved.api.enable_docs else None,
        openapi_url="/openapi.json" if resolved.api.enable_docs else None,
        root_path=resolved.api.root_path,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.started_at = time.time()

    app.add_middleware(RequestContextMiddleware)
    if resolved.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.api.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )

    app.include_router(health.router)
    app.include_router(agents.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(tools.router, prefix=API_PREFIX)
    app.include_router(sessions.router, prefix=API_PREFIX)

    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentOSError)
    async def _handle_agentos_error(request: Request, exc: AgentOSError) -> JSONResponse:
        logger.warning(
            "request failed",
            extra={
                "extra_fields": {
                    "path": request.url.path,
                    "code": exc.code,
                    "status_code": exc.status_code,
                }
            },
        )
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled error", extra={"extra_fields": {"path": request.url.path}}
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )


app = create_app()
