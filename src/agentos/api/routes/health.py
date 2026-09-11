"""系统探针路由。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from agentos import __version__
from agentos.api.deps import LLMClientDep, RuntimeDep, SettingsDep
from agentos.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="存活探针")
async def health(request: Request, settings: SettingsDep) -> HealthResponse:
    """返回服务存活状态与基础元信息。"""
    started_at = getattr(request.app.state, "started_at", time.time())
    return HealthResponse(
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        uptime_seconds=round(max(0.0, time.time() - started_at), 3),
    )


@router.get("/health/ready", response_model=ReadyResponse, summary="就绪探针")
async def ready(runtime: RuntimeDep, llm_client: LLMClientDep) -> ReadyResponse:
    """返回依赖是否就绪，可用于容器编排的健康检查。"""
    return ReadyResponse(
        llm_provider=llm_client.provider,
        agents=len(runtime.registry),
        tools=len(runtime.tools),
    )