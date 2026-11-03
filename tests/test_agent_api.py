"""Agent management API contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
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
        auth={
            "enabled": auth,
            "api_keys": [SecretStr(BOOTSTRAP_KEY)] if auth else [],
        },
        registry={"persist": True, "db_path": str(tmp_path / "agents.db")},
        runs={"db_path": str(tmp_path / "runs.db")},
        api_keys={"db_path": str(tmp_path / "api-keys.db")},
        memory={"long_term_db_path": str(tmp_path / "memory.db")},
    )


def _app(tmp_path: Path, *, auth: bool = False):
    return create_app(_settings(tmp_path, auth=auth))


def _issue(client: TestClient, *, permissions: list[str]) -> str:
    response = client.post(
        "/api/v1/api-keys",
        headers={HEADER: BOOTSTRAP_KEY},
        json={"name": "tester", "permissions": permissions},
    )
    assert response.status_code == 201, response.text
    return response.json()["key"]


def test_create_returns_complete_agent_details(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "researcher",
                "description": "搜索与归纳",
                "system_prompt": "只返回可靠结论",
                "model": "qwen3.8-max",
                "temperature": 0.2,
                "max_iterations": 5,
                "tools": ["calculate"],
                "metadata": {"team": "data"},
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] is not None
    assert body["name"] == "researcher"
    assert body["description"] == "搜索与归纳"
    assert body["system_prompt"] == "只返回可靠结论"
    assert body["model"] == "qwen3.8-max"
    assert body["temperature"] == 0.2
    assert body["max_iterations"] == 5
    assert body["tools"] == ["calculate"]
    assert body["metadata"] == {"team": "data"}
    assert body["created_at"] and body["updated_at"]


def test_list_supports_page_and_page_size(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for name in ("zeta", "alpha", "middle"):
            client.post("/api/v1/agents", json={"name": name})
        response = client.get("/api/v1/agents?page=2&page_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert body["total"] == 4
    assert len(body["items"]) == 1


def test_get_agent_detail(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "worker", "description": "x"})
        response = client.get("/api/v1/agents/worker")

    assert response.status_code == 200
    assert response.json()["description"] == "x"


def test_update_agent_preserves_omitted_fields_and_can_clear_optional_fields(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post(
            "/api/v1/agents",
            json={
                "name": "worker",
                "description": "old",
                "system_prompt": "old prompt",
                "model": "qwen3.8-max",
                "temperature": 0.2,
                "max_iterations": 5,
                "tools": ["calculate"],
                "metadata": {"owner": "platform"},
            },
        )
        response = client.patch(
            "/api/v1/agents/worker",
            json={
                "description": "updated",
                "system_prompt": None,
                "tools": None,
                "metadata": None,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "updated"
    assert body["system_prompt"] is None
    assert body["model"] == "qwen3.8-max"
    assert body["temperature"] == 0.2
    assert body["max_iterations"] == 5
    assert body["tools"] == []
    assert body["metadata"] == {}


def test_update_unknown_agent_returns_not_found(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.patch(
            "/api/v1/agents/missing",
            json={"description": "updated"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_update_agent_rejects_an_empty_patch(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "worker"})
        response = client.patch("/api/v1/agents/worker", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_batch_update_agents_reports_updated_and_missing_names(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        for name in ("alpha", "beta"):
            assert client.post("/api/v1/agents", json={"name": name}).status_code == 201

        response = client.patch(
            "/api/v1/agents/batch",
            json={
                "updates": [
                    {"name": "beta", "description": "updated beta"},
                    {"name": "alpha", "temperature": 0.5},
                    {"name": "missing", "model": "qwen3.8-flash"},
                ]
            },
        )
        audit = client.get(
            "/api/v1/audit",
            params={"action": "agent.update", "limit": 10},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == 3
    assert body["updated"] == 2
    assert body["missing_names"] == ["missing"]
    assert [item["name"] for item in body["items"]] == ["beta", "alpha"]
    assert body["items"][0]["description"] == "updated beta"
    assert body["items"][1]["temperature"] == 0.5
    assert audit.status_code == 200
    assert {entry["target"] for entry in audit.json()} == {"alpha", "beta"}


@pytest.mark.parametrize(
    "updates",
    [
        [],
        [
            {"name": "worker", "description": "x"},
            {"name": "worker", "model": "qwen3.8-flash"},
        ],
        [{"name": "worker"}],
        [{"name": "bad name", "description": "x"}],
        [
            {"name": f"agent{index}", "description": "x"}
            for index in range(101)
        ],
    ],
)
def test_batch_update_rejects_invalid_updates(
    tmp_path: Path, updates: list[dict[str, object]]
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.patch(
            "/api/v1/agents/batch",
            json={"updates": updates},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_duplicate_agent_returns_conflict(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "worker"})
        response = client.post("/api/v1/agents", json={"name": "worker"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_invalid_agent_returns_validation_error(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/agents", json={"name": "bad name!", "temperature": 3.0}
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_agent_returns_not_found(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/agents/ghost")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_delete_agent_then_get_returns_not_found(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "temporary"})
        deleted = client.delete("/api/v1/agents/temporary")
        fetched = client.get("/api/v1/agents/temporary")

    assert deleted.status_code == 204
    assert fetched.status_code == 404


def test_batch_delete_agents_reports_deleted_and_missing_names(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        for name in ("first", "second", "third"):
            assert client.post("/api/v1/agents", json={"name": name}).status_code == 201

        response = client.post(
            "/api/v1/agents/batch-delete",
            json={"names": ["third", "first", "missing"]},
        )

        second = client.get("/api/v1/agents/second")
        first = client.get("/api/v1/agents/first")

    assert response.status_code == 200
    assert response.json() == {
        "requested": 3,
        "deleted": 2,
        "missing_names": ["missing"],
    }
    assert second.status_code == 200
    assert first.status_code == 404


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["worker", "worker"],
        [""],
        ["bad name"],
        [f"agent{index}" for index in range(101)],
    ],
)
def test_batch_delete_agents_rejects_invalid_name_sets(
    tmp_path: Path, names: list[str]
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/agents/batch-delete",
            json={"names": names},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_agent_survives_application_restart(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/agents", json={"name": "persistent", "description": "keep"})

    with TestClient(_app(tmp_path)) as restarted:
        response = restarted.get("/api/v1/agents/persistent")

    assert response.status_code == 200
    assert response.json()["description"] == "keep"


def test_agent_api_requires_auth_when_enabled(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 401


def test_read_only_key_cannot_create_agent(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        key = _issue(client, permissions=[Permission.AGENT_READ.value])
        read = client.get("/api/v1/agents", headers={HEADER: key})
        write = client.post(
            "/api/v1/agents", headers={HEADER: key}, json={"name": "blocked"}
        )

    assert read.status_code == 200
    assert write.status_code == 403


def test_read_only_key_cannot_batch_delete_agents(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        created = client.post(
            "/api/v1/agents",
            headers={HEADER: BOOTSTRAP_KEY},
            json={"name": "protected"},
        )
        key = _issue(client, permissions=[Permission.AGENT_READ.value])
        response = client.post(
            "/api/v1/agents/batch-delete",
            headers={HEADER: key},
            json={"names": ["protected"]},
        )

    assert created.status_code == 201
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/agents/protected", {"description": "blocked"}),
        (
            "/api/v1/agents/batch",
            {"updates": [{"name": "protected", "description": "blocked"}]},
        ),
    ],
)
def test_read_only_key_cannot_update_agents(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
) -> None:
    with TestClient(_app(tmp_path, auth=True)) as client:
        created = client.post(
            "/api/v1/agents",
            headers={HEADER: BOOTSTRAP_KEY},
            json={"name": "protected"},
        )
        key = _issue(client, permissions=[Permission.AGENT_READ.value])
        response = client.patch(path, headers={HEADER: key}, json=payload)

    assert created.status_code == 201
    assert response.status_code == 403
