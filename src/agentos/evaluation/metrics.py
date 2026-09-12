"""Evaluation metric models and reusable calculations."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.runtime.repositories import RunAggregate


class Metric(ABC):
    """Extension point for a metric computed from run aggregates."""

    name: str = "metric"

    @abstractmethod
    def compute(self, aggregate: RunAggregate, durations: list[float]) -> Any:
        """Compute the metric value."""


class LatencyMetrics(BaseModel):
    """Latency distribution in milliseconds."""

    avg: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    max: float = 0.0


class TokenMetrics(BaseModel):
    """Token usage metrics."""

    prompt: int = 0
    completion: int = 0
    total: int = 0
    avg_per_run: float = 0.0


class ToolCallMetrics(BaseModel):
    """Tool-call metrics."""

    total: int = 0
    avg_per_run: float = 0.0
    max_in_run: int = 0
    runs_with_tools: int = 0


class EvaluationSummary(BaseModel):
    """Aggregated evaluation result for a set of runs."""

    runs: int = 0
    succeeded: int = 0
    failed: int = 0
    success_rate: float = 0.0
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    tokens: TokenMetrics = Field(default_factory=TokenMetrics)
    tool_calls: ToolCallMetrics = Field(default_factory=ToolCallMetrics)
    agent: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def percentile(values: list[float], quantile: float) -> float:
    """Linear-interpolation percentile; values must be sorted ascending."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] + (values[upper] - values[lower]) * weight


class LatencyMetric(Metric):
    """Built-in latency metric."""

    name = "latency"

    def compute(self, aggregate: RunAggregate, durations: list[float]) -> LatencyMetrics:
        return LatencyMetrics(
            avg=round(aggregate.avg_duration_ms, 3),
            p50=round(percentile(durations, 0.5), 3),
            p95=round(percentile(durations, 0.95), 3),
            max=round(durations[-1], 3) if durations else 0.0,
        )


class TokenMetric(Metric):
    """Built-in token metric."""

    name = "tokens"

    def compute(self, aggregate: RunAggregate, durations: list[float]) -> TokenMetrics:
        del durations
        return TokenMetrics(
            prompt=aggregate.prompt_tokens,
            completion=aggregate.completion_tokens,
            total=aggregate.total_tokens,
            avg_per_run=round(aggregate.avg_total_tokens, 2),
        )


class ToolCallMetric(Metric):
    """Built-in tool-call metric."""

    name = "tool_calls"

    def compute(self, aggregate: RunAggregate, durations: list[float]) -> ToolCallMetrics:
        del durations
        return ToolCallMetrics(
            total=aggregate.total_tool_calls,
            avg_per_run=round(aggregate.avg_tool_calls, 2),
            max_in_run=aggregate.max_tool_calls,
            runs_with_tools=aggregate.runs_with_tools,
        )


__all__ = [
    "EvaluationSummary",
    "LatencyMetric",
    "LatencyMetrics",
    "Metric",
    "TokenMetric",
    "TokenMetrics",
    "ToolCallMetric",
    "ToolCallMetrics",
    "percentile",
]
