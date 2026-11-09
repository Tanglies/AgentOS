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
from agentos.runtime.audit import ACTION_WORKSPACE_MEMBER_UPDATE
from tenancy_support import (
    create_tenant,
    create_workspace_key,
    headers,
    tenant_app,
)


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


def test_workspace_member_role_update_is_audited(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        user = client.post(
            "/api/v1/users", headers=headers(), json={"username": "member"}
        ).json()
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        member_path = f"/api/v1/workspaces/{workspace['id']}/members/{user['id']}"
        added = client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": user["id"], "role": "member"},
        )
        updated = client.patch(
            member_path,
            headers=headers(),
            json={"role": "admin"},
        )
        audit_entries = client.app.state.audit_log.list(
            workspace_id=workspace["id"],
            action=ACTION_WORKSPACE_MEMBER_UPDATE,
        )

    assert added.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["user_id"] == user["id"]
    assert updated.json()["username"] == "member"
    assert updated.json()["role"] == "admin"
    assert len(audit_entries) == 1
    assert audit_entries[0].target == str(user["id"])
    assert audit_entries[0].detail == "role: member -> admin"


def test_batch_update_workspace_member_roles_is_audited(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        admin = client.post(
            "/api/v1/users", headers=headers(), json={"username": "admin"}
        ).json()
        alice = client.post(
            "/api/v1/users", headers=headers(), json={"username": "alice"}
        ).json()
        bob = client.post(
            "/api/v1/users", headers=headers(), json={"username": "bob"}
        ).json()
        client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": admin["id"], "role": "admin"},
        )
        for user in (alice, bob):
            client.post(
                f"/api/v1/workspaces/{workspace['id']}/members",
                headers=headers(),
                json={"user_id": user["id"], "role": "member"},
            )
        admin_key = create_workspace_key(
            client,
            user_id=admin["id"],
            workspace_id=workspace["id"],
            name="admin-key",
        )
        path = f"/api/v1/workspaces/{workspace['id']}/members/batch"
        updates = {
            "updates": [
                {"user_id": alice["id"], "role": "admin"},
                {"user_id": bob["id"], "role": "viewer"},
                {"user_id": 9999, "role": "member"},
            ]
        }
        response = client.patch(path, headers=headers(admin_key), json=updates)
        repeated = client.patch(path, headers=headers(admin_key), json=updates)
        audit_entries = client.app.state.audit_log.list(
            workspace_id=workspace["id"],
            action=ACTION_WORKSPACE_MEMBER_UPDATE,
        )

    body = response.json()
    assert response.status_code == 200
    assert repeated.status_code == 200
    assert body["requested"] == 3
    assert body["updated"] == 2
    assert body["missing_user_ids"] == [9999]
    assert [(item["username"], item["role"]) for item in body["items"]] == [
        ("alice", "admin"),
        ("bob", "viewer"),
    ]
    assert repeated.json()["items"] == body["items"]
    assert len(audit_entries) == 2
    assert {entry.detail for entry in audit_entries} == {
        "role: member -> admin",
        "role: member -> viewer",
    }


def test_batch_workspace_member_update_protects_owner_atomically(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": target["id"], "role": "member"},
        )
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/batch",
            headers=headers(),
            json={
                "updates": [
                    {"user_id": target["id"], "role": "admin"},
                    {"user_id": 1, "role": "member"},
                ]
            },
        )
        members = client.get(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
        ).json()["items"]

    assert response.status_code == 403
    target_state = next(item for item in members if item["user_id"] == target["id"])
    assert target_state["role"] == "member"


@pytest.mark.parametrize(
    "updates",
    [
        [],
        [
            {"user_id": 2, "role": "admin"},
            {"user_id": 2, "role": "viewer"},
        ],
        [{"user_id": 2, "role": "owner"}],
        [{"user_id": 0, "role": "member"}],
        [{"user_id": index + 2, "role": "member"} for index in range(101)],
    ],
)
def test_batch_workspace_member_update_rejects_invalid_updates(
    tmp_path: Path,
    updates: list[dict[str, object]],
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.patch(
            "/api/v1/workspaces/1/members/batch",
            headers=headers(),
            json={"updates": updates},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_workspace_member_cannot_batch_update_roles(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        actor = client.post(
            "/api/v1/users", headers=headers(), json={"username": "actor"}
        ).json()
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        for user in (actor, target):
            client.post(
                f"/api/v1/workspaces/{workspace['id']}/members",
                headers=headers(),
                json={"user_id": user["id"], "role": "member"},
            )
        actor_key = create_workspace_key(
            client,
            user_id=actor["id"],
            workspace_id=workspace["id"],
            name="actor-key",
        )
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/batch",
            headers=headers(actor_key),
            json={"updates": [{"user_id": target["id"], "role": "admin"}]},
        )

    assert response.status_code == 403


def test_batch_workspace_member_update_is_workspace_scoped(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        client.post(
            "/api/v1/workspaces/1/members",
            headers=headers(),
            json={"user_id": target["id"], "role": "member"},
        )
        outsider = create_tenant(client, "outsider")
        response = client.patch(
            "/api/v1/workspaces/1/members/batch",
            headers=outsider["headers"],
            json={"updates": [{"user_id": target["id"], "role": "admin"}]},
        )

    assert response.status_code == 404


def test_workspace_admin_can_update_another_member_role(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        admin = client.post(
            "/api/v1/users", headers=headers(), json={"username": "admin"}
        ).json()
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": admin["id"], "role": "admin"},
        )
        client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": target["id"], "role": "member"},
        )
        admin_key = create_workspace_key(
            client,
            user_id=admin["id"],
            workspace_id=workspace["id"],
            name="admin-key",
        )
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/{target['id']}",
            headers=headers(admin_key),
            json={"role": "viewer"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


def test_workspace_member_cannot_update_roles(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        actor = client.post(
            "/api/v1/users", headers=headers(), json={"username": "actor"}
        ).json()
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        for user in (actor, target):
            client.post(
                f"/api/v1/workspaces/{workspace['id']}/members",
                headers=headers(),
                json={"user_id": user["id"], "role": "member"},
            )
        actor_key = create_workspace_key(
            client,
            user_id=actor["id"],
            workspace_id=workspace["id"],
            name="actor-key",
        )
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/{target['id']}",
            headers=headers(actor_key),
            json={"role": "admin"},
        )

    assert response.status_code == 403


def test_workspace_owner_role_is_protected_from_member_api(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        user = client.post(
            "/api/v1/users", headers=headers(), json={"username": "member"}
        ).json()
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        client.post(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
            json={"user_id": user["id"], "role": "member"},
        )
        change_owner = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/1",
            headers=headers(),
            json={"role": "admin"},
        )
        assign_owner = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/{user['id']}",
            headers=headers(),
            json={"role": "owner"},
        )

    assert change_owner.status_code == 403
    assert assign_owner.status_code == 422


def test_workspace_member_role_update_is_workspace_scoped(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        owner_workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Owner Team"}
        ).json()
        target = client.post(
            "/api/v1/users", headers=headers(), json={"username": "target"}
        ).json()
        client.post(
            f"/api/v1/workspaces/{owner_workspace['id']}/members",
            headers=headers(),
            json={"user_id": target["id"], "role": "member"},
        )
        outsider = create_tenant(client, "outsider")
        response = client.patch(
            f"/api/v1/workspaces/{owner_workspace['id']}/members/{target['id']}",
            headers=outsider["headers"],
            json={"role": "admin"},
        )

    assert response.status_code == 404


def test_workspace_member_cursor_pagination_is_stable_when_member_is_added(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        members_path = f"/api/v1/workspaces/{workspace['id']}/members"

        for username in ("alice", "bob", "carol"):
            user = client.post(
                "/api/v1/users",
                headers=headers(),
                json={"username": username},
            ).json()
            response = client.post(
                members_path,
                headers=headers(),
                json={"user_id": user["id"], "role": "member"},
            )
            assert response.status_code == 201

        first = client.get(
            members_path,
            headers=headers(),
            params={"page_size": 2},
        ).json()
        dave = client.post(
            "/api/v1/users",
            headers=headers(),
            json={"username": "dave"},
        ).json()
        response = client.post(
            members_path,
            headers=headers(),
            json={"user_id": dave["id"], "role": "member"},
        )
        assert response.status_code == 201
        second = client.get(
            members_path,
            headers=headers(),
            params={"page_size": 2, "cursor": first["next_cursor"]},
        ).json()
        third = client.get(
            members_path,
            headers=headers(),
            params={"page_size": 2, "cursor": second["next_cursor"]},
        ).json()

    assert [item["username"] for item in first["items"]] == ["bootstrap", "alice"]
    assert [item["username"] for item in second["items"]] == ["bob", "carol"]
    assert [item["username"] for item in third["items"]] == ["dave"]
    assert first["total"] == 4
    assert second["total"] == third["total"] == 5
    assert first["page"] == second["page"] == third["page"] == 1
    assert first["page_size"] == second["page_size"] == third["page_size"] == 2
    assert first["next_cursor"] and second["next_cursor"]
    assert third["next_cursor"] is None


def test_workspace_member_page_pagination_remains_available(tmp_path: Path) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        members_path = f"/api/v1/workspaces/{workspace['id']}/members"
        for username in ("alice", "bob", "carol"):
            user = client.post(
                "/api/v1/users",
                headers=headers(),
                json={"username": username},
            ).json()
            client.post(
                members_path,
                headers=headers(),
                json={"user_id": user["id"], "role": "member"},
            )

        response = client.get(
            members_path,
            headers=headers(),
            params={"page": 2, "page_size": 2},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert [item["username"] for item in body["items"]] == ["bob", "carol"]
    assert body["next_cursor"] is None


def test_workspace_member_cursor_cannot_be_combined_with_page(
    tmp_path: Path,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        workspace = client.post(
            "/api/v1/workspaces", headers=headers(), json={"name": "Team"}
        ).json()
        members_path = f"/api/v1/workspaces/{workspace['id']}/members"
        user = client.post(
            "/api/v1/users",
            headers=headers(),
            json={"username": "alice"},
        ).json()
        client.post(
            members_path,
            headers=headers(),
            json={"user_id": user["id"], "role": "member"},
        )
        first = client.get(
            members_path,
            headers=headers(),
            params={"page_size": 1},
        ).json()
        response = client.get(
            members_path,
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
                created_at=datetime(2026, 11, 6, tzinfo=UTC),
                item_id="1",
            )
        ),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="2")),
        encode_keyset_cursor(KeysetCursor(key="1", item_id="1", order="desc")),
    ],
)
def test_workspace_member_list_rejects_foreign_or_malformed_cursors(
    tmp_path: Path,
    token: str,
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/workspaces/1/members",
            headers=headers(),
            params={"cursor": token},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


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
