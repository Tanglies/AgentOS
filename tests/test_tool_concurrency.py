"""Tool timeout and safe concurrency tests."""

from __future__ import annotations

import asyncio
import time

import pytest

from agentos.llm.base import ToolCall
from agentos.llm.echo import EchoLLMClient
from agentos.runtime.agent import Agent
from agentos.runtime.runtime import AgentRuntime
from agentos.runtime.tools import FunctionTool, Tool, ToolRegistry


class _SleepTool(Tool):
    name = "sleepy"
    description = "sleep"
    parameters = {"type": "object", "properties": {}}
    parallel_safe = True
    timeout_seconds = None

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay

    async def run(self) -> str:
        await asyncio.sleep(self.delay)
        return self.name


class _SequentialTool(Tool):
    name = "sequential"
    description = "side effect"
    parameters = {"type": "object", "properties": {}}
    parallel_safe = False
    timeout_seconds = None

    def __init__(self) -> None:
        self.active = False

    async def run(self) -> str:
        if self.active:
            raise RuntimeError("overlap")
        self.active = True
        await asyncio.sleep(0.03)
        self.active = False
        return "ok"


def _runtime(tools: list[Tool]) -> AgentRuntime:
    return AgentRuntime(
        EchoLLMClient(),
        tools=ToolRegistry(tools, default_timeout_seconds=None),
    )


@pytest.mark.asyncio
async def test_parallel_safe_tools_run_concurrently() -> None:
    runtime = _runtime([_SleepTool()])
    started = time.perf_counter()
    results = await runtime._run_tool_calls(
        [ToolCall(id="1", name="sleepy"), ToolCall(id="2", name="sleepy")],
        Agent(name="chat", tools=["sleepy"]),
    )
    duration = time.perf_counter() - started

    assert [result.content for result in results] == ["sleepy", "sleepy"]
    assert duration < 0.09
    await runtime.aclose()


@pytest.mark.asyncio
async def test_side_effect_tools_do_not_overlap() -> None:
    runtime = _runtime([_SequentialTool()])
    results = await runtime._run_tool_calls(
        [ToolCall(id="1", name="sequential"), ToolCall(id="2", name="sequential")],
        Agent(name="chat", tools=["sequential"]),
    )

    assert [result.is_error for result in results] == [False, False]
    await runtime.aclose()


@pytest.mark.asyncio
async def test_tool_timeout_is_returned_as_error_result() -> None:
    tool = FunctionTool("slow", lambda: "ok")
    tool.parallel_safe = True
    registry = ToolRegistry([tool], default_timeout_seconds=0.01)

    async def slow() -> str:
        await asyncio.sleep(0.1)
        return "late"

    tool._func = slow  # noqa: SLF001 - test-specific timeout behavior
    result = await registry.execute(ToolCall(id="1", name="slow"))

    assert result.is_error is True
    assert "timed out" in result.content
