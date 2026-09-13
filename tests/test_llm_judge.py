"""Tests for optional LLM judge and regression comparison."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from agentos.evaluation import EvaluationCase, EvaluationRegression, EvaluationRun
from agentos.evaluation.evaluators import LLMJudgeEvaluator
from agentos.evaluation.models import EvaluationResult, EvaluationScore
from agentos.evaluation.runner import default_evaluators
from agentos.llm.base import CompletionOptions, LLMClient, LLMMessage, LLMResponse
from agentos.runtime.runtime import RunResult


class _JudgeClient(LLMClient):
    provider = "judge-test"

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        options: CompletionOptions | None = None,
    ) -> LLMResponse:
        del messages, options
        return LLMResponse(
            content='{"score": 0.9, "passed": true, "reason": "close enough"}',
            model="judge-test",
        )


def _run(output: str) -> RunResult:
    return RunResult(
        run_id="run_1",
        agent="assistant",
        output=output,
        messages=[],
    )


@pytest.mark.asyncio
async def test_llm_judge_returns_score() -> None:
    case = EvaluationCase(id="a", input="question", expected_output="expected")

    score = await LLMJudgeEvaluator(_JudgeClient()).evaluate(case, _run("actual"))

    assert score.passed is True
    assert score.score == 0.9
    assert score.reason == "close enough"


def test_judge_is_disabled_by_default() -> None:
    assert all(evaluator.name != "llm_judge" for evaluator in default_evaluators())


def _evaluation_run(run_id: str, score: float, latency: float, tokens: int) -> EvaluationRun:
    return EvaluationRun(
        id=run_id,
        workspace_id=1,
        dataset_name="data",
        cases=[EvaluationCase(id="a", input="q")],
        results=[
            EvaluationResult(
                case_id="a",
                agent="assistant",
                input="q",
                output="a",
                latency_ms=latency,
                token_usage={"total_tokens": tokens},
                scores=[
                    EvaluationScore(
                        metric="exact_match",
                        score=score,
                        passed=score >= 0.5,
                    )
                ],
            )
        ],
    )


def test_regression_comparison() -> None:
    baseline = _evaluation_run("base", 0.5, 100.0, 100)
    candidate = _evaluation_run("candidate", 0.8, 80.0, 120)

    result = EvaluationRegression.compare(baseline, candidate)

    assert result["score_delta"]["absolute"] == 0.3
    assert result["latency_delta"]["absolute"] == -20.0
    assert result["token_delta"]["absolute"] == 20.0
