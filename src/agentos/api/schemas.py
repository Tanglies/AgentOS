"""API 请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.llm.base import TokenUsage
from agentos.runtime.agent import AGENT_NAME_PATTERN, Agent
from agentos.runtime.long_term_memory import MemoryRecord
from agentos.runtime.memory import SessionState
from agentos.runtime.message import Message
from agentos.runtime.planning import ExecutionPlan
from agentos.runtime.runtime import RunResult
from agentos.runtime.tools import Tool


class HealthResponse(BaseModel):
    """存活探针响应。"""

    status: str = "ok"
    app: str
    version: str
    environment: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    """就绪探针响应。"""

    status: str = "ready"
    llm_provider: str
    agents: int
    tools: int = 0


class ToolSummary(BaseModel):
    """工具摘要信息。"""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_tool(cls, tool: Tool) -> ToolSummary:
        # 用 spec() 而不是类属性：像 delegate_to_agent 这类工具的描述是
        # 运行时动态生成的（列出当前可用 Agent），API 应展示模型真正看到的内容
        spec = tool.spec()
        return cls(
            name=spec.name, description=spec.description, parameters=spec.parameters
        )


class ToolListResponse(BaseModel):
    """工具列表响应。"""

    items: list[ToolSummary]
    total: int


class AgentSummary(BaseModel):
    """Agent 摘要信息。"""

    name: str
    description: str = ""
    model: str | None = None
    max_iterations: int | None = None
    tools: list[str] = Field(default_factory=list)

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentSummary:
        return cls(
            name=agent.name,
            description=agent.description,
            model=agent.model,
            max_iterations=agent.max_iterations,
            tools=list(agent.tools),
        )


class AgentCreateRequest(BaseModel):
    """注册 Agent 的请求体。"""

    name: str = Field(min_length=1, max_length=64, pattern=AGENT_NAME_PATTERN)
    description: str = ""
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_iterations: int | None = Field(default=None, ge=1, le=64)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_agent(self) -> Agent:
        return Agent(**self.model_dump())


class AgentListResponse(BaseModel):
    """Agent 列表响应。"""

    items: list[AgentSummary]
    total: int


class MemorySummary(BaseModel):
    """长期记忆摘要。"""

    id: int
    content: str
    session_id: str | None = None
    created_at: datetime

    @classmethod
    def from_record(cls, record: MemoryRecord) -> MemorySummary:
        return cls(
            id=record.id,
            content=record.content,
            session_id=record.session_id,
            created_at=record.created_at,
        )


class MemoryCreateRequest(BaseModel):
    """写入长期记忆的请求体。"""

    content: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)


class MemoryListResponse(BaseModel):
    """长期记忆列表响应。"""

    items: list[MemorySummary]
    total: int


class SessionSummary(BaseModel):
    """会话摘要。"""

    session_id: str
    turns: int
    messages: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_state(cls, state: SessionState) -> SessionSummary:
        return cls(
            session_id=state.session_id,
            turns=state.turn_count,
            messages=len(state.messages),
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


class SessionDetail(BaseModel):
    """会话详情。"""

    session_id: str
    turns: int
    messages: list[Message]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_state(cls, state: SessionState) -> SessionDetail:
        return cls(
            session_id=state.session_id,
            turns=state.turn_count,
            messages=state.messages,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


class SessionListResponse(BaseModel):
    """会话列表响应。"""

    items: list[SessionSummary]
    total: int


class RunRequest(BaseModel):
    """执行 Agent 的请求体。"""

    agent: str | None = Field(default=None, max_length=64)
    input: str = Field(min_length=1, max_length=32_000)
    history: list[Message] = Field(default_factory=list)
    session_id: str | None = Field(default=None, max_length=64)


class RunResponse(BaseModel):
    """一次运行的响应体。"""

    run_id: str
    agent: str
    output: str
    messages: list[Message]
    iterations: int
    duration_ms: float
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    tool_call_count: int = 0
    session_id: str | None = None
    plan: ExecutionPlan | None = None

    @classmethod
    def from_result(cls, result: RunResult) -> RunResponse:
        return cls(
            run_id=result.run_id,
            agent=result.agent,
            output=result.output,
            messages=result.messages,
            iterations=result.iterations,
            duration_ms=result.duration_ms,
            finish_reason=result.finish_reason,
            usage=result.usage,
            tool_call_count=result.tool_call_count,
            session_id=result.session_id,
            plan=result.plan,
        )