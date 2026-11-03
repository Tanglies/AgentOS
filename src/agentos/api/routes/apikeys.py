"""API Key 管理路由。

数据库密钥带权限集合，明文只在签发响应中出现一次；列表接口只返回元数据。
列表按 ``id`` 升序返回，支持稳定的 keyset ``cursor`` 分页：游标记录上一页最后一条
记录的 id，翻页期间新增或吊销密钥都不会让客户端重复或跳过记录。
静态配置密钥被视为管理员，用于首次签发数据库密钥。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.auth import get_current_identity
from agentos.api.deps import ApiKeyStoreDep, require
from agentos.api.schemas import (
    ApiKeyBatchRevokeRequest,
    ApiKeyBatchRevokeResponse,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeySummary,
)
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import (
    KeysetCursor,
    decode_keyset_cursor,
    encode_keyset_cursor,
    ensure_cursor_order,
    ensure_cursor_row_id,
)
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.runtime.api_keys import Permission

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[require(Permission.API_KEY_ADMIN)],
)


@router.get("", response_model=ApiKeyListResponse, summary="列出 API Key")
async def list_api_keys(
    store: ApiKeyStoreDep,
    include_revoked: bool = Query(default=False, description="是否包含已吊销记录"),
    limit: int = Query(default=50, ge=1, le=500, description="每页数量"),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> ApiKeyListResponse:
    """返回密钥元数据，不包含明文与哈希；``next_cursor`` 为空表示已到末页。"""
    identity = get_current_identity()
    workspace_id = identity.workspace_id if identity else DEFAULT_WORKSPACE_ID
    after_id = None
    if cursor:
        position = decode_keyset_cursor(cursor)
        ensure_cursor_order(position.order, "asc")
        key_id = ensure_cursor_row_id(position.key)
        after_id = ensure_cursor_row_id(position.item_id)
        if key_id != after_id:
            # 排序键与记录 id 不一致，说明这个游标不是本列表发出的
            raise ValidationError(
                "invalid pagination cursor", details={"parameter": "cursor"}
            )
    # 多取一条用来判断是否还有下一页，避免末页再返回一个空页游标
    records = store.list(
        include_revoked=include_revoked,
        workspace_id=workspace_id,
        limit=limit + 1,
        after_id=after_id,
    )
    next_cursor = None
    if len(records) > limit:
        last = records[limit - 1]
        next_cursor = encode_keyset_cursor(
            KeysetCursor(key=str(last.id), item_id=str(last.id), order="asc")
        )
        records = records[:limit]
    return ApiKeyListResponse(
        items=[ApiKeySummary.from_record(record) for record in records],
        total=store.count(include_revoked=include_revoked, workspace_id=workspace_id),
        next_cursor=next_cursor,
    )


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="签发 API Key",
)
async def create_api_key(
    payload: ApiKeyCreateRequest, store: ApiKeyStoreDep
) -> ApiKeyCreateResponse:
    """签发新密钥；明文仅在本次响应返回，服务端只保存 SHA-256 哈希。"""
    identity = get_current_identity()
    user_id = identity.user_id if identity else DEFAULT_USER_ID
    workspace_id = identity.workspace_id if identity else DEFAULT_WORKSPACE_ID
    if identity is not None and identity.source == "config":
        user_id = payload.user_id or user_id
        workspace_id = payload.workspace_id or workspace_id
    result = store.issue(
        payload.name,
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=payload.permissions,
    )
    summary = ApiKeySummary.from_record(result.record)
    return ApiKeyCreateResponse(**summary.model_dump(), key=result.key)


@router.post(
    "/batch-revoke",
    response_model=ApiKeyBatchRevokeResponse,
    summary="批量吊销 API Key",
)
async def batch_revoke_api_keys(
    payload: ApiKeyBatchRevokeRequest, store: ApiKeyStoreDep
) -> ApiKeyBatchRevokeResponse:
    """Soft-delete visible active keys and report ids that were not revoked."""
    identity = get_current_identity()
    workspace_id = identity.workspace_id if identity else DEFAULT_WORKSPACE_ID
    revoked_ids = store.revoke_many(payload.ids, workspace_id=workspace_id)
    revoked_set = set(revoked_ids)
    return ApiKeyBatchRevokeResponse(
        requested=len(payload.ids),
        revoked=len(revoked_ids),
        missing_ids=[key_id for key_id in payload.ids if key_id not in revoked_set],
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="吊销 API Key",
)
async def revoke_api_key(key_id: int, store: ApiKeyStoreDep) -> Response:
    """软删除密钥，保留记录用于审计。"""
    identity = get_current_identity()
    workspace_id = identity.workspace_id if identity else DEFAULT_WORKSPACE_ID
    store.revoke(key_id, workspace_id=workspace_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
