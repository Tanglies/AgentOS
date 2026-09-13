"""SQLite persistence for Evaluation 2.0 runs."""

from __future__ import annotations

import json
from pathlib import Path

from agentos.core.config import EvaluationSettings
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database
from agentos.database.repository import Repository
from agentos.evaluation.models import EvaluationRun

EVALUATION_SCHEMA = """CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER,
    dataset_name TEXT NOT NULL,
    dataset_path TEXT,
    status TEXT NOT NULL,
    total_cases INTEGER NOT NULL DEFAULT 0,
    completed_cases INTEGER NOT NULL DEFAULT 0,
    passed_cases INTEGER NOT NULL DEFAULT 0,
    failed_cases INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_workspace_created
    ON evaluation_runs (workspace_id, created_at DESC);
"""


class EvaluationRepository(Repository):
    """Persistence repository for Evaluation runs."""

    def save(self, run: EvaluationRun) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO evaluation_runs "
            "(id, workspace_id, user_id, dataset_name, dataset_path, status, "
            "total_cases, completed_cases, passed_cases, failed_cases, "
            "payload, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.workspace_id,
                run.user_id,
                run.dataset_name,
                run.dataset_path,
                run.status.value,
                run.total_cases,
                run.completed_cases,
                run.passed_cases,
                run.failed_cases,
                run.model_dump_json(),
                run.created_at.isoformat(),
                (run.finished_at or run.started_at or run.created_at).isoformat(),
            ),
        )

    def get(
        self, run_id: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID
    ) -> EvaluationRun | None:
        row = self._db.query_one(
            "SELECT payload FROM evaluation_runs WHERE id = ? AND workspace_id = ?",
            (run_id, workspace_id),
        )
        if row is None:
            return None
        return EvaluationRun.model_validate(json.loads(str(row["payload"])))

    def list(
        self,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvaluationRun]:
        rows = self._db.query(
            "SELECT payload FROM evaluation_runs WHERE workspace_id = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        )
        return [
            EvaluationRun.model_validate(json.loads(str(row["payload"])))
            for row in rows
        ]

    def count(self, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> int:
        row = self._db.query_one(
            "SELECT COUNT(*) AS total FROM evaluation_runs WHERE workspace_id = ?",
            (workspace_id,),
        )
        return int(row["total"]) if row is not None else 0

    def prune(self, keep: int, *, workspace_id: int = DEFAULT_WORKSPACE_ID) -> int:
        return self._db.execute(
            "DELETE FROM evaluation_runs WHERE workspace_id = ? AND id IN ("
            "  SELECT id FROM evaluation_runs WHERE workspace_id = ? "
            "  ORDER BY created_at DESC LIMIT -1 OFFSET ?"
            ")",
            (workspace_id, workspace_id, keep),
        )

    def clear(self, *, workspace_id: int | None = None) -> int:
        if workspace_id is None:
            return self._db.execute("DELETE FROM evaluation_runs")
        return self._db.execute(
            "DELETE FROM evaluation_runs WHERE workspace_id = ?", (workspace_id,)
        )


class EvaluationStore:
    """Thin business facade over EvaluationRepository."""

    def __init__(self, settings: EvaluationSettings | None = None) -> None:
        self._settings = settings or EvaluationSettings()
        self.path = Path(self._settings.db_path).expanduser()
        self._db = Database(self.path, schema=EVALUATION_SCHEMA)
        self._repo = EvaluationRepository(self._db)

    @property
    def repository(self) -> EvaluationRepository:
        return self._repo

    def save(self, run: EvaluationRun) -> EvaluationRun:
        self._repo.save(run)
        self._repo.prune(self._settings.max_records, workspace_id=run.workspace_id)
        return run

    def get(
        self, run_id: str, *, workspace_id: int = DEFAULT_WORKSPACE_ID
    ) -> EvaluationRun | None:
        return self._repo.get(run_id, workspace_id=workspace_id)

    def list(
        self,
        *,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EvaluationRun], int]:
        return (
            self._repo.list(workspace_id=workspace_id, limit=limit, offset=offset),
            self._repo.count(workspace_id=workspace_id),
        )


__all__ = ["EVALUATION_SCHEMA", "EvaluationRepository", "EvaluationStore"]
