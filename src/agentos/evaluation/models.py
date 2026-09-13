"""Evaluation 2.0 domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agentos.llm.base import TokenUsage
from agentos.runtime.message import Message


class EvaluationStatus(StrEnum):
    """Lifecycle status for an Evaluation run."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class EvaluationCase(BaseModel):
    """One benchmark case."""

    id: str = Field(min_length=1, max_length=128)
    name: str = ""
    input: str = Field(min_length=1, max_length=32_000)
    agent: str | None = Field(default=None, max_length=64)
    expected_output: str | None = None
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationDataset(BaseModel):
    """An ordered collection of Evaluation cases."""

    name: str = "default"
    cases: list[EvaluationCase] = Field(default_factory=list)
    source: str | None = None

    @classmethod
    def from_jsonl(cls, path: str | Path, *, name: str | None = None) -> EvaluationDataset:
        """Load a dataset from JSONL."""
        from agentos.evaluation.dataset import load_jsonl

        resolved = Path(path).expanduser()
        return cls(
            name=name or resolved.stem,
            cases=load_jsonl(resolved),
            source=str(resolved),
        )


class EvaluationScore(BaseModel):
    """Score returned by one Evaluator."""

    metric: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    applicable: bool = True
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Result and scores for one Evaluation Case."""

    case_id: str
    agent: str
    input: str
    output: str = ""
    run_id: str | None = None
    status: EvaluationStatus = EvaluationStatus.COMPLETED
    error: str | None = None
    actual_tools: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    latency_ms: float = 0.0
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    tool_error_count: int = 0
    tool_timeout_count: int = 0
    llm_call_count: int = 0
    llm_error_count: int = 0
    memory_recall_count: int = 0
    memory_context_chars: int = 0
    estimated_cost: float | None = None
    max_iterations_reached: bool = False
    scores: list[EvaluationScore] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        """Pass when all applicable scores pass."""
        applicable = [score for score in self.scores if score.applicable]
        return bool(applicable) and all(score.passed for score in applicable)

    @property
    def average_score(self) -> float:
        """Average score across applicable evaluators."""
        applicable = [score for score in self.scores if score.applicable]
        if not applicable:
            return 0.0
        return round(sum(score.score for score in applicable) / len(applicable), 4)


class EvaluationRun(BaseModel):
    """A persisted evaluation run."""

    id: str
    workspace_id: int
    user_id: int | None = None
    dataset_name: str
    dataset_path: str | None = None
    cases: list[EvaluationCase] = Field(default_factory=list)
    status: EvaluationStatus = EvaluationStatus.QUEUED
    total_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    config: dict[str, Any] = Field(default_factory=dict)
    results: list[EvaluationResult] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
