"""Human- and machine-readable evaluation reports."""

from __future__ import annotations

from typing import Any

from agentos.evaluation.metrics import EvaluationSummary
from agentos.evaluation.models import EvaluationResult, EvaluationRun


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


__all__ = ["EvaluationReport", "EvaluationReportBuilder"]


class EvaluationReportBuilder:
    """Build quality and regression reports for Evaluation runs."""

    @staticmethod
    def build(run: EvaluationRun) -> dict[str, Any]:
        """Aggregate case results by status, agent, tag, and evaluator."""
        results = run.results
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        failed = total - passed
        average_score = (
            round(sum(result.average_score for result in results) / total, 4)
            if total
            else 0.0
        )
        average_latency = (
            round(sum(result.latency_ms for result in results) / total, 3)
            if total
            else 0.0
        )
        average_tokens = (
            round(
                sum(result.token_usage.total_tokens for result in results) / total,
                2,
            )
            if total
            else 0.0
        )
        tool_scores = [
            score.score
            for result in results
            for score in result.scores
            if score.metric == "tool_call" and score.applicable
        ]
        tool_accuracy = (
            round(sum(tool_scores) / len(tool_scores), 4) if tool_scores else 0.0
        )
        report = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "average_score": average_score,
            "average_latency": average_latency,
            "average_tokens": average_tokens,
            "tool_accuracy": tool_accuracy,
            "by_agent": EvaluationReportBuilder._by_agent(results),
            "by_tag": EvaluationReportBuilder._by_tag(run),
            "by_evaluator": EvaluationReportBuilder._by_evaluator(results),
        }
        return report

    @staticmethod
    def _by_agent(results: list[EvaluationResult]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[EvaluationResult]] = {}
        for result in results:
            grouped.setdefault(result.agent, []).append(result)
        return {
            agent: EvaluationReportBuilder._summary(items)
            for agent, items in grouped.items()
        }

    @staticmethod
    def _by_tag(run: EvaluationRun) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[EvaluationResult]] = {}
        case_map = {case.id: case for case in getattr(run, "cases", [])}
        for result in run.results:
            case = case_map.get(result.case_id)
            for tag in case.tags if case is not None else ["untagged"]:
                grouped.setdefault(tag, []).append(result)
        return {
            tag: EvaluationReportBuilder._summary(items)
            for tag, items in grouped.items()
        }

    @staticmethod
    def _by_evaluator(results: list[EvaluationResult]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[float]] = {}
        for result in results:
            for score in result.scores:
                if score.applicable:
                    grouped.setdefault(score.metric, []).append(score.score)
        return {
            metric: {
                "count": len(scores),
                "average_score": round(sum(scores) / len(scores), 4),
            }
            for metric, scores in grouped.items()
        }

    @staticmethod
    def _summary(results: list[EvaluationResult]) -> dict[str, Any]:
        total = len(results)
        passed = sum(1 for result in results if result.passed)
        return {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
        }
