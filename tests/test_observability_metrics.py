"""Prometheus metrics tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentos.api.app import create_app
from agentos.core.config import Settings
from agentos.observability.metrics import (
    configure_metrics,
    record_llm,
    record_run,
    record_tool,
    render_metrics,
)


def test_metrics_are_not_rendered_when_disabled() -> None:
    configure_metrics(Settings(_env_file=None).observability)

    assert render_metrics().find(b"agentos_runs_total") == -1


def test_metric_names_and_low_cardinality_labels() -> None:
    configure_metrics(
        Settings(
            _env_file=None,
            observability={"prometheus_enabled": True},
        ).observability
    )
    record_run(
        agent="assistant",
        status="completed",
        duration_seconds=0.2,
    )
    record_llm(
        model="echo",
        status="success",
        duration_seconds=0.1,
        prompt_tokens=10,
        completion_tokens=5,
    )
    record_tool(tool="calculate", status="success", duration_seconds=0.01)

    body = render_metrics().decode("utf-8")

    assert "agentos_runs_total" in body
    assert "agentos_run_duration_seconds" in body
    assert "agentos_llm_tokens_total" in body
    assert "agentos_tool_calls_total" in body
    assert 'run_id=' not in body
    assert 'user_id=' not in body


def _app(tmp_path: Path, *, enabled: bool):
    return create_app(
        Settings(
            _env_file=None,
            llm={"provider": "echo"},
            logging={"level": "ERROR"},
            observability={"prometheus_enabled": enabled},
            registry={"persist": False},
            runs={"db_path": str(tmp_path / "runs.db")},
            memory={"long_term_db_path": str(tmp_path / "memory.db")},
        )
    )


def test_metrics_endpoint_enabled(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, enabled=True)) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "agentos_runs_total" in response.text


def test_metrics_endpoint_disabled(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, enabled=False)) as client:
        response = client.get("/metrics")

    assert response.status_code == 404
