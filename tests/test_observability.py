"""可观测性测试：上下文传递、trace 头、工具名绑定。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.context import (
    bind,
    current_context,
    get_actor,
    get_agent_name,
    get_run_id,
    get_tool_name,
    get_trace_id,
)
from agentos.llm.base import ToolCall
from agentos.runtime import Tool, ToolRegistry

# --- 上下文基础 -----------------------------------------------------------


def test_context_starts_empty() -> None:
    assert current_context() == {}


def test_bind_sets_and_restores_fields() -> None:
    with bind(trace_id="trace_1", run_id="run_1"):
        assert get_trace_id() == "trace_1"
        assert get_run_id() == "run_1"

    assert get_trace_id() is None
    assert get_run_id() is None


def test_bind_supports_nesting() -> None:
    with bind(trace_id="trace_outer"):
        with bind(run_id="run_inner"):
            assert get_trace_id() == "trace_outer"
            assert get_run_id() == "run_inner"
        # 内层退出后外层仍在
        assert get_trace_id() == "trace_outer"
        assert get_run_id() is None


def test_bind_rejects_unknown_field() -> None:
    """拼错字段名直接报错，而不是被静默忽略。"""
    with pytest.raises(ValueError, match="unknown context field"), bind(traec_id="typo"):
        pass


def test_all_observability_fields_are_exposed() -> None:
    with bind(
        trace_id="t",
        run_id="r",
        agent_name="a",
        tool_name="tool",
        actor="key_abc",
    ):
        assert get_trace_id() == "t"
        assert get_run_id() == "r"
        assert get_agent_name() == "a"
        assert get_tool_name() == "tool"
        assert get_actor() == "key_abc"


# --- trace 响应头 ---------------------------------------------------------


def test_response_carries_generated_trace_id(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["x-trace-id"].startswith("trace_")


def test_response_echoes_incoming_trace_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Trace-ID": "trace_fixed_123"})

    assert response.headers["x-trace-id"] == "trace_fixed_123"


def test_request_and_trace_ids_are_distinct(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["x-request-id"] != response.headers["x-trace-id"]


def test_paths_share_one_trace_id_per_request(client: TestClient) -> None:
    response = client.post("/api/v1/runs", json={"input": "hi"})

    assert response.headers["x-trace-id"].startswith("trace_")


# --- 认证注入 actor -------------------------------------------------------


def test_actor_is_set_when_api_key_matches() -> None:
    """认证通过后 actor 会被绑定，供日志与审计使用。"""
    app = create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            auth={"enabled": True, "api_keys": [SecretStr("sk-secret")]},
            registry={"persist": False},
            runs={"enabled": False},
            audit={"enabled": False},
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/agents", headers={"X-API-Key": "sk-secret"})

    assert response.status_code == 200


def test_actor_is_absent_without_auth(client: TestClient) -> None:
    """认证关闭时没有身份，actor 保持为空。"""
    assert get_actor() is None


# --- 工具执行期间绑定 tool_name -------------------------------------------


class ProbeTool(Tool):
    """在 run() 里记录当前上下文的测试工具。"""

    name = "probe"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    async def run(self, **kwargs: Any) -> str:
        self.seen = {
            "tool_name": get_tool_name(),
            "run_id": get_run_id(),
            "trace_id": get_trace_id(),
        }
        return "ok"


async def test_tool_execution_binds_tool_name() -> None:
    tool = ProbeTool()
    registry = ToolRegistry([tool])

    with bind(trace_id="trace_x", run_id="run_x"):
        await registry.execute(ToolCall(id="c1", name="probe", arguments="{}"))

    assert tool.seen["tool_name"] == "probe"
    # 外层上下文在工具执行期间仍然可见
    assert tool.seen["trace_id"] == "trace_x"
    assert tool.seen["run_id"] == "run_x"


async def test_tool_name_is_restored_after_execution() -> None:
    registry = ToolRegistry([ProbeTool()])

    await registry.execute(ToolCall(id="c1", name="probe", arguments="{}"))

    assert get_tool_name() is None


async def test_tool_name_is_cleared_after_missing_tool() -> None:
    """工具不存在时执行同样会绑定并还原 tool_name，不会污染后续调用。"""
    registry = ToolRegistry([])

    result = await registry.execute(ToolCall(id="c1", name="ghost", arguments="{}"))

    assert result.is_error is True
    assert get_tool_name() is None