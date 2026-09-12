"""API Key, permission, and tool-execution security tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from agentos.llm.base import ToolCall
from agentos.runtime.api_keys import ApiKeySettings, ApiKeyStore, Permission, hash_key
from agentos.runtime.tools import FunctionTool, ToolRegistry, tool_permission_scope

BOOTSTRAP_KEY = "sk-bootstrap-admin"
HEADER = "X-API-Key"


def _store(tmp_path: Path) -> ApiKeyStore:
    return ApiKeyStore(ApiKeySettings(db_path=str(tmp_path / "api-keys.db")))


def _app(
    tmp_path: Path,
    *,
    auth_enabled: bool = True,
    static_keys: tuple[str, ...] = (BOOTSTRAP_KEY,),
) -> object:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            auth={
                "enabled": auth_enabled,
                "api_keys": [SecretStr(key) for key in static_keys],
            },
            api_keys={"db_path": str(tmp_path / "api-keys.db")},
            runs={"db_path": str(tmp_path / "runs.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
            registry={"persist": False},
        )
    )


def _issue(client: TestClient, name: str, permissions: list[str] | None = None) -> dict:
    payload: dict[str, object] = {"name": name}
    if permissions is not None:
        payload["permissions"] = permissions
    response = client.post(
        "/api/v1/api-keys", json=payload, headers={HEADER: BOOTSTRAP_KEY}
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- Store layer ---------------------------------------------------------


def test_issue_returns_plaintext_once_and_stores_hash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.issue("worker")

    assert result.key.startswith("sk-agentos-")
    assert result.record.id is not None
    assert result.record.key_hash == hash_key(result.key)
    assert result.key not in result.record.model_dump_json()


def test_default_permissions_exclude_admin(tmp_path: Path) -> None:
    result = _store(tmp_path).issue("worker")

    assert Permission.TOOL_EXECUTE.value in result.record.permissions
    assert Permission.API_KEY_ADMIN.value not in result.record.permissions
    assert Permission.ALL.value not in result.record.permissions


def test_issue_accepts_explicit_permissions(tmp_path: Path) -> None:
    result = _store(tmp_path).issue("reader", permissions=[Permission.RUN_READ.value])

    assert result.record.permissions == [Permission.RUN_READ.value]


def test_issue_rejects_blank_name(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _store(tmp_path).issue("   ")


def test_issue_rejects_unknown_permissions(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _store(tmp_path).issue("worker", permissions=["not:a:permission"])


def test_issue_rejects_duplicate_name(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.issue("worker")

    with pytest.raises(ConflictError):
        store.issue("worker")


def test_authenticate_valid_key_returns_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.issue("worker", permissions=[Permission.RUN_READ.value])

    identity = store.authenticate(result.key)

    assert identity is not None
    assert identity.name == "worker"
    assert identity.can(Permission.RUN_READ)
    assert not identity.can(Permission.RUN_CREATE)


def test_authenticate_rejects_empty_and_wrong_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.issue("worker")

    assert store.authenticate("") is None
    assert store.authenticate("sk-agentos-wrong") is None


def test_authenticate_updates_last_used_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.issue("worker")

    store.authenticate(result.key)

    record = store.repository.get_by_hash(hash_key(result.key))
    assert record is not None
    assert record.last_used_at is not None


def test_revoke_disables_key_and_is_reflected_in_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.issue("worker")
    assert result.record.id is not None

    revoked = store.revoke(result.record.id)

    assert revoked.revoked
    assert store.authenticate(result.key) is None
    assert [item.name for item in store.list()] == []
    assert [item.name for item in store.list(include_revoked=True)] == ["worker"]


def test_revoke_missing_key_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        _store(tmp_path).revoke(999)


# --- HTTP management and route permissions --------------------------------


def test_admin_can_issue_and_list_database_keys(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        listed = client.get("/api/v1/api-keys", headers={HEADER: BOOTSTRAP_KEY})

    assert created["key"].startswith("sk-agentos-")
    assert created["name"] == "reader"
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["name"] == "reader"


def test_list_never_exposes_plaintext_or_hash(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        body = client.get("/api/v1/api-keys", headers={HEADER: BOOTSTRAP_KEY}).json()

    serialized = str(body)
    assert created["key"] not in serialized
    assert "key_hash" not in serialized


def test_issued_key_can_call_allowed_route(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        response = client.get("/api/v1/runs", headers={HEADER: created["key"]})

    assert response.status_code == 200


def test_issued_key_cannot_call_route_outside_permissions(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        response = client.post(
            "/api/v1/runs", json={"input": "hello"}, headers={HEADER: created["key"]}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_issued_key_cannot_manage_api_keys(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        response = client.get("/api/v1/api-keys", headers={HEADER: created["key"]})

    assert response.status_code == 403


def test_revoked_key_is_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.RUN_READ.value])
        key_id = created["id"]
        assert client.delete(
            f"/api/v1/api-keys/{key_id}", headers={HEADER: BOOTSTRAP_KEY}
        ).status_code == 204
        response = client.get("/api/v1/runs", headers={HEADER: created["key"]})

    assert response.status_code == 401


def test_invalid_permission_request_returns_422(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/api-keys",
            json={"name": "bad", "permissions": ["nope"]},
            headers={HEADER: BOOTSTRAP_KEY},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_duplicate_key_name_returns_conflict(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        _issue(client, "worker")
        response = client.post(
            "/api/v1/api-keys",
            json={"name": "worker"},
            headers={HEADER: BOOTSTRAP_KEY},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_health_remains_public_with_auth_enabled(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/health").status_code == 200


def test_route_permission_is_checked_before_runtime(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = _issue(client, "reader", [Permission.TOOL_READ.value])
        allowed = client.get("/api/v1/tools", headers={HEADER: created["key"]})
        denied = client.get("/api/v1/agents", headers={HEADER: created["key"]})

    assert allowed.status_code == 200
    assert denied.status_code == 403


# --- Tool execution enforcement ------------------------------------------


async def _call_tool(registry: ToolRegistry) -> object:
    return await registry.execute(ToolCall(id="call_1", name="echo", arguments="{}"))


@pytest.mark.asyncio
async def test_tool_execution_denied_without_permission() -> None:
    registry = ToolRegistry([FunctionTool("echo", lambda: "ok")])

    with tool_permission_scope(lambda permission: False), pytest.raises(PermissionDeniedError):
        await _call_tool(registry)


@pytest.mark.asyncio
async def test_tool_execution_allowed_with_permission() -> None:
    registry = ToolRegistry([FunctionTool("echo", lambda: "ok")])

    with tool_permission_scope(lambda permission: permission == Permission.TOOL_EXECUTE.value):
        result = await _call_tool(registry)

    assert result.content == "ok"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_direct_runtime_tool_call_remains_allowed_without_http_scope() -> None:
    registry = ToolRegistry([FunctionTool("echo", lambda: "ok")])

    result = await _call_tool(registry)

    assert result.content == "ok"
