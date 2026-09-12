"""Read-only tool-call analytics backed by audit records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.database.repository import Repository, build_filter

TOOL_EXECUTE_ACTION = "tool.execute"
TOOL_FAILURE_STATUS = "failure"


class ToolRepository(Repository):
    """Aggregate tool usage and failures from the audit log.

    Tool execution audit records are already produced by the Runtime, so the
    dashboard reads that single source instead of maintaining a second table.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    def call_counts(
        self,
        *,
        since: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        limit: int = 50,
    ) -> dict[str, int]:
        """Return call counts keyed by tool name, highest count first."""
        where, params = build_filter(
            [
                ("workspace_id = ?", workspace_id),
                ("action = ?", TOOL_EXECUTE_ACTION),
                ("created_at >= ?", since.isoformat() if since else None),
            ]
        )
        rows = self._db.query(
            "SELECT COALESCE(NULLIF(target, ''), NULLIF(tool_name, ''), 'unknown') "
            "AS tool_name, COUNT(*) AS calls "
            f"FROM audit_logs {where} "
            "GROUP BY 1 ORDER BY calls DESC, 1 ASC LIMIT ?",
            (*params, limit),
        )
        return {str(row["tool_name"]): int(row["calls"]) for row in rows}

    def recent_failures(
        self, *, workspace_id: int = DEFAULT_WORKSPACE_ID, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return the most recent failed tool executions."""
        rows = self._db.query(
            "SELECT id, target, tool_name, run_id, detail, actor, created_at "
            "FROM audit_logs "
            "WHERE workspace_id = ? AND action = ? AND status = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (workspace_id, TOOL_EXECUTE_ACTION, TOOL_FAILURE_STATUS, limit),
        )
        return [
            {
                "id": int(row["id"]),
                "tool_name": str(row["target"] or row["tool_name"] or "unknown"),
                "run_id": row["run_id"],
                "detail": str(row["detail"] or ""),
                "actor": row["actor"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]


__all__ = ["ToolRepository"]
