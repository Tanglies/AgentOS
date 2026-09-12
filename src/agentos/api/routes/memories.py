"""长期记忆路由。

长期记忆跨会话保留，落盘在 SQLite。这里提供程序化读写接口，
Agent 运行时也可以通过 ``remember`` / ``recall`` 工具自行维护。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import RuntimeDep, require
from agentos.api.schemas import MemoryCreateRequest, MemoryListResponse, MemorySummary
from agentos.core.exceptions import NotFoundError
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
    runtime: RuntimeDep, limit: int = Query(default=50, ge=1, le=500)
) -> MemoryListResponse:
    memory = _require_memory(runtime)
    items = [MemorySummary.from_record(record) for record in memory.list(limit=limit)]
    return MemoryListResponse(items=items, total=memory.count())


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
