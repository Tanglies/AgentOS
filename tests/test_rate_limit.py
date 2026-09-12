"""Workspace/API-key rate limiting tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import create_tenant, tenant_app


def test_rate_limit_returns_429_after_threshold(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 2})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        first = client.get("/api/v1/workspaces", headers=tenant["headers"])
        second = client.get("/api/v1/workspaces", headers=tenant["headers"])
        third = client.get("/api/v1/workspaces", headers=tenant["headers"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limit_exceeded"


def test_rate_limit_is_isolated_per_workspace_and_key(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1})) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        first_a = client.get("/api/v1/workspaces", headers=tenant_a["headers"])
        second_a = client.get("/api/v1/workspaces", headers=tenant_a["headers"])
        first_b = client.get("/api/v1/workspaces", headers=tenant_b["headers"])

    assert first_a.status_code == 200
    assert second_a.status_code == 429
    assert first_b.status_code == 200


def test_rate_limit_exceeded_is_audited(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, quota={"requests_per_minute": 1})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        client.get("/api/v1/workspaces", headers=tenant["headers"])
        client.get("/api/v1/workspaces", headers=tenant["headers"])
        records = client.app.state.audit_log.list(
            workspace_id=tenant["workspace_id"]
        )

    assert any(record.action == "rate_limit.exceeded" for record in records)
