"""Agent lifecycle service.

Routes delegate to this service instead of reaching into repositories or
registry internals. The service keeps the existing AgentRegistry interface and
adds persisted metadata when the backing registry is SQLite-backed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from agentos.core.context import get_workspace_id
from agentos.core.exceptions import NotFoundError
from agentos.core.pagination import KeysetCursor, encode_keyset_cursor
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.database.models import AgentRecord
from agentos.runtime.agent import Agent
from agentos.runtime.audit import (
    ACTION_AGENT_REGISTER,
    ACTION_AGENT_UNREGISTER,
    AuditLog,
)
from agentos.runtime.registry import AgentRegistry


def _next_cursor(
    records: list[AgentRecord],
    page_size: int,
    *,
    order: Literal["asc", "desc"],
) -> str | None:
    """Encode the keyset position of the last record on a full page."""
    last = records[page_size - 1]
    return encode_keyset_cursor(
        KeysetCursor(key=last.name, item_id=last.name, order=order)
    )


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

    @staticmethod
    def _workspace_id(workspace_id: int | None = None) -> int:
        return workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID

    def create(self, agent: Agent, *, workspace_id: int | None = None) -> AgentRecord:
        """Create an Agent and return its persisted lifecycle record."""
        scope = self._workspace_id(workspace_id)
        saved = self._registry.register(agent, workspace_id=scope)
        if self._audit is not None:
            self._audit.record(
                ACTION_AGENT_REGISTER,
                target=saved.name,
                detail=saved.description,
            )
        return self._record(saved, workspace_id=scope)

    def replace(self, agent: Agent, *, workspace_id: int | None = None) -> AgentRecord:
        """Replace an existing Agent definition while preserving its identity."""
        scope = self._workspace_id(workspace_id)
        saved = self._registry.register(agent, overwrite=True, workspace_id=scope)
        if self._audit is not None:
            self._audit.record(
                ACTION_AGENT_REGISTER,
                target=saved.name,
                detail=saved.description,
            )
        return self._record(saved, workspace_id=scope)

    def get(self, name: str, *, workspace_id: int | None = None) -> AgentRecord:
        """Return one Agent with persistence metadata."""
        scope = self._workspace_id(workspace_id)
        agent = self._registry.get(name, workspace_id=scope)
        return self._record(agent, workspace_id=scope)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        cursor: KeysetCursor | None = None,
        order: Literal["asc", "desc"] = "asc",
        workspace_id: int | None = None,
    ) -> tuple[list[AgentRecord], int, str | None]:
        """Return one page of Agents, the total count, and the next cursor.

        Agents are ordered by their unique ``name``, so a cursor is a keyset
        position on that key rather than on ``created_at``.  Each query reads one
        extra row: if it exists the page is full and ``next_cursor`` points at the
        last row of the returned page, otherwise the caller is on the final page.
        """
        scope = self._workspace_id(workspace_id)
        offset = 0 if cursor is not None else (page - 1) * page_size
        repository = self.repository
        if repository is not None and hasattr(repository, "list_records"):
            total = int(repository.count(workspace_id=scope))
            records: list[AgentRecord] = repository.list_records(
                workspace_id=scope,
                limit=page_size + 1,
                offset=offset,
                cursor=cursor,
                order=order,
            )
        else:
            agents = self._registry.list(workspace_id=scope)
            total = len(agents)
            ordered = sorted(
                agents, key=lambda item: item.name, reverse=order == "desc"
            )
            if cursor is not None:
                if order == "desc":
                    ordered = [item for item in ordered if item.name < cursor.key]
                else:
                    ordered = [item for item in ordered if item.name > cursor.key]
                window = ordered[: page_size + 1]
            else:
                window = ordered[offset : offset + page_size + 1]
            records = [self._record(item, workspace_id=scope) for item in window]

        next_cursor = (
            _next_cursor(records, page_size, order=order)
            if len(records) > page_size
            else None
        )
        return records[:page_size], total, next_cursor

    def delete(self, name: str, *, workspace_id: int | None = None) -> None:
        """Delete an Agent, keeping the existing unregister behavior."""
        scope = self._workspace_id(workspace_id)
        self._registry.delete(name, workspace_id=scope)
        if self._audit is not None:
            self._audit.record(ACTION_AGENT_UNREGISTER, target=name)

    def _record(self, agent: Agent, *, workspace_id: int) -> AgentRecord:
        repository = self.repository
        if repository is not None and hasattr(repository, "get_record"):
            record = repository.get_record(agent.name, workspace_id=workspace_id)
            if record is not None:
                return record
            raise NotFoundError(
                f"agent not found: {agent.name}",
                details={"agent": agent.name, "workspace_id": workspace_id},
            )
        now = datetime.now(UTC)
        return AgentRecord(
            workspace_id=workspace_id,
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
