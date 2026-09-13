"""Exact output matching evaluator."""

from __future__ import annotations

from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.runtime.runtime import RunResult


class ExactMatchEvaluator(Evaluator):
    """Compare the final output with an expected value."""

    name = "exact_match"

    def __init__(self, *, case_sensitive: bool = False) -> None:
        self.case_sensitive = case_sensitive

    def _normalize(self, value: str) -> str:
        text = " ".join(value.strip().split())
        return text if self.case_sensitive else text.casefold()

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
        passed = expected == actual
        return EvaluationScore(
            metric=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason="exact output match" if passed else "output differs",
            metadata={"expected": case.expected_output, "actual": run_result.output},
        )


__all__ = ["ExactMatchEvaluator"]
