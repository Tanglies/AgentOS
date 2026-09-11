"""工具管理路由。

工具由服务端代码注册（避免通过 HTTP 注入可执行代码），
本路由只提供只读查询，供前端与调试使用。
"""

from __future__ import annotations

from fastapi import APIRouter

from agentos.api.deps import RuntimeDep
from agentos.api.schemas import ToolListResponse, ToolSummary

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse, summary="列出全部工具")
async def list_tools(runtime: RuntimeDep) -> ToolListResponse:
    items = [ToolSummary.from_tool(tool) for tool in runtime.tools.list()]
    return ToolListResponse(items=items, total=len(items))