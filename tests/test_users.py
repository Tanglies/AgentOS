"""Platform user API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.core.pagination import (
    KeysetCursor,
    PaginationCursor,
    encode_cursor,
    encode_keyset_cursor,
)
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


def test_user_cursor_pagination_is_stable_when_a_user_is_added(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        for username in ("alice", "bob", "carol"):
            response = client.post(
                "/api/v1/users",
                headers=headers(),
                json={"username": username},
            )
            assert response.status_code == 201

        first = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page_size": 2},
        ).json()
        client.post(
            "/api/v1/users",
            headers=headers(),
            json={"username": "dave"},
        )
        second = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page_size": 2, "cursor": first["next_cursor"]},
        ).json()
        third = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page_size": 2, "cursor": second["next_cursor"]},
        ).json()

    assert [item["username"] for item in first["items"]] == ["bootstrap", "alice"]
    assert [item["username"] for item in second["items"]] == ["bob", "carol"]
    assert [item["username"] for item in third["items"]] == ["dave"]
    assert first["total"] == 4
    assert second["total"] == third["total"] == 5
    assert first["next_cursor"] and second["next_cursor"]
    assert third["next_cursor"] is None


def test_user_page_pagination_remains_available(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        for username in ("alice", "bob", "carol"):
            client.post(
                "/api/v1/users",
                headers=headers(),
                json={"username": username},
            )

        response = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page": 2, "page_size": 2},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert [item["username"] for item in body["items"]] == ["bob", "carol"]
    assert body["next_cursor"] is None


def test_user_cursor_cannot_be_combined_with_page(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        client.post(
            "/api/v1/users",
            headers=headers(),
            json={"username": "alice"},
        )
        first = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page_size": 1},
        ).json()
        response = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"page": 2, "cursor": first["next_cursor"]},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "token",
    [
        "not-a-cursor",
        encode_cursor(
            PaginationCursor(
                created_at=datetime(2026, 11, 4, tzinfo=UTC),
                item_id="1",
            )
        ),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="2")),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="1", order="desc")),
    ],
)
def test_user_list_rejects_foreign_or_malformed_cursors(
    tmp_path: Path,
    token: str,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/users",
            headers=headers(),
            params={"cursor": token},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
