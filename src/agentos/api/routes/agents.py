"""Agent 管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from agentos.api.deps import AgentServiceDep, RuntimeDep, ToolPolicyServiceDep, require
from agentos.api.schemas import (
    AgentCreateRequest,
    AgentListResponse,
    AgentSummary,
    ToolListResponse,
    ToolSummary,
    ToolUpdateRequest,
)
from agentos.core.exceptions import ValidationError
from agentos.core.pagination import (
    decode_keyset_cursor,
    ensure_cursor_order,
)
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/agents", tags=["agents"])

#: Agent 列表始终按名称升序返回，cursor 也必须使用相同方向
AGENT_ORDER = "asc"


@router.get(
    "",
    response_model=AgentListResponse,
    summary="分页列出 Agent",
    dependencies=[require(Permission.AGENT_READ)],
)
async def list_agents(
    service: AgentServiceDep,
    page: int | None = Query(default=None, ge=1, description="页码，从 1 开始"),
    page_size: int | None = Query(default=None, ge=1, le=500, description="每页数量"),
    cursor: str | None = Query(default=None, description="上一页返回的 next_cursor"),
) -> AgentListResponse:
    """按名称返回 Agent，兼容 page/page_size 与稳定的 cursor 分页。"""
    if cursor and page is not None:
        raise ValidationError(
            "cursor cannot be combined with page",
            details={"parameter": "cursor"},
        )
    resolved_page = 1 if cursor else (page or 1)
    resolved_page_size = page_size or 20
    position = decode_keyset_cursor(cursor) if cursor else None
    if position is not None:
        ensure_cursor_order(position.order, AGENT_ORDER)
    records, total, next_cursor = service.list(
        page=resolved_page,
        page_size=resolved_page_size,
        cursor=position,
        order=AGENT_ORDER,
    )
    return AgentListResponse(
        items=[AgentSummary.from_record(record) for record in records],
        total=total,
        page=resolved_page,
        page_size=resolved_page_size,
        next_cursor=next_cursor,
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


@router.get(
    "/{name}/tools",
    response_model=ToolListResponse,
    summary="列出 Agent 可用工具",
    dependencies=[require(Permission.TOOL_READ)],
)
async def list_agent_tools(
    name: str,
    service: AgentServiceDep,
    runtime: RuntimeDep,
    policy: ToolPolicyServiceDep,
) -> ToolListResponse:
    """返回 Agent 在当前 Workspace 下的工具可见性。"""
    service.get(name)
    items = [
        ToolSummary.from_tool(tool, enabled=enabled)
        for tool, enabled in policy.agent_tool_status(
            runtime.registry, runtime.tools, name
        )
    ]
    return ToolListResponse(items=items, total=len(items))


@router.patch(
    "/{name}/tools/{tool_name}",
    response_model=ToolSummary,
    summary="启用或禁用 Agent 工具",
    dependencies=[require(Permission.TOOL_ADMIN)],
)
async def update_agent_tool(
    name: str,
    tool_name: str,
    payload: ToolUpdateRequest,
    service: AgentServiceDep,
    runtime: RuntimeDep,
    policy: ToolPolicyServiceDep,
) -> ToolSummary:
    """设置 Agent 级 Tool override。"""
    service.get(name)
    policy.set_agent_tool(
        runtime.registry,
        runtime.tools,
        name,
        tool_name,
        enabled=payload.enabled,
    )
    tool, enabled = next(
        item
        for item in policy.agent_tool_status(runtime.registry, runtime.tools, name)
        if item[0].name == tool_name
    )
    return ToolSummary.from_tool(tool, enabled=enabled)


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
