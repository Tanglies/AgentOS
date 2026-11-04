"""Platform user management routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from agentos.api.deps import UserServiceDep, require
from agentos.api.schemas import UserCreateRequest, UserListResponse, UserSummary
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import decode_keyset_cursor
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
    page: int | None = Query(default=None, ge=1, description="页码，从 1 开始"),
    page_size: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="每页数量",
    ),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> UserListResponse:
    """按用户 id 返回稳定的 cursor 分页，同时保留 page/page_size。"""
    if cursor and page is not None:
        raise ValidationError(
            "cursor cannot be combined with page",
            details={"parameter": "cursor"},
        )
    resolved_page = 1 if cursor else (page or 1)
    resolved_page_size = page_size or 100
    position = decode_keyset_cursor(cursor) if cursor else None
    records, total, next_cursor = service.list(
        page=resolved_page,
        page_size=resolved_page_size,
        cursor=position,
    )
    return UserListResponse(
        items=[UserSummary.from_record(record) for record in records],
        total=total,
        page=resolved_page,
        page_size=resolved_page_size,
        next_cursor=next_cursor,
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
