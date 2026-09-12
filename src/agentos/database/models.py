"""Small persistence-layer models shared by repositories."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.tenancy import DEFAULT_WORKSPACE_ID


class SchemaMigration(BaseModel):
    """One row in the migration ledger."""

    version: int
    name: str
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Pagination(BaseModel):
    """Normalized pagination parameters."""

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class AgentRecord(BaseModel):
    """Persisted Agent representation with lifecycle metadata."""

    id: int | None = None
    workspace_id: int = DEFAULT_WORKSPACE_ID
    name: str
    description: str = ""
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_iterations: int | None = None
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = ["AgentRecord", "Pagination", "SchemaMigration"]
