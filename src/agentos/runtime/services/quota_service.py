"""Workspace quota and usage services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentos.core.config import QuotaSettings
from agentos.core.exceptions import QuotaExceededError, RateLimitExceededError
from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.runtime.audit import (
    ACTION_QUOTA_UPDATE,
    ACTION_RATE_LIMIT_EXCEEDED,
    AuditLog,
    AuditStatus,
)
from agentos.runtime.platform_repositories import (
    WorkspaceQuotaRecord,
    WorkspaceQuotaRepository,
)
from agentos.runtime.rate_limit import RateLimiter
from agentos.runtime.repositories import RunAggregate, RunRepository


class QuotaService:
    """Resolve quota limits and enforce daily run/token budgets."""

    def __init__(
        self,
        quotas: WorkspaceQuotaRepository,
        runs: RunRepository | None,
        settings: QuotaSettings,
        *,
        audit: AuditLog | None = None,
    ) -> None:
        self._quotas = quotas
        self._runs = runs
        self._settings = settings
        self._audit = audit

    def get_limits(self, workspace_id: int = DEFAULT_WORKSPACE_ID) -> WorkspaceQuotaRecord:
        """Return persisted limits or configured defaults."""
        record = self._quotas.get(workspace_id)
        if record is not None:
            return record
        return WorkspaceQuotaRecord(
            workspace_id=workspace_id,
            daily_run_limit=self._settings.daily_run_limit,
            daily_token_limit=self._settings.daily_token_limit,
            requests_per_minute=self._settings.requests_per_minute,
            max_iterations_per_run=self._settings.max_iterations_per_run,
            max_tool_calls_per_run=self._settings.max_tool_calls_per_run,
        )

    def update(
        self,
        workspace_id: int,
        *,
        daily_run_limit: int | None = None,
        daily_token_limit: int | None = None,
        requests_per_minute: int | None = None,
        max_iterations_per_run: int | None = None,
        max_tool_calls_per_run: int | None = None,
    ) -> WorkspaceQuotaRecord:
        """Persist a quota override for a Workspace."""
        current = self.get_limits(workspace_id)
        updated = current.model_copy(
            update={
                "daily_run_limit": daily_run_limit or current.daily_run_limit,
                "daily_token_limit": daily_token_limit or current.daily_token_limit,
                "requests_per_minute": requests_per_minute or current.requests_per_minute,
                "max_iterations_per_run": (
                    max_iterations_per_run or current.max_iterations_per_run
                ),
                "max_tool_calls_per_run": (
                    max_tool_calls_per_run or current.max_tool_calls_per_run
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        saved = self._quotas.upsert(updated)
        if self._audit is not None:
            self._audit.record(
                ACTION_QUOTA_UPDATE,
                target=str(workspace_id),
                workspace_id=workspace_id,
            )
        return saved

    def validate_run(self, workspace_id: int = DEFAULT_WORKSPACE_ID) -> WorkspaceQuotaRecord:
        """Reject a run when today's run or token limit is exhausted."""
        limits = self.get_limits(workspace_id)
        aggregate = self._today_usage(workspace_id)
        if aggregate.runs + 1 > limits.daily_run_limit:
            raise QuotaExceededError(
                "daily run quota exceeded",
                details={
                    "workspace_id": workspace_id,
                    "used": aggregate.runs,
                    "limit": limits.daily_run_limit,
                },
            )
        if aggregate.total_tokens >= limits.daily_token_limit:
            raise QuotaExceededError(
                "daily token quota exceeded",
                details={
                    "workspace_id": workspace_id,
                    "used": aggregate.total_tokens,
                    "limit": limits.daily_token_limit,
                },
            )
        return limits

    def usage(
        self, workspace_id: int = DEFAULT_WORKSPACE_ID, *, period: str = "day"
    ) -> dict[str, Any]:
        """Aggregate Workspace usage from Run History."""
        since, until, label = self._period(period)
        aggregate = self._aggregate(workspace_id, since=since, until=until)
        return {
            "period": label,
            "runs": aggregate.runs,
            "prompt_tokens": aggregate.prompt_tokens,
            "completion_tokens": aggregate.completion_tokens,
            "total_tokens": aggregate.total_tokens,
            "tool_calls": aggregate.total_tool_calls,
        }

    def dashboard_usage(self, workspace_id: int = DEFAULT_WORKSPACE_ID) -> dict[str, Any]:
        """Return today's usage and quotas for the dashboard."""
        limits = self.get_limits(workspace_id)
        aggregate = self._today_usage(workspace_id)
        return {
            "runs": {"used": aggregate.runs, "limit": limits.daily_run_limit},
            "tokens": {
                "used": aggregate.total_tokens,
                "limit": limits.daily_token_limit,
            },
            "requests_per_minute": limits.requests_per_minute,
            "max_iterations_per_run": limits.max_iterations_per_run,
            "max_tool_calls_per_run": limits.max_tool_calls_per_run,
        }

    def _aggregate(
        self, workspace_id: int, *, since: datetime | None, until: datetime | None
    ) -> RunAggregate:
        if self._runs is None:
            return RunAggregate()
        return self._runs.aggregate(
            workspace_id=workspace_id, since=since, until=until
        )

    def _today_usage(self, workspace_id: int) -> RunAggregate:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self._aggregate(
            workspace_id, since=start, until=start + timedelta(days=1)
        )

    @staticmethod
    def _period(period: str) -> tuple[datetime, datetime, str]:
        now = datetime.now(UTC)
        if period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end, start.strftime("%Y-%m")
        if period != "day":
            raise ValueError("period must be 'day' or 'month'")
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1), start.strftime("%Y-%m-%d")


class RateLimitService:
    """Apply per-Workspace and per-API-key request rate limits."""

    def __init__(
        self,
        quota: QuotaService,
        limiter: RateLimiter,
        *,
        audit: AuditLog | None = None,
    ) -> None:
        self._quota = quota
        self._limiter = limiter
        self._audit = audit

    def check(
        self, workspace_id: int, actor: str | None, *, user_id: int | None = None
    ) -> None:
        """Raise ``RateLimitExceededError`` when the request is over limit."""
        limits = self._quota.get_limits(workspace_id)
        key = f"{workspace_id}:{actor or 'anonymous'}"
        if not self._limiter.allow(key, limit=limits.requests_per_minute):
            if self._audit is not None:
                self._audit.record(
                    ACTION_RATE_LIMIT_EXCEEDED,
                    status=AuditStatus.FAILURE,
                    target=actor,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            raise RateLimitExceededError(
                "workspace request rate exceeded",
                details={
                    "workspace_id": workspace_id,
                    "limit": limits.requests_per_minute,
                    "window_seconds": 60,
                },
            )


class UsageService:
    """Compatibility wrapper for Workspace usage queries."""

    def __init__(self, quota: QuotaService) -> None:
        self._quota = quota

    def summary(self, workspace_id: int, *, period: str = "day") -> dict[str, Any]:
        return self._quota.usage(workspace_id, period=period)

    def dashboard(self, workspace_id: int) -> dict[str, Any]:
        return self._quota.dashboard_usage(workspace_id)


__all__ = ["QuotaService", "RateLimitService", "UsageService"]
