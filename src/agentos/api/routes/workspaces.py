"""Workspace lifecycle and membership routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import UserServiceDep, WorkspaceServiceDep, require
from agentos.api.schemas import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceMemberAddRequest,
    WorkspaceMemberBatchRemoveRequest,
    WorkspaceMemberBatchRemoveResponse,
    WorkspaceMemberBatchUpdateRequest,
    WorkspaceMemberBatchUpdateResponse,
    WorkspaceMemberListResponse,
    WorkspaceMemberSummary,
    WorkspaceMemberUpdateRequest,
    WorkspaceSummary,
    WorkspaceUpdateRequest,
)
from agentos.core.context import get_user_id
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import KeysetCursor, decode_keyset_cursor
from agentos.core.tenancy import DEFAULT_USER_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _current_user_id() -> int:
    return get_user_id() or DEFAULT_USER_ID


@router.post(
    "",
    response_model=WorkspaceSummary,
    status_code=status.HTTP_201_CREATED,
    summary="创建 Workspace",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    service: WorkspaceServiceDep,
) -> WorkspaceSummary:
    user_id = _current_user_id()
    workspace = service.create(name=payload.name, owner_id=user_id)
    return WorkspaceSummary.from_record(workspace, role=service.role(workspace.id or 0, user_id))


@router.get(
    "",
    response_model=WorkspaceListResponse,
    summary="列出当前用户的 Workspace",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def list_workspaces(
    service: WorkspaceServiceDep,
    page: int | None = Query(default=None, ge=1, description="页码，从 1 开始"),
    page_size: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="每页数量",
    ),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> WorkspaceListResponse:
    """按 Workspace id 返回稳定游标分页，同时保留 page/page_size。"""
    if cursor and page is not None:
        raise ValidationError(
            "cursor cannot be combined with page",
            details={"parameter": "cursor"},
        )
    user_id = _current_user_id()
    resolved_page = 1 if cursor else (page or 1)
    resolved_page_size = page_size or 100
    position = decode_keyset_cursor(cursor) if cursor else None
    workspaces, total, next_cursor = service.list(
        user_id,
        page=resolved_page,
        page_size=resolved_page_size,
        cursor=position,
    )
    return WorkspaceListResponse(
        items=[
            WorkspaceSummary.from_record(
                workspace, role=service.role(workspace.id or 0, user_id)
            )
            for workspace in workspaces
        ],
        total=total,
        page=resolved_page,
        page_size=resolved_page_size,
        next_cursor=next_cursor,
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceSummary,
    summary="获取 Workspace",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def get_workspace(workspace_id: int, service: WorkspaceServiceDep) -> WorkspaceSummary:
    user_id = _current_user_id()
    return WorkspaceSummary.from_record(
        service.get(workspace_id, user_id),
        role=service.role(workspace_id, user_id),
    )


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceSummary,
    summary="更新 Workspace",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdateRequest,
    service: WorkspaceServiceDep,
) -> WorkspaceSummary:
    user_id = _current_user_id()
    return WorkspaceSummary.from_record(
        service.update(workspace_id, user_id, name=payload.name),
        role=service.role(workspace_id, user_id),
    )


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 Workspace",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def delete_workspace(workspace_id: int, service: WorkspaceServiceDep) -> Response:
    service.delete(workspace_id, _current_user_id())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberListResponse,
    summary="列出 Workspace 成员",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def list_workspace_members(
    workspace_id: int,
    service: WorkspaceServiceDep,
    page: int | None = Query(default=None, ge=1, description="页码，从 1 开始"),
    page_size: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="每页数量",
    ),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> WorkspaceMemberListResponse:
    """按成员 user id 返回稳定游标分页，同时保留 page/page_size。"""
    if cursor and page is not None:
        raise ValidationError(
            "cursor cannot be combined with page",
            details={"parameter": "cursor"},
        )
    resolved_page = 1 if cursor else (page or 1)
    resolved_page_size = page_size or 100
    position = decode_keyset_cursor(cursor) if cursor else None
    return _member_list_response(
        workspace_id,
        service,
        _current_user_id(),
        page=resolved_page,
        page_size=resolved_page_size,
        cursor=position,
    )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberSummary,
    status_code=status.HTTP_201_CREATED,
    summary="添加 Workspace 成员",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def add_workspace_member(
    workspace_id: int,
    payload: WorkspaceMemberAddRequest,
    service: WorkspaceServiceDep,
    users: UserServiceDep,
) -> WorkspaceMemberSummary:
    member = service.add_member(
        workspace_id,
        _current_user_id(),
        member_user_id=payload.user_id,
        role=payload.role,
    )
    user = users.get(member.user_id)
    return WorkspaceMemberSummary.from_record(
        member, username=user.username, display_name=user.display_name
    )


@router.patch(
    "/{workspace_id}/members/batch",
    response_model=WorkspaceMemberBatchUpdateResponse,
    summary="批量更新 Workspace 成员角色",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def batch_update_workspace_member_roles(
    workspace_id: int,
    payload: WorkspaceMemberBatchUpdateRequest,
    service: WorkspaceServiceDep,
    users: UserServiceDep,
) -> WorkspaceMemberBatchUpdateResponse:
    """Atomically update visible members and report absent user ids."""
    records, missing_user_ids = service.update_member_roles(
        workspace_id,
        _current_user_id(),
        updates=[(item.user_id, item.role) for item in payload.updates],
    )
    items = []
    for record in records:
        user = users.get(record.user_id)
        items.append(
            WorkspaceMemberSummary.from_record(
                record,
                username=user.username,
                display_name=user.display_name,
            )
        )
    return WorkspaceMemberBatchUpdateResponse(
        requested=len(payload.updates),
        updated=len(records),
        items=items,
        missing_user_ids=missing_user_ids,
    )


@router.patch(
    "/{workspace_id}/members/{member_user_id}",
    response_model=WorkspaceMemberSummary,
    summary="更新 Workspace 成员角色",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def update_workspace_member_role(
    workspace_id: int,
    member_user_id: int,
    payload: WorkspaceMemberUpdateRequest,
    service: WorkspaceServiceDep,
    users: UserServiceDep,
) -> WorkspaceMemberSummary:
    member = service.update_member_role(
        workspace_id,
        _current_user_id(),
        member_user_id=member_user_id,
        role=payload.role,
    )
    user = users.get(member.user_id)
    return WorkspaceMemberSummary.from_record(
        member, username=user.username, display_name=user.display_name
    )


@router.delete(
    "/{workspace_id}/members/batch",
    response_model=WorkspaceMemberBatchRemoveResponse,
    summary="批量移除 Workspace 成员",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def batch_remove_workspace_members(
    workspace_id: int,
    payload: WorkspaceMemberBatchRemoveRequest,
    service: WorkspaceServiceDep,
) -> WorkspaceMemberBatchRemoveResponse:
    """Atomically remove visible non-owner members and report absent user ids."""
    removed_ids, missing_user_ids = service.remove_members(
        workspace_id,
        _current_user_id(),
        member_user_ids=payload.user_ids,
    )
    return WorkspaceMemberBatchRemoveResponse(
        requested=len(payload.user_ids),
        removed=len(removed_ids),
        missing_user_ids=missing_user_ids,
    )


@router.delete(
    "/{workspace_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="移除 Workspace 成员",
    dependencies=[require(Permission.WORKSPACE_WRITE)],
)
async def remove_workspace_member(
    workspace_id: int,
    member_user_id: int,
    service: WorkspaceServiceDep,
) -> Response:
    service.remove_member(
        workspace_id,
        _current_user_id(),
        member_user_id=member_user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _member_list_response(
    workspace_id: int,
    service: WorkspaceServiceDep,
    user_id: int,
    *,
    page: int,
    page_size: int,
    cursor: KeysetCursor | None,
) -> WorkspaceMemberListResponse:
    members, total, next_cursor = service.list_members(
        workspace_id,
        user_id,
        page=page,
        page_size=page_size,
        cursor=cursor,
    )
    items = [
        WorkspaceMemberSummary.from_record(
            member,
            username=user.username if user is not None else "",
            display_name=user.display_name if user is not None else "",
        )
        for member, user in members
    ]
    return WorkspaceMemberListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        next_cursor=next_cursor,
    )
