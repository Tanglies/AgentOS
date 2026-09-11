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
from collections.abc import AsyncIterator, Sequence
from typing import Literal

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
from agentos.runtime.agent_tools import DEFAULT_MAX_DEPTH, DelegateToAgentTool
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.long_term_memory import LongTermMemory
from agentos.runtime.memory import MemoryStore
from agentos.runtime.message import Message, MessageRole
from agentos.runtime.planning import (
    ExecutionPlan,
    get_plan,
    reset_plan,
    set_plan,
)
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
    session_id: str | None = None
    plan: ExecutionPlan | None = None


class RunEvent(BaseModel):
    """流式运行中的事件。

    通过 ``type`` 区分载荷：

    - ``start``       运行开始，带 ``run_id`` / ``agent`` / ``session_id``
    - ``delta``       模型输出的文本增量，内容在 ``delta``
    - ``tool_call``   模型请求调用工具，内容在 ``tool_call``
    - ``tool_result`` 工具执行结果，内容在 ``tool_result``
    - ``end``         运行结束，完整结果在 ``result``
    - ``error``       运行失败，原因在 ``error``
    """

    type: Literal["start", "delta", "tool_call", "tool_result", "end", "error"]
    run_id: str | None = None
    agent: str | None = None
    session_id: str | None = None
    delta: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolCallResult | None = None
    result: RunResult | None = None
    error: str | None = None


class AgentRuntime:
    """Agent 执行内核。"""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        settings: RuntimeSettings | None = None,
        registry: AgentRegistry | None = None,
        tools: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        long_term: LongTermMemory | None = None,
        enable_delegation: bool = True,
        max_delegation_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self._llm = llm_client
        self._settings = settings or RuntimeSettings()
        self._tools = tools if tools is not None else create_default_tool_registry()
        self._memory = memory if memory is not None else MemoryStore()
        self._long_term = long_term

        # 委托工具需要引用 Runtime 自身，只能在实例化过程中注册
        if enable_delegation:
            self._tools.register(
                DelegateToAgentTool(self, max_depth=max_delegation_depth),
                overwrite=True,
            )

        # 默认 Agent 的工具清单必须在委托工具注册之后再生成，否则会漏掉它
        self._registry = (
            registry
            if registry is not None
            else create_default_registry(
                self._settings, tools=[tool.name for tool in self._tools.list()]
            )
        )

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
    def memory(self) -> MemoryStore:
        return self._memory

    @property
    def long_term(self) -> LongTermMemory | None:
        return self._long_term

    @property
    def settings(self) -> RuntimeSettings:
        return self._settings

    async def run(
        self,
        agent: Agent | str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
        session_id: str | None = None,
        stateless: bool = False,
    ) -> RunResult:
        """执行一次 Agent 运行并返回结构化结果。

        这是 :meth:`run_stream` 的薄封装：消费全部事件后返回最终结果。
        需要边生成边返回（例如 SSE 推送）时请直接用 :meth:`run_stream`。
        """
        result: RunResult | None = None
        async for event in self.run_stream(
            agent,
            input_text,
            history=history,
            session_id=session_id,
            stateless=stateless,
        ):
            if event.type == "end":
                result = event.result

        if result is None:  # pragma: no cover - 正常路径必然产出 end 事件
            raise AgentRuntimeError("agent run produced no result")
        return result

    async def run_stream(
        self,
        agent: Agent | str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
        session_id: str | None = None,
        stateless: bool = False,
    ) -> AsyncIterator[RunEvent]:
        """流式执行一次 Agent 运行，逐段产出 :class:`RunEvent`。

        典型事件顺序：

        ``start`` → (``delta`` | ``tool_call`` | ``tool_result``)* → ``end``

        文本增量是**真正边收边发**的：收到一个片段就立即产出 ``delta`` 事件，
        不会先缓冲整段回答再一次性发出。

        出错时先产出 ``error`` 事件，再继续抛出异常，让调用方既能推送错误、
        又能走统一的异常处理路径。会话记忆与长期记忆的规则与 :meth:`run` 一致。
        """
        resolved = self._resolve_agent(agent)
        if not input_text.strip():
            raise ValidationError("input must not be empty", details={"agent": resolved.name})

        # 优先级：stateless > 显式 session_id > 显式 history（无状态）> 默认会话。
        # stateless 用于子 Agent 委托：父级已给出自包含任务，不应复用任何会话记忆。
        if stateless:
            resolved_session: str | None = None
            history = None
        elif history and not session_id:
            resolved_session = None
        else:
            resolved_session = self._memory.resolve_session_id(session_id)
            if resolved_session:
                history = self._memory.history(resolved_session)

        run_id = new_id("run_")
        run_token = set_run_id(run_id)
        agent_token = set_agent_name(resolved.name)
        # 计划按运行隔离：开始时清空，结束时随上下文一起还原
        plan_token = set_plan(None)
        started_at = time.perf_counter()
        max_iterations = resolved.max_iterations or self._settings.max_iterations
        messages = resolved.build_messages(input_text, history=history)
        base_prompt = resolved.system_prompt
        long_term_context = self._recall_long_term(input_text)
        self._rebuild_system_prompt(messages, base_prompt, long_term_context)
        # 本轮消息从 user 开始，用于运行结束后写回会话记忆
        new_turn_start = len(messages) - 1
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

        yield RunEvent(
            type="start",
            run_id=run_id,
            agent=resolved.name,
            session_id=resolved_session,
        )

        try:
            for iteration in range(1, max_iterations + 1):
                # 计划可能在上一轮被更新，每轮都重建系统提示词
                if self._rebuild_system_prompt(messages, base_prompt, long_term_context):
                    new_turn_start += 1

                content_parts: list[str] = []
                tool_calls: list[ToolCall] = []
                finish_reason: str | None = None
                chunk_usage: TokenUsage | None = None

                async for chunk in self._llm.stream(
                    [message.to_llm_message() for message in messages], options=options
                ):
                    if chunk.delta:
                        content_parts.append(chunk.delta)
                        # 真正的增量推送：收到即发，不缓冲
                        yield RunEvent(type="delta", delta=chunk.delta)
                    if chunk.tool_calls:
                        tool_calls = chunk.tool_calls
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.usage is not None:
                        chunk_usage = chunk.usage

                response = LLMResponse(
                    content="".join(content_parts),
                    model=resolved.model or "",
                    finish_reason=finish_reason,
                    usage=chunk_usage,
                    tool_calls=tool_calls or None,
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

                for call in response.tool_calls or []:
                    yield RunEvent(type="tool_call", tool_call=call)

                results = await self._run_tool_calls(response.tool_calls or [])
                tool_call_count += len(results)
                for tool_result in results:
                    yield RunEvent(type="tool_result", tool_result=tool_result)
                    messages.append(
                        Message.tool(
                            tool_result.content,
                            tool_call_id=tool_result.tool_call_id,
                            name=tool_result.name,
                        )
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
                session_id=resolved_session,
                plan=get_plan(),
            )
            if resolved_session:
                self._memory.append(resolved_session, messages[new_turn_start:])
                logger.debug(
                    "session memory updated",
                    extra={
                        "extra_fields": {
                            "session_id": resolved_session,
                            "session_messages": len(messages) - new_turn_start,
                        }
                    },
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
            yield RunEvent(type="end", result=result)
        except Exception as exc:
            logger.exception(
                "agent run failed", extra={"extra_fields": {"agent": resolved.name}}
            )
            yield RunEvent(type="error", run_id=run_id, error=str(exc))
            raise
        finally:
            reset_plan(plan_token)
            reset_run_id(run_token)
            reset_agent_name(agent_token)

    async def aclose(self) -> None:
        """关闭底层 LLM 客户端。"""
        await self._llm.aclose()

    def _recall_long_term(self, query: str) -> str | None:
        """召回相关长期记忆，返回可注入系统提示词的文本。"""
        if self._long_term is None or not self._long_term.auto_recall:
            return None

        records = self._long_term.recall(query)
        if not records:
            return None

        lines = ["[长期记忆] 以下是与当前问题相关的历史记录，供参考："]
        lines.extend(f"- {record.content}" for record in records)
        return "\n".join(lines)

    @staticmethod
    def _rebuild_system_prompt(
        messages: list[Message], base_prompt: str | None, long_term_context: str | None
    ) -> bool:
        """按「基础提示词 + 长期记忆 + 执行计划」重组系统提示词。

        执行计划每轮都可能变化，所以每次调用模型前都要重建。
        返回是否**新插入**了 system 消息 —— 调用方需要据此调整消息切片下标。
        """
        parts = [base_prompt] if base_prompt else []
        if long_term_context:
            parts.append(long_term_context)

        plan = get_plan()
        if plan is not None and plan.steps:
            parts.append(plan.render())

        content = "\n\n".join(parts)
        if not content:
            return False

        if messages and messages[0].role == MessageRole.SYSTEM:
            if messages[0].content != content:
                messages[0] = Message.system(content)
            return False

        messages.insert(0, Message.system(content))
        return True

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