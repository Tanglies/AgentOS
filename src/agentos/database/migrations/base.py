"""Migration model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered, idempotent SQL migration."""

    version: int
    name: str
    sql: str
    applied_at: datetime = field(default_factory=lambda: datetime.now(UTC))


__all__ = ["Migration"]
