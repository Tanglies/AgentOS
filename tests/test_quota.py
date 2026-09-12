"""Workspace quota enforcement tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import create_tenant, tenant_app


def _create_chat_agent(client: TestClient, headers: dict[str, str]) -> None:
    client.post(
        "/api/v1/agents", headers=headers, json={"name": "chat"}
    )


def test_daily_run_quota_rejects_excess_runs(tmp_path: Path) -> None:
    with TestClient(
        tenant_app(
            tmp_path,
            quota={"daily_run_limit": 1, "requests_per_minute": 1000},
        )
    ) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        _create_chat_agent(client, tenant["headers"])
        first = client.post(
            "/api/v1/runs", headers=tenant["headers"], json={"agent": "chat", "input": "a"}
        )
        second = client.post(
            "/api/v1/runs", headers=tenant["headers"], json={"agent": "chat", "input": "b"}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"


def test_quota_is_isolated_per_workspace(tmp_path: Path) -> None:
    with TestClient(
        tenant_app(
            tmp_path,
            quota={"daily_run_limit": 1, "requests_per_minute": 1000},
        )
    ) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        _create_chat_agent(client, tenant_a["headers"])
        _create_chat_agent(client, tenant_b["headers"])
        client.post(
            "/api/v1/runs", headers=tenant_a["headers"], json={"agent": "chat", "input": "a"}
        )
        response_a = client.post(
            "/api/v1/runs", headers=tenant_a["headers"], json={"agent": "chat", "input": "b"}
        )
        response_b = client.post(
            "/api/v1/runs", headers=tenant_b["headers"], json={"agent": "chat", "input": "c"}
        )

    assert response_a.status_code == 429
    assert response_b.status_code == 200


def test_quota_can_be_updated_through_api(tmp_path: Path) -> None:
    with TestClient(
        tenant_app(
            tmp_path,
            quota={"daily_run_limit": 5, "requests_per_minute": 1000},
        )
    ) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        response = client.patch(
            "/api/v1/quota",
            headers=tenant["headers"],
            json={"daily_run_limit": 2, "max_tool_calls_per_run": 3},
        )
        fetched = client.get("/api/v1/quota", headers=tenant["headers"]).json()

    assert response.status_code == 200
    assert fetched["daily_run_limit"] == 2
    assert fetched["max_tool_calls_per_run"] == 3


def test_token_quota_rejects_after_budget_reached(tmp_path: Path) -> None:
    with TestClient(
        tenant_app(
            tmp_path,
            quota={"daily_token_limit": 1, "requests_per_minute": 1000},
        )
    ) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        _create_chat_agent(client, tenant["headers"])
        first = client.post(
            "/api/v1/runs", headers=tenant["headers"], json={"agent": "chat", "input": "a"}
        )
        second = client.post(
            "/api/v1/runs", headers=tenant["headers"], json={"agent": "chat", "input": "b"}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "token quota" in second.json()["error"]["message"]
