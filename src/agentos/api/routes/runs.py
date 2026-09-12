"""Agent 运行路由。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from agentos.api.deps import RuntimeDep, SettingsDep
from agentos.api.schemas import (
    RunDetail,
    RunListResponse,
    RunRequest,
    RunResponse,
    RunSummary,
)
from agentos.core.exceptions import AgentOSError, NotFoundError
from agentos.runtime.run_store import RunStatus
from agentos.runtime.runtime import RunEvent

router = APIRouter(prefix="/runs", tags=["runs"])

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    # 关闭 Nginx 等反向代理的缓冲，否则前端会等到整段结束才收到内容
    "x-accel-buffering": "no",
}


def _format_sse(event: RunEvent) -> str:
    """按 SSE 协议格式化一个事件。"""
    payload = event.model_dump(mode="json", exclude_none=True)
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event.type}\ndata: {data}\n\n"


def _format_error(code: str, message: str, status_code: int) -> str:
    payload = {"type": "error", "error": message, "code": code, "status_code": status_code}
    return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("", response_model=RunResponse, summary="执行一次 Agent 运行")
async def create_run(
    payload: RunRequest, runtime: RuntimeDep, settings: SettingsDep
) -> RunResponse:
    agent_name = payload.agent or settings.runtime.default_agent
    result = await runtime.run(
        agent_name,
        payload.input,
        history=payload.history,
        session_id=payload.session_id,
    )
    return RunResponse.from_result(result)


@router.post("/stream", summary="流式执行一次 Agent 运行（SSE）")
async def create_run_stream(
    payload: RunRequest, runtime: RuntimeDep, settings: SettingsDep
) -> StreamingResponse:
    """以 Server-Sent Events 逐段推送运行过程。

    事件类型：``start`` / ``delta`` / ``tool_call`` / ``tool_result`` / ``end`` / ``error``。
    """
    agent_name = payload.agent or settings.runtime.default_agent

    async def event_source() -> AsyncIterator[str]:
        emitted_error = False
        try:
            async for event in runtime.run_stream(
                agent_name,
                payload.input,
                history=payload.history,
                session_id=payload.session_id,
            ):
                if event.type == "error":
                    emitted_error = True
                yield _format_sse(event)
        except AgentOSError as exc:
            # 生成器内部的异常早于任何事件时，补一个 error 事件再结束
            if not emitted_error:
                yield _format_error(exc.code, exc.message, exc.status_code)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免连接被直接掐断
            if not emitted_error:
                yield _format_error("internal_error", str(exc), 500)

    return StreamingResponse(
        event_source(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS
    )


def _require_run_store(runtime: RuntimeDep) -> object:
    """运行记录被关闭时给出明确错误，而不是静默返回空列表。"""
    store = runtime.runs
    if store is None:
        raise NotFoundError(
            "run history is disabled",
            details={"hint": "set AGENTOS_RUNS__ENABLED=true"},
        )
    return store


@router.get("", response_model=RunListResponse, summary="查询运行历史")
async def list_runs(
    runtime: RuntimeDep,
    agent: str | None = Query(default=None, description="按 Agent 名过滤"),
    session_id: str | None = Query(default=None, description="按会话过滤"),
    status: Annotated[RunStatus | None, Query(description="按状态过滤")] = None,
    order: Annotated[str, Query(pattern="^(asc|desc)$", description="按时间排序")] = "desc",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> RunListResponse:
    """按时间倒序返回运行记录（不含消息列表）。"""
    store = _require_run_store(runtime)
    records = store.list(  # type: ignore[attr-defined]
        agent=agent,
        session_id=session_id,
        status=status,
        order=order,
        limit=limit,
        offset=offset,
    )
    return RunListResponse(
        items=[RunSummary.from_record(record) for record in records],
        total=store.count(agent=agent, session_id=session_id, status=status),  # type: ignore[attr-defined]
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=RunDetail, summary="查看运行详情")
async def get_run(run_id: str, runtime: RuntimeDep) -> RunDetail:
    """返回单次运行的完整记录，含消息轨迹与 token 明细。"""
    store = _require_run_store(runtime)
    return RunDetail.from_record(store.get(run_id))  # type: ignore[attr-defined]
