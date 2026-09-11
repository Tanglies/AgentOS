"""会话记忆路由。

会话记忆当前是进程内实现，重启即清空。这些接口用于查看与清理
``session_id`` 对应的短期记忆，便于调试多轮对话。
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from agentos.api.deps import RuntimeDep
from agentos.api.schemas import SessionDetail, SessionListResponse, SessionSummary
from agentos.core.exceptions import NotFoundError
from agentos.runtime.memory import SessionState

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _require_session(session_id: str, runtime: RuntimeDep) -> SessionState:
    state = runtime.memory.get(session_id)
    if state is None:
        raise NotFoundError(
            f"session not found: {session_id}", details={"session_id": session_id}
        )
    return state


@router.get("", response_model=SessionListResponse, summary="列出全部会话")
async def list_sessions(runtime: RuntimeDep) -> SessionListResponse:
    items = [SessionSummary.from_state(state) for state in runtime.memory.list()]
    return SessionListResponse(items=items, total=len(items))


@router.get("/{session_id}", response_model=SessionDetail, summary="获取会话详情")
async def get_session(session_id: str, runtime: RuntimeDep) -> SessionDetail:
    return SessionDetail.from_state(_require_session(session_id, runtime))


@router.delete(
    "/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="清除会话记忆"
)
async def delete_session(session_id: str, runtime: RuntimeDep) -> Response:
    _require_session(session_id, runtime)
    runtime.memory.clear(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)