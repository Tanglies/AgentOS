"""Collect evaluation metrics from run history."""

from __future__ import annotations

from datetime import datetime

from agentos.core.tenancy import DEFAULT_WORKSPACE_ID
from agentos.evaluation.metrics import (
    EvaluationSummary,
    LatencyMetric,
    Metric,
    TokenMetric,
    ToolCallMetric,
)
from agentos.runtime.repositories import RunAggregate, RunRepository


class Evaluator:
    """Build an :class:`EvaluationSummary` from a run repository."""

    def __init__(self, runs: RunRepository, metrics: list[Metric] | None = None) -> None:
        self._runs = runs
        self._metrics = [
            LatencyMetric(),
            TokenMetric(),
            ToolCallMetric(),
            *(metrics or []),
        ]

    def summarize(
        self,
        *,
        agent: str | None = None,
        since: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> EvaluationSummary:
        """Aggregate metrics inside one Workspace."""
        aggregate = self._runs.aggregate(
            workspace_id=workspace_id, agent=agent, since=since
        )
        durations = self._runs.durations(
            workspace_id=workspace_id, agent=agent, since=since
        )
        return self._build(aggregate, durations, agent=agent)

    def collect(
        self,
        *,
        agent: str | None = None,
        since: datetime | None = None,
        workspace_id: int = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, object]:
        """Run all configured metrics and return values by metric name.

        ``summarize`` keeps the stable API shape while ``collect`` is the
        extension point for callers that register additional metrics.
        """
        aggregate = self._runs.aggregate(
            workspace_id=workspace_id, agent=agent, since=since
        )
        durations = self._runs.durations(
            workspace_id=workspace_id, agent=agent, since=since
        )
        return {
            metric.name: metric.compute(aggregate, durations)
            for metric in self._metrics
        }

    def _build(
        self, aggregate: RunAggregate, durations: list[float], *, agent: str | None
    ) -> EvaluationSummary:
        values = {
            metric.name: metric.compute(aggregate, durations)
            for metric in self._metrics
        }
        return EvaluationSummary(
            runs=aggregate.runs,
            succeeded=aggregate.succeeded,
            failed=aggregate.failed,
            success_rate=round(aggregate.success_rate, 4),
            latency=values["latency"],
            tokens=values["tokens"],
            tool_calls=values["tool_calls"],
            average_latency=round(aggregate.avg_duration_ms, 3),
            average_tokens=round(aggregate.avg_total_tokens, 2),
            average_tool_calls=round(aggregate.avg_tool_calls, 2),
            agent=agent,
        )


EvaluationCollector = Evaluator

__all__ = ["EvaluationCollector", "Evaluator"]
