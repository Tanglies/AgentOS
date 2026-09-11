"""Agent 运行路由。"""

from __future__ import annotations

from fastapi import APIRouter

from agentos.api.deps import RuntimeDep, SettingsDep
from agentos.api.schemas import RunRequest, RunResponse

router = APIRouter(prefix="/runs", tags=["runs"])


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