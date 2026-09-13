"""Structural tests for production container files."""

from __future__ import annotations

from pathlib import Path


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_dockerfile_is_multistage_non_root_and_does_not_copy_workspace() -> None:
    text = _text("Dockerfile")

    assert "FROM python:3.11-slim AS builder" in text
    assert "FROM python:3.11-slim AS runtime" in text
    assert "USER agentos" in text
    assert "HEALTHCHECK" in text
    assert "COPY . ." not in text
    assert "COPY .env " not in text


def test_dockerignore_excludes_secrets_and_runtime_data() -> None:
    text = _text(".dockerignore")

    for item in (".env", ".agentos", ".git", ".venv", "*.db"):
        assert item in text


def test_compose_persists_sqlite_volume_and_health_port() -> None:
    text = _text("docker-compose.yml")

    assert "agentos-data:/app/.agentos" in text
    assert '"8000:8000"' in text
    assert 'AGENTOS_TOOLS__ALLOW_SHELL: "false"' in text


def test_ci_runs_quality_and_container_build_without_real_models() -> None:
    text = _text(".github/workflows/ci.yml")

    assert 'python-version: "3.11"' in text
    assert "python -m ruff check ." in text
    assert "python -m pytest" in text
    assert "docker build -t agentos:ci ." in text
    assert "AGENTOS_LLM__PROVIDER: echo" in text
    assert "secrets." not in text
