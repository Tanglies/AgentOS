"""Small persistence-layer models shared by repositories."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SchemaMigration(BaseModel):
    """One row in the migration ledger."""

    version: int
    name: str
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Pagination(BaseModel):
    """Normalized pagination parameters."""

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


__all__ = ["Pagination", "SchemaMigration"]
