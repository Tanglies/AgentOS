"""Multi-Agent 测试：委托工具、深度限制、隔离与注册表集成。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi.testclient import TestClient

from agentos.core.context import get_agent_name
from agentos.core.exceptions import NotFoundError
from agentos.llm import EchoLLMClient
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    ToolCall,
)
from agentos.runtime import Agent, AgentRegistry, AgentRuntime, ToolRegistry
from agentos.runtime.agent_tools import (
    DEFAULT_MAX_DEPTH,
    DelegateToAgentTool,
    create_agent_tools,
    current_delegation_depth,
)


class RoutingClient(LLMClient):
    """按当前 Agent 名分流：primary 先委托，专家直接给结论。"""

    provider = "routing"

    def __init__(self, *, always_delegate: bool = False) -> None:
        self.always_delegate = always_delegate
        self.trace: list[str] = []
        self.calls: dict[str, int] = {}

    async def complete(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> LLMResponse:  # pragma: no cover - 仅满足抽象方法
        raise NotImplementedError

    async def stream(
        self, messages: Sequence[LLMMessage], *, options: CompletionOptions | None = None
    ) -> AsyncIterator[StreamChunk]:
        agent = get_agent_name() or "?"
        self.calls[agent] = self.calls.get(agent, 0) + 1
        first_call = self.calls[agent] == 1
        self.trace.append(f"{agent}@{current_delegation_depth()}")

        if agent != "primary":
            if self.always_delegate and first_call:
                yield StreamChunk(
                    tool_calls=[
                        ToolCall(
                            id="loop",
                            name="delegate_to_agent",
                            arguments='{"agent": "primary", "task": "回传"}',
                        )
                    ],
                    finish_reason="tool_calls",
                )
                return
            yield StreamChunk(delta=f"{agent} 的结论")
            yield StreamChunk(finish_reason="stop")
            return

        if first_call:
            yield StreamChunk(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="delegate_to_agent",
                        arguments='{"agent": "researcher", "task": "调研核心能力"}',
                    )
                ],
                finish_reason="tool_calls",
            )
            return

        yield StreamChunk(delta="已综合专家结论。")
        yield StreamChunk(finish_reason="stop")


def _registry_with_expert() -> AgentRegistry:
    return AgentRegistry(
        [
            Agent(name="primary", system_prompt="主协调者"),
            Agent(name="researcher", system_prompt="研究员"),
        ]
    )


# --- 工具本身 -------------------------------------------------------------


def test_spec_lists_available_agents() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    tool = DelegateToAgentTool(runtime)

    description = tool.spec().description

    assert "primary" in description
    assert "researcher" in description


def test_create_agent_tools_returns_delegate_tool() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())

    tools = create_agent_tools(runtime)

    assert [tool.name for tool in tools] == ["delegate_to_agent"]


def test_default_tool_registry_contains_delegate_tool() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    assert "delegate_to_agent" in {tool.name for tool in runtime.tools.list()}


def test_default_agent_gets_delegate_tool() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    assert "delegate_to_agent" in runtime.registry.get("assistant").tools


def test_delegation_can_be_disabled() -> None:
    runtime = AgentRuntime(EchoLLMClient(), enable_delegation=False)

    assert "delegate_to_agent" not in {tool.name for tool in runtime.tools.list()}


async def test_delegate_rejects_unknown_agent() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    tool = DelegateToAgentTool(runtime)

    result = await tool.run(agent="ghost", task="做点什么")

    assert "不存在" in result
    assert "researcher" in result


async def test_delegate_rejects_blank_task() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    tool = DelegateToAgentTool(runtime)

    assert "不能为空" in await tool.run(agent="researcher", task="   ")


async def test_delegate_refuses_self_delegation() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    tool = DelegateToAgentTool(runtime)

    # 模拟当前正在 primary 内运行
    async for _ in runtime.run_stream("primary", "占位"):
        break

    result = await tool.run(agent="primary", task="自己做")
    assert "不能把任务委托给当前 Agent 自己" in result


# --- 端到端委托 -----------------------------------------------------------


async def test_delegation_runs_sub_agent_and_returns_output() -> None:
    client = RoutingClient()
    runtime = AgentRuntime(client, registry=_registry_with_expert())

    result = await runtime.run("primary", "调研一下")

    assert client.trace == ["primary@0", "researcher@1", "primary@0"]
    assert result.tool_call_count == 1
    assert result.output == "已综合专家结论。"

    tool_messages = [m.content for m in result.messages if m.role.value == "tool"]
    assert any("researcher 的结论" in content for content in tool_messages)


async def test_sub_agent_does_not_touch_session_memory() -> None:
    """子 Agent 以无状态方式运行，父级记忆不应被子任务污染。"""
    client = RoutingClient()
    runtime = AgentRuntime(client, registry=_registry_with_expert())

    await runtime.run("primary", "调研一下", stateless=True)

    assert len(runtime.memory) == 0


async def test_delegation_depth_is_bounded() -> None:
    client = RoutingClient(always_delegate=True)
    runtime = AgentRuntime(
        client,
        registry=_registry_with_expert(),
        max_delegation_depth=1,
    )

    result = await runtime.run("primary", "无限委托", stateless=True)

    # primary@0 → researcher@1 → 试图再委托被拒绝 → 各自收尾。
    # 关键断言：轨迹里**没有出现 depth=2**，说明委托链确实被截断。
    depths = [int(entry.split("@")[1]) for entry in client.trace]
    assert max(depths) <= 1
    assert any(entry.startswith("researcher") for entry in client.trace)
    assert result.finish_reason == "stop"


async def test_delegate_reports_depth_limit_message(monkeypatch) -> None:
    """直接在最大深度上调用，应返回明确的拒绝提示。"""
    from agentos.runtime import agent_tools

    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    tool = DelegateToAgentTool(runtime, max_depth=1)

    token = agent_tools._delegation_depth.set(1)
    try:
        result = await tool.run(agent="researcher", task="再来一层")
    finally:
        agent_tools._delegation_depth.reset(token)

    assert "最大委托深度" in result


async def test_delegation_depth_default_value() -> None:
    assert DEFAULT_MAX_DEPTH == 3
    assert current_delegation_depth() == 0


# --- 注册表与 API ---------------------------------------------------------


async def test_delegate_tool_uses_runtime_registry() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())
    registry = ToolRegistry([DelegateToAgentTool(runtime)])

    from agentos.llm.base import ToolCall as Call

    result = await registry.execute(
        Call(
            id="c1",
            name="delegate_to_agent",
            arguments='{"agent": "researcher", "task": "你好"}',
        )
    )

    assert result.is_error is False
    assert "researcher 的回复" in result.content


def test_api_exposes_delegate_tool(client: TestClient) -> None:
    names = {item["name"] for item in client.get("/api/v1/tools").json()["items"]}

    assert "delegate_to_agent" in names


def test_api_delegation_tool_lists_default_agent(client: TestClient) -> None:
    items = client.get("/api/v1/tools").json()["items"]
    delegate = next(item for item in items if item["name"] == "delegate_to_agent")

    assert "assistant" in delegate["description"]


def test_runtime_accepts_explicit_registry_without_delegation() -> None:
    registry = _registry_with_expert()
    runtime = AgentRuntime(
        EchoLLMClient(), registry=registry, enable_delegation=False
    )

    assert runtime.registry is registry
    assert "delegate_to_agent" not in {tool.name for tool in runtime.tools.list()}


async def test_run_with_unknown_agent_still_raises() -> None:
    runtime = AgentRuntime(EchoLLMClient(), registry=_registry_with_expert())

    with pytest.raises(NotFoundError):
        await runtime.run("ghost", "hi")