"""Agent 管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from agentos.api.deps import RuntimeDep
from agentos.api.schemas import AgentCreateRequest, AgentListResponse, AgentSummary

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentListResponse, summary="列出全部 Agent")
async def list_agents(runtime: RuntimeDep) -> AgentListResponse:
    items = [AgentSummary.from_agent(agent) for agent in runtime.registry.list()]
    return AgentListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=AgentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="注册 Agent",
)
async def create_agent(payload: AgentCreateRequest, runtime: RuntimeDep) -> AgentSummary:
    agent = runtime.registry.register(payload.to_agent())
    return AgentSummary.from_agent(agent)


@router.get("/{name}", response_model=AgentSummary, summary="获取单个 Agent")
async def get_agent(name: str, runtime: RuntimeDep) -> AgentSummary:
    return AgentSummary.from_agent(runtime.registry.get(name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="注销 Agent")
async def delete_agent(name: str, runtime: RuntimeDep) -> Response:
    runtime.registry.unregister(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)