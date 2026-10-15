"""长期记忆路由。

长期记忆跨会话保留，落盘在 SQLite。这里提供程序化读写接口，
Agent 运行时也可以通过 ``remember`` / ``recall`` 工具自行维护。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import RuntimeDep, require
from agentos.api.schemas import MemoryCreateRequest, MemoryListResponse, MemorySummary
from agentos.core.exceptions import NotFoundError, ValidationError
from agentos.core.pagination import (
    PaginationCursor,
    decode_cursor,
    encode_cursor,
    ensure_cursor_order,
)
from agentos.runtime.api_keys import Permission
from agentos.runtime.long_term_memory import LongTermMemory

router = APIRouter(prefix="/memories", tags=["memories"])
_MAX_SQLITE_ROW_ID = 2**63 - 1


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
        try:
            memory_id = int(position.item_id)
        except ValueError as exc:
            raise ValidationError(
                "invalid pagination cursor", details={"parameter": "cursor"}
            ) from exc
        if not 1 <= memory_id <= _MAX_SQLITE_ROW_ID:
            raise ValidationError(
                "invalid pagination cursor", details={"parameter": "cursor"}
            )
        position = PaginationCursor(
            created_at=position.created_at,
            item_id=str(memory_id),
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
