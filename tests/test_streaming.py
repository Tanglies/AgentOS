"""流式回复测试：SSE 解析、事件流与 SSE 端点。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agentos.core.config import RuntimeSettings
from agentos.core.exceptions import AgentRuntimeError, NotFoundError
from agentos.llm import EchoLLMClient, OpenAICompatibleLLMClient
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from agentos.runtime import Agent, AgentRuntime
from agentos.runtime.runtime import RunEvent


def _sse_body(events: list[dict[str, Any]]) -> bytes:
    lines = [f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


def _stream_client(handler: Any) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        base_url="https://llm.test/v1",
        model="test-model",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://llm.test/v1"
        ),
        retry_backoff_seconds=0,
    )


class ScriptedStreamClient(LLMClient):
    """按脚本产出片段，用于验证 Runtime 的事件流。"""

    provider = "scripted-stream"

    def __init__(self, *, with_tool: bool = False) -> None:
        self.with_tool = with_tool
        self.rounds = 0

    async def complete(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> LLMResponse:  # pragma: no cover - 仅满足抽象方法
        raise NotImplementedError

    async def stream(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> AsyncIterator[StreamChunk]:
        self.rounds += 1
        if self.with_tool and self.rounds == 1:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(id="call_1", name="calculate", arguments='{"expression": "2+2"}')
                ],
                finish_reason="tool_calls",
            )
            return

        for piece in ["你好", "，世界"]:
            yield StreamChunk(delta=piece)
        yield StreamChunk(
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6),
        )


# --- 默认流式实现 ---------------------------------------------------------


async def test_default_stream_falls_back_to_complete() -> None:
    chunks = [chunk async for chunk in EchoLLMClient().stream([LLMMessage.user("你好")])]

    assert chunks[0].delta == "Echo: 你好"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens > 0


# --- OpenAI 兼容 SSE 解析 -------------------------------------------------


async def test_openai_stream_yields_text_deltas() -> None:
    body = _sse_body(
        [
            {"choices": [{"delta": {"content": "你"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "好"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        assert json.loads(request.content)["stream_options"]["include_usage"] is True
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    client = _stream_client(handler)
    chunks = [chunk async for chunk in client.stream([LLMMessage.user("hi")])]
    await client.aclose()

    assert [chunk.delta for chunk in chunks if chunk.delta] == ["你", "好"]
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


async def test_openai_stream_assembles_tool_call_fragments() -> None:
    body = _sse_body(
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "calculate", "arguments": '{"expr'},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": 'ession": "2+2"}'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    client = _stream_client(handler)
    chunks = [chunk async for chunk in client.stream([LLMMessage.user("hi")])]
    await client.aclose()

    calls = chunks[-1].tool_calls
    assert calls is not None
    assert calls[0].id == "call_1"
    assert calls[0].name == "calculate"
    assert json.loads(calls[0].arguments) == {"expression": "2+2"}


async def test_openai_stream_raises_on_error_status() -> None:
    from agentos.core.exceptions import LLMProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error": "bad key"}')

    client = _stream_client(handler)
    with pytest.raises(LLMProviderError):
        async for _ in client.stream([LLMMessage.user("hi")]):
            pass
    await client.aclose()


async def test_openai_stream_skips_malformed_lines() -> None:
    body = (
        b"data: not-json\n\n"
        b": comment line\n\n"
        b'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    client = _stream_client(handler)
    chunks = [chunk async for chunk in client.stream([LLMMessage.user("hi")])]
    await client.aclose()

    assert [chunk.delta for chunk in chunks if chunk.delta] == ["ok"]


# --- Runtime 事件流 -------------------------------------------------------


async def test_run_stream_emits_expected_event_order() -> None:
    runtime = AgentRuntime(ScriptedStreamClient())
    events = [
        event
        async for event in runtime.run_stream(
            Agent(name="chat", system_prompt="be nice"), "打招呼"
        )
    ]

    assert [event.type for event in events] == ["start", "delta", "delta", "end"]
    assert [event.delta for event in events if event.type == "delta"] == ["你好", "，世界"]

    start = events[0]
    assert start.run_id is not None and start.run_id.startswith("run_")
    assert start.agent == "chat"

    end = events[-1]
    assert end.result is not None
    assert end.result.output == "你好，世界"
    assert end.result.session_id == "default"


async def test_run_stream_emits_tool_events() -> None:
    runtime = AgentRuntime(ScriptedStreamClient(with_tool=True))
    events = [
        event
        async for event in runtime.run_stream(
            Agent(name="calc", tools=["calculate"]), "2+2 等于几"
        )
    ]

    types = [event.type for event in events]
    assert types == ["start", "tool_call", "tool_result", "delta", "delta", "end"]

    call_event = next(event for event in events if event.type == "tool_call")
    assert call_event.tool_call is not None
    assert call_event.tool_call.name == "calculate"

    result_event = next(event for event in events if event.type == "tool_result")
    assert result_event.tool_result is not None
    assert "2+2 = 4" in result_event.tool_result.content

    end = events[-1]
    assert end.result is not None
    assert end.result.tool_call_count == 1


async def test_run_stream_raises_before_any_event_for_blank_input() -> None:
    """参数校验在产出任何事件之前完成，不留半截事件流。"""
    from agentos.core.exceptions import ValidationError

    runtime = AgentRuntime(EchoLLMClient())
    events: list[RunEvent] = []

    with pytest.raises(ValidationError):
        async for event in runtime.run_stream(Agent(name="chat"), "   "):
            events.append(event)

    assert events == []


async def test_run_stream_reports_unknown_agent_as_error_event() -> None:
    runtime = AgentRuntime(EchoLLMClient())
    events: list[RunEvent] = []

    with pytest.raises(NotFoundError):
        async for event in runtime.run_stream("ghost", "hi"):
            events.append(event)

    assert events == []


async def test_run_stream_reports_tool_loop_error() -> None:
    class LoopingStreamClient(ScriptedStreamClient):
        async def stream(
            self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
        ) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(id="c", name="calculate", arguments='{"expression": "1+1"}')
                ],
                finish_reason="tool_calls",
            )

    runtime = AgentRuntime(
        LoopingStreamClient(), settings=RuntimeSettings(max_iterations=2)
    )
    events = []

    with pytest.raises(AgentRuntimeError):
        async for event in runtime.run_stream(Agent(name="loop", tools=["calculate"]), "loop"):
            events.append(event)

    assert events[-1].type == "error"
    assert "max_iterations" in (events[-1].error or "")


async def test_run_still_returns_result_after_refactor() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    result = await runtime.run(Agent(name="chat", system_prompt="be nice"), "你好")

    assert result.output == "Echo: 你好"
    assert result.iterations == 1


# --- SSE 端点 -------------------------------------------------------------


def test_stream_endpoint_emits_sse_events(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/v1/runs/stream", json={"input": "你好"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: start" in body
    assert "event: delta" in body
    assert "event: end" in body
    assert "Echo: 你好" in body


def test_stream_endpoint_reports_unknown_agent(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/v1/runs/stream", json={"agent": "ghost", "input": "hi"}
    ) as response:
        body = "".join(response.iter_text())

    assert "event: error" in body
    assert "not_found" in body


def test_stream_endpoint_rejects_invalid_body(client: TestClient) -> None:
    response = client.post("/api/v1/runs/stream", json={"input": ""})

    assert response.status_code == 422


def test_stream_endpoint_shares_session_memory(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/v1/runs/stream", json={"input": "第一句", "session_id": "sse-1"}
    ) as response:
        "".join(response.iter_text())

    with client.stream(
        "POST", "/api/v1/runs/stream", json={"input": "第二句", "session_id": "sse-1"}
    ) as response:
        body = "".join(response.iter_text())

    assert "第一句" in body


def test_openapi_exposes_stream_route(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/runs/stream" in schema["paths"]