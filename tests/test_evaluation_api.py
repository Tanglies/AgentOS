"""Evaluation summary API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.runtime.api_keys import Permission

BOOTSTRAP_KEY = "sk-bootstrap-admin"
HEADER = "X-API-Key"


def _settings(tmp_path: Path, *, auth: bool = False, runs: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "ERROR"},
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"enabled": runs, "db_path": str(tmp_path / "runs.db")},
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
        json={"name": "evaluation-reader", "permissions": permissions},
    )
    assert response.status_code == 201
    return response.json()["key"]


def test_empty_summary_keeps_zero_metrics(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        body = client.get("/api/v1/evaluation/summary").json()

    assert body["runs"] == 0
    assert body["success_rate"] == 0.0
    assert body["average_latency"] == 0.0
    assert body["average_tokens"] == 0.0
    assert body["average_tool_calls"] == 0.0


def test_summary_returns_top_level_averages(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "a"})
        client.post("/api/v1/runs", json={"input": "b"})
        body = client.get("/api/v1/evaluation/summary").json()

    assert body["runs"] == 2
    assert body["succeeded"] == 2
    assert body["success_rate"] == 1.0
    assert body["average_latency"] >= 0.0
    assert body["average_tokens"] > 0.0
    assert body["tokens"]["total"] == body["average_tokens"] * 2


def test_summary_filters_by_agent(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "worker"})
        client.post("/api/v1/runs", json={"input": "a", "agent": "worker"})
        matching = client.get(
            "/api/v1/evaluation/summary?agent=worker"
        ).json()
        missing = client.get(
            "/api/v1/evaluation/summary?agent=ghost"
        ).json()

    assert matching["runs"] == 1
    assert missing["runs"] == 0


def test_invalid_since_is_validation_error(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/evaluation/summary?since=not-a-date")

    assert response.status_code == 422


def test_summary_requires_run_history(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, runs=False)) as client:
        response = client.get("/api/v1/evaluation/summary")

    assert response.status_code == 404


def test_summary_requires_authentication(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        response = client.get("/api/v1/evaluation/summary")

    assert response.status_code == 401


def test_summary_requires_evaluation_permission(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.RUN_READ.value])
        response = client.get(
            "/api/v1/evaluation/summary", headers={HEADER: key}
        )

    assert response.status_code == 403


def test_summary_permission_allows_read(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.EVALUATION_READ.value])
        response = client.get(
            "/api/v1/evaluation/summary", headers={HEADER: key}
        )

    assert response.status_code == 200
