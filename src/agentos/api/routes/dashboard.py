"""Dashboard read-only metrics routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from agentos.api.deps import DashboardServiceDep, require
from agentos.api.schemas import (
    DashboardErrorItem,
    DashboardOverviewResponse,
    DashboardUsageResponse,
)
from agentos.core.context import get_workspace_id
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Dashboard 总览",
    dependencies=[require(Permission.DASHBOARD_READ)],
)
async def dashboard_overview(service: DashboardServiceDep) -> DashboardOverviewResponse:
    """返回运行数、成功率、平均延迟、token 与活跃 Agent 数。"""
    return DashboardOverviewResponse(
        **service.overview(workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID)
    )


@router.get(
    "/tools",
    response_model=dict[str, int],
    summary="工具调用统计",
    dependencies=[require(Permission.DASHBOARD_READ)],
)
async def dashboard_tools(
    service: DashboardServiceDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, int]:
    """按工具名返回审计记录中的调用次数。"""
    return service.tools(
        workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID, limit=limit
    )




@router.get(
    "/usage",
    response_model=DashboardUsageResponse,
    summary="Dashboard 配额使用量",
    dependencies=[require(Permission.USAGE_READ)],
)
async def dashboard_usage(service: DashboardServiceDep) -> DashboardUsageResponse:
    """返回今日 Runs、Tokens 及 Workspace 配额。"""
    return DashboardUsageResponse(
        **service.usage(workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID)
    )


@router.get(
    "/errors",
    response_model=list[DashboardErrorItem],
    summary="最近错误",
    dependencies=[require(Permission.DASHBOARD_READ)],
)
async def dashboard_errors(
    service: DashboardServiceDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[DashboardErrorItem]:
    """返回最近失败的运行记录。"""
    return [
        DashboardErrorItem(**item)
        for item in service.errors(
            workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID, limit=limit
        )
    ]
