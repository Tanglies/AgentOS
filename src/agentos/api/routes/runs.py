"""Agent 运行路由。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agentos.api.deps import RuntimeDep, SettingsDep
from agentos.api.schemas import RunRequest, RunResponse
from agentos.core.exceptions import AgentOSError
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
