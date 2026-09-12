"""Tool metadata and Workspace/Agent management API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import create_tenant, headers, tenant_app


def test_high_risk_tool_is_disabled_by_default(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, tools={"allow_shell": True})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        body = client.get("/api/v1/tools", headers=tenant["headers"]).json()

    command = next(item for item in body["items"] if item["name"] == "run_command")
    assert command["risk_level"] == "high"
    assert command["enabled"] is False


def test_high_risk_tool_can_be_explicitly_enabled(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path, tools={"allow_shell": True})) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        response = client.patch(
            "/api/v1/tools/run_command",
            headers=tenant["headers"],
            json={"enabled": True},
        )

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_tool_list_exposes_metadata(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        body = client.get("/api/v1/tools", headers=tenant["headers"]).json()

    calculate = next(item for item in body["items"] if item["name"] == "calculate")
    assert calculate["category"] == "general"
    assert calculate["risk_level"] == "low"
    assert calculate["enabled"] is True


def test_tool_management_requires_admin_permission(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant = create_tenant(client, "alice", workspace_name="A")
        key = client.app.state.api_key_store.issue(
            "tool-reader",
            user_id=tenant["user_id"],
            workspace_id=tenant["workspace_id"],
            permissions=["tool:read"],
        ).key
        response = client.patch(
            "/api/v1/tools/calculate",
            headers=headers(key),
            json={"enabled": False},
        )

    assert response.status_code == 403


def test_workspace_tool_override_does_not_leak_to_other_workspace(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        tenant_a = create_tenant(client, "alice", workspace_name="A")
        tenant_b = create_tenant(client, "bob", workspace_name="B")
        client.patch(
            "/api/v1/tools/calculate",
            headers=tenant_a["headers"],
            json={"enabled": False},
        )
        body_b = client.get("/api/v1/tools", headers=tenant_b["headers"]).json()

    calculate_b = next(item for item in body_b["items"] if item["name"] == "calculate")
    assert calculate_b["enabled"] is True
