"""把 Agent 定义持久化到 SQLite 的注册表。

接口与内存版 :class:`~agentos.runtime.registry.AgentRegistry` 一致，
区别是进程重启后 Agent 不会丢失。

数据访问委托给 :class:`~agentos.runtime.repositories.AgentRepository`，
本模块只负责注册表语义：重名冲突、不存在报错。

.. note::

   Agent 定义整体序列化成 JSON 存 ``payload`` 列，而不是逐字段建列 ——
   Agent 还在快速演进（工具、记忆、规划都会往上挂），
   JSON 列免去每加一个字段就改表结构。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.database.connection import Database
from agentos.runtime.agent import Agent
from agentos.runtime.repositories import AGENTS_SCHEMA, AgentRepository


class SQLiteAgentRegistry:
    """基于 SQLite 的 Agent 注册表。"""

    def __init__(self, db_path: str, agents: Iterable[Agent] | None = None) -> None:
        self.path = Path(db_path).expanduser()
        self._db = Database(self.path, schema=AGENTS_SCHEMA)
        self._repo = AgentRepository(self._db)
        for agent in agents or ():
            self.register(agent)

    @property
    def repository(self) -> AgentRepository:
        """Expose the persistence repository for platform services."""
        return self._repo

    def register(self, agent: Agent, *, overwrite: bool = False) -> Agent:
        """注册 Agent；重名时默认抛 :class:`ConflictError`。"""
        if self._repo.exists(agent.name):
            if not overwrite:
                raise ConflictError(
                    f"agent already registered: {agent.name}",
                    details={"agent": agent.name},
                )
            self._repo.replace(agent, updated_at=datetime.now(UTC))
        else:
            self._repo.add(agent, created_at=datetime.now(UTC))
        return agent

    def unregister(self, name: str) -> None:
        """注销 Agent，不存在时报错。"""
        if not self._repo.remove(name):
            raise NotFoundError(f"agent not found: {name}", details={"agent": name})

    def delete(self, name: str) -> None:
        """Delete an Agent; ``unregister`` remains a compatibility alias."""
        self.unregister(name)

    def get(self, name: str) -> Agent:
        """按名称获取 Agent。"""
        agent = self._repo.get(name)
        if agent is None:
            raise NotFoundError(
                f"agent not found: {name}",
                details={"agent": name, "available": self._repo.names()},
            )
        return agent

    def list(self) -> list[Agent]:
        """返回全部 Agent（按名称排序）。"""
        return self._repo.list()

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._repo.exists(name)

    def __len__(self) -> int:
        return self._repo.count()