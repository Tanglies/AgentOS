"""API Key 管理路由。

数据库密钥带权限集合，明文只在签发响应中出现一次；列表接口只返回元数据。
静态配置密钥被视为管理员，用于首次签发数据库密钥。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import ApiKeyStoreDep, require
from agentos.api.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeySummary,
)
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
) -> ApiKeyListResponse:
    """返回密钥元数据，不包含明文与哈希。"""
    records = store.list(include_revoked=include_revoked)
    return ApiKeyListResponse(
        items=[ApiKeySummary.from_record(record) for record in records],
        total=len(records),
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
    result = store.issue(payload.name, permissions=payload.permissions)
    summary = ApiKeySummary.from_record(result.record)
    return ApiKeyCreateResponse(**summary.model_dump(), key=result.key)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="吊销 API Key",
)
async def revoke_api_key(key_id: int, store: ApiKeyStoreDep) -> Response:
    """软删除密钥，保留记录用于审计。"""
    store.revoke(key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
