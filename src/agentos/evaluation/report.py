"""Human- and machine-readable evaluation reports."""

from __future__ import annotations

from typing import Any

from agentos.evaluation.metrics import EvaluationSummary


class EvaluationReport:
    """Format an evaluation summary without changing the API response model."""

    @staticmethod
    def as_dict(summary: EvaluationSummary) -> dict[str, Any]:
        """Return a JSON-serializable report dictionary."""
        return summary.model_dump(mode="json")

    @staticmethod
    def as_markdown(summary: EvaluationSummary) -> str:
        """Render a compact Markdown report."""
        return (
            "| Metric | Value |\n"
            "| --- | ---: |\n"
            f"| Runs | {summary.runs} |\n"
            f"| Success rate | {summary.success_rate:.2%} |\n"
            f"| Avg latency (ms) | {summary.latency.avg:.3f} |\n"
            f"| P95 latency (ms) | {summary.latency.p95:.3f} |\n"
            f"| Total tokens | {summary.tokens.total} |\n"
            f"| Tool calls | {summary.tool_calls.total} |\n"
        )


__all__ = ["EvaluationReport"]
