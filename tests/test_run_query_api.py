"""Run history query API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.runtime.api_keys import Permission

BOOTSTRAP_KEY = "sk-bootstrap-admin"
HEADER = "X-API-Key"


def _settings(tmp_path: Path, *, auth: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        llm={"provider": "echo"},
        logging={"level": "ERROR"},
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"enabled": True, "db_path": str(tmp_path / "runs.db")},
        audit={"db_path": str(tmp_path / "audit.db")},
        api_keys={"db_path": str(tmp_path / "api-keys.db")},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
        auth={
            "enabled": auth,
            "api_keys": [SecretStr(BOOTSTRAP_KEY)] if auth else [],
        },
    )


def _app(tmp_path: Path, *, auth: bool = False):
    return create_app(_settings(tmp_path, auth=auth))


def _issue(client: TestClient, *, permissions: list[str]) -> str:
    response = client.post(
        "/api/v1/api-keys",
        headers={HEADER: BOOTSTRAP_KEY},
        json={"name": "run-reader", "permissions": permissions},
    )
    assert response.status_code == 201
    return response.json()["key"]


def test_run_summary_includes_token_usage(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "hello"})
        body = client.get("/api/v1/runs").json()

    item = body["items"][0]
    assert item["total_tokens"] > 0
    assert item["token_usage"]["total_tokens"] == item["total_tokens"]
    assert item["token_usage"]["prompt_tokens"] >= 0


def test_page_and_page_size_pagination(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for value in ("a", "b", "c"):
            client.post("/api/v1/runs", json={"input": value})
        body = client.get("/api/v1/runs?page=2&page_size=1").json()

    assert body["page"] == 2
    assert body["page_size"] == 1
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["total"] == 3
    assert len(body["items"]) == 1


def test_legacy_limit_offset_remains_supported(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for value in ("a", "b", "c"):
            client.post("/api/v1/runs", json={"input": value})
        body = client.get("/api/v1/runs?limit=1&offset=2").json()

    assert body["limit"] == 1
    assert body["offset"] == 2
    assert body["page"] == 3
    assert len(body["items"]) == 1


def test_filters_by_agent_and_status(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "researcher"})
        client.post("/api/v1/runs", json={"input": "ok", "agent": "researcher"})
        runs = client.app.state.runtime.runs
        runs.record_failure(
            run_id="run_failed",
            agent="researcher",
            input_text="bad",
            error="boom",
        )

        by_agent = client.get("/api/v1/runs?agent=researcher").json()
        failed = client.get("/api/v1/runs?status=failed").json()

    assert by_agent["total"] == 2
    assert failed["total"] == 1
    assert failed["items"][0]["run_id"] == "run_failed"


def test_sort_created_at_supports_descending_order(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "first"})
        client.post("/api/v1/runs", json={"input": "second"})
        body = client.get("/api/v1/runs?sort=-created_at").json()

    assert body["items"][0]["input"] == "second"
    assert body["items"][1]["input"] == "first"


def test_invalid_page_returns_validation_error(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/runs?page=0")

    assert response.status_code == 422


def test_unknown_run_returns_not_found(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/runs/ghost")

    assert response.status_code == 404


def test_run_query_requires_permission(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[])
        response = client.get("/api/v1/runs", headers={HEADER: key})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_run_query_permission_allows_read(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.RUN_READ.value])
        response = client.get("/api/v1/runs", headers={HEADER: key})

    assert response.status_code == 200
