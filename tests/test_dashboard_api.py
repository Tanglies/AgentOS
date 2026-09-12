"""Dashboard API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.runtime.api_keys import Permission
from agentos.runtime.audit import ACTION_TOOL_EXECUTE, AuditStatus

BOOTSTRAP_KEY = "sk-bootstrap-admin"
HEADER = "X-API-Key"


def _settings(tmp_path: Path, *, auth: bool = False, runs: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "ERROR"},
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"enabled": runs, "db_path": str(tmp_path / "runs.db")},
        audit={"enabled": True, "db_path": str(tmp_path / "audit.db")},
        api_keys={"db_path": str(tmp_path / "api-keys.db")},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
        auth={
            "enabled": auth,
            "api_keys": [SecretStr(BOOTSTRAP_KEY)] if auth else [],
        },
    )


def _app(tmp_path: Path, *, auth: bool = False, runs: bool = True):
    return create_app(_settings(tmp_path, auth=auth, runs=runs))


def _issue(client: TestClient, *, permissions: list[str]) -> str:
    response = client.post(
        "/api/v1/api-keys",
        headers={HEADER: BOOTSTRAP_KEY},
        json={"name": "dashboard-reader", "permissions": permissions},
    )
    assert response.status_code == 201
    return response.json()["key"]


def test_overview_is_zeroed_with_empty_history(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        body = client.get("/api/v1/dashboard/overview").json()

    assert body == {
        "total_runs": 0,
        "success_rate": 0.0,
        "average_latency": 0.0,
        "total_tokens": 0,
        "active_agents": 1,
    }


def test_overview_reflects_recorded_runs(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "a"})
        client.post("/api/v1/runs", json={"input": "b"})
        body = client.get("/api/v1/dashboard/overview").json()

    assert body["total_runs"] == 2
    assert body["success_rate"] == 1.0
    assert body["total_tokens"] > 0
    assert body["active_agents"] == 1


def test_tool_counts_come_from_audit_events(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        audit = client.app.state.audit_log
        audit.record(ACTION_TOOL_EXECUTE, target="calculate")
        audit.record(ACTION_TOOL_EXECUTE, target="calculate")
        audit.record(ACTION_TOOL_EXECUTE, target="search_text")
        body = client.get("/api/v1/dashboard/tools").json()

    assert body == {"calculate": 2, "search_text": 1}


def test_recent_errors_return_failed_runs(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.app.state.runtime.runs.record_failure(
            run_id="run_failed",
            agent="assistant",
            input_text="bad input",
            error="boom",
        )
        body = client.get("/api/v1/dashboard/errors").json()

    assert len(body) == 1
    assert body[0]["run_id"] == "run_failed"
    assert body[0]["error"] == "boom"


def test_tool_failures_do_not_break_overview(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.app.state.audit_log.record(
            ACTION_TOOL_EXECUTE,
            status=AuditStatus.FAILURE,
            target="calculate",
            detail="bad expression",
        )
        overview = client.get("/api/v1/dashboard/overview")
        tools = client.get("/api/v1/dashboard/tools")

    assert overview.status_code == 200
    assert tools.json() == {"calculate": 1}


def test_dashboard_without_run_history_returns_empty_metrics(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, runs=False)) as client:
        overview = client.get("/api/v1/dashboard/overview").json()
        errors = client.get("/api/v1/dashboard/errors").json()

    assert overview["total_runs"] == 0
    assert errors == []


def test_dashboard_requires_auth(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        response = client.get("/api/v1/dashboard/overview")

    assert response.status_code == 401


def test_dashboard_requires_dashboard_permission(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.RUN_READ.value])
        response = client.get(
            "/api/v1/dashboard/overview", headers={HEADER: key}
        )

    assert response.status_code == 403


def test_dashboard_permission_allows_read(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.DASHBOARD_READ.value])
        responses = [
            client.get("/api/v1/dashboard/overview", headers={HEADER: key}),
            client.get("/api/v1/dashboard/tools", headers={HEADER: key}),
            client.get("/api/v1/dashboard/errors", headers={HEADER: key}),
        ]

    assert all(response.status_code == 200 for response in responses)
