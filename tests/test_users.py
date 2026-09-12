"""Platform user API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tenancy_support import headers, tenant_app


def test_create_list_and_get_user(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        created = client.post(
            "/api/v1/users",
            headers=headers(),
            json={"username": "alice", "display_name": "Alice"},
        )
        listed = client.get("/api/v1/users", headers=headers())
        fetched = client.get(
            f"/api/v1/users/{created.json()['id']}", headers=headers()
        )

    assert created.status_code == 201
    assert created.json()["username"] == "alice"
    assert listed.json()["total"] == 2
    assert fetched.json()["display_name"] == "Alice"


def test_duplicate_username_returns_conflict(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        client.post("/api/v1/users", headers=headers(), json={"username": "alice"})
        response = client.post(
            "/api/v1/users", headers=headers(), json={"username": "alice"}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_unknown_user_returns_not_found(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.get("/api/v1/users/999", headers=headers())

    assert response.status_code == 404


def test_user_api_requires_auth(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.get("/api/v1/users")

    assert response.status_code == 401


def test_user_creation_requires_permission(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        key = client.app.state.api_key_store.issue(
            "reader",
            permissions=["user:read"],
        ).key
        response = client.post(
            "/api/v1/users", headers=headers(key), json={"username": "blocked"}
        )

    assert response.status_code == 403


def test_bootstrap_user_is_seeded(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        body = client.get("/api/v1/users", headers=headers()).json()

    assert body["items"][0]["id"] == 1
    assert body["items"][0]["username"] == "bootstrap"
