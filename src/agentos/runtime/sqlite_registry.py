"""把 Agent 定义按 Workspace 持久化到 SQLite。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from agentos.core.context import get_workspace_id
from agentos.core.exceptions import ConflictError, NotFoundError
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.runtime.agent import Agent
from agentos.runtime.repositories import AGENTS_SCHEMA, AgentRepository


class SQLiteAgentRegistry:
    """SQLite-backed Agent registry with Workspace isolation."""

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
        scope = self._scope(workspace_id)
        if self._repo.exists(agent.name, workspace_id=scope):
            if not overwrite:
                raise ConflictError(
                    f"agent already registered: {agent.name}",
                    details={"agent": agent.name, "workspace_id": scope},
                )
            self._repo.replace(
                agent, updated_at=datetime.now(UTC), workspace_id=scope
            )
        else:
            self._repo.add(agent, created_at=datetime.now(UTC), workspace_id=scope)
        return agent

    def unregister(self, name: str, *, workspace_id: int | None = None) -> None:
        scope = self._scope(workspace_id)
        if not self._repo.remove(name, workspace_id=scope):
            raise NotFoundError(
                f"agent not found: {name}",
                details={"agent": name, "workspace_id": scope},
            )

    def delete(self, name: str, *, workspace_id: int | None = None) -> None:
        """Delete an Agent; ``unregister`` remains a compatibility alias."""
        self.unregister(name, workspace_id=workspace_id)

    def get(self, name: str, *, workspace_id: int | None = None) -> Agent:
        scope = self._scope(workspace_id)
        agent = self._repo.get(name, workspace_id=scope)
        if agent is None:
            raise NotFoundError(
                f"agent not found: {name}",
                details={
                    "agent": name,
                    "workspace_id": scope,
                    "available": self._repo.names(workspace_id=scope),
                },
            )
        return agent

    def list(self, *, workspace_id: int | None = None) -> list[Agent]:
        return self._repo.list(workspace_id=self._scope(workspace_id))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._repo.exists(
            name, workspace_id=self._scope(None)
        )

    def __len__(self) -> int:
        return self._repo.count(workspace_id=self._scope(None))
