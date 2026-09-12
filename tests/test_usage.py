"""Workspace usage and Dashboard quota usage tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import create_tenant, tenant_app


def _create_chat_agent(client: TestClient, headers: dict[str, str]) -> None:
    client.post("/api/v1/agents", headers=headers, json={"name": "chat"})


def test_empty_usage_is_zeroed(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        body = client.get("/api/v1/usage", headers=tenant["headers"]).json()

    assert body["runs"] == 0
    assert body["total_tokens"] == 0
    assert body["tool_calls"] == 0


def test_usage_aggregates_runs_and_tokens(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1000})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        _create_chat_agent(client, tenant["headers"])
        for value in ("a", "b"):
            client.post(
                "/api/v1/runs",
                headers=tenant["headers"],
                json={"agent": "chat", "input": value},
            )
        body = client.get("/api/v1/usage", headers=tenant["headers"]).json()

    assert body["runs"] == 2
    assert body["total_tokens"] > 0
    assert body["prompt_tokens"] > 0


def test_month_period_and_dashboard_usage(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1000})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        month = client.get(
            "/api/v1/usage?period=month", headers=tenant["headers"]
        ).json()
        dashboard = client.get(
            "/api/v1/dashboard/usage", headers=tenant["headers"]
        ).json()

    assert len(month["period"]) == 7
    assert "runs" in dashboard
    assert "tokens" in dashboard


def test_usage_is_workspace_isolated(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1000})) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        _create_chat_agent(client, tenant_a["headers"])
        client.post(
            "/api/v1/runs",
            headers=tenant_a["headers"],
            json={"agent": "chat", "input": "A-only"},
        )
        usage_b = client.get("/api/v1/usage", headers=tenant_b["headers"]).json()

    assert usage_b["runs"] == 0


def test_invalid_usage_period_is_rejected(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        response = client.get(
            "/api/v1/usage?period=year", headers=tenant["headers"]
        )

    assert response.status_code == 422
