"""Agent Runtime：把 Agent 定义、LLM 客户端与会话历史串成一次可观测的运行。

当前版本负责：

- 组装消息（系统提示词 → 历史 → 用户输入）
- 驱动「模型调用 → 追加回复 → 执行工具 → 回填结果」的迭代循环，并用 ``max_iterations`` 兜底
- 记录 run_id / 耗时 / token 用量 / 工具调用次数，供日志与 API 返回

Tool Calling 已通过 :meth:`AgentRuntime._should_continue` 与
:meth:`AgentRuntime._run_tool_calls` 接入；Planning 与 Memory 将在后续版本沿用同一扩展点。
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from pydantic import BaseModel

from agentos.core.config import RuntimeSettings
from agentos.core.context import (
    new_id,
    reset_agent_name,
    reset_run_id,
    set_agent_name,
    set_run_id,
)
from agentos.core.exceptions import AgentRuntimeError, ValidationError
from agentos.core.logging import get_logger
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMResponse,
    TokenUsage,
    ToolCall,
)
from agentos.runtime.agent import Agent
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.message import Message
from agentos.runtime.registry import AgentRegistry, create_default_registry
from agentos.runtime.tools import ToolCallResult, ToolRegistry

logger = get_logger(__name__)


class RunResult(BaseModel):
    """一次 Agent 运行的完整结果。"""

    run_id: str
    agent: str
    output: str
    messages: list[Message]
    usage: TokenUsage | None = None
    iterations: int = 1
    duration_ms: float = 0.0
    finish_reason: str | None = None
    tool_call_count: int = 0


class AgentRuntime:
    """Agent 执行内核。"""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        settings: RuntimeSettings | None = None,
        registry: AgentRegistry | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self._llm = llm_client
        self._settings = settings or RuntimeSettings()
        self._registry = (
            registry if registry is not None else create_default_registry(self._settings)
        )
        self._tools = tools if tools is not None else create_default_tool_registry()

    @property
    def llm_client(self) -> LLMClient:
        return self._llm

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def settings(self) -> RuntimeSettings:
        return self._settings

    async def run(
        self,
        agent: Agent | str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
    ) -> RunResult:
        """执行一次 Agent 运行并返回结构化结果。

        当模型发起工具调用时，会执行工具并把结果作为 ``tool`` 消息回填，
        然后再次调用模型，直到模型给出最终回答或触及 ``max_iterations``。
        """
        resolved = self._resolve_agent(agent)
        if not input_text.strip():
            raise ValidationError("input must not be empty", details={"agent": resolved.name})

        run_id = new_id("run_")
        run_token = set_run_id(run_id)
        agent_token = set_agent_name(resolved.name)
        started_at = time.perf_counter()
        max_iterations = resolved.max_iterations or self._settings.max_iterations
        messages = resolved.build_messages(input_text, history=history)
        options = self._build_options(resolved)
        usage: TokenUsage | None = None
        response: LLMResponse | None = None
        iteration = 0
        tool_call_count = 0

        logger.info(
            "agent run started",
            extra={
                "extra_fields": {
                    "agent": resolved.name,
                    "max_iterations": max_iterations,
                    "tools": [spec.name for spec in options.tools or []],
                }
            },
        )

        try:
            for iteration in range(1, max_iterations + 1):
                response = await self._llm.complete(
                    [message.to_llm_message() for message in messages],
                    options=options,
                )
                messages.append(
                    Message.assistant(response.content, tool_calls=response.tool_calls)
                )
                if response.usage is not None:
                    usage = response.usage if usage is None else usage + response.usage

                logger.debug(
                    "agent run iteration completed",
                    extra={
                        "extra_fields": {
                            "iteration": iteration,
                            "finish_reason": response.finish_reason,
                            "tool_calls": len(response.tool_calls or []),
                        }
                    },
                )

                if not self._should_continue(response, messages):
                    break

                results = await self._run_tool_calls(response.tool_calls or [])
                tool_call_count += len(results)
                messages.extend(
                    Message.tool(
                        result.content, tool_call_id=result.tool_call_id, name=result.name
                    )
                    for result in results
                )
            else:
                raise AgentRuntimeError(
                    f"agent '{resolved.name}' exceeded max_iterations={max_iterations}",
                    details={
                        "agent": resolved.name,
                        "max_iterations": max_iterations,
                        "tool_call_count": tool_call_count,
                    },
                )

            # 循环至少执行一次，此处仅用于类型收窄
            if response is None:  # pragma: no cover
                raise AgentRuntimeError(
                    f"agent '{resolved.name}' produced no response",
                    details={"agent": resolved.name},
                )

            duration_ms = (time.perf_counter() - started_at) * 1000
            result = RunResult(
                run_id=run_id,
                agent=resolved.name,
                output=response.content,
                messages=messages,
                usage=usage,
                iterations=iteration,
                duration_ms=round(duration_ms, 3),
                finish_reason=response.finish_reason,
                tool_call_count=tool_call_count,
            )
            logger.info(
                "agent run completed",
                extra={
                    "extra_fields": {
                        "agent": resolved.name,
                        "iterations": result.iterations,
                        "duration_ms": result.duration_ms,
                        "total_tokens": usage.total_tokens if usage else 0,
                        "tool_call_count": tool_call_count,
                    }
                },
            )
            return result
        except Exception:
            logger.exception("agent run failed", extra={"extra_fields": {"agent": resolved.name}})
            raise
        finally:
            reset_run_id(run_token)
            reset_agent_name(agent_token)

    async def aclose(self) -> None:
        """关闭底层 LLM 客户端。"""
        await self._llm.aclose()

    def _resolve_agent(self, agent: Agent | str) -> Agent:
        if isinstance(agent, Agent):
            return agent
        return self._registry.get(agent)

    def _build_options(self, agent: Agent) -> CompletionOptions:
        """把 Agent 的模型参数与可用工具合并成单次调用选项。"""
        options = agent.completion_options()
        if not agent.tools:
            return options
        return options.model_copy(update={"tools": self._tools.specs(agent.tools)})

    async def _run_tool_calls(self, tool_calls: Sequence[ToolCall]) -> list[ToolCallResult]:
        """按声明顺序执行工具调用。

        顺序执行而非并发，保证同一轮内多个工具调用的副作用可预期；
        单个工具失败会返回 ``is_error=True`` 的结果，不会中断整次运行。
        """
        results: list[ToolCallResult] = []
        for tool_call in tool_calls:
            results.append(await self._tools.execute(tool_call))
        return results

    def _should_continue(self, response: LLMResponse, messages: Sequence[Message]) -> bool:
        """是否需要进入下一轮迭代。

        模型返回工具调用时为 ``True``：Runtime 先执行工具、回填结果，
        再由模型基于真实数据组织最终回答。Planning 与 Memory 后续在此扩展。
        """
        return response.has_tool_calls