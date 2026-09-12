"""Dashboard read-model service.

The dashboard is intentionally read-only. It projects existing Agent, Run, and
Audit data into the small views needed by the frontend instead of creating a
second source of truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agentos.repositories.tool_repository import ToolRepository
from agentos.runtime.audit import AuditLog
from agentos.runtime.registry import AgentRegistry
from agentos.runtime.repositories import RunAggregate, RunRepository, RunStatus
from agentos.runtime.run_store import RunStore


class DashboardService:
    """Build dashboard overview, tool usage, and recent-error views."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        runs: RunStore | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self._registry = registry
        self._runs = runs
        self._audit = audit

    @property
    def run_repository(self) -> RunRepository | None:
        """Return the run repository when run history is enabled."""
        return self._runs.repository if self._runs is not None else None

    def overview(self) -> dict[str, Any]:
        """Return aggregate run and Agent counts for the dashboard."""
        repository = self.run_repository
        aggregate = repository.aggregate() if repository is not None else RunAggregate()
        return {
            "total_runs": aggregate.runs,
            "success_rate": round(aggregate.success_rate, 4),
            "average_latency": round(aggregate.avg_duration_ms, 3),
            "total_tokens": aggregate.total_tokens,
            "active_agents": len(self._registry),
        }

    def tools(self, *, limit: int = 50, since: datetime | None = None) -> dict[str, int]:
        """Return tool call counts from audit events."""
        if self._audit is None:
            return {}
        repository = ToolRepository(self._audit.repository.database)
        return repository.call_counts(limit=limit, since=since)

    def errors(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent failed runs."""
        repository = self.run_repository
        if repository is None:
            return []
        records = repository.list(status=RunStatus.FAILED, limit=limit)
        return [
            {
                "run_id": record.run_id,
                "agent": record.agent,
                "status": record.status.value,
                "error": record.error or "",
                "duration_ms": record.duration_ms,
                "created_at": record.created_at,
            }
            for record in records
        ]


__all__ = ["DashboardService"]
