"""Collect evaluation metrics from run history."""

from __future__ import annotations

from datetime import datetime

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
        self, *, agent: str | None = None, since: datetime | None = None
    ) -> EvaluationSummary:
        """Aggregate the built-in metrics with optional agent and time filters."""
        aggregate = self._runs.aggregate(agent=agent, since=since)
        durations = self._runs.durations(agent=agent, since=since)
        return self._build(aggregate, durations, agent=agent)

    def collect(
        self, *, agent: str | None = None, since: datetime | None = None
    ) -> dict[str, object]:
        """Run all configured metrics and return values by metric name.

        ``summarize`` keeps the stable API shape while ``collect`` is the
        extension point for callers that register additional metrics.
        """
        aggregate = self._runs.aggregate(agent=agent, since=since)
        durations = self._runs.durations(agent=agent, since=since)
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
            agent=agent,
        )


EvaluationCollector = Evaluator

__all__ = ["EvaluationCollector", "Evaluator"]
