"""Agent persistence and lifecycle repository tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentos.core.exceptions import NotFoundError
from agentos.database import Database
from agentos.runtime.agent import Agent
from agentos.runtime.repositories import AGENTS_SCHEMA, AgentRepository
from agentos.runtime.sqlite_registry import SQLiteAgentRegistry

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)


def _repository(path: Path) -> AgentRepository:
    return AgentRepository(Database(path, schema=AGENTS_SCHEMA))


def test_add_writes_structured_columns(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "agents.db")
    repo.add(
        Agent(
            name="researcher",
            description="调研专家",
            system_prompt="搜索资料",
            model="qwen3.8-max",
            temperature=0.2,
            max_iterations=4,
            tools=["read_file"],
            metadata={"team": "data"},
        ),
        created_at=NOW,
    )

    row = repo._db.query_one("SELECT * FROM agents WHERE name = ?", ("researcher",))
    assert row is not None
    assert row["id"] is not None
    assert row["description"] == "调研专家"
    assert row["system_prompt"] == "搜索资料"
    assert row["model"] == "qwen3.8-max"
    assert row["temperature"] == 0.2
    assert row["max_iterations"] == 4
    assert json.loads(row["tools"]) == ["read_file"]
    assert json.loads(row["metadata"]) == {"team": "data"}


def test_record_round_trips_all_agent_fields(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "agents.db")
    original = Agent(
        name="researcher",
        description="调研专家",
        system_prompt="搜索资料",
        model="qwen3.8-max",
        temperature=0.2,
        max_iterations=4,
        tools=["read_file"],
        metadata={"team": "data"},
    )

    repo.add(original, created_at=NOW)
    record = repo.get_record("researcher")

    assert record is not None
    assert record.id is not None
    assert record.name == original.name
    assert record.description == original.description
    assert record.system_prompt == original.system_prompt
    assert record.model == original.model
    assert record.temperature == original.temperature
    assert record.max_iterations == original.max_iterations
    assert record.tools == original.tools
    assert record.metadata == original.metadata
    assert record.created_at == NOW


def test_replace_preserves_id_and_created_at(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "agents.db")
    first = repo.add(Agent(name="worker", description="old"), created_at=NOW)

    updated = repo.replace(
        Agent(name="worker", description="new", tools=["calculate"]),
        updated_at=NOW + timedelta(seconds=1),
    )

    assert updated.id == first.id
    assert updated.created_at == NOW
    assert updated.updated_at == NOW + timedelta(seconds=1)
    assert repo.get("worker").description == "new"


def test_list_records_supports_pagination(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "agents.db")
    for name in ("z", "a", "m"):
        repo.add(Agent(name=name), created_at=NOW)

    records = repo.list_records(limit=2, offset=1)

    assert [record.name for record in records] == ["m", "z"]
    assert repo.count() == 3


def test_remove_is_idempotent_for_missing_agent(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "agents.db")
    repo.add(Agent(name="temp"), created_at=NOW)

    assert repo.remove("temp") is True
    assert repo.remove("temp") is False


def test_legacy_payload_is_backfilled_into_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    db = Database(
        path,
        schema=(
            "CREATE TABLE agents ("
            "name TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        ),
    )
    legacy = Agent(
        name="legacy",
        description="旧的",
        system_prompt="旧提示词",
        model="qwen3.8-max",
        tools=["calculate"],
        metadata={"source": "legacy"},
    )
    stamp = NOW.isoformat()
    db.execute(
        "INSERT INTO agents (name, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("legacy", legacy.model_dump_json(), stamp, stamp),
    )

    repo = AgentRepository(db)
    record = repo.get_record("legacy")

    assert record is not None
    assert record.description == "旧的"
    assert record.system_prompt == "旧提示词"
    assert record.tools == ["calculate"]
    assert record.metadata == {"source": "legacy"}


def test_database_file_can_be_recreated_after_removal(tmp_path: Path) -> None:
    path = tmp_path / "agents.db"
    repo = _repository(path)
    repo.add(Agent(name="first"), created_at=NOW)
    path.unlink()

    repo.add(Agent(name="second"), created_at=NOW)

    assert repo.names() == ["second"]


def test_sqlite_registry_delete_alias(tmp_path: Path) -> None:
    registry = SQLiteAgentRegistry(str(tmp_path / "agents.db"))
    registry.register(Agent(name="temp"))

    registry.delete("temp")

    with pytest.raises(NotFoundError):
        registry.get("temp")
