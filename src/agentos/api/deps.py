"""FastAPI 依赖注入。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from agentos.api.auth import get_current_identity
from agentos.core.config import Settings
from agentos.core.exceptions import PermissionDeniedError
from agentos.llm.base import LLMClient
from agentos.runtime.api_keys import ApiKeyStore, Permission
from agentos.runtime.runtime import AgentRuntime
from agentos.runtime.services.agent_service import AgentService
from agentos.runtime.services.dashboard_service import DashboardService
from agentos.runtime.services.user_service import UserService
from agentos.runtime.services.workspace_service import WorkspaceService


def get_app_settings(request: Request) -> Settings:
    """从应用状态读取配置。"""
    return request.app.state.settings


def get_runtime(request: Request) -> AgentRuntime:
    """从应用状态读取 Agent Runtime。"""
    return request.app.state.runtime


def get_llm_client(request: Request) -> LLMClient:
    """从应用状态读取 LLM 客户端。"""
    return request.app.state.llm_client


def get_agent_service(request: Request) -> AgentService:
    """从应用状态读取 Agent 生命周期服务。"""
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise PermissionDeniedError(
            "agent service is not initialized",
            details={"hint": "create the application through create_app lifespan"},
        )
    return service


def get_user_service(request: Request) -> UserService:
    """Return the platform user service."""
    service = getattr(request.app.state, "user_service", None)
    if service is None:
        raise PermissionDeniedError(
            "user service is not initialized",
            details={"hint": "create the application through create_app lifespan"},
        )
    return service


def get_workspace_service(request: Request) -> WorkspaceService:
    """Return the Workspace lifecycle service."""
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise PermissionDeniedError(
            "workspace service is not initialized",
            details={"hint": "create the application through create_app lifespan"},
        )
    return service


def get_dashboard_service(request: Request) -> DashboardService:
    """从应用状态读取 Dashboard 只读服务。"""
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise PermissionDeniedError(
            "dashboard service is not initialized",
            details={"hint": "create the application through create_app lifespan"},
        )
    return service


def get_api_key_store(request: Request) -> ApiKeyStore:
    """从应用状态读取 API Key 存储。"""
    store = getattr(request.app.state, "api_key_store", None)
    if store is None:
        raise PermissionDeniedError(
            "api key management is disabled",
            details={"hint": "enable AGENTOS_AUTH__ENABLED and AGENTOS_API_KEYS__ENABLED"},
        )
    return store


def require(permission: Permission) -> Any:
    """构造一个路由级权限依赖。

    ``require`` 返回的是 ``Depends`` 对象，调用方应把它放进
    ``APIRouter(... dependencies=[...])`` 或路由装饰器。认证关闭时放行，
    保持本地开发与嵌入式运行不受影响；认证开启时缺少身份或权限即返回 403。
    """

    def _check(request: Request) -> None:
        settings: Settings = request.app.state.settings
        if not settings.auth.enabled:
            return
        identity = get_current_identity()
        if identity is None or not identity.can(permission):
            raise PermissionDeniedError(
                "permission denied",
                details={"required": permission.value},
            )

    return Depends(_check)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RuntimeDep = Annotated[AgentRuntime, Depends(get_runtime)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
ApiKeyStoreDep = Annotated[ApiKeyStore, Depends(get_api_key_store)]
