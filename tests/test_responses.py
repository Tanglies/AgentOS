"""JSON 响应头测试。

Starlette 默认不给 ``application/json`` 补 charset，而 Windows PowerShell 5.1
的 ``Invoke-WebRequest`` 在缺少 charset 时按 ISO-8859-1 解码，中文会变乱码。
这里锁住「所有 JSON 响应都显式声明 charset=utf-8」这个约定。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings


def _app() -> object:
    return create_app(
        Settings(_env_file=None, llm={"provider": "echo"}, logging={"level": "ERROR"})
    )


def test_tools_endpoint_declares_utf8_charset(client: TestClient) -> None:
    response = client.get("/api/v1/tools")

    assert response.headers["content-type"] == "application/json; charset=utf-8"


def test_all_json_endpoints_declare_charset(client: TestClient) -> None:
    for path in ("/health", "/health/ready", "/api/v1/agents", "/api/v1/tools"):
        response = client.get(path)
        assert "charset=utf-8" in response.headers["content-type"], path


def test_agent_listing_declares_charset(client: TestClient) -> None:
    response = client.get("/api/v1/agents")

    assert response.headers["content-type"] == "application/json; charset=utf-8"


def test_error_response_declares_charset(client: TestClient) -> None:
    response = client.get("/api/v1/agents/ghost")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json; charset=utf-8"


def test_validation_error_declares_charset(client: TestClient) -> None:
    response = client.post("/api/v1/agents", json={"name": "bad name!"})

    assert response.status_code == 422
    assert "charset=utf-8" in response.headers["content-type"]


def test_stream_endpoint_keeps_event_stream_type(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/v1/runs/stream", json={"input": "hi"}
    ) as response:
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


def test_unauthorized_response_declares_charset(tmp_path) -> None:
    """认证中间件自己构造响应，同样要带 charset。"""
    app = create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            auth={"enabled": True, "api_keys": [SecretStr("sk-x")]},
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/json; charset=utf-8"


def test_chinese_payload_is_intact(client: TestClient) -> None:
    """原始字节应是合法 UTF-8 —— 这才是乱码问题的根源。"""
    response = client.get("/api/v1/tools")

    decoded = response.content.decode("utf-8")
    assert "计算一个基础算术表达式" in decoded


def test_openapi_schema_declares_charset(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert "charset=utf-8" in response.headers["content-type"]


def test_media_type_not_polluted_in_openapi(client: TestClient) -> None:
    """charset 应加在响应头，而不是写进 OpenAPI 声明的 media type。"""
    schema = client.get("/openapi.json").json()
    content = schema["paths"]["/api/v1/agents"]["get"]["responses"]["200"]["content"]

    assert list(content) == ["application/json"]