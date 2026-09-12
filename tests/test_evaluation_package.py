"""Tests for the extracted evaluation package."""

from __future__ import annotations

from typing import Any

from agentos.evaluation import (
    EvaluationCollector,
    EvaluationReport,
    EvaluationSummary,
    Evaluator,
    LatencyMetric,
    LatencyMetrics,
    Metric,
    TokenMetric,
    ToolCallMetric,
)
from agentos.runtime.repositories import RunAggregate


class ConstantMetric(Metric):
    name = "constant"

    def compute(self, aggregate: RunAggregate, durations: list[float]) -> Any:
        del aggregate, durations
        return 7


def test_metric_is_an_extension_point() -> None:
    metric = ConstantMetric()
    value = metric.compute(RunAggregate(), [])

    assert metric.name == "constant"
    assert value == 7


def test_latency_metric_builds_distribution() -> None:
    aggregate = RunAggregate(total_duration_ms=250, runs=2)
    result = LatencyMetric().compute(aggregate, [100.0, 200.0, 300.0, 400.0])

    assert result.avg == 125.0
    assert result.p95 == 385.0
    assert result.max == 400.0


def test_token_and_tool_metrics_are_available() -> None:
    aggregate = RunAggregate(
        runs=2,
        total_tokens=100,
        total_tool_calls=4,
        max_tool_calls=3,
        runs_with_tools=2,
    )

    assert TokenMetric().compute(aggregate, []).avg_per_run == 50.0
    assert ToolCallMetric().compute(aggregate, []).total == 4


def test_evaluation_collector_alias_points_to_evaluator() -> None:
    assert EvaluationCollector is Evaluator


def test_report_formatters_return_stable_shapes() -> None:
    summary = EvaluationSummary(runs=2, succeeded=1, success_rate=0.5)

    payload = EvaluationReport.as_dict(summary)
    markdown = EvaluationReport.as_markdown(summary)

    assert payload["runs"] == 2
    assert "| Runs | 2 |" in markdown


def test_empty_latency_is_zero() -> None:
    assert LatencyMetrics().max == 0.0
