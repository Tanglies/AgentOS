"""Agent execution service with quota enforcement."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from agentos.core.context import get_workspace_id
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.message import Message
from agentos.runtime.runtime import AgentRuntime, RunEvent, RunResult
from agentos.runtime.services.quota_service import QuotaService


class RunService:
    """Execute Agents under the current Workspace quota."""

    def __init__(self, runtime: AgentRuntime, quota: QuotaService) -> None:
        self._runtime = runtime
        self._quota = quota

    @staticmethod
    def _workspace_id() -> int:
        return get_workspace_id() or DEFAULT_WORKSPACE_ID

    async def run(
        self,
        agent_name: str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
        session_id: str | None = None,
    ) -> RunResult:
        scope = self._workspace_id()
        limits = self._quota.validate_run(scope)
        return await self._runtime.run(
            agent_name,
            input_text,
            history=history,
            session_id=session_id,
            max_iterations=limits.max_iterations_per_run,
            max_tool_calls=limits.max_tool_calls_per_run,
        )

    async def run_stream(
        self,
        agent_name: str,
        input_text: str,
        *,
        history: Sequence[Message] | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[RunEvent]:
        scope = self._workspace_id()
        limits = self._quota.validate_run(scope)
        async for event in self._runtime.run_stream(
            agent_name,
            input_text,
            history=history,
            session_id=session_id,
            max_iterations=limits.max_iterations_per_run,
            max_tool_calls=limits.max_tool_calls_per_run,
        ):
            yield event


__all__ = ["RunService"]
