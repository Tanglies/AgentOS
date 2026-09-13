"""Evaluation regression comparison."""

from __future__ import annotations

from typing import Any

from agentos.evaluation.models import EvaluationRun
from agentos.evaluation.report import EvaluationReportBuilder


class EvaluationRegression:
    """Compare baseline and candidate evaluation reports."""

    @staticmethod
    def compare(baseline: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
        """Return absolute and relative deltas for quality and cost metrics."""
        before = EvaluationReportBuilder.build(baseline)
        after = EvaluationReportBuilder.build(candidate)
        return {
            "baseline": before,
            "candidate": after,
            "pass_rate_delta": _delta(before["pass_rate"], after["pass_rate"]),
            "score_delta": _delta(before["average_score"], after["average_score"]),
            "latency_delta": _delta(
                before["average_latency"], after["average_latency"]
            ),
            "token_delta": _delta(before["average_tokens"], after["average_tokens"]),
            "tool_accuracy_delta": _delta(
                before["tool_accuracy"], after["tool_accuracy"]
            ),
        }


def _delta(before: float, after: float) -> dict[str, float]:
    absolute = round(after - before, 4)
    relative = round(absolute / before, 4) if before else 0.0
    return {"absolute": absolute, "relative": relative}


__all__ = ["EvaluationRegression"]
