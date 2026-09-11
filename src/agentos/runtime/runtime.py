"""Agent Runtime：把 Agent 定义、LLM 客户端与会话历史串成一次可观测的运行。

v0.1 负责：

- 组装消息（系统提示词 → 历史 → 用户输入）
- 驱动「模型调用 → 追加回复」的迭代循环，并用 ``max_iterations`` 兜底
- 记录 run_id / 耗时 / token 用量，供日志与 API 返回

工具调用、规划与记忆将在 :meth:`AgentRuntime._should_continue` 这个扩展点接入。
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
from agentos.llm.base import LLMClient, LLMResponse, TokenUsage
from agentos.runtime.agent import Agent
from agentos.runtime.message import Message
from agentos.runtime.registry import AgentRegistry, create_default_registry

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


class AgentRuntime:
    """Agent 执行内核。"""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        settings: RuntimeSettings | None = None,
        registry: AgentRegistry | None = None,
    ) -> None:
        self._llm = llm_client
        self._settings = settings or RuntimeSettings()
        self._registry = (
            registry if registry is not None else create_default_registry(self._settings)
        )

    @property
    def llm_client(self) -> LLMClient:
        return self._llm

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

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
        """执行一次 Agent 运行并返回结构化结果。"""
        resolved = self._resolve_agent(agent)
        if not input_text.strip():
            raise ValidationError("input must not be empty", details={"agent": resolved.name})

        run_id = new_id("run_")
        run_token = set_run_id(run_id)
        agent_token = set_agent_name(resolved.name)
        started_at = time.perf_counter()
        max_iterations = resolved.max_iterations or self._settings.max_iterations
        messages = resolved.build_messages(input_text, history=history)
        usage: TokenUsage | None = None
        response: LLMResponse | None = None
        iteration = 0

        logger.info(
            "agent run started",
            extra={"extra_fields": {"agent": resolved.name, "max_iterations": max_iterations}},
        )

        try:
            for iteration in range(1, max_iterations + 1):
                response = await self._llm.complete(
                    [message.to_llm_message() for message in messages],
                    options=resolved.completion_options(),
                )
                messages.append(Message.assistant(response.content))
                if response.usage is not None:
                    usage = response.usage if usage is None else usage + response.usage

                logger.debug(
                    "agent run iteration completed",
                    extra={
                        "extra_fields": {
                            "iteration": iteration,
                            "finish_reason": response.finish_reason,
                        }
                    },
                )
                if not self._should_continue(response, messages):
                    break
            else:
                raise AgentRuntimeError(
                    f"agent '{resolved.name}' exceeded max_iterations={max_iterations}",
                    details={"agent": resolved.name, "max_iterations": max_iterations},
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
            )
            logger.info(
                "agent run completed",
                extra={
                    "extra_fields": {
                        "agent": resolved.name,
                        "iterations": result.iterations,
                        "duration_ms": result.duration_ms,
                        "total_tokens": usage.total_tokens if usage else 0,
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

    def _should_continue(self, response: LLMResponse, messages: Sequence[Message]) -> bool:
        """是否需要进入下一轮迭代。

        v0.1 尚未接入工具调用，模型返回即结束；
        Tool Calling / Planning 落地后在此判断 ``tool_calls`` 或计划完成度。
        """
        return False