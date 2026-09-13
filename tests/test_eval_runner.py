"""Evaluation runner, persistence, and report tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import EvaluationSettings, Settings
from agentos.evaluation import (
    ContainsEvaluator,
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
)
from agentos.evaluation.report import EvaluationReportBuilder
from agentos.evaluation.runner import EvaluationRunner
from agentos.evaluation.store import EvaluationStore
from agentos.llm.echo import EchoLLMClient
from agentos.runtime.runtime import AgentRuntime


def _dataset() -> EvaluationDataset:
    return EvaluationDataset(
        name="small",
        cases=[
            EvaluationCase(id="a", input="hello", expected_output="hello"),
            EvaluationCase(id="b", input="world", expected_output="world"),
        ],
    )


async def test_runner_executes_cases_with_evaluators() -> None:
    runtime = AgentRuntime(EchoLLMClient(prefix=""))
    runner = EvaluationRunner(
        runtime,
        evaluators=[ContainsEvaluator()],
        max_concurrency=2,
    )

    run = await runner.run(
        _dataset(),
        run_id="eval_1",
        workspace_id=1,
        user_id=1,
    )

    assert run.status.value == "completed"
    assert run.passed_cases == 2
    assert run.failed_cases == 0
    assert all(result.scores for result in run.results)
    await runtime.aclose()


def test_report_aggregates_scores() -> None:
    from agentos.evaluation.models import EvaluationResult, EvaluationScore

    run = EvaluationRun(
        id="eval_1",
        workspace_id=1,
        dataset_name="small",
        cases=_dataset().cases,
        results=[
            EvaluationResult(
                case_id="a",
                agent="assistant",
                input="hello",
                output="hello",
                scores=[EvaluationScore(metric="contains", score=1.0, passed=True)],
            ),
            EvaluationResult(
                case_id="b",
                agent="assistant",
                input="world",
                output="nope",
                scores=[EvaluationScore(metric="contains", score=0.0, passed=False)],
            ),
        ],
    )

    report = EvaluationReportBuilder.build(run)

    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["pass_rate"] == 0.5
    assert report["by_evaluator"]["contains"]["average_score"] == 0.5


def test_evaluation_store_is_workspace_scoped(tmp_path: Path) -> None:
    store = EvaluationStore(EvaluationSettings(db_path=str(tmp_path / "evals.db")))
    run = EvaluationRun(
        id="eval_1",
        workspace_id=1,
        dataset_name="small",
        cases=_dataset().cases,
    )
    store.save(run)

    assert store.get("eval_1", workspace_id=1) is not None
    assert store.get("eval_1", workspace_id=2) is None


def test_evaluation_api_runs_in_background(tmp_path: Path) -> None:
    dataset_root = tmp_path / "evals"
    dataset_root.mkdir()
    dataset = dataset_root / "small.jsonl"
    dataset.write_text(
        "\n".join(
            json.dumps({"id": "a", "input": "hello", "expected_output": "hello"})
            for _ in range(1)
        ),
        encoding="utf-8",
    )
    app = create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            evaluation={
                "db_path": str(tmp_path / "evals.db"),
                "dataset_root": str(dataset_root),
            },
            registry={"persist": False},
            runs={"db_path": str(tmp_path / "runs.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
        )
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/evaluations/run", json={"dataset": "small"})
        payload = response.json()
        for _ in range(30):
            detail = client.get(f"/api/v1/evaluations/{payload['id']}").json()
            if detail["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)

    assert response.status_code == 202
    assert detail["status"] == "completed"
    assert detail["report"]["total"] == 1
