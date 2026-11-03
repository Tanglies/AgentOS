"""长期记忆路由。

长期记忆跨会话保留，落盘在 SQLite。这里提供程序化读写接口，
Agent 运行时也可以通过 ``remember`` / ``recall`` 工具自行维护。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import RuntimeDep, require
from agentos.api.schemas import (
    MemoryBatchDeleteRequest,
    MemoryBatchDeleteResponse,
    MemoryBatchUpdateRequest,
    MemoryBatchUpdateResponse,
    MemoryCreateRequest,
    MemoryListResponse,
    MemorySummary,
    MemoryUpdateRequest,
)
from agentos.core.exceptions import NotFoundError
from agentos.core.pagination import (
    PaginationCursor,
    decode_cursor,
    encode_cursor,
    ensure_cursor_order,
    ensure_cursor_row_id,
)
from agentos.runtime.api_keys import Permission
from agentos.runtime.long_term_memory import LongTermMemory

router = APIRouter(prefix="/memories", tags=["memories"])


def _require_memory(runtime: RuntimeDep) -> LongTermMemory:
    """长期记忆被关闭时返回明确错误，而不是静默当成空库。"""
    memory = runtime.long_term
    if memory is None:
        raise NotFoundError(
            "long-term memory is disabled",
            details={"hint": "set AGENTOS_MEMORY__LONG_TERM_ENABLED=true"},
        )
    return memory


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="列出长期记忆",
    dependencies=[require(Permission.MEMORY_READ)],
)
async def list_memories(
    runtime: RuntimeDep,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> MemoryListResponse:
    memory = _require_memory(runtime)
    position = decode_cursor(cursor) if cursor else None
    if position is not None:
        ensure_cursor_order(position.order, "desc")
        position = PaginationCursor(
            created_at=position.created_at,
            item_id=str(ensure_cursor_row_id(position.item_id)),
            order="desc",
        )

    records = memory.list(limit=limit + 1, cursor=position)
    next_cursor = None
    if len(records) > limit:
        last = records[limit - 1]
        next_cursor = encode_cursor(
            PaginationCursor(
                created_at=last.created_at,
                item_id=str(last.id),
                order="desc",
            )
        )
    items = [MemorySummary.from_record(record) for record in records[:limit]]
    return MemoryListResponse(
        items=items,
        total=memory.count(),
        next_cursor=next_cursor,
    )


@router.post(
    "/batch-delete",
    response_model=MemoryBatchDeleteResponse,
    summary="批量删除长期记忆",
    dependencies=[require(Permission.MEMORY_WRITE)],
)
async def batch_delete_memories(
    payload: MemoryBatchDeleteRequest, runtime: RuntimeDep
) -> MemoryBatchDeleteResponse:
    """删除当前租户可见的指定记忆，并报告未找到的 id。"""
    memory = _require_memory(runtime)
    removed_ids = memory.forget_many(payload.ids)
    removed_set = set(removed_ids)
    return MemoryBatchDeleteResponse(
        requested=len(payload.ids),
        deleted=len(removed_ids),
        missing_ids=[memory_id for memory_id in payload.ids if memory_id not in removed_set],
    )


@router.patch(
    "/batch",
    response_model=MemoryBatchUpdateResponse,
    summary="批量更新长期记忆",
    dependencies=[require(Permission.MEMORY_WRITE)],
)
async def batch_update_memories(
    payload: MemoryBatchUpdateRequest, runtime: RuntimeDep
) -> MemoryBatchUpdateResponse:
    """Update visible memories and report ids that were not found."""
    memory = _require_memory(runtime)
    updates = [(item.id, item.to_patch()) for item in payload.updates]
    records = memory.update_many(updates)
    updated_ids = {record.id for record in records}
    return MemoryBatchUpdateResponse(
        requested=len(payload.updates),
        updated=len(records),
        items=[MemorySummary.from_record(record) for record in records],
        missing_ids=[
            item.id for item in payload.updates if item.id not in updated_ids
        ],
    )


@router.patch(
    "/{memory_id}",
    response_model=MemorySummary,
    summary="部分更新长期记忆",
    dependencies=[require(Permission.MEMORY_WRITE)],
)
async def update_memory(
    memory_id: int, payload: MemoryUpdateRequest, runtime: RuntimeDep
) -> MemorySummary:
    """Update one visible memory while preserving omitted fields."""
    memory = _require_memory(runtime)
    records = memory.update_many([(memory_id, payload.to_patch())])
    if not records:
        raise NotFoundError(
            f"memory not found: {memory_id}", details={"memory_id": memory_id}
        )
    return MemorySummary.from_record(records[0])


@router.post(
    "",
    response_model=MemorySummary,
    status_code=status.HTTP_201_CREATED,
    summary="写入一条长期记忆",
    dependencies=[require(Permission.MEMORY_WRITE)],
)
async def create_memory(
    payload: MemoryCreateRequest, runtime: RuntimeDep
) -> MemorySummary:
    memory = _require_memory(runtime)
    record = memory.remember(
        payload.content, session_id=payload.session_id, scope=payload.scope
    )
    return MemorySummary.from_record(record)


@router.delete(
    "/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除一条长期记忆",
    dependencies=[require(Permission.MEMORY_WRITE)],
)
async def delete_memory(memory_id: int, runtime: RuntimeDep) -> Response:
    memory = _require_memory(runtime)
    if not memory.forget(memory_id):
        raise NotFoundError(
            f"memory not found: {memory_id}", details={"memory_id": memory_id}
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
