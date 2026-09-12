"""Tests for the canonical database package and migrations."""

from __future__ import annotations

from pathlib import Path

from agentos.core.database import Database as LegacyDatabase
from agentos.database import Database, DatabaseManager, Migration, MigrationRunner


def test_database_manager_creates_schema_and_ledger(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "x.db", schema="CREATE TABLE t (id INTEGER);")

    db.execute("INSERT INTO t (id) VALUES (1)")

    assert db.query_one("SELECT COUNT(*) AS n FROM t")["n"] == 1
    assert db.applied_migrations() == []


def test_database_migrations_are_applied_once(tmp_path: Path) -> None:
    migrations = [
        Migration(1, "create-widgets", "CREATE TABLE widgets (id INTEGER);"),
        Migration(2, "add-name", "ALTER TABLE widgets ADD COLUMN name TEXT;"),
    ]
    db = Database(tmp_path / "x.db", migrations=migrations)

    db.execute("INSERT INTO widgets (name) VALUES ('one')")

    assert db.applied_migrations() == [1, 2]
    assert db.query_one("SELECT name FROM widgets")["name"] == "one"


def test_database_migrations_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    migration = Migration(1, "create", "CREATE TABLE t (id INTEGER);")
    first = Database(path, migrations=[migration])
    first.execute("INSERT INTO t (id) VALUES (1)")

    second = Database(path, migrations=[migration])

    assert second.applied_migrations() == [1]
    assert second.query_one("SELECT COUNT(*) AS n FROM t")["n"] == 1


def test_migration_runner_reports_pending_then_applies(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    runner = MigrationRunner(
        db,
        [Migration(1, "create", "CREATE TABLE t (id INTEGER);")],
    )

    pending = runner.pending()
    assert [(item.version, item.name, item.sql) for item in pending] == [
        (1, "create", "CREATE TABLE t (id INTEGER);")
    ]
    assert runner.apply() == [1]
    assert runner.pending() == []


def test_core_database_path_remains_compatible(tmp_path: Path) -> None:
    assert LegacyDatabase is Database
    legacy = LegacyDatabase(tmp_path / "legacy.db")
    assert isinstance(legacy, Database)
