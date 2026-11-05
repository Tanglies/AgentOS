"""Workspace lifecycle and membership API tests."""

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


def test_create_list_get_update_and_delete_workspace(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        created = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Alpha"}
        )
        workspace_id = created.json()["id"]
        listed = client.get("/api/v1/workspaces", headers=headers())
        fetched = client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers())
        updated = client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            headers=headers(),
            json={"name": "Alpha Renamed"},
        )
        deleted = client.delete(
            f"/api/v1/workspaces/{workspace_id}", headers=headers()
        )
        missing = client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers())

    assert created.status_code == 201
    assert created.json()["role"] == "owner"
    assert listed.json()["total"] == 2
    assert fetched.json()["name"] == "Alpha"
    assert updated.json()["name"] == "Alpha Renamed"
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_duplicate_workspace_returns_conflict(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        client.post("/api/v1/workspaces", headers=headers(), json={"name": "Alpha"})
        response = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Alpha"}
        )

    assert response.status_code == 409


def test_member_lifecycle(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        user = client.post(
            "/api/v1/users", headers=headers(), json={"username": "member"}
        ).json()
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        added = client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": user["id"], "role": "member"},
        )
        listed = client.get(
            f"/api/v1/workspaces/{workspace['id']}/members", headers=headers()
        )
        removed = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/members/{user['id']}",
            headers=headers(),
        )
        after = client.get(
            f"/api/v1/workspaces/{workspace['id']}/members", headers=headers()
        )

    assert added.status_code == 201
    assert added.json()["user_id"] == user["id"]
    assert listed.json()["total"] == 2
    assert removed.status_code == 204
    assert after.json()["total"] == 1


def test_default_workspace_cannot_be_deleted(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.delete("/api/v1/workspaces/1", headers=headers())

    assert response.status_code == 403


def test_non_member_cannot_read_workspace(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        outsider = client.post(
            "/api/v1/users", headers=headers(), json={"username": "outsider"}
        ).json()
        other = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Other"}
        ).json()
        key = client.app.state.api_key_store.issue(
            "outsider-key",
            user_id=outsider["id"],
            workspace_id=other["id"],
            permissions=["workspace:read"],
        ).key
        response = client.get("/api/v1/workspaces/1", headers=headers(key))

    assert response.status_code == 404


def test_workspace_cursor_pagination_is_stable_when_a_workspace_is_added(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        for name in ("alice-team", "bob-team", "carol-team"):
            response = client.post(
                "/api/v1/workspaces",
                headers=headers(),
                json={"name": name},
            )
            assert response.status_code == 201

        first = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"page_size": 2},
        ).json()
        client.post(
            "/api/v1/workspaces",
            headers=headers(),
            json={"name": "dave-team"},
        )
        second = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"page_size": 2, "cursor": first["next_cursor"]},
        ).json()
        third = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"page_size": 2, "cursor": second["next_cursor"]},
        ).json()

    assert [item["name"] for item in first["items"]] == [
        "Default Workspace",
        "alice-team",
    ]
    assert [item["name"] for item in second["items"]] == ["bob-team", "carol-team"]
    assert [item["name"] for item in third["items"]] == ["dave-team"]
    assert first["total"] == 4
    assert second["total"] == third["total"] == 5
    assert first["next_cursor"] and second["next_cursor"]
    assert third["next_cursor"] is None


def test_workspace_page_pagination_remains_available(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        for name in ("alice-team", "bob-team", "carol-team"):
            client.post(
                "/api/v1/workspaces",
                headers=headers(),
                json={"name": name},
            )

        response = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"page": 2, "page_size": 2},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert [item["name"] for item in body["items"]] == ["bob-team", "carol-team"]
    assert body["next_cursor"] is None


def test_workspace_cursor_cannot_be_combined_with_page(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        client.post(
            "/api/v1/workspaces",
            headers=headers(),
            json={"name": "alice-team"},
        )
        first = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"page_size": 1},
        ).json()
        response = client.get(
            "/api/v1/workspaces",
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
                created_at=datetime(2026, 11, 5, tzinfo=UTC),
                item_id="1",
            )
        ),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="2")),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="1", order="desc")),
    ],
)
def test_workspace_list_rejects_foreign_or_malformed_cursors(
    tmp_path: Path,
    token: str,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/workspaces",
            headers=headers(),
            params={"cursor": token},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
