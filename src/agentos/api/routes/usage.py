"""Workspace usage routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from agentos.api.deps import UsageServiceDep, WorkspaceServiceDep, require
from agentos.api.schemas import UsageResponse
from agentos.core.context import get_user_id, get_workspace_id
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get(
    "",
    response_model=UsageResponse,
    summary="获取 Workspace 用量",
    dependencies=[require(Permission.USAGE_READ)],
)
async def get_usage(
    service: UsageServiceDep,
    workspaces: WorkspaceServiceDep,
    period: Annotated[str, Query(pattern="^(day|month)$")] = "day",
) -> UsageResponse:
    workspace_id = get_workspace_id() or DEFAULT_WORKSPACE_ID
    workspaces.get(workspace_id, get_user_id() or DEFAULT_USER_ID)
    return UsageResponse(**service.summary(workspace_id, period=period))
