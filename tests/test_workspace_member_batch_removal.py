"""Workspace member batch removal API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.runtime.audit import ACTION_WORKSPACE_MEMBER_REMOVE
from tenancy_support import (
    create_tenant,
    create_workspace_key,
    headers,
    tenant_app,
)


def test_batch_remove_workspace_members_reports_missing_and_audits(
    tmp_path: Path,
) -> None:
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
        body = {"user_ids": [alice["id"], bob["id"], 9999]}
        response = client.request(
            "DELETE",
            path,
            headers=headers(admin_key),
            json=body,
        )
        repeated = client.request(
            "DELETE",
            path,
            headers=headers(admin_key),
            json=body,
        )
        members = client.get(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(admin_key),
        ).json()
        audit_entries = client.app.state.audit_log.list(
            workspace_id=workspace["id"],
            action=ACTION_WORKSPACE_MEMBER_REMOVE,
        )

    assert response.status_code == 200
    assert response.json() == {
        "requested": 3,
        "removed": 2,
        "missing_user_ids": [9999],
    }
    assert repeated.status_code == 200
    assert repeated.json() == {
        "requested": 3,
        "removed": 0,
        "missing_user_ids": [alice["id"], bob["id"], 9999],
    }
    remaining_usernames = {member["username"] for member in members["items"]}
    assert "admin" in remaining_usernames
    assert "alice" not in remaining_usernames
    assert "bob" not in remaining_usernames
    assert {entry.target for entry in audit_entries} == {
        str(alice["id"]),
        str(bob["id"]),
    }


def test_batch_remove_workspace_members_protects_owner_atomically(
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
        response = client.request(
            "DELETE",
            f"/api/v1/workspaces/{workspace['id']}/members/batch",
            headers=headers(),
            json={"user_ids": [target["id"], 1]},
        )
        members = client.get(
            f"/api/v1/workspaces/{workspace['id']}/members",
            headers=headers(),
        ).json()

    assert response.status_code == 403
    assert any(member["user_id"] == target["id"] for member in members["items"])


def test_workspace_member_cannot_batch_remove_members(tmp_path: Path) -> None:
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
        response = client.request(
            "DELETE",
            f"/api/v1/workspaces/{workspace['id']}/members/batch",
            headers=headers(actor_key),
            json={"user_ids": [target["id"]]},
        )

    assert response.status_code == 403


def test_batch_remove_workspace_members_is_workspace_scoped(tmp_path: Path) -> None:
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
        response = client.request(
            "DELETE",
            "/api/v1/workspaces/1/members/batch",
            headers=outsider["headers"],
            json={"user_ids": [target["id"]]},
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "user_ids",
    [
        [],
        [2, 2],
        [0],
        [index + 2 for index in range(101)],
    ],
)
def test_batch_remove_workspace_members_rejects_invalid_ids(
    tmp_path: Path,
    user_ids: list[int],
) -> None:
    with TestClient(tenant_app(tmp_path)) as client:
        response = client.request(
            "DELETE",
            "/api/v1/workspaces/1/members/batch",
            headers=headers(),
            json={"user_ids": user_ids},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
