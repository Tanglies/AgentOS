"""Evaluator contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.runtime.runtime import RunResult


class Evaluator(ABC):
    """Score one Evaluation Case against an Agent run result."""

    name: str = "evaluator"

    @abstractmethod
    async def evaluate(
        self, case: EvaluationCase, run_result: RunResult
    ) -> EvaluationScore:
        """Return a score in the range 0.0 to 1.0."""


__all__ = ["Evaluator"]
