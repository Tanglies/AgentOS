"""Expected substring evaluator."""

from __future__ import annotations

from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.runtime.runtime import RunResult


class ContainsEvaluator(Evaluator):
    """Check that the expected output occurs in the actual output."""

    name = "contains"

    def __init__(self, *, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def _normalize(self, value: str) -> str:
        return value if self.case_sensitive else value.casefold()

    async def evaluate(
        self, case: EvaluationCase, run_result: RunResult
    ) -> EvaluationScore:
        if case.expected_output is None:
            return EvaluationScore(
                metric=self.name,
                score=1.0,
                passed=True,
                applicable=False,
                reason="expected_output is not set",
            )
        expected = self._normalize(case.expected_output)
        actual = self._normalize(run_result.output)
        passed = expected in actual
        return EvaluationScore(
            metric=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason="expected text found" if passed else "expected text missing",
            metadata={"expected": case.expected_output, "actual": run_result.output},
        )


__all__ = ["ContainsEvaluator"]
