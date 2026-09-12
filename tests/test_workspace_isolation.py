"""Cross-Workspace isolation regression tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import create_tenant, headers, tenant_app


def test_agents_are_isolated_between_workspaces(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        created = client.post(
            "/api/v1/agents",
            headers=tenant_a["headers"],
            json={"name": "research_agent", "description": "A only"},
        )
        missing = client.get(
            "/api/v1/agents/research_agent", headers=tenant_b["headers"]
        )
        listed_b = client.get("/api/v1/agents", headers=tenant_b["headers"]).json()
        deleted_b = client.delete(
            "/api/v1/agents/research_agent", headers=tenant_b["headers"]
        )

    assert created.status_code == 201
    assert created.json()["workspace_id"] == tenant_a["workspace_id"]
    assert missing.status_code == 404
    assert listed_b["total"] == 0
    assert deleted_b.status_code == 404


def test_same_agent_name_can_exist_in_two_workspaces(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        first = client.post(
            "/api/v1/agents", headers=tenant_a["headers"], json={"name": "assistant"}
        )
        second = client.post(
            "/api/v1/agents", headers=tenant_b["headers"], json={"name": "assistant"}
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_run_history_and_detail_are_workspace_scoped(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        client.post(
            "/api/v1/agents", headers=tenant_a["headers"], json={"name": "chat"}
        )
        run = client.post(
            "/api/v1/runs",
            headers=tenant_a["headers"],
            json={"agent": "chat", "input": "A secret"},
        ).json()
        listed_b = client.get("/api/v1/runs", headers=tenant_b["headers"]).json()
        detail_b = client.get(
            f"/api/v1/runs/{run['run_id']}", headers=tenant_b["headers"]
        )

    assert listed_b["total"] == 0
    assert detail_b.status_code == 404


def test_memory_is_isolated_between_workspaces(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        memory = client.post(
            "/api/v1/memories",
            headers=tenant_a["headers"],
            json={"content": "workspace A memory", "scope": "workspace"},
        ).json()
        listed_b = client.get(
            "/api/v1/memories", headers=tenant_b["headers"]
        ).json()
        delete_b = client.delete(
            f"/api/v1/memories/{memory['id']}", headers=tenant_b["headers"]
        )

    assert listed_b["total"] == 0
    assert delete_b.status_code == 404


def test_api_key_lists_are_workspace_scoped(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        key_a = client.app.state.api_key_store.issue(
            "alice-admin",
            user_id=tenant_a["user_id"],
            workspace_id=tenant_a["workspace_id"],
            permissions=["apikey:admin"],
        ).key
        key_b = client.app.state.api_key_store.issue(
            "bob-admin",
            user_id=tenant_b["user_id"],
            workspace_id=tenant_b["workspace_id"],
            permissions=["apikey:admin"],
        ).key
        listed_a = client.get("/api/v1/api-keys", headers=headers(key_a)).json()
        listed_b = client.get("/api/v1/api-keys", headers=headers(key_b)).json()

    assert listed_a["total"] == 2
    assert listed_b["total"] == 2
    assert listed_a["items"][0]["id"] != listed_b["items"][0]["id"]


def test_cross_workspace_query_parameters_cannot_expand_scope(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        client.post(
            "/api/v1/agents", headers=tenant_a["headers"], json={"name": "chat"}
        )
        client.post(
            "/api/v1/runs",
            headers=tenant_a["headers"],
            json={"agent": "chat", "input": "A-only"},
        )
        response = client.get(
            f"/api/v1/runs?workspace_id={tenant_a['workspace_id']}",
            headers=tenant_b["headers"],
        )

    assert response.json()["total"] == 0


def test_legacy_agent_database_migrates_to_default_workspace(tmp_path: Path) -> None:
    from agentos.database import Database
    from agentos.runtime.agent import Agent
    from agentos.runtime.sqlite_registry import SQLiteAgentRegistry

    path = tmp_path / "agents.db"
    legacy = Database(
        path,
        schema=(
            "CREATE TABLE agents (name TEXT PRIMARY KEY, payload TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        ),
    )
    agent = Agent(name="legacy", description="old")
    stamp = datetime.now(UTC).isoformat()
    legacy.execute(
        "INSERT INTO agents (name, payload, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("legacy", agent.model_dump_json(), stamp, stamp),
    )

    registry = SQLiteAgentRegistry(str(path))

    assert registry.get("legacy", workspace_id=1).description == "old"


def test_legacy_run_and_memory_rows_get_default_workspace(tmp_path: Path) -> None:
    import json

    from agentos.core.config import MemorySettings, RunStoreSettings
    from agentos.database import Database
    from agentos.runtime.long_term_memory import LongTermMemory
    from agentos.runtime.run_store import RunStore

    run_db = Database(
        tmp_path / "runs.db",
        schema=(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, agent TEXT NOT NULL, "
            "session_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, "
            "duration_ms REAL NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0, "
            "tool_call_count INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)"
        ),
    )
    stamp = datetime.now(UTC).isoformat()
    payload = {
        "run_id": "run_legacy",
        "agent": "assistant",
        "status": "completed",
        "created_at": stamp,
        "duration_ms": 1.0,
        "messages": [],
    }
    run_db.execute(
        "INSERT INTO runs (run_id, agent, status, created_at, duration_ms, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run_legacy", "assistant", "completed", stamp, 1.0, json.dumps(payload)),
    )
    runs = RunStore(RunStoreSettings(db_path=str(tmp_path / "runs.db")))

    memory_db = Database(
        tmp_path / "memory.db",
        schema=(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "content TEXT NOT NULL, session_id TEXT, created_at TEXT NOT NULL)"
        ),
    )
    memory_db.execute(
        "INSERT INTO memories (content, created_at) VALUES (?, ?)",
        ("legacy memory", stamp),
    )
    memory = LongTermMemory(
        MemorySettings(long_term_db_path=str(tmp_path / "memory.db"))
    )

    assert runs.list(workspace_id=1)[0].run_id == "run_legacy"
    assert memory.list(workspace_id=1)[0].content == "legacy memory"


def test_cannot_execute_agent_from_another_workspace(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1000})) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        client.post(
            "/api/v1/agents", headers=tenant_a["headers"], json={"name": "secret"}
        )
        response = client.post(
            "/api/v1/runs",
            headers=tenant_b["headers"],
            json={"agent": "secret", "input": "run it"},
        )

    assert response.status_code == 404
