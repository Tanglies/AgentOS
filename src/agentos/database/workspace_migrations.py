"""Incremental migrations for tenant-aware resource tables."""

from __future__ import annotations

from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.database.connection import Database


def ensure_workspace_columns(
    database: Database,
    table: str,
    *,
    include_user: bool = True,
    backfill: str | None = None,
) -> None:
    """Add tenant columns to an existing table and backfill default values."""
    columns = {"workspace_id": "INTEGER NOT NULL DEFAULT 1"}
    if include_user:
        columns["user_id"] = "INTEGER"
    statement = backfill or (
        f"UPDATE {table} SET workspace_id = {DEFAULT_WORKSPACE_ID} "
        "WHERE workspace_id IS NULL"
    )
    if include_user:
        statement += (
            f"; UPDATE {table} SET user_id = {DEFAULT_USER_ID} "
            "WHERE user_id IS NULL"
        )
    database.ensure_columns(table, columns, backfill=statement)


__all__ = ["ensure_workspace_columns"]
