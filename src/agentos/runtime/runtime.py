"""Agent Runtime：把 Agent 定义、LLM 客户端与会话历史串成一次可观测的运行。

当前版本负责：

- 组装消息（系统提示词 → 历史 → 用户输入）
- 驱动「模型调用 → 追加回复 → 执行工具 → 回填结果」的迭代循环，并用 ``max_iterations`` 兜底
- 记录 run_id / 耗时 / token 用量 / 工具调用次数，供日志与 API 返回

Tool Calling 已通过 :meth:`AgentRuntime._should_continue` 与
:meth:`AgentRuntime._run_tool_calls` 接入；Planning 与 Memory 将在后续版本沿用同一扩展点。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from agentos.core.config import ModelPricing, RuntimeSettings
from agentos.core.context import (
    get_user_id,
    get_workspace_id,
    new_id,
    reset_agent_name,
    reset_run_id,
    set_agent_name,
    set_run_id,
)
from agentos.core.exceptions import (
    AgentRuntimeError,
    NotFoundError,
    ValidationError,
)
from agentos.core.logging import get_logger
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.llm.base import (
    CompletionOptions,
    LLMClient,
    LLMMessage,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from agentos.observability.cost import estimate_cost
from agentos.observability.instrumentation import runtime_attributes, tool_attributes
from agentos.observability.metrics import record_llm, record_run, record_tool
from agentos.observability.tracing import set_span_attributes, start_span
from agentos.runtime.agent import Agent
from agentos.runtime.agent_tools import DEFAULT_MAX_DEPTH, DelegateToAgentTool
from agentos.runtime.audit import (
    ACTION_AGENT_RUN,
    ACTION_TOOL_EXECUTE,
    AuditLog,
)
from agentos.runtime.builtin_tools import create_default_tool_registry
from agentos.runtime.long_term_memory import LongTermMemory, MemoryContext
from agentos.runtime.memory import MemoryStore
from agentos.runtime.message import Message, MessageRole
from agentos.runtime.planning import (
    ExecutionPlan,
    get_plan,
    reset_plan,
    set_plan,
)
from agentos.runtime.registry import AgentRegistry, build_registry
from agentos.runtime.repositories import AuditStatus
from agentos.runtime.run_store import RunStore
from agentos.runtime.services.tool_policy_service import ToolPolicyService
from agentos.runtime.tools import ToolCallResult, ToolRegistry

logger = get_logger(__name__)


@dataclass
class _RunTracker:
    """Mutable counters for one Runtime execution."""

    llm_call_count: int = 0
    llm_error_count: int = 0
    tool_error_count: int = 0
    tool_timeout_count: int = 0
    memory_recall_count: int = 0
    memory_context_chars: int = 0
    max_iterations_reached: bool = False


class RunResult(BaseModel):
    """一次 Agent 运行的完整结果。"""

    run_id: str
    workspace_id: int = DEFAULT_WORKSPACE_ID
    user_id: int | None = None
    agent: str
    output: str
    messages: list[Message]
    usage: TokenUsage | None = None
    iterations: int = 1
    duration_ms: float = 0.0
    finish_reason: str | None = None
    tool_call_count: int = 0
    tool_error_count: int = 0
    tool_timeout_count: int = 0
    llm_call_count: int = 0
    llm_error_count: int = 0
    memory_recall_count: int = 0
    memory_context_chars: int = 0
    estimated_cost: float | None = None
    max_iterations_reached: bool = False
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
        pricing: Mapping[str, ModelPricing] | None = None,
        runs: RunStore | None = None,
        audit: AuditLog | None = None,
        tool_policy: ToolPolicyService | None = None,
        registry_db_path: str | None = None,
        enable_delegation: bool = True,
        max_delegation_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self._llm = llm_client
        self._settings = settings or RuntimeSettings()
        self._tools = tools if tools is not None else create_default_tool_registry()
        self._memory = memory if memory is not None else MemoryStore()
        self._long_term = long_term
        self._pricing = dict(pricing or {})
        self._runs = runs
        self._audit = audit
        self._tool_policy = tool_policy

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
            else build_registry(
                self._settings,
                tools=[tool.name for tool in self._tools.list()],
                persist_path=registry_db_path,
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
    def runs(self) -> RunStore | None:
        return self._runs

    @property
    def audit(self) -> AuditLog | None:
        return self._audit

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
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
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
            max_iterations=max_iterations,
            max_tool_calls=max_tool_calls,
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
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
    ) -> AsyncIterator[RunEvent]:
        """Wrap the runtime loop in an ``agent.run`` OpenTelemetry Span."""
        agent_name = agent.name if isinstance(agent, Agent) else agent
        started_at = time.perf_counter()
        final_result: RunResult | None = None
        with start_span(
            "agent.run", attributes=runtime_attributes(agent_name)
        ) as span:
            try:
                async for event in self._run_stream_inner(
                    agent,
                    input_text,
                    history=history,
                    session_id=session_id,
                    stateless=stateless,
                    max_iterations=max_iterations,
                    max_tool_calls=max_tool_calls,
                ):
                    if event.type == "end" and event.result is not None:
                        final_result = event.result
                        set_span_attributes(
                            span,
                            {
                                "iterations": event.result.iterations,
                                "tool_call_count": event.result.tool_call_count,
                                "duration_ms": event.result.duration_ms,
                                "estimated_cost": event.result.estimated_cost,
                                "memory_recall_count": event.result.memory_recall_count,
                                "memory_context_chars": event.result.memory_context_chars,
                            },
                        )
                    yield event
            except asyncio.CancelledError:
                record_run(
                    agent=agent_name,
                    status="cancelled",
                    duration_seconds=time.perf_counter() - started_at,
                )
                raise
            except Exception as exc:
                record_run(
                    agent=agent_name,
                    status="failed",
                    duration_seconds=time.perf_counter() - started_at,
                    error_type=type(exc).__name__,
                )
                raise
            else:
                result = final_result
                record_run(
                    agent=agent_name,
                    status="completed",
                    duration_seconds=time.perf_counter() - started_at,
                    tool_call_count=result.tool_call_count if result else 0,
                    tool_error_count=result.tool_error_count if result else 0,
                    tool_timeout_count=result.tool_timeout_count if result else 0,
                    llm_call_count=result.llm_call_count if result else 0,
                    llm_error_count=result.llm_error_count if result else 0,
                    estimated_cost=result.estimated_cost if result else None,
                )


    async def _run_stream_inner(
        self,
        agent: Agent | str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
        session_id: str | None = None,
        stateless: bool = False,
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
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
        max_iterations = (
            max_iterations
            or resolved.max_iterations
            or self._settings.max_iterations
        )
        messages = resolved.build_messages(input_text, history=history)
        base_prompt = resolved.system_prompt
        memory_context = self._recall_long_term(input_text)
        long_term_context = memory_context.text
        self._rebuild_system_prompt(messages, base_prompt, long_term_context)
        # 本轮消息从 user 开始，用于运行结束后写回会话记忆
        new_turn_start = len(messages) - 1
        options = self._build_options(resolved)
        model_name = self._model_name(options)
        tracker = _RunTracker(
            memory_recall_count=memory_context.recall_count,
            memory_context_chars=memory_context.char_count,
        )
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

                async for chunk in self._stream_llm(
                    [message.to_llm_message() for message in messages],
                    options=options,
                    tracker=tracker,
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
                    model=model_name,
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

                pending_tool_calls = response.tool_calls or []
                if (
                    max_tool_calls is not None
                    and tool_call_count + len(pending_tool_calls) > max_tool_calls
                ):
                    raise AgentRuntimeError(
                        f"agent '{resolved.name}' exceeded max_tool_calls={max_tool_calls}",
                        details={
                            "agent": resolved.name,
                            "max_tool_calls": max_tool_calls,
                        },
                    )
                for call in pending_tool_calls:
                    yield RunEvent(type="tool_call", tool_call=call)

                results = await self._run_tool_calls(
                    pending_tool_calls, resolved, tracker
                )
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
                tracker.max_iterations_reached = True
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
                workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
                user_id=get_user_id(),
                agent=resolved.name,
                output=response.content,
                messages=messages,
                usage=usage,
                iterations=iteration,
                duration_ms=round(duration_ms, 3),
                finish_reason=response.finish_reason,
                tool_call_count=tool_call_count,
                tool_error_count=tracker.tool_error_count,
                tool_timeout_count=tracker.tool_timeout_count,
                llm_call_count=tracker.llm_call_count,
                llm_error_count=tracker.llm_error_count,
                memory_recall_count=tracker.memory_recall_count,
                memory_context_chars=tracker.memory_context_chars,
                estimated_cost=estimate_cost(
                    usage, model=model_name, pricing=self._pricing
                ),
                max_iterations_reached=tracker.max_iterations_reached,
                session_id=resolved_session,
                plan=get_plan(),
            )
            if resolved_session:
                self._memory.append(resolved_session, messages[new_turn_start:])

            if self._runs is not None:
                self._runs.record(result, input_text=input_text)

            if self._audit is not None:
                self._audit.record(
                    ACTION_AGENT_RUN,
                    target=resolved.name,
                    detail=(
                        f"iterations={result.iterations} "
                        f"tools={tool_call_count} "
                        f"tokens={usage.total_tokens if usage else 0}"
                    ),
                )
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
                        "tool_error_count": tracker.tool_error_count,
                        "tool_timeout_count": tracker.tool_timeout_count,
                        "llm_call_count": tracker.llm_call_count,
                        "llm_error_count": tracker.llm_error_count,
                        "memory_recall_count": tracker.memory_recall_count,
                        "memory_context_chars": tracker.memory_context_chars,
                        "estimated_cost": result.estimated_cost,
                    }
                },
            )
            yield RunEvent(type="end", result=result)
        except asyncio.CancelledError:
            logger.info(
                "agent run cancelled",
                extra={"extra_fields": {"agent": resolved.name}},
            )
            if self._audit is not None:
                self._audit.record(
                    ACTION_AGENT_RUN,
                    status=AuditStatus.FAILURE,
                    target=resolved.name,
                    detail="cancelled",
                )
            if self._runs is not None:
                self._runs.record_cancelled(
                    run_id=run_id,
                    agent=resolved.name,
                    input_text=input_text,
                    session_id=resolved_session,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
                    user_id=get_user_id(),
                    tool_error_count=tracker.tool_error_count,
                    tool_timeout_count=tracker.tool_timeout_count,
                    llm_call_count=tracker.llm_call_count,
                    llm_error_count=tracker.llm_error_count,
                    memory_recall_count=tracker.memory_recall_count,
                    memory_context_chars=tracker.memory_context_chars,
                    estimated_cost=estimate_cost(
                        usage, model=model_name, pricing=self._pricing
                    ),
                )
            raise
        except Exception as exc:
            logger.exception(
                "agent run failed", extra={"extra_fields": {"agent": resolved.name}}
            )
            if self._audit is not None:
                self._audit.record(
                    ACTION_AGENT_RUN,
                    status=AuditStatus.FAILURE,
                    target=resolved.name,
                    detail=str(exc),
                )
            if self._runs is not None:
                self._runs.record_failure(
                    run_id=run_id,
                    agent=resolved.name,
                    workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
                    user_id=get_user_id(),
                    input_text=input_text,
                    error=str(exc),
                    session_id=resolved_session,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    tool_error_count=tracker.tool_error_count,
                    tool_timeout_count=tracker.tool_timeout_count,
                    llm_call_count=tracker.llm_call_count,
                    llm_error_count=tracker.llm_error_count,
                    memory_recall_count=tracker.memory_recall_count,
                    memory_context_chars=tracker.memory_context_chars,
                    estimated_cost=estimate_cost(
                        usage, model=model_name, pricing=self._pricing
                    ),
                    max_iterations_reached=tracker.max_iterations_reached,
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

    def _recall_long_term(self, query: str) -> MemoryContext:
        """Recall long-term memory within the configured prompt budget."""
        if self._long_term is None or not self._long_term.auto_recall:
            return MemoryContext()
        return self._long_term.build_context(query)

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

    def _agent_record_id(self, agent_name: str) -> int | None:
        repository = getattr(self._registry, "repository", None)
        if repository is None or not hasattr(repository, "get_record"):
            return None
        record = repository.get_record(
            agent_name,
            workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
        )
        return record.id if record is not None else None

    async def _stream_llm(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None,
        tracker: _RunTracker,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from the model inside an ``llm.call`` Span."""
        model = self._model_name(options)
        tracker.llm_call_count += 1
        started_at = time.perf_counter()
        prompt_tokens = 0
        completion_tokens = 0
        with start_span(
            "llm.call",
            attributes={
                "model": model,
                "workspace.id": get_workspace_id(),
                "user.id": get_user_id(),
            },
        ):
            try:
                async for chunk in self._llm.stream(messages, options=options):
                    if chunk.usage is not None:
                        prompt_tokens += chunk.usage.prompt_tokens
                        completion_tokens += chunk.usage.completion_tokens
                    yield chunk
            except Exception:
                tracker.llm_error_count += 1
                record_llm(
                    model=str(model),
                    status="error",
                    duration_seconds=time.perf_counter() - started_at,
                )
                raise
            else:
                record_llm(
                    model=str(model),
                    status="success",
                    duration_seconds=time.perf_counter() - started_at,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

    def _build_options(self, agent: Agent) -> CompletionOptions:
        """把 Agent 的模型参数与租户可见工具合并成单次调用选项。"""
        options = agent.completion_options()
        names = list(agent.tools)
        if self._tool_policy is not None:
            names = self._tool_policy.visible_tool_names(
                self._tools,
                agent,
                workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
                agent_id=self._agent_record_id(agent.name),
            )
        if not names:
            if not agent.tools:
                return options
            return options.model_copy(update={"tools": []})
        return options.model_copy(update={"tools": self._tools.specs(names)})

    def _model_name(self, options: CompletionOptions | None) -> str:
        """Resolve the effective model name for metrics and cost estimation."""
        if options is not None and options.model:
            return options.model
        return str(getattr(self._llm, "model", self._llm.provider))

    async def _run_tool_calls(
        self,
        tool_calls: Sequence[ToolCall],
        agent: Agent,
        tracker: _RunTracker | None = None,
    ) -> list[ToolCallResult]:
        """Run consecutive parallel-safe Tools concurrently and preserve order."""
        resolved_tracker = tracker or _RunTracker()
        results: list[ToolCallResult | None] = [None] * len(tool_calls)
        index = 0
        while index < len(tool_calls):
            if self._is_parallel_safe(tool_calls[index].name):
                batch: list[int] = []
                while index < len(tool_calls) and self._is_parallel_safe(
                    tool_calls[index].name
                ):
                    batch.append(index)
                    index += 1
                completed = await asyncio.gather(
                    *[
                        self._execute_tool_call(
                            tool_calls[position], agent, resolved_tracker
                        )
                        for position in batch
                    ]
                )
                for position, result in zip(batch, completed, strict=True):
                    results[position] = result
            else:
                results[index] = await self._execute_tool_call(
                    tool_calls[index], agent, resolved_tracker
                )
                index += 1
        return [result for result in results if result is not None]

    def _is_parallel_safe(self, tool_name: str) -> bool:
        try:
            return self._tools.get(tool_name).parallel_safe
        except NotFoundError:
            return False

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        agent: Agent,
        tracker: _RunTracker | None = None,
    ) -> ToolCallResult:
        """Execute one Tool call with policy and tracing checks."""
        resolved_tracker = tracker or _RunTracker()
        started_at = time.perf_counter()
        with start_span(
            "tool.call",
            attributes=tool_attributes(tool_call.name, call_id=tool_call.id),
        ) as span:
            if self._tool_policy is not None:
                allowed = self._tool_policy.visible_tool_names(
                    self._tools,
                    agent,
                    workspace_id=get_workspace_id() or DEFAULT_WORKSPACE_ID,
                    agent_id=self._agent_record_id(agent.name),
                )
                if tool_call.name not in allowed:
                    result = ToolCallResult(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=(
                            f"Error: tool execution permission denied: {tool_call.name}"
                        ),
                        is_error=True,
                        error_type="policy_denied",
                    )
                    resolved_tracker.tool_error_count += 1
                    set_span_attributes(
                        span, {"status": "denied", "error": True}
                    )
                    if self._audit is not None:
                        self._audit.record(
                            ACTION_TOOL_EXECUTE,
                            status=AuditStatus.FAILURE,
                            target=tool_call.name,
                            detail="tool not visible in current workspace/agent policy",
                        )
                    record_tool(
                        tool=tool_call.name,
                        status="denied",
                        duration_seconds=time.perf_counter() - started_at,
                    )
                    return result

            result = await self._tools.execute(tool_call)
            if result.is_error:
                resolved_tracker.tool_error_count += 1
            if result.error_type == "timeout":
                resolved_tracker.tool_timeout_count += 1
            set_span_attributes(
                span,
                {
                    "status": "error" if result.is_error else "success",
                    "error": result.is_error,
                    "result_length": len(result.content),
                },
            )
            if self._audit is not None:
                self._audit.record(
                    ACTION_TOOL_EXECUTE,
                    status=(
                        AuditStatus.FAILURE if result.is_error else AuditStatus.SUCCESS
                    ),
                    target=result.name,
                    detail=f"result_length={len(result.content)}",
                )
            record_tool(
                tool=tool_call.name,
                status="error" if result.is_error else "success",
                duration_seconds=time.perf_counter() - started_at,
                timeout=result.error_type == "timeout",
            )
            return result

    def _should_continue(self, response: LLMResponse, messages: Sequence[Message]) -> bool:
        """是否需要进入下一轮迭代。

        模型返回工具调用时为 ``True``：Runtime 先执行工具、回填结果，
        再由模型基于真实数据组织最终回答。Planning 与 Memory 后续在此扩展。
        """
        return response.has_tool_calls