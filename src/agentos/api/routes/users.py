"""Platform user management routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from agentos.api.deps import UserServiceDep, require
from agentos.api.schemas import UserCreateRequest, UserListResponse, UserSummary
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=UserListResponse,
    summary="列出平台用户",
    dependencies=[require(Permission.USER_READ)],
)
async def list_users(
    service: UserServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> UserListResponse:
    records, total = service.list(
        limit=page_size, offset=(page - 1) * page_size
    )
    return UserListResponse(
        items=[UserSummary.from_record(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=UserSummary,
    status_code=status.HTTP_201_CREATED,
    summary="创建平台用户",
    dependencies=[require(Permission.USER_WRITE)],
)
async def create_user(payload: UserCreateRequest, service: UserServiceDep) -> UserSummary:
    return UserSummary.from_record(
        service.create(
            payload.username,
            display_name=payload.display_name,
            status=payload.status,
        )
    )


@router.get(
    "/{user_id}",
    response_model=UserSummary,
    summary="获取平台用户",
    dependencies=[require(Permission.USER_READ)],
)
async def get_user(user_id: int, service: UserServiceDep) -> UserSummary:
    return UserSummary.from_record(service.get(user_id))
