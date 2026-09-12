"""Repository layer tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentos.database import Database, Repository, build_filter
from agentos.runtime.repositories import (
    MEMORIES_SCHEMA,
    RUNS_SCHEMA,
    AgentRepository,
    ApiKeyRepository,
    AuditRepository,
    MemoryRepository,
    RunRecord,
    RunRepository,
)


def test_build_filter_skips_none_values() -> None:
    where, params = build_filter([("agent = ?", "assistant"), ("status = ?", None)])

    assert where == "WHERE agent = ?"
    assert params == ("assistant",)


def test_build_filter_without_active_clauses() -> None:
    assert build_filter([("agent = ?", None)]) == ("", ())


def test_repository_exposes_database(tmp_path: Path) -> None:
    class ExampleRepository(Repository):
        pass

    db = Database(tmp_path / "example.db")
    repository = ExampleRepository(db)

    assert repository.database is db


def test_domain_repositories_inherit_base_repository() -> None:
    for repository in (
        AgentRepository,
        ApiKeyRepository,
        AuditRepository,
        MemoryRepository,
        RunRepository,
    ):
        assert issubclass(repository, Repository)


def test_run_repository_named_create_and_finish_methods(tmp_path: Path) -> None:
    db = Database(tmp_path / "runs.db")
    db.execute_script(RUNS_SCHEMA)
    repo = RunRepository(db)
    record = RunRecord(run_id="run_1", agent="assistant")

    repo.create_run(record)
    repo.finish_run(record)

    assert repo.get("run_1") is not None


def test_memory_repository_named_save_and_search_methods(tmp_path: Path) -> None:
    db = Database(tmp_path / "memory.db")
    db.execute_script(MEMORIES_SCHEMA)
    repo = MemoryRepository(db)

    created = repo.save_memory(
        content="remember this", session_id=None, created_at=datetime.now(UTC)
    )

    assert created.id > 0
    assert repo.search_memory(terms=["remember"], limit=5)[0].content == "remember this"
