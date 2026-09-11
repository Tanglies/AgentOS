"""HTTP API 集成测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "AgentOS"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "local"
    assert body["uptime_seconds"] >= 0


def test_request_id_is_generated_and_propagated(client: TestClient) -> None:
    generated = client.get("/health")
    assert generated.headers["x-request-id"].startswith("req_")

    propagated = client.get("/health", headers={"X-Request-ID": "req_fixed"})
    assert propagated.headers["x-request-id"] == "req_fixed"


def test_ready_endpoint_reports_dependencies(client: TestClient) -> None:
    body = client.get("/health/ready").json()

    assert body["status"] == "ready"
    assert body["llm_provider"] == "echo"
    assert body["agents"] >= 1


def test_openapi_schema_is_exposed(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "/api/v1/agents" in schema["paths"]
    assert "/api/v1/runs" in schema["paths"]
    assert "/api/v1/tools" in schema["paths"]


def test_list_agents_contains_default_agent(client: TestClient) -> None:
    body = client.get("/api/v1/agents").json()

    assert body["total"] >= 1
    assert any(item["name"] == "assistant" for item in body["items"])


def test_create_get_and_delete_agent(client: TestClient) -> None:
    payload = {
        "name": "researcher",
        "description": "检索型 Agent",
        "system_prompt": "You search.",
        "temperature": 0.2,
    }

    created = client.post("/api/v1/agents", json=payload)
    assert created.status_code == 201
    assert created.json()["name"] == "researcher"

    fetched = client.get("/api/v1/agents/researcher")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "检索型 Agent"

    assert client.delete("/api/v1/agents/researcher").status_code == 204
    assert client.get("/api/v1/agents/researcher").status_code == 404


def test_duplicate_agent_returns_conflict(client: TestClient) -> None:
    response = client.post("/api/v1/agents", json={"name": "assistant"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_run_agent_with_echo_provider(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"input": "做个自我介绍"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "assistant"
    assert body["output"] == "Echo: 做个自我介绍"
    assert body["iterations"] == 1
    assert body["finish_reason"] == "stop"
    assert body["run_id"].startswith("run_")
    assert body["usage"]["total_tokens"] > 0
    assert [message["role"] for message in body["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_run_registered_agent(client: TestClient) -> None:
    client.post(
        "/api/v1/agents",
        json={"name": "greeter", "system_prompt": "Greet the user."},
    )

    response = client.post("/api/v1/runs", json={"agent": "greeter", "input": "hi"})

    assert response.status_code == 200
    assert response.json()["agent"] == "greeter"


def test_run_unknown_agent_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"agent": "ghost", "input": "hi"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_run_with_empty_input_returns_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"input": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_create_agent_with_invalid_name_returns_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/agents", json={"name": "bad name!"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

def test_ready_endpoint_reports_tool_count(client: TestClient) -> None:
    body = client.get("/health/ready").json()

    assert body["tools"] >= 2


def test_list_tools_returns_builtin_tools(client: TestClient) -> None:
    body = client.get("/api/v1/tools").json()

    assert body["total"] >= 2
    names = {item["name"] for item in body["items"]}
    assert {"calculate", "get_current_time"} <= names


def test_tool_summary_exposes_json_schema(client: TestClient) -> None:
    body = client.get("/api/v1/tools").json()
    calculate = next(item for item in body["items"] if item["name"] == "calculate")

    assert calculate["parameters"]["type"] == "object"
    assert "expression" in calculate["parameters"]["properties"]
    assert calculate["description"]


def test_default_agent_exposes_builtin_tools(client: TestClient) -> None:
    body = client.get("/api/v1/agents").json()
    assistant = next(item for item in body["items"] if item["name"] == "assistant")

    assert {"calculate", "get_current_time"} <= set(assistant["tools"])


def test_create_agent_with_tools_round_trips(client: TestClient) -> None:
    created = client.post(
        "/api/v1/agents",
        json={"name": "calculator-agent", "tools": ["calculate"]},
    )

    assert created.status_code == 201
    assert created.json()["tools"] == ["calculate"]

    fetched = client.get("/api/v1/agents/calculator-agent")
    assert fetched.status_code == 200
    assert fetched.json()["tools"] == ["calculate"]


def test_run_response_includes_tool_call_count(client: TestClient) -> None:
    body = client.post("/api/v1/runs", json={"input": "hi"}).json()

    assert body["tool_call_count"] == 0
