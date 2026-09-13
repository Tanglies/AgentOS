"""OpenTelemetry tracing integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentos.core.config import ObservabilitySettings
from agentos.core.context import bind, get_otel_span_id, get_otel_trace_id
from agentos.database.connection import Database
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    ToolCall,
)
from agentos.observability.tracing import (
    configure_tracing,
    force_flush,
    reset_tracing,
    start_span,
)
from agentos.runtime.agent import Agent
from agentos.runtime.builtin_tools import CalculateTool
from agentos.runtime.runtime import AgentRuntime
from agentos.runtime.tools import ToolRegistry


class _ToolClient(LLMClient):
    provider = "tool-trace"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(
                tool_calls=[ToolCall(id="c1", name="calculate", arguments='{"expression":"1+1"}')],
                finish_reason="tool_calls",
            )
            return
        yield StreamChunk(delta="2", finish_reason="stop")


def test_tracing_is_disabled_by_default() -> None:
    reset_tracing()
    with start_span("noop") as span:
        assert span is None
        assert get_otel_trace_id() is None


@pytest.mark.asyncio
async def test_span_ids_are_bound_to_log_context() -> None:
    exporter = InMemorySpanExporter()
    configure_tracing(ObservabilitySettings(enabled=True), span_exporter=exporter)
    try:
        with start_span("test.span"):
            assert get_otel_trace_id()
            assert get_otel_span_id()
        assert get_otel_trace_id() is None
        assert get_otel_span_id() is None
    finally:
        reset_tracing()


@pytest.mark.asyncio
async def test_runtime_emits_agent_llm_tool_and_repository_spans(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    configure_tracing(ObservabilitySettings(enabled=True), span_exporter=exporter)
    try:
        runtime = AgentRuntime(
            _ToolClient(),
            tools=ToolRegistry([CalculateTool()]),
        )
        with bind(workspace_id=1, user_id=1):
            await runtime.run(Agent(name="assistant", tools=["calculate"]), "calculate")
            Database(tmp_path / "trace.db").query("SELECT 1")
        force_flush()
        spans = exporter.get_finished_spans()
        names = {span.name for span in spans}
        assert {"agent.run", "llm.call", "tool.call", "repository.query"} <= names
        agent_span = next(span for span in spans if span.name == "agent.run")
        llm_span = next(span for span in spans if span.name == "llm.call")
        tool_span = next(span for span in spans if span.name == "tool.call")
        assert llm_span.parent is not None
        assert tool_span.parent is not None
        assert llm_span.parent.span_id == agent_span.context.span_id
        assert tool_span.parent.span_id == agent_span.context.span_id
        assert agent_span.attributes["workspace.id"] == 1
        assert tool_span.attributes["tool.name"] == "calculate"
        assert "prompt" not in tool_span.attributes
        await runtime.aclose()
    finally:
        reset_tracing()
