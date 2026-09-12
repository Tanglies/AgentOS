"""Agent lifecycle service.

Routes delegate to this service instead of reaching into repositories or
registry internals. The service keeps the existing AgentRegistry interface and
adds persisted metadata when the backing registry is SQLite-backed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentos.core.exceptions import NotFoundError
from agentos.database.models import AgentRecord
from agentos.runtime.agent import Agent
from agentos.runtime.audit import (
    ACTION_AGENT_REGISTER,
    ACTION_AGENT_UNREGISTER,
    AuditLog,
)
from agentos.runtime.registry import AgentRegistry


class AgentService:
    """Application service for Agent create, list, detail, and delete operations."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        audit: AuditLog | None = None,
    ) -> None:
        self._registry = registry
        self._audit = audit

    @property
    def repository(self) -> object | None:
        """Return the SQLite repository when the registry supports one."""
        return getattr(self._registry, "repository", None)

    def create(self, agent: Agent) -> AgentRecord:
        """Create an Agent and return its persisted lifecycle record."""
        saved = self._registry.register(agent)
        if self._audit is not None:
            self._audit.record(
                ACTION_AGENT_REGISTER,
                target=saved.name,
                detail=saved.description,
            )
        return self._record(saved)

    def replace(self, agent: Agent) -> AgentRecord:
        """Replace an existing Agent definition while preserving its identity."""
        saved = self._registry.register(agent, overwrite=True)
        if self._audit is not None:
            self._audit.record(
                ACTION_AGENT_REGISTER,
                target=saved.name,
                detail=saved.description,
            )
        return self._record(saved)

    def get(self, name: str) -> AgentRecord:
        """Return one Agent with persistence metadata."""
        agent = self._registry.get(name)
        return self._record(agent)

    def list(self, *, page: int = 1, page_size: int = 20) -> tuple[list[AgentRecord], int]:
        """Return a page of Agents and the total count."""
        offset = (page - 1) * page_size
        repository = self.repository
        if repository is not None and hasattr(repository, "list_records"):
            records = repository.list_records(limit=page_size, offset=offset)
            total = int(repository.count())
            return records, total

        agents = self._registry.list()
        total = len(agents)
        return [self._record(agent) for agent in agents[offset : offset + page_size]], total

    def delete(self, name: str) -> None:
        """Delete an Agent, keeping the existing unregister behavior."""
        self._registry.delete(name)
        if self._audit is not None:
            self._audit.record(ACTION_AGENT_UNREGISTER, target=name)

    def _record(self, agent: Agent) -> AgentRecord:
        repository = self.repository
        if repository is not None and hasattr(repository, "get_record"):
            record = repository.get_record(agent.name)
            if record is not None:
                return record
            raise NotFoundError(
                f"agent not found: {agent.name}", details={"agent": agent.name}
            )
        now = datetime.now(UTC)
        return AgentRecord(
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            model=agent.model,
            temperature=agent.temperature,
            max_iterations=agent.max_iterations,
            tools=list(agent.tools),
            metadata=dict(agent.metadata),
            created_at=now,
            updated_at=now,
        )


__all__ = ["AgentService"]
