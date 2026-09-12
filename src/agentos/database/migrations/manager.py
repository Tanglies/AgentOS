"""Migration runner used by database managers and tests."""

from __future__ import annotations

from agentos.database.migrations.base import Migration


class MigrationRunner:
    """Apply a migration sequence to a :class:`Database` instance."""

    def __init__(self, database: object, migrations: list[Migration] | None = None) -> None:
        self._database = database
        self._migrations = migrations

    def pending(self) -> list[Migration]:
        """Return migrations not yet recorded in the ledger."""
        if self._migrations is None:
            return []
        with self._database.connect() as conn:  # type: ignore[attr-defined]
            applied = {
                int(row["version"])
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
        return [item for item in self._migrations if item.version not in applied]

    def apply(self) -> list[int]:
        """Apply pending migrations and return their versions."""
        pending = self.pending()
        if not pending:
            return []
        with self._database.connect() as conn:  # type: ignore[attr-defined]
            for migration in sorted(pending, key=lambda item: item.version):
                conn.executescript(migration.sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.applied_at.isoformat(),
                    ),
                )
        return [item.version for item in pending]


__all__ = ["MigrationRunner"]
