"""Workspace lifecycle and membership routes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from agentos.api.deps import UserServiceDep, WorkspaceServiceDep, require
from agentos.api.schemas import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceMemberAddRequest,
    WorkspaceMemberListResponse,
    WorkspaceMemberSummary,
    WorkspaceSummary,
    WorkspaceUpdateRequest,
)
from agentos.core.context import get_user_id
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
async def list_workspaces(service: WorkspaceServiceDep) -> WorkspaceListResponse:
    user_id = _current_user_id()
    workspaces = service.list(user_id)
    return WorkspaceListResponse(
        items=[
            WorkspaceSummary.from_record(
                workspace, role=service.role(workspace.id or 0, user_id)
            )
            for workspace in workspaces
        ],
        total=len(workspaces),
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
    workspace_id: int, service: WorkspaceServiceDep
) -> WorkspaceMemberListResponse:
    return _member_list_response(workspace_id, service, _current_user_id())


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
) -> WorkspaceMemberListResponse:
    items = [
        WorkspaceMemberSummary.from_record(
            member,
            username=user.username if user is not None else "",
            display_name=user.display_name if user is not None else "",
        )
        for member, user in service.list_members(workspace_id, user_id)
    ]
    return WorkspaceMemberListResponse(items=items, total=len(items))
