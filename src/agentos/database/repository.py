"""Base class and shared helpers for repositories."""

from __future__ import annotations

from typing import Any

from agentos.database.connection import Database


class Repository:
    """Base repository holding a database connection factory."""

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        """Expose the backing database for diagnostics and tests."""
        return self._db


def build_filter(clauses: list[tuple[str, Any]]) -> tuple[str, tuple[Any, ...]]:
    """Build a parameterized ``WHERE`` clause from non-null pairs."""
    active = [(sql, value) for sql, value in clauses if value is not None]
    if not active:
        return "", ()
    where = "WHERE " + " AND ".join(sql for sql, _ in active)
    return where, tuple(value for _, value in active)


__all__ = ["Repository", "build_filter"]
