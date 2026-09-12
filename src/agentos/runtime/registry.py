"""进程内 Agent 注册表。

v0.1 使用内存实现；后续可替换为数据库或配置中心支持的实现，接口保持不变。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from agentos.core.config import RuntimeSettings
from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.runtime.agent import Agent
from agentos.runtime.sqlite_registry import SQLiteAgentRegistry


class AgentRegistry:
    """线程内的 Agent 注册表。"""

    def __init__(self, agents: Iterable[Agent] | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        for agent in agents or ():
            self.register(agent)

    def register(self, agent: Agent, *, overwrite: bool = False) -> Agent:
        """注册 Agent；重名时默认抛 :class:`ConflictError`。"""
        if agent.name in self._agents and not overwrite:
            raise ConflictError(
                f"agent already registered: {agent.name}", details={"agent": agent.name}
            )
        self._agents[agent.name] = agent
        return agent

    def unregister(self, name: str) -> None:
        """注销 Agent，不存在时报错。"""
        if name not in self._agents:
            raise NotFoundError(f"agent not found: {name}", details={"agent": name})
        del self._agents[name]

    def delete(self, name: str) -> None:
        """Delete an Agent; ``unregister`` remains a compatibility alias."""
        self.unregister(name)

    def get(self, name: str) -> Agent:
        """按名称获取 Agent。"""
        try:
            return self._agents[name]
        except KeyError as exc:
            raise NotFoundError(
                f"agent not found: {name}",
                details={"agent": name, "available": sorted(self._agents)},
            ) from exc

    def list(self) -> list[Agent]:
        """返回全部 Agent（按名称排序）。"""
        return [self._agents[name] for name in sorted(self._agents)]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._agents

    def __len__(self) -> int:
        return len(self._agents)


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
    """按配置创建注册表。

    ``persist_path`` 为空时使用内存实现；否则用 SQLite，
    并且在默认 Agent 缺失时补种一个（已有的不会被覆盖）。
    """
    if not persist_path:
        return create_default_registry(settings, tools=tools)

    registry = SQLiteAgentRegistry(persist_path)
    if settings.default_agent not in registry:
        registry.register(build_default_agent(settings, tools=tools))
    return registry
