"""Platform database storing users, Workspaces, and memberships."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentos.core.config import PlatformSettings
from agentos.core.tenancy import (
    DEFAULT_DISPLAY_NAME,
    DEFAULT_USER_ID,
    DEFAULT_USERNAME,
    DEFAULT_WORKSPACE_ID,
    DEFAULT_WORKSPACE_NAME,
)
from agentos.database.connection import Database
from agentos.runtime.platform_repositories import (
    PLATFORM_SCHEMA,
    UserRecord,
    UserRepository,
    UserStatus,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRole,
)


class PlatformStore:
    """Platform metadata store with a deterministic default tenant."""

    def __init__(self, settings: PlatformSettings | None = None) -> None:
        self._settings = settings or PlatformSettings()
        self.path = Path(self._settings.db_path).expanduser()
        self._db = Database(self.path, schema=PLATFORM_SCHEMA)
        self.users = UserRepository(self._db)
        self.workspaces = WorkspaceRepository(self._db)
        self.members = WorkspaceMemberRepository(self._db)
        self._ensure_default_tenant()

    def _ensure_default_tenant(self) -> None:
        now = datetime.now(UTC)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users "
                "(id, username, display_name, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    DEFAULT_USER_ID,
                    DEFAULT_USERNAME,
                    DEFAULT_DISPLAY_NAME,
                    UserStatus.ACTIVE.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO workspaces "
                "(id, name, owner_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    DEFAULT_WORKSPACE_ID,
                    DEFAULT_WORKSPACE_NAME,
                    DEFAULT_USER_ID,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO workspace_members "
                "(workspace_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                (
                    DEFAULT_WORKSPACE_ID,
                    DEFAULT_USER_ID,
                    WorkspaceRole.OWNER.value,
                    now.isoformat(),
                ),
            )

    @property
    def database(self) -> Database:
        """Expose the shared platform database for repository construction."""
        return self._db


__all__ = [
    "PlatformStore",
    "UserRecord",
    "UserRepository",
    "UserStatus",
    "WorkspaceMemberRecord",
    "WorkspaceMemberRepository",
    "WorkspaceRecord",
    "WorkspaceRepository",
    "WorkspaceRole",
]
