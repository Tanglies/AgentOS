"""Workspace quota management routes."""

from __future__ import annotations

from fastapi import APIRouter

from agentos.api.deps import QuotaServiceDep, WorkspaceServiceDep, require
from agentos.api.schemas import QuotaSummary, QuotaUpdateRequest
from agentos.core.context import get_user_id, get_workspace_id
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/quota", tags=["quota"])


def _scope() -> tuple[int, int]:
    return (
        get_workspace_id() or DEFAULT_WORKSPACE_ID,
        get_user_id() or DEFAULT_USER_ID,
    )


@router.get(
    "",
    response_model=QuotaSummary,
    summary="获取 Workspace 配额",
    dependencies=[require(Permission.QUOTA_READ)],
)
async def get_quota(
    service: QuotaServiceDep, workspaces: WorkspaceServiceDep
) -> QuotaSummary:
    workspace_id, user_id = _scope()
    workspaces.get(workspace_id, user_id)
    return QuotaSummary(**service.get_limits(workspace_id).model_dump())


@router.patch(
    "",
    response_model=QuotaSummary,
    summary="更新 Workspace 配额",
    dependencies=[require(Permission.QUOTA_WRITE)],
)
async def update_quota(
    payload: QuotaUpdateRequest,
    service: QuotaServiceDep,
    workspaces: WorkspaceServiceDep,
) -> QuotaSummary:
    workspace_id, user_id = _scope()
    workspaces.get(workspace_id, user_id)
    record = service.update(workspace_id, **payload.model_dump(exclude_none=True))
    return QuotaSummary(**record.model_dump())
