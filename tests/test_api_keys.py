"""API Key, permission, and tool-execution security tests."""

from __future__ import annotations

from datetime import UTC, datetime
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
from agentos.core.pagination import (
    KeysetCursor,
    PaginationCursor,
    encode_cursor,
    encode_keyset_cursor,
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


def test_authenticate_updates_last_used_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('agentos.runtime.api_keys.time.monotonic', lambda: 1.0)
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


def test_revoke_many_revokes_only_visible_active_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.issue("first", workspace_id=1)
    second = store.issue("second", workspace_id=2)
    assert first.record.id is not None
    assert second.record.id is not None

    revoked = store.revoke_many(
        [first.record.id, second.record.id, first.record.id, 999],
        workspace_id=1,
    )

    assert revoked == [first.record.id]
    assert store.authenticate(first.key) is None
    assert store.authenticate(second.key) is not None


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


def test_batch_revoke_revokes_keys_and_reports_missing_ids(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        keys = [
            _issue(client, name, [Permission.RUN_READ.value])
            for name in ("first", "second", "third")
        ]
        already_revoked = client.delete(
            f"/api/v1/api-keys/{keys[2]['id']}", headers={HEADER: BOOTSTRAP_KEY}
        )
        assert already_revoked.status_code == 204

        response = client.post(
            "/api/v1/api-keys/batch-revoke",
            json={"ids": [keys[0]["id"], keys[2]["id"], 999]},
            headers={HEADER: BOOTSTRAP_KEY},
        )

        first_request = client.get(
            "/api/v1/runs", headers={HEADER: keys[0]["key"]}
        )
        second_request = client.get(
            "/api/v1/runs", headers={HEADER: keys[1]["key"]}
        )
        listed = client.get("/api/v1/api-keys", headers={HEADER: BOOTSTRAP_KEY})

    assert response.status_code == 200
    assert response.json() == {
        "requested": 3,
        "revoked": 1,
        "missing_ids": [keys[2]["id"], 999],
    }
    assert first_request.status_code == 401
    assert second_request.status_code == 200
    assert [item["name"] for item in listed.json()["items"]] == ["second"]


@pytest.mark.parametrize(
    "ids",
    [
        [],
        [1, 1],
        [0],
        list(range(1, 102)),
    ],
)
def test_batch_revoke_rejects_invalid_id_sets(
    tmp_path: Path, ids: list[int]
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/api-keys/batch-revoke",
            json={"ids": ids},
            headers={HEADER: BOOTSTRAP_KEY},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


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


# --- List pagination ------------------------------------------------------


def _list_keys(client: TestClient, **params: object) -> dict:
    response = client.get(
        "/api/v1/api-keys", params=params, headers={HEADER: BOOTSTRAP_KEY}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_key_list_walks_all_pages_with_a_cursor(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for name in ("first", "second", "third", "fourth", "fifth"):
            _issue(client, name, [Permission.RUN_READ.value])

        first = _list_keys(client, limit=2)
        second = _list_keys(client, limit=2, cursor=first["next_cursor"])
        third = _list_keys(client, limit=2, cursor=second["next_cursor"])

    assert [item["name"] for item in first["items"]] == ["first", "second"]
    assert [item["name"] for item in second["items"]] == ["third", "fourth"]
    assert [item["name"] for item in third["items"]] == ["fifth"]
    # total 是过滤后的总数，不是本页条数
    assert first["total"] == second["total"] == third["total"] == 5
    assert third["next_cursor"] is None


@pytest.mark.parametrize("limit", [0, 501])
def test_api_key_list_rejects_out_of_range_limit(tmp_path: Path, limit: int) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/api-keys",
            params={"limit": limit},
            headers={HEADER: BOOTSTRAP_KEY},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_api_key_list_returns_an_empty_page_after_the_last_id(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        ids = [_issue(client, name)["id"] for name in ("a", "b", "c")]
        cursor = encode_keyset_cursor(
            KeysetCursor(key=str(ids[-1]), item_id=str(ids[-1]), order="asc")
        )
        page = _list_keys(client, limit=2, cursor=cursor)

    assert page["items"] == []
    assert page["total"] == 3
    assert page["next_cursor"] is None


def test_api_key_cursor_does_not_skip_after_a_key_is_revoked(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        ids = {name: _issue(client, name)["id"] for name in ("a", "b", "c", "d")}
        first = _list_keys(client, limit=2)
        assert [item["name"] for item in first["items"]] == ["a", "b"]

        assert (
            client.delete(
                f"/api/v1/api-keys/{ids['a']}", headers={HEADER: BOOTSTRAP_KEY}
            ).status_code
            == 204
        )

        second = _list_keys(client, limit=2, cursor=first["next_cursor"])

    assert [item["name"] for item in second["items"]] == ["c", "d"]
    assert second["total"] == 3  # 已吊销的密钥不再计入
    assert second["next_cursor"] is None


def test_api_key_cursor_is_stable_when_a_new_key_is_issued(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for name in ("a", "b", "c"):
            _issue(client, name)
        first = _list_keys(client, limit=2)

        _issue(client, "d")

        second = _list_keys(client, limit=2, cursor=first["next_cursor"])

    assert [item["name"] for item in first["items"]] == ["a", "b"]
    assert [item["name"] for item in second["items"]] == ["c", "d"]
    assert second["total"] == 4


def test_api_key_list_includes_revoked_keys_when_asked(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        ids = {name: _issue(client, name)["id"] for name in ("a", "b")}
        client.delete(f"/api/v1/api-keys/{ids['a']}", headers={HEADER: BOOTSTRAP_KEY})

        without_revoked = _list_keys(client, limit=1)
        with_revoked = _list_keys(client, limit=1, include_revoked=True, cursor=None)

    assert [item["name"] for item in without_revoked["items"]] == ["b"]
    assert without_revoked["total"] == 1
    assert [item["name"] for item in with_revoked["items"]] == ["a"]
    assert with_revoked["total"] == 2
    assert with_revoked["next_cursor"]


@pytest.mark.parametrize(
    "token",
    [
        "not-a-cursor",
        "e30",
        # 来自 Agent 列表的字符串游标：本列表按整数 id 排序，必须拒绝
        encode_keyset_cursor(KeysetCursor(key="alpha", item_id="alpha")),
        # 排序键与记录 id 不一致
        encode_keyset_cursor(KeysetCursor(key="1", item_id="2")),
        # id 超出 SQLite rowid 范围
        encode_keyset_cursor(KeysetCursor(key="0", item_id="0")),
        # 排序方向与本列表不符（本列表固定升序）
        encode_keyset_cursor(KeysetCursor(key="1", item_id="1", order="desc")),
        # 时间型游标属于另一个编码版本
        encode_cursor(
            PaginationCursor(created_at=datetime(2026, 10, 16, tzinfo=UTC), item_id="1")
        ),
    ],
)
def test_api_key_list_rejects_foreign_or_malformed_cursors(
    tmp_path: Path, token: str
) -> None:
    with TestClient(_app(tmp_path)) as client:
        _issue(client, "worker")
        response = client.get(
            "/api/v1/api-keys", params={"cursor": token}, headers={HEADER: BOOTSTRAP_KEY}
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_repository_list_resumes_after_an_id_cursor(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = [store.issue(name).record for name in ("a", "b", "c")]

    page = store.list(limit=2)
    assert [record.id for record in page] == [created[0].id, created[1].id]

    rest = store.list(limit=2, after_id=page[-1].id)
    assert [record.id for record in rest] == [created[2].id]
    assert store.list(after_id=created[2].id) == []


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
