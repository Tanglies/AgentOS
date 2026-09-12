"""Compatibility import for the database package.

New code should import from :mod:`agentos.database`. The old
:mod:`agentos.core.database` path remains available for existing callers
and third-party integrations.
"""

from agentos.database.connection import Database, DatabaseManager

__all__ = ["Database", "DatabaseManager"]
