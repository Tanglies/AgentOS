"""API Key 认证测试。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings

API_KEY = "sk-test-key"
HEADER = "X-API-Key"


def _app(*, enabled: bool = True, keys: tuple[str, ...] = (API_KEY,)) -> FastAPI:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            auth={"enabled": enabled, "api_keys": [SecretStr(key) for key in keys]},
        )
    )


# --- 关闭认证（默认）------------------------------------------------------


def test_auth_disabled_allows_anonymous_access() -> None:
    with TestClient(_app(enabled=False)) as client:
        assert client.get("/api/v1/agents").status_code == 200


def test_auth_is_disabled_by_default() -> None:
    assert Settings(_env_file=None).auth.enabled is False


# --- 开启认证 -------------------------------------------------------------


def test_missing_key_returns_401() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_wrong_key_returns_401() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/agents", headers={HEADER: "wrong"})

    assert response.status_code == 401


def test_correct_key_allows_access() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/agents", headers={HEADER: API_KEY})

    assert response.status_code == 200
    assert response.json()["total"] >= 1


def test_key_is_case_insensitive_header_name() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/agents", headers={"x-api-key": API_KEY})

    assert response.status_code == 200


def test_multiple_keys_are_accepted() -> None:
    with TestClient(_app(keys=("k1", "k2"))) as client:
        first = client.get("/api/v1/agents", headers={HEADER: "k1"})
        second = client.get("/api/v1/agents", headers={HEADER: "k2"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_any_configured_key_works_for_writes() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/agents",
            json={"name": "secured"},
            headers={HEADER: API_KEY},
        )

    assert response.status_code == 201


# --- 失败关闭 -------------------------------------------------------------


def test_enabled_without_keys_rejects_everything() -> None:
    """配置失误不能退化成不校验。"""
    with TestClient(_app(keys=())) as client:
        assert client.get("/api/v1/agents").status_code == 401
        assert client.get("/health").status_code == 200  # 公开路径仍可用


# --- 公开路径 -------------------------------------------------------------


def test_health_endpoints_are_public() -> None:
    with TestClient(_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/ready").status_code == 200


def test_openapi_docs_are_public() -> None:
    with TestClient(_app()) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_trailing_slash_on_public_path_is_public() -> None:
    with TestClient(_app()) as client:
        assert client.get("/health/").status_code == 200


def test_protected_routes_cover_sessions_and_memories() -> None:
    """最敏感的只读接口必须受保护 —— 否则任何人都能读别人的会话与记忆。"""
    with TestClient(_app()) as client:
        assert client.get("/api/v1/sessions").status_code == 401
        assert client.get("/api/v1/memories").status_code == 401
        assert client.get("/api/v1/tools").status_code == 401


def test_options_requests_bypass_auth() -> None:
    """CORS 预检不携带自定义请求头，不能被认证拦住。"""
    with TestClient(_app()) as client:
        response = client.options(
            "/api/v1/agents",
            headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET"},
        )

    assert response.status_code != 401


# --- 响应细节 -------------------------------------------------------------


def test_401_response_uses_unified_error_shape() -> None:
    with TestClient(_app()) as client:
        body = client.get("/api/v1/agents").json()

    assert set(body) == {"error"}
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["message"]
    assert body["error"]["details"]["header"] == HEADER


def test_401_response_still_carries_request_id() -> None:
    """认证中间件在请求上下文内层，401 也要有 request_id 方便排查。"""
    with TestClient(_app()) as client:
        response = client.get("/api/v1/agents")

    assert response.headers["x-request-id"].startswith("req_")


def test_custom_header_name_is_honoured() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            auth={
                "enabled": True,
                "api_keys": [SecretStr(API_KEY)],
                "header_name": "X-Custom-Token",
            },
        )
    )

    with TestClient(app) as client:
        assert client.get("/api/v1/agents").status_code == 401
        assert (
            client.get("/api/v1/agents", headers={"X-Custom-Token": API_KEY}).status_code
            == 200
        )
        # 默认头名不再生效
        assert client.get("/api/v1/agents", headers={HEADER: API_KEY}).status_code == 401


def test_api_key_is_not_leaked_in_response() -> None:
    with TestClient(_app()) as client:
        body = client.get("/api/v1/agents").text

    assert API_KEY not in body