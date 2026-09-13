"""SQLite connection and schema migration management.

Every operation opens one short-lived connection. This keeps the local
single-process platform simple and sidesteps SQLite's thread affinity rules.
The manager also creates the parent directory on demand and recreates the
schema when the database file was removed while the process is running.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentos.database.migrations.base import Migration

MIGRATION_TABLE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS schema_migrations (\n"
    "    version INTEGER PRIMARY KEY,\n"
    "    name TEXT NOT NULL,\n"
    "    applied_at TEXT NOT NULL\n"
    ");\n"
)


class Database:
    """A SQLite database with optional schema and ordered migrations."""

    def __init__(
        self,
        path: str | Path,
        *,
        schema: str = "",
        migrations: Sequence[Migration] = (),
    ) -> None:
        self.path = Path(path).expanduser()
        self._schema = schema
        self._migrations = tuple(migrations)
        # Fail early for an unwritable path instead of on the first query.
        with self.connect():
            pass

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection and commit or roll back on exit."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists()
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                if is_new and self._schema:
                    conn.executescript(self._schema)
                conn.executescript(MIGRATION_TABLE_SCHEMA)
                self._apply_migrations(conn)
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        """Initialize the database and ensure the configured schema exists."""
        with self.connect():
            pass

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction scope for an atomic multi-statement operation."""
        with self.connect() as connection, connection:
            yield connection

    def ensure_columns(
        self,
        table: str,
        columns: dict[str, str],
        *,
        backfill: str | None = None,
    ) -> None:
        """Add missing columns to an existing SQLite table.

        SQLite does not support ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``.
        This helper keeps the new canonical schema compatible with databases
        created by earlier AgentOS versions.
        """
        with self.connect() as connection:
            existing = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                    )
            if backfill:
                connection.executescript(backfill)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a write statement and return the affected row count."""
        from agentos.observability.tracing import start_span

        with start_span(
            "repository.query",
            attributes={"db.system": "sqlite", "db.operation": sql.split(maxsplit=1)[0]},
        ):
            with self.connect() as conn:
                cursor = conn.execute(sql, params)
            return max(0, cursor.rowcount)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """Execute a query and return all rows."""
        from agentos.observability.tracing import start_span

        with start_span(
            "repository.query",
            attributes={"db.system": "sqlite", "db.operation": sql.split(maxsplit=1)[0]},
        ), self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        """Execute a query and return the first row, if any."""
        from agentos.observability.tracing import start_span

        with start_span(
            "repository.query",
            attributes={"db.system": "sqlite", "db.operation": sql.split(maxsplit=1)[0]},
        ), self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def execute_script(self, script: str) -> None:
        """Execute a multi-statement SQL script."""
        from agentos.observability.tracing import start_span

        with start_span(
            "repository.query",
            attributes={"db.system": "sqlite", "db.operation": "script"},
        ), self.connect() as conn:
            conn.executescript(script)

    def applied_migrations(self) -> list[int]:
        """Return applied migration versions in ascending order."""
        rows = self.query(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        return [int(row["version"]) for row in rows]

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Create the ledger and apply each pending migration exactly once."""
        if not self._migrations:
            return
        applied = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in sorted(self._migrations, key=lambda item: item.version):
            if migration.version in applied:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.applied_at.isoformat()),
            )
            applied.add(migration.version)


class DatabaseManager(Database):
    """Named facade used by the database package and application wiring."""


__all__ = ["Database", "DatabaseManager"]
