"""Optional LLM-as-a-Judge evaluator."""

from __future__ import annotations

import json
import re

from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.models import EvaluationCase, EvaluationScore
from agentos.llm.base import CompletionOptions, LLMClient, LLMMessage
from agentos.runtime.runtime import RunResult

_SYSTEM_PROMPT = (
    "You are an evaluation judge. Return only strict JSON with keys "
    '"score" (0..1), "passed" (boolean), and "reason" (string). '
    "Compare the actual answer with the expected answer for the user input."
)


class LLMJudgeEvaluator(Evaluator):
    """Score open-ended answers with a configured LLM judge."""

    name = "llm_judge"

    def __init__(self, client: LLMClient, *, model: str | None = None) -> None:
        self._client = client
        self._model = model

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
        prompt = (
            f"User input:\n{case.input}\n\n"
            f"Expected answer:\n{case.expected_output}\n\n"
            f"Actual answer:\n{run_result.output}\n"
        )
        response = await self._client.complete(
            [
                LLMMessage.system(_SYSTEM_PROMPT),
                LLMMessage.user(prompt),
            ],
            options=CompletionOptions(model=self._model, temperature=0.0),
        )
        payload = self._parse(response.content)
        score = min(1.0, max(0.0, float(payload.get("score", 0.0))))
        passed = bool(payload.get("passed", score >= 0.5))
        return EvaluationScore(
            metric=self.name,
            score=score,
            passed=passed,
            reason=str(payload.get("reason", "")),
            metadata={"judge_model": response.model},
        )

    @staticmethod
    def _parse(content: str) -> dict[str, object]:
        cleaned = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fenced:
            cleaned = fenced.group(1)
        try:
            payload = json.loads(cleaned)
        except ValueError:
            return {"score": 0.0, "passed": False, "reason": "invalid judge output"}
        return payload if isinstance(payload, dict) else {"score": 0.0, "passed": False}


__all__ = ["LLMJudgeEvaluator"]
