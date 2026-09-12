"""进程内 Agent 注册表。

注册表按 ``(workspace_id, name)`` 隔离，未显式传 Workspace 时从请求上下文
读取，旧测试和嵌入式调用则回退到 default workspace。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from agentos.core.config import RuntimeSettings
from agentos.core.context import get_workspace_id
from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.agent import Agent
from agentos.runtime.sqlite_registry import SQLiteAgentRegistry


class AgentRegistry:
    """进程内、Workspace 隔离的 Agent 注册表。"""

    def __init__(self, agents: Iterable[Agent] | None = None) -> None:
        self._agents: dict[tuple[int, str], Agent] = {}
        for agent in agents or ():
            self.register(agent)

    @staticmethod
    def _scope(workspace_id: int | None) -> int:
        return workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID

    def register(
        self,
        agent: Agent,
        *,
        overwrite: bool = False,
        workspace_id: int | None = None,
    ) -> Agent:
        """注册 Agent；同名只在当前 Workspace 内检查冲突。"""
        scope = self._scope(workspace_id)
        key = (scope, agent.name)
        if key in self._agents and not overwrite:
            raise ConflictError(
                f"agent already registered: {agent.name}",
                details={"agent": agent.name, "workspace_id": scope},
            )
        self._agents[key] = agent
        return agent

    def unregister(self, name: str, *, workspace_id: int | None = None) -> None:
        scope = self._scope(workspace_id)
        key = (scope, name)
        if key not in self._agents:
            raise NotFoundError(
                f"agent not found: {name}",
                details={"agent": name, "workspace_id": scope},
            )
        del self._agents[key]

    def delete(self, name: str, *, workspace_id: int | None = None) -> None:
        """Delete an Agent; ``unregister`` remains a compatibility alias."""
        self.unregister(name, workspace_id=workspace_id)

    def get(self, name: str, *, workspace_id: int | None = None) -> Agent:
        scope = self._scope(workspace_id)
        try:
            return self._agents[(scope, name)]
        except KeyError as exc:
            available = sorted(key[1] for key in self._agents if key[0] == scope)
            raise NotFoundError(
                f"agent not found: {name}",
                details={
                    "agent": name,
                    "workspace_id": scope,
                    "available": available,
                },
            ) from exc

    def list(self, *, workspace_id: int | None = None) -> list[Agent]:
        scope = self._scope(workspace_id)
        return [
            self._agents[(scope, name)]
            for name in sorted(key[1] for key in self._agents if key[0] == scope)
        ]

    def __contains__(self, name: object) -> bool:
        return (
            isinstance(name, str)
            and (self._scope(None), name) in self._agents
        )

    def __len__(self) -> int:
        scope = self._scope(None)
        return sum(1 for key in self._agents if key[0] == scope)


def build_default_agent(
    settings: RuntimeSettings, *, tools: Sequence[str] = ()
) -> Agent:
    """构造内置的默认助手 Agent。"""
    return Agent(
        name=settings.default_agent,
        description="AgentOS 内置通用助手，用于验证服务链路。",
        system_prompt=settings.system_prompt,
        tools=list(tools),
    )


def create_default_registry(
    settings: RuntimeSettings, *, tools: Sequence[str] = ()
) -> AgentRegistry:
    """创建包含默认助手 Agent 的**内存**注册表。"""
    return AgentRegistry([build_default_agent(settings, tools=tools)])


def build_registry(
    settings: RuntimeSettings,
    *,
    tools: Sequence[str] = (),
    persist_path: str | None = None,
) -> AgentRegistry | SQLiteAgentRegistry:
    """按配置创建注册表并在默认 Agent 缺失时补种。"""
    if not persist_path:
        return create_default_registry(settings, tools=tools)

    registry = SQLiteAgentRegistry(persist_path)
    if settings.default_agent not in registry:
        registry.register(build_default_agent(settings, tools=tools))
    return registry
