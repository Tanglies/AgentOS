"""工作区工具可见性路由。"""

from __future__ import annotations

from fastapi import APIRouter

from agentos.api.deps import RuntimeDep, ToolPolicyServiceDep, require
from agentos.api.schemas import ToolListResponse, ToolSummary, ToolUpdateRequest
from agentos.runtime.api_keys import Permission

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    response_model=ToolListResponse,
    summary="列出当前 Workspace 可见工具",
    dependencies=[require(Permission.TOOL_READ)],
)
async def list_tools(
    runtime: RuntimeDep,
    policy: ToolPolicyServiceDep,
) -> ToolListResponse:
    items = [
        ToolSummary.from_tool(tool, enabled=enabled)
        for tool, enabled in policy.list_workspace_tools(runtime.tools)
    ]
    return ToolListResponse(items=items, total=len(items))


@router.patch(
    "/{name}",
    response_model=ToolSummary,
    summary="启用或禁用 Workspace 工具",
    dependencies=[require(Permission.TOOL_ADMIN)],
)
async def update_tool(
    name: str,
    payload: ToolUpdateRequest,
    runtime: RuntimeDep,
    policy: ToolPolicyServiceDep,
) -> ToolSummary:
    policy.set_workspace_tool(runtime.tools, name, enabled=payload.enabled)
    tool, enabled = next(
        item for item in policy.list_workspace_tools(runtime.tools) if item[0].name == name
    )
    return ToolSummary.from_tool(tool, enabled=enabled)
