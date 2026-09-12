"""数据库与 Repository 层测试。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentos.core.database import Database
from agentos.runtime.agent import Agent
from agentos.runtime.repositories import (
    AGENTS_SCHEMA,
    MEMORIES_SCHEMA,
    RUNS_SCHEMA,
    AgentRepository,
    MemoryRepository,
    RunRecord,
    RunRepository,
    RunStatus,
)

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)


# --- Database -------------------------------------------------------------


def test_database_creates_file_and_schema(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db", schema="CREATE TABLE t (id INTEGER PRIMARY KEY);")

    assert db.path.exists()
    db.execute("INSERT INTO t (id) VALUES (1)")
    assert db.query_one("SELECT COUNT(*) AS n FROM t")["n"] == 1


def test_database_creates_missing_parent_directory(tmp_path: Path) -> None:
    db = Database(tmp_path / "nested" / "deep" / "x.db", schema="CREATE TABLE t (id INTEGER);")

    assert db.path.parent.is_dir()


def test_database_recovers_after_directory_removed(tmp_path: Path) -> None:
    root = tmp_path / "data"
    db = Database(root / "x.db", schema="CREATE TABLE t (id INTEGER);")
    db.execute("INSERT INTO t (id) VALUES (1)")

    shutil.rmtree(root)

    db.execute("INSERT INTO t (id) VALUES (2)")
    assert db.query_one("SELECT COUNT(*) AS n FROM t")["n"] == 1


def test_database_recovers_after_file_removed(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db", schema="CREATE TABLE t (id INTEGER);")
    db.execute("INSERT INTO t (id) VALUES (1)")

    db.path.unlink()

    # 文件不在 -> 视为新建 -> 重建表结构，而不是抛 no such table
    assert db.query_one("SELECT COUNT(*) AS n FROM t")["n"] == 0


def test_database_execute_returns_rowcount(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db", schema="CREATE TABLE t (id INTEGER);")
    db.execute("INSERT INTO t (id) VALUES (1)")

    assert db.execute("DELETE FROM t") == 1


def test_database_query_returns_all_rows(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db", schema="CREATE TABLE t (id INTEGER);")
    for index in range(3):
        db.execute("INSERT INTO t (id) VALUES (?)", (index,))

    assert [row["id"] for row in db.query("SELECT id FROM t ORDER BY id")] == [0, 1, 2]


# --- AgentRepository ------------------------------------------------------


@pytest.fixture
def agents(tmp_path: Path) -> AgentRepository:
    return AgentRepository(Database(tmp_path / "agents.db", schema=AGENTS_SCHEMA))


def test_agent_repository_add_and_get(agents: AgentRepository) -> None:
    agents.add(Agent(name="assistant", description="助手"), created_at=NOW)

    fetched = agents.get("assistant")
    assert fetched is not None
    assert fetched.description == "助手"


def test_agent_repository_get_unknown_returns_none(agents: AgentRepository) -> None:
    assert agents.get("ghost") is None


def test_agent_repository_replace(agents: AgentRepository) -> None:
    agents.add(Agent(name="a", description="旧"), created_at=NOW)

    agents.replace(Agent(name="a", description="新"), updated_at=NOW)

    assert agents.get("a").description == "新"
    assert agents.count() == 1


def test_agent_repository_exists_and_names(agents: AgentRepository) -> None:
    agents.add(Agent(name="zeta"), created_at=NOW)
    agents.add(Agent(name="alpha"), created_at=NOW)

    assert agents.exists("alpha") is True
    assert agents.exists("ghost") is False
    assert agents.names() == ["alpha", "zeta"]


def test_agent_repository_remove(agents: AgentRepository) -> None:
    agents.add(Agent(name="temp"), created_at=NOW)

    assert agents.remove("temp") is True
    assert agents.remove("temp") is False
    assert agents.count() == 0


def test_agent_repository_round_trips_complex_fields(agents: AgentRepository) -> None:
    original = Agent(
        name="complex",
        system_prompt="你是助手",
        model="qwen3.8-max",
        temperature=0.3,
        tools=["calculate"],
        metadata={"team": "data"},
    )
    agents.add(original, created_at=NOW)

    assert agents.get("complex").model_dump() == original.model_dump()


# --- RunRepository --------------------------------------------------------


@pytest.fixture
def runs(tmp_path: Path) -> RunRepository:
    return RunRepository(Database(tmp_path / "runs.db", schema=RUNS_SCHEMA))


def _record(index: int, **overrides: object) -> RunRecord:
    payload: dict[str, object] = {
        "run_id": f"run_{index}",
        "agent": "assistant" if index % 2 else "researcher",
        "status": RunStatus.COMPLETED,
        "duration_ms": float(index * 100),
        "total_tokens": index * 10,
        "prompt_tokens": index * 6,
        "completion_tokens": index * 4,
        "tool_call_count": index - 1,
        "created_at": NOW + timedelta(seconds=index),
    }
    payload.update(overrides)
    return RunRecord.model_validate(payload)


def test_run_repository_add_and_get(runs: RunRepository) -> None:
    runs.add(_record(1, messages=[]))

    assert runs.get("run_1").agent == "assistant"
    assert runs.get("ghost") is None


def test_run_repository_default_order_is_newest_first(runs: RunRepository) -> None:
    for index in range(1, 4):
        runs.add(_record(index))

    assert [r.run_id for r in runs.list()] == ["run_3", "run_2", "run_1"]


def test_run_repository_supports_ascending_order(runs: RunRepository) -> None:
    for index in range(1, 4):
        runs.add(_record(index))

    assert [r.run_id for r in runs.list(order="asc")] == ["run_1", "run_2", "run_3"]


def test_run_repository_filters_by_agent(runs: RunRepository) -> None:
    for index in range(1, 5):
        runs.add(_record(index))

    assert runs.count(agent="researcher") == 2
    assert all(r.agent == "researcher" for r in runs.list(agent="researcher"))


def test_run_repository_filters_by_status(runs: RunRepository) -> None:
    runs.add(_record(1))
    runs.add(_record(2, status=RunStatus.FAILED))

    assert runs.count(status=RunStatus.FAILED) == 1
    assert runs.list(status=RunStatus.FAILED)[0].run_id == "run_2"


def test_run_repository_pagination(runs: RunRepository) -> None:
    for index in range(1, 6):
        runs.add(_record(index))

    assert [r.run_id for r in runs.list(limit=2, offset=0)] == ["run_5", "run_4"]
    assert [r.run_id for r in runs.list(limit=2, offset=2)] == ["run_3", "run_2"]
    assert runs.count() == 5


def test_run_repository_prune_keeps_newest(runs: RunRepository) -> None:
    for index in range(1, 6):
        runs.add(_record(index))

    assert runs.prune(2) == 3
    assert [r.run_id for r in runs.list()] == ["run_5", "run_4"]


def test_run_repository_aggregate_empty(runs: RunRepository) -> None:
    aggregate = runs.aggregate()

    assert aggregate.runs == 0
    assert aggregate.success_rate == 0.0
    assert aggregate.avg_duration_ms == 0.0


def test_run_repository_aggregate_totals(runs: RunRepository) -> None:
    runs.add(_record(1))
    runs.add(_record(2, status=RunStatus.FAILED, tool_call_count=0))

    aggregate = runs.aggregate()

    assert aggregate.runs == 2
    assert aggregate.succeeded == 1
    assert aggregate.failed == 1
    assert aggregate.success_rate == 0.5
    assert aggregate.total_tokens == 30
    assert aggregate.total_duration_ms == 300.0
    assert aggregate.avg_duration_ms == 150.0


def test_run_repository_aggregate_counts_runs_with_tools(runs: RunRepository) -> None:
    runs.add(_record(1, tool_call_count=0))
    runs.add(_record(2, tool_call_count=3))

    assert runs.aggregate().runs_with_tools == 1


def test_run_repository_durations_are_sorted(runs: RunRepository) -> None:
    for index in (3, 1, 2):
        runs.add(_record(index))

    assert runs.durations() == [100.0, 200.0, 300.0]


# --- MemoryRepository -----------------------------------------------------


@pytest.fixture
def memories(tmp_path: Path) -> MemoryRepository:
    return MemoryRepository(Database(tmp_path / "mem.db", schema=MEMORIES_SCHEMA))


def test_memory_repository_add_returns_record(memories: MemoryRepository) -> None:
    record = memories.add(content="用户叫周明", session_id=None, created_at=NOW)

    assert record.id > 0
    assert record.content == "用户叫周明"
    assert memories.count() == 1


def test_memory_repository_get_unknown_returns_none(memories: MemoryRepository) -> None:
    assert memories.get(999) is None


def test_memory_repository_list_is_newest_first(memories: MemoryRepository) -> None:
    memories.add(content="第一", session_id=None, created_at=NOW)
    memories.add(content="第二", session_id=None, created_at=NOW + timedelta(seconds=1))

    assert [r.content for r in memories.list()] == ["第二", "第一"]


def test_memory_repository_search_scores_longer_terms_higher(
    memories: MemoryRepository,
) -> None:
    memories.add(content="数据分析", session_id=None, created_at=NOW)
    memories.add(content="数据分析师", session_id=None, created_at=NOW)

    hits = memories.search(terms=["数据分析师"], limit=5)

    assert hits[0].content == "数据分析师"


def test_memory_repository_search_empty_terms_returns_nothing(
    memories: MemoryRepository,
) -> None:
    memories.add(content="任意内容", session_id=None, created_at=NOW)

    assert memories.search(terms=[], limit=5) == []


def test_memory_repository_remove_and_clear(memories: MemoryRepository) -> None:
    first = memories.add(content="a", session_id=None, created_at=NOW)
    memories.add(content="b", session_id=None, created_at=NOW)

    assert memories.remove(first.id) is True
    assert memories.remove(first.id) is False
    assert memories.clear() == 1
    assert memories.count() == 0