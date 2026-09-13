"""Concurrent Evaluation runner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from agentos.core.exceptions import AgentOSError
from agentos.evaluation.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    ForbiddenToolEvaluator,
    RuleEvaluator,
    ToolCallEvaluator,
    extract_actual_tools,
)
from agentos.evaluation.evaluators.base import Evaluator
from agentos.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationStatus,
)
from agentos.runtime.runtime import AgentRuntime


def default_evaluators() -> list[Evaluator]:
    """Return the default rule-based evaluator set."""
    return [
        ExactMatchEvaluator(),
        ContainsEvaluator(),
        ToolCallEvaluator(),
        ForbiddenToolEvaluator(),
        RuleEvaluator(),
    ]


class EvaluationRunner:
    """Execute a dataset through AgentRuntime and score every case."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        evaluators: list[Evaluator] | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self._runtime = runtime
        self._evaluators = evaluators or default_evaluators()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(
        self,
        dataset: EvaluationDataset,
        *,
        run_id: str,
        workspace_id: int,
        user_id: int | None = None,
        on_result: Callable[[EvaluationRun], None] | None = None,
    ) -> EvaluationRun:
        """Run all cases with bounded concurrency."""
        run = EvaluationRun(
            id=run_id,
            workspace_id=workspace_id,
            user_id=user_id,
            dataset_name=dataset.name,
            dataset_path=dataset.source,
            cases=list(dataset.cases),
            status=EvaluationStatus.RUNNING,
            total_cases=len(dataset.cases),
            started_at=datetime.now(UTC),
        )
        tasks = [self._run_case(run, case) for case in dataset.cases]
        results = await asyncio.gather(*tasks)
        run.results = list(results)
        run.completed_cases = len(results)
        run.passed_cases = sum(1 for result in results if result.passed)
        run.failed_cases = run.completed_cases - run.passed_cases
        run.status = EvaluationStatus.COMPLETED
        run.finished_at = datetime.now(UTC)
        if on_result is not None:
            on_result(run)
        return run

    async def _run_case(self, run: EvaluationRun, case: EvaluationCase) -> EvaluationResult:
        async with self._semaphore:
            try:
                session_id = case.metadata.get("session_id")
                result = await self._runtime.run(
                    case.agent or self._runtime.settings.default_agent,
                    case.input,
                    session_id=session_id,
                    stateless=session_id is None,
                )
                scores = [
                    await evaluator.evaluate(case, result) for evaluator in self._evaluators
                ]
                return EvaluationResult(
                    case_id=case.id,
                    agent=result.agent,
                    input=case.input,
                    output=result.output,
                    run_id=result.run_id,
                    actual_tools=extract_actual_tools(result),
                    messages=list(result.messages),
                    latency_ms=result.duration_ms,
                    token_usage=result.usage,
                    scores=scores,
                )
            except Exception as exc:  # noqa: BLE001 - a case failure must not fail the dataset
                return EvaluationResult(
                    case_id=case.id,
                    agent=case.agent or self._runtime.settings.default_agent,
                    input=case.input,
                    status=EvaluationStatus.FAILED,
                    error=(
                        str(exc)
                        if isinstance(exc, AgentOSError)
                        else f"{type(exc).__name__}: {exc}"
                    ),
                )


__all__ = ["EvaluationRunner", "default_evaluators"]
