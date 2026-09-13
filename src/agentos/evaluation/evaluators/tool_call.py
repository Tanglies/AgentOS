"""Tool trajectory evaluators."""

from __future__ import annotations

from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.runtime.runtime import RunResult


def extract_actual_tools(run_result: RunResult) -> list[str]:
    """Extract real Tool calls from the runtime message trajectory."""
    tools: list[str] = []
    for message in run_result.messages:
        for tool_call in message.tool_calls or []:
            tools.append(tool_call.name)
    return tools


class ToolCallEvaluator(Evaluator):
    """Check that every expected Tool appears in the real trajectory."""

    name = "tool_call"

    def __init__(self, *, ordered: bool = False) -> None:
        self.ordered = ordered

    async def evaluate(
        self, case: EvaluationCase, run_result: RunResult
    ) -> EvaluationScore:
        if not case.expected_tools:
            return EvaluationScore(
                metric=self.name,
                score=1.0,
                passed=True,
                applicable=False,
                reason="expected_tools is not set",
            )
        actual = extract_actual_tools(run_result)
        expected = list(case.expected_tools)
        if self.ordered:
            matched = sum(1 for a, e in zip(actual, expected, strict=False) if a == e)
            passed = actual[: len(expected)] == expected
            missing = [tool for tool in expected if tool not in actual]
        else:
            actual_set = set(actual)
            missing = [tool for tool in expected if tool not in actual_set]
            matched = len(expected) - len(missing)
            passed = not missing
        score = matched / len(expected)
        return EvaluationScore(
            metric=self.name,
            score=round(score, 4),
            passed=passed,
            reason="expected tools were called" if passed else "missing expected tools",
            metadata={"expected": expected, "actual": actual, "missing": missing},
        )


class ForbiddenToolEvaluator(Evaluator):
    """Check that forbidden Tools never appear in the trajectory."""

    name = "forbidden_tool"

    async def evaluate(
        self, case: EvaluationCase, run_result: RunResult
    ) -> EvaluationScore:
        if not case.forbidden_tools:
            return EvaluationScore(
                metric=self.name,
                score=1.0,
                passed=True,
                applicable=False,
                reason="forbidden_tools is not set",
            )
        actual = extract_actual_tools(run_result)
        used = [tool for tool in case.forbidden_tools if tool in actual]
        passed = not used
        return EvaluationScore(
            metric=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason="no forbidden tool called" if passed else "forbidden tool called",
            metadata={"forbidden": case.forbidden_tools, "used": used, "actual": actual},
        )


__all__ = ["ForbiddenToolEvaluator", "ToolCallEvaluator", "extract_actual_tools"]
