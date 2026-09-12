"""Evaluation 指标测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.core.database import Database
from agentos.runtime.evaluation import Evaluator, percentile
from agentos.runtime.repositories import RUNS_SCHEMA, RunRecord, RunRepository, RunStatus

NOW = datetime(2026, 9, 12, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> RunRepository:
    return RunRepository(Database(tmp_path / "runs.db", schema=RUNS_SCHEMA))


def _add(
    repo: RunRepository,
    index: int,
    *,
    agent: str = "assistant",
    status: RunStatus = RunStatus.COMPLETED,
    duration_ms: float = 100.0,
    tokens: int = 10,
    tools: int = 0,
) -> None:
    repo.add(
        RunRecord(
            run_id=f"run_{index}",
            agent=agent,
            status=status,
            duration_ms=duration_ms,
            prompt_tokens=tokens,
            completion_tokens=tokens // 2,
            total_tokens=tokens + tokens // 2,
            tool_call_count=tools,
            created_at=NOW + timedelta(seconds=index),
        )
    )


# --- 分位数工具 -----------------------------------------------------------


def test_percentile_handles_empty_input() -> None:
    assert percentile([], 0.5) == 0.0


def test_percentile_handles_single_value() -> None:
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_uses_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 0.5) == 3.0
    assert percentile(values, 1.0) == 5.0
    assert percentile(values, 0.25) == 2.0


# --- 空数据集 -------------------------------------------------------------


def test_empty_summary_is_all_zeros(runs: RunRepository) -> None:
    summary = Evaluator(runs).summarize()

    assert summary.runs == 0
    assert summary.success_rate == 0.0
    assert summary.latency.avg == 0.0
    assert summary.latency.p95 == 0.0
    assert summary.tokens.total == 0
    assert summary.tool_calls.total == 0


# --- 各指标 ---------------------------------------------------------------


def test_summary_counts_runs_and_success_rate(runs: RunRepository) -> None:
    _add(runs, 1)
    _add(runs, 2)
    _add(runs, 3, status=RunStatus.FAILED)

    summary = Evaluator(runs).summarize()

    assert summary.runs == 3
    assert summary.succeeded == 2
    assert summary.failed == 1
    assert summary.success_rate == pytest.approx(2 / 3, abs=1e-4)


def test_summary_reports_latency_distribution(runs: RunRepository) -> None:
    for index, duration in enumerate([100.0, 200.0, 300.0, 400.0], start=1):
        _add(runs, index, duration_ms=duration)

    latency = Evaluator(runs).summarize().latency

    assert latency.avg == 250.0
    assert latency.p50 == 250.0
    assert latency.p95 == 385.0
    assert latency.max == 400.0


def test_summary_reports_token_usage(runs: RunRepository) -> None:
    _add(runs, 1, tokens=10)
    _add(runs, 2, tokens=20)

    tokens = Evaluator(runs).summarize().tokens

    assert tokens.prompt == 30
    assert tokens.completion == 15
    assert tokens.total == 45
    assert tokens.avg_per_run == 22.5


def test_summary_reports_tool_calls(runs: RunRepository) -> None:
    _add(runs, 1, tools=0)
    _add(runs, 2, tools=2)
    _add(runs, 3, tools=4)

    tools = Evaluator(runs).summarize().tool_calls

    assert tools.total == 6
    assert tools.avg_per_run == 2.0
    assert tools.max_in_run == 4
    assert tools.runs_with_tools == 2


def test_summary_can_scope_to_one_agent(runs: RunRepository) -> None:
    _add(runs, 1, agent="assistant")
    _add(runs, 2, agent="assistant", status=RunStatus.FAILED)
    _add(runs, 3, agent="researcher")

    summary = Evaluator(runs).summarize(agent="assistant")

    assert summary.runs == 2
    assert summary.agent == "assistant"
    assert summary.success_rate == 0.5


def test_summary_can_scope_by_time(runs: RunRepository) -> None:
    _add(runs, 1)
    _add(runs, 2)
    _add(runs, 3)

    # 只要第 3 条（NOW + 3s）之后
    summary = Evaluator(runs).summarize(since=NOW + timedelta(seconds=3))

    assert summary.runs == 1


def test_summary_records_generation_time(runs: RunRepository) -> None:
    assert Evaluator(runs).summarize().generated_at is not None


# --- API ------------------------------------------------------------------


def _app(tmp_path: Path, *, enabled: bool = True) -> object:
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            runs={"enabled": enabled, "db_path": str(tmp_path / "runs.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
            registry={"persist": False},
        )
    )


def test_api_summary_reflects_recorded_runs(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for text in ("a", "b"):
            client.post("/api/v1/runs", json={"input": text})

        body = client.get("/api/v1/evaluation/summary").json()

    assert body["runs"] == 2
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert body["success_rate"] == 1.0
    assert body["tokens"]["total"] > 0


def test_api_summary_on_empty_history(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        body = client.get("/api/v1/evaluation/summary").json()

    assert body["runs"] == 0
    assert body["success_rate"] == 0.0
    assert body["latency"]["avg"] == 0.0


def test_api_summary_filters_by_agent(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/v1/runs", json={"input": "a"})
        matching = client.get("/api/v1/evaluation/summary?agent=assistant").json()
        missing = client.get("/api/v1/evaluation/summary?agent=ghost").json()

    assert matching["runs"] == 1
    assert missing["runs"] == 0


def test_api_summary_requires_run_history(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, enabled=False)) as client:
        response = client.get("/api/v1/evaluation/summary")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_openapi_exposes_evaluation_route(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        schema = client.get("/openapi.json").json()

    assert "/api/v1/evaluation/summary" in schema["paths"]