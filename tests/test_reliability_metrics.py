"""Reliability metric calculations shared by Dashboard and Evaluation."""

from __future__ import annotations

from agentos.runtime.repositories import RunAggregate


def test_reliability_rates_are_derived_from_denominators() -> None:
    aggregate = RunAggregate(
        runs=4,
        succeeded=2,
        failed=1,
        cancelled=1,
        total_tool_calls=10,
        tool_errors=2,
        tool_timeouts=1,
        llm_calls=8,
        llm_errors=2,
        max_iteration_runs=1,
    )

    metrics = aggregate.reliability

    assert metrics.timeout_rate == 0.1
    assert metrics.tool_error_rate == 0.2
    assert metrics.llm_error_rate == 0.25
    assert metrics.max_iteration_rate == 0.25
    assert metrics.cancelled_rate == 0.25


def test_reliability_rates_are_safe_with_empty_history() -> None:
    metrics = RunAggregate().reliability

    assert metrics.timeout_rate == 0.0
    assert metrics.tool_error_rate == 0.0
    assert metrics.llm_error_rate == 0.0
    assert metrics.max_iteration_rate == 0.0
    assert metrics.cancelled_rate == 0.0
