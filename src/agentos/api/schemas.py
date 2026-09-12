"""API 请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.database.models import AgentRecord
from agentos.llm.base import TokenUsage
from agentos.runtime.agent import AGENT_NAME_PATTERN, Agent
from agentos.runtime.long_term_memory import MemoryRecord
from agentos.runtime.memory import SessionState
from agentos.runtime.message import Message
from agentos.runtime.planning import ExecutionPlan
from agentos.runtime.platform_repositories import (
    UserRecord,
    UserStatus,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    WorkspaceRole,
)
from agentos.runtime.repositories import ApiKeyRecord, MemoryScope
from agentos.runtime.run_store import RunRecord
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
    """???????"""

    name: str
    description: str = ""
    category: str = "general"
    risk_level: str = "low"
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_tool(cls, tool: Tool, *, enabled: bool = True) -> ToolSummary:
        # ? spec() ???????????????????????
        spec = tool.spec()
        return cls(
            name=spec.name,
            description=spec.description,
            category=tool.category,
            risk_level=tool.risk_level,
            enabled=enabled,
            parameters=spec.parameters,
        )


class ToolListResponse(BaseModel):
    """工具列表响应。"""

    items: list[ToolSummary]
    total: int


class AgentSummary(BaseModel):
    """Agent 摘要与详情共用的响应模型。"""

    id: int | None = None
    workspace_id: int = 1
    name: str
    description: str = ""
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_iterations: int | None = None
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentSummary:
        return cls(
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            model=agent.model,
            temperature=agent.temperature,
            max_iterations=agent.max_iterations,
            tools=list(agent.tools),
            metadata=dict(agent.metadata),
        )

    @classmethod
    def from_record(cls, record: AgentRecord) -> AgentSummary:
        """Build a response from a persisted Agent record."""
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            name=record.name,
            description=record.description,
            system_prompt=record.system_prompt,
            model=record.model,
            temperature=record.temperature,
            max_iterations=record.max_iterations,
            tools=list(record.tools),
            metadata=dict(record.metadata),
            created_at=record.created_at,
            updated_at=record.updated_at,
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
    """Agent 列表响应，保留总数并增加分页元数据。"""

    items: list[AgentSummary]
    total: int
    page: int = 1
    page_size: int = 20


class RunSummary(BaseModel):
    """运行记录摘要（不含消息列表，用于列表接口）。"""

    run_id: str
    workspace_id: int = 1
    user_id: int | None = None
    agent: str
    session_id: str | None = None
    status: str = "completed"
    input: str = ""
    output: str = ""
    error: str | None = None
    iterations: int = 0
    duration_ms: float = 0.0
    tool_call_count: int = 0
    finish_reason: str | None = None
    total_tokens: int = 0
    token_usage: TokenUsage | None = None
    created_at: datetime

    @classmethod
    def from_record(cls, record: RunRecord) -> RunSummary:
        return cls(
            run_id=record.run_id,
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            agent=record.agent,
            session_id=record.session_id,
            status=record.status.value,
            input=record.input,
            output=record.output,
            error=record.error,
            iterations=record.iterations,
            duration_ms=record.duration_ms,
            tool_call_count=record.tool_call_count,
            finish_reason=record.finish_reason,
            total_tokens=record.total_tokens,
            token_usage=TokenUsage(
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
            ),
            created_at=record.created_at,
        )


class RunDetail(RunSummary):
    """运行记录详情（含完整消息轨迹）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    messages: list[Message] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: RunRecord) -> RunDetail:
        return cls(
            **RunSummary.from_record(record).model_dump(),
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            messages=list(record.messages),
        )


class RunListResponse(BaseModel):
    """运行历史列表响应，兼容 offset/limit 与 page/page_size。"""

    items: list[RunSummary]
    total: int
    limit: int
    offset: int
    page: int = 1
    page_size: int = 50


class MemorySummary(BaseModel):
    """长期记忆摘要。"""

    id: int
    workspace_id: int = 1
    user_id: int | None = None
    scope: MemoryScope = MemoryScope.WORKSPACE
    content: str
    session_id: str | None = None
    created_at: datetime

    @classmethod
    def from_record(cls, record: MemoryRecord) -> MemorySummary:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            scope=record.scope,
            content=record.content,
            session_id=record.session_id,
            created_at=record.created_at,
        )


class MemoryCreateRequest(BaseModel):
    """写入长期记忆的请求体。"""

    content: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    scope: MemoryScope = MemoryScope.WORKSPACE


class MemoryListResponse(BaseModel):
    """长期记忆列表响应。"""

    items: list[MemorySummary]
    total: int


class SessionSummary(BaseModel):
    """会话摘要。"""

    session_id: str
    workspace_id: int = 1
    user_id: int = 1
    turns: int
    messages: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_state(cls, state: SessionState) -> SessionSummary:
        return cls(
            session_id=state.session_id,
            workspace_id=state.workspace_id,
            user_id=state.user_id,
            turns=state.turn_count,
            messages=len(state.messages),
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


class SessionDetail(BaseModel):
    """会话详情。"""

    session_id: str
    workspace_id: int = 1
    user_id: int = 1
    turns: int
    messages: list[Message]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_state(cls, state: SessionState) -> SessionDetail:
        return cls(
            session_id=state.session_id,
            workspace_id=state.workspace_id,
            user_id=state.user_id,
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


class ApiKeyCreateRequest(BaseModel):
    """签发 API Key 的请求体。"""

    name: str = Field(min_length=1, max_length=64)
    user_id: int | None = Field(default=None, gt=0)
    workspace_id: int | None = Field(default=None, gt=0)
    permissions: list[str] | None = Field(default=None, max_length=32)


class ApiKeySummary(BaseModel):
    """API Key 记录摘要（绝不包含明文与哈希）。"""

    id: int
    name: str
    user_id: int = 1
    workspace_id: int = 1
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def from_record(cls, record: ApiKeyRecord) -> ApiKeySummary:
        if record.id is None:  # pragma: no cover - 已持久化记录必然有 id
            raise ValueError("api key record has no id")
        return cls(
            id=record.id,
            name=record.name,
            user_id=record.user_id,
            workspace_id=record.workspace_id,
            permissions=list(record.permissions),
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            revoked_at=record.revoked_at,
        )


class ApiKeyCreateResponse(ApiKeySummary):
    """签发响应；``key`` 是明文，只在本次响应中出现。"""

    key: str


class ApiKeyListResponse(BaseModel):
    """API Key 列表响应。"""

    items: list[ApiKeySummary]
    total: int


class DashboardOverviewResponse(BaseModel):
    """Dashboard overview metrics."""

    total_runs: int = 0
    success_rate: float = 0.0
    average_latency: float = 0.0
    total_tokens: int = 0
    active_agents: int = 0


class DashboardErrorItem(BaseModel):
    """One recent failed run for the dashboard."""

    run_id: str
    agent: str
    status: str
    error: str = ""
    duration_ms: float = 0.0
    created_at: datetime


class UserCreateRequest(BaseModel):
    """Create a platform user."""

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    status: UserStatus = UserStatus.ACTIVE


class UserSummary(BaseModel):
    """Platform user response."""

    id: int
    username: str
    display_name: str = ""
    status: UserStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: UserRecord) -> UserSummary:
        if record.id is None:  # pragma: no cover
            raise ValueError("user record has no id")
        return cls(**record.model_dump())


class UserListResponse(BaseModel):
    """Paginated user list."""

    items: list[UserSummary]
    total: int
    page: int = 1
    page_size: int = 100


class WorkspaceCreateRequest(BaseModel):
    """Create a Workspace owned by the current user."""

    name: str = Field(min_length=1, max_length=128)


class WorkspaceUpdateRequest(BaseModel):
    """Update Workspace metadata."""

    name: str = Field(min_length=1, max_length=128)


class WorkspaceSummary(BaseModel):
    """Workspace response."""

    id: int
    name: str
    owner_id: int
    role: WorkspaceRole | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(
        cls, record: WorkspaceRecord, *, role: WorkspaceRole | None = None
    ) -> WorkspaceSummary:
        if record.id is None:  # pragma: no cover
            raise ValueError("workspace record has no id")
        return cls(
            id=record.id,
            name=record.name,
            owner_id=record.owner_id,
            role=role,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class WorkspaceListResponse(BaseModel):
    """Workspace list visible to the current user."""

    items: list[WorkspaceSummary]
    total: int


class WorkspaceMemberAddRequest(BaseModel):
    """Add a user to a Workspace."""

    user_id: int = Field(gt=0)
    role: WorkspaceRole = WorkspaceRole.MEMBER


class WorkspaceMemberSummary(BaseModel):
    """Workspace membership response."""

    workspace_id: int
    user_id: int
    username: str = ""
    display_name: str = ""
    role: WorkspaceRole
    created_at: datetime

    @classmethod
    def from_record(
        cls,
        record: WorkspaceMemberRecord,
        *,
        username: str = "",
        display_name: str = "",
    ) -> WorkspaceMemberSummary:
        return cls(
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            username=username,
            display_name=display_name,
            role=record.role,
            created_at=record.created_at,
        )


class WorkspaceMemberListResponse(BaseModel):
    """Workspace membership list."""

    items: list[WorkspaceMemberSummary]
    total: int


class ToolUpdateRequest(BaseModel):
    """Enable or disable a Tool for the current Workspace."""

    enabled: bool


class QuotaSummary(BaseModel):
    """Workspace quota limits."""

    workspace_id: int
    daily_run_limit: int
    daily_token_limit: int
    requests_per_minute: int
    max_iterations_per_run: int
    max_tool_calls_per_run: int
    updated_at: datetime


class QuotaUpdateRequest(BaseModel):
    """Update Workspace quota limits."""

    daily_run_limit: int | None = Field(default=None, ge=1)
    daily_token_limit: int | None = Field(default=None, ge=1)
    requests_per_minute: int | None = Field(default=None, ge=1)
    max_iterations_per_run: int | None = Field(default=None, ge=1, le=64)
    max_tool_calls_per_run: int | None = Field(default=None, ge=1, le=1000)


class UsageResponse(BaseModel):
    """Workspace usage aggregate."""

    period: str
    runs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
