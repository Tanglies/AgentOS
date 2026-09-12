"""Agent 管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import AgentServiceDep, require
from agentos.api.schemas import AgentCreateRequest, AgentListResponse, AgentSummary
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get(
    "",
    response_model=AgentListResponse,
    summary="分页列出 Agent",
    dependencies=[require(Permission.AGENT_READ)],
)
async def list_agents(
    service: AgentServiceDep,
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=500, description="每页数量"),
) -> AgentListResponse:
    """按名称分页返回全部 Agent 及其持久化元数据。"""
    records, total = service.list(page=page, page_size=page_size)
    return AgentListResponse(
        items=[AgentSummary.from_record(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=AgentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="创建 Agent",
    dependencies=[require(Permission.AGENT_WRITE)],
)
async def create_agent(
    payload: AgentCreateRequest, service: AgentServiceDep
) -> AgentSummary:
    """创建 Agent，业务校验与审计由服务层处理。"""
    return AgentSummary.from_record(service.create(payload.to_agent()))


@router.get(
    "/{name}",
    response_model=AgentSummary,
    summary="获取单个 Agent",
    dependencies=[require(Permission.AGENT_READ)],
)
async def get_agent(name: str, service: AgentServiceDep) -> AgentSummary:
    """返回 Agent 的完整配置与生命周期元数据。"""
    return AgentSummary.from_record(service.get(name))


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 Agent",
    dependencies=[require(Permission.AGENT_WRITE)],
)
async def delete_agent(name: str, service: AgentServiceDep) -> Response:
    """删除 Agent，不存在时由服务层返回 404。"""
    service.delete(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
