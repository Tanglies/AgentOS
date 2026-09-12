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
from agentos.api.auth import APIKeyMiddleware, install_api_key_security_scheme
from agentos.api.middleware import (
    JSONCharsetMiddleware,
    RequestContextMiddleware,
)
from agentos.api.routes import (
    agents,
    apikeys,
    audit,
    evaluation,
    health,
    memories,
    runs,
    sessions,
    tools,
)
from agentos.core.config import Settings, get_settings
from agentos.core.exceptions import AgentOSError
from agentos.core.logging import configure_logging, get_logger
from agentos.llm.factory import create_llm_client
from agentos.runtime.api_keys import ApiKeyStore
from agentos.runtime.audit import AuditLog
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.long_term_memory import LongTermMemory
from agentos.runtime.memory import MemoryStore
from agentos.runtime.run_store import RunStore
from agentos.runtime.runtime import AgentRuntime
from agentos.runtime.services.agent_service import AgentService

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
        memory = MemoryStore(resolved.memory)
        long_term = (
            LongTermMemory(resolved.memory) if resolved.memory.long_term_enabled else None
        )
        tool_registry = create_default_tool_registry(resolved.tools, long_term=long_term)
        run_store = RunStore(resolved.runs) if resolved.runs.enabled else None
        audit_log = AuditLog(resolved.audit) if resolved.audit.enabled else None
        runtime = AgentRuntime(
            llm_client,
            settings=resolved.runtime,
            tools=tool_registry,
            registry_db_path=(
                resolved.registry.db_path if resolved.registry.persist else None
            ),
            memory=memory,
            long_term=long_term,
            runs=run_store,
            audit=audit_log,
        )
        app.state.llm_client = llm_client
        app.state.runtime = runtime
        app.state.audit_log = audit_log
        app.state.agent_service = AgentService(runtime.registry, audit=audit_log)
        app.state.api_key_store = api_key_store
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

    # 中间件 add 的顺序决定执行顺序：后 add 的在外层。
    # 期望的执行顺序是 CORS → 请求上下文 → 认证 → 路由，
    # 这样 401 响应也会带上 request_id 并进入访问日志。
    # 认证关闭时不必建库；静态配置密钥在没有数据库密钥时充当引导管理员
    api_key_store = (
        ApiKeyStore(resolved.api_keys)
        if resolved.auth.enabled and resolved.api_keys.enabled
        else None
    )
    if resolved.auth.enabled:
        app.add_middleware(
            APIKeyMiddleware, settings=resolved.auth, store=api_key_store
        )
        install_api_key_security_scheme(app, resolved.auth)
    app.add_middleware(RequestContextMiddleware)
    if resolved.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.api.cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )
    # 放最外层，保证所有内层响应（含 FastAPI 内置的 /openapi.json）都补上 charset
    app.add_middleware(JSONCharsetMiddleware)

    app.include_router(health.router)
    app.include_router(agents.router, prefix=API_PREFIX)
    app.include_router(apikeys.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(tools.router, prefix=API_PREFIX)
    app.include_router(sessions.router, prefix=API_PREFIX)
    app.include_router(memories.router, prefix=API_PREFIX)
    app.include_router(evaluation.router, prefix=API_PREFIX)
    app.include_router(audit.router, prefix=API_PREFIX)

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
