"""Run repository compatibility facade."""

from agentos.runtime.repositories import (
    RUNS_SCHEMA,
    RunAggregate,
    RunRecord,
    RunRepository,
    RunStatus,
)

__all__ = [
    "RUNS_SCHEMA",
    "RunAggregate",
    "RunRecord",
    "RunRepository",
    "RunStatus",
]
