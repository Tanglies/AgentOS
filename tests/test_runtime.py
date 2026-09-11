"""Agent 注册表与 Runtime 测试。"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError as PydanticValidationError

from agentos.core.config import RuntimeSettings
from agentos.core.exceptions import (
    AgentRuntimeError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from agentos.llm import EchoLLMClient
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    TokenUsage,
    ToolCall,
)
from agentos.runtime import (
    Agent,
    AgentRegistry,
    AgentRuntime,
    Message,
    create_default_registry,
)


class LoopingLLMClient(LLMClient):
    """始终要求继续下一轮的测试替身，用于验证 max_iterations 兜底。"""

    provider = "looping"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="still thinking", model="looping", finish_reason="tool_calls")


class AlwaysContinueRuntime(AgentRuntime):
    """把「是否继续」固定为 True，模拟尚未接入工具调用的多轮循环。"""

    def _should_continue(self, response: LLMResponse, messages: Sequence[Message]) -> bool:
        return True


class CloseAwareEchoClient(EchoLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_runtime_runs_default_agent_and_reports_usage() -> None:
    runtime = AgentRuntime(EchoLLMClient(), settings=RuntimeSettings(default_agent="assistant"))

    result = await runtime.run("assistant", "你好")

    assert result.agent == "assistant"
    assert result.output == "Echo: 你好"
    assert result.run_id.startswith("run_")
    assert result.iterations == 1
    assert result.duration_ms >= 0
    assert [message.role.value for message in result.messages] == [
        "system",
        "user",
        "assistant",
    ]
    assert result.usage is not None
    assert result.usage.total_tokens > 0

    await runtime.aclose()


async def test_runtime_accepts_agent_instance_with_history() -> None:
    runtime = AgentRuntime(EchoLLMClient())
    agent = Agent(name="custom", system_prompt="custom prompt")
    history = [Message.user("上一轮"), Message.assistant("上一轮回复")]

    result = await runtime.run(agent, "继续", history=history)

    assert result.agent == "custom"
    assert [message.content for message in result.messages[:3]] == [
        "custom prompt",
        "上一轮",
        "上一轮回复",
    ]
    assert result.messages[-1].content == "Echo: 继续"


async def test_runtime_rejects_unknown_agent() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    with pytest.raises(NotFoundError):
        await runtime.run("missing", "hi")


async def test_runtime_rejects_blank_input() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    with pytest.raises(ValidationError):
        await runtime.run("assistant", "   ")


async def test_runtime_enforces_max_iterations() -> None:
    client = LoopingLLMClient()
    runtime = AlwaysContinueRuntime(client, settings=RuntimeSettings(max_iterations=3))

    with pytest.raises(AgentRuntimeError) as excinfo:
        await runtime.run("assistant", "loop")

    assert excinfo.value.details["max_iterations"] == 3
    assert client.calls == 3


async def test_runtime_aclose_closes_llm_client() -> None:
    client = CloseAwareEchoClient()
    runtime = AgentRuntime(client)

    await runtime.aclose()

    assert client.closed is True


def test_registry_registers_and_lists_agents() -> None:
    registry = AgentRegistry()
    registry.register(Agent(name="b"))
    registry.register(Agent(name="a"))

    assert [agent.name for agent in registry.list()] == ["a", "b"]
    assert "a" in registry
    assert len(registry) == 2

    registry.unregister("a")
    assert "a" not in registry


def test_registry_rejects_duplicate_name() -> None:
    registry = AgentRegistry([Agent(name="dup")])

    with pytest.raises(ConflictError):
        registry.register(Agent(name="dup"))

    registry.register(Agent(name="dup"), overwrite=True)
    assert registry.get("dup").name == "dup"


def test_registry_get_unknown_agent_raises() -> None:
    with pytest.raises(NotFoundError):
        AgentRegistry().get("nope")


def test_create_default_registry_uses_settings() -> None:
    registry = create_default_registry(
        RuntimeSettings(default_agent="main", system_prompt="be helpful")
    )

    assert registry.get("main").system_prompt == "be helpful"
    assert len(registry) == 1


def test_agent_name_must_follow_pattern() -> None:
    with pytest.raises(PydanticValidationError):
        Agent(name="bad name!")


def test_agent_messages_convert_to_llm_messages() -> None:
    message = Message.tool("result", tool_call_id="call_1", name="search")

    converted = message.to_llm_message()

    assert converted.role == "tool"
    assert converted.tool_call_id == "call_1"
    assert converted.name == "search"

class ToolCallingLLMClient(LLMClient):
    """首轮请求工具调用，次轮基于工具结果给出最终回答。"""

    provider = "tool-calling"

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []
        self.options: list[CompletionOptions | None] = []

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.options.append(options)
        if len(self.calls) == 1:
            return LLMResponse(
                content="",
                model="tool-calling",
                finish_reason="tool_calls",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                tool_calls=[
                    ToolCall(id="call_1", name="calculate", arguments='{"expression": "6*7"}')
                ],
            )
        return LLMResponse(
            content="结果是 42",
            model="tool-calling",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
        )


class AlwaysToolCallLLMClient(LLMClient):
    """每轮都请求调用工具，用于验证工具循环的迭代上限。"""

    provider = "always-tool"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="",
            model="always-tool",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCall(
                    id=f"call_{self.calls}",
                    name="calculate",
                    arguments='{"expression": "1+1"}',
                )
            ],
        )


class RecordingEchoClient(EchoLLMClient):
    """记录每次调用选项的 echo 客户端。"""

    def __init__(self) -> None:
        super().__init__()
        self.options: list[CompletionOptions | None] = []

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        self.options.append(options)
        return await super().complete(messages, options=options)


async def test_runtime_executes_tool_call_and_feeds_result_back() -> None:
    client = ToolCallingLLMClient()
    runtime = AgentRuntime(client)
    agent = Agent(name="calc", tools=["calculate"])

    result = await runtime.run(agent, "6*7 等于多少")

    assert result.output == "结果是 42"
    assert result.iterations == 2
    assert result.tool_call_count == 1
    assert result.usage is not None
    # token 用量跨轮累加
    assert result.usage.total_tokens == 43
    assert [message.role.value for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]

    tool_message = result.messages[2]
    assert tool_message.tool_call_id == "call_1"
    assert tool_message.name == "calculate"
    assert tool_message.content == "6*7 = 42"

    # 工具声明被透传给 LLM
    assert client.options[0] is not None
    assert [spec.name for spec in client.options[0].tools or []] == ["calculate"]
    # 第二轮请求里带上了 tool 结果
    assert any(message.role == "tool" for message in client.calls[1])


async def test_runtime_agent_without_tools_sends_no_tool_specs() -> None:
    client = RecordingEchoClient()
    runtime = AgentRuntime(client)

    await runtime.run(Agent(name="plain"), "hi")

    assert client.options[0] is not None
    assert client.options[0].tools is None


async def test_runtime_rejects_unknown_tool_name() -> None:
    runtime = AgentRuntime(EchoLLMClient())

    with pytest.raises(NotFoundError) as excinfo:
        await runtime.run(Agent(name="broken", tools=["not-registered"]), "hi")

    assert excinfo.value.details["tool"] == "not-registered"


async def test_runtime_tool_loop_is_bounded_by_max_iterations() -> None:
    client = AlwaysToolCallLLMClient()
    runtime = AgentRuntime(client, settings=RuntimeSettings(max_iterations=3))

    with pytest.raises(AgentRuntimeError) as excinfo:
        await runtime.run(Agent(name="loopy", tools=["calculate"]), "loop")

    assert client.calls == 3
    assert excinfo.value.details["tool_call_count"] == 3
