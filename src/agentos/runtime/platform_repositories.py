"""Persistence models and repositories for users and Workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentos.database.repository import Repository


class UserStatus(StrEnum):
    """Account lifecycle state."""

    ACTIVE = "active"
    DISABLED = "disabled"


class WorkspaceRole(StrEnum):
    """Membership roles ordered from most to least privileged."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    owner_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user
    ON workspace_members (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace
    ON workspace_members (workspace_id);
CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'general',
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    risk_level TEXT NOT NULL DEFAULT 'low',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_tools (
    workspace_id INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, tool_name)
);
CREATE TABLE IF NOT EXISTS agent_tools (
    workspace_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, agent_id, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_workspace_tools_workspace
    ON workspace_tools (workspace_id);
CREATE INDEX IF NOT EXISTS idx_agent_tools_agent
    ON agent_tools (workspace_id, agent_id);
"""


class UserRecord(BaseModel):
    """A platform user."""

    id: int | None = None
    username: str
    display_name: str = ""
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkspaceRecord(BaseModel):
    """A tenant Workspace."""

    id: int | None = None
    name: str
    owner_id: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkspaceMemberRecord(BaseModel):
    """A user's membership and role in a Workspace."""

    workspace_id: int
    user_id: int
    role: WorkspaceRole
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserRepository(Repository):
    """SQL access for ``users``."""

    @staticmethod
    def _to_record(row: Any) -> UserRecord:
        return UserRecord(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or ""),
            status=UserStatus(str(row["status"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def add(self, user: UserRecord) -> UserRecord:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users "
                "(username, display_name, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    user.username,
                    user.display_name,
                    user.status.value,
                    user.created_at.isoformat(),
                    user.updated_at.isoformat(),
                ),
            )
        return user.model_copy(update={"id": int(cursor.lastrowid or 0)})

    def get(self, user_id: int) -> UserRecord | None:
        row = self._db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._to_record(row) if row is not None else None

    def get_by_username(self, username: str) -> UserRecord | None:
        row = self._db.query_one("SELECT * FROM users WHERE username = ?", (username,))
        return self._to_record(row) if row is not None else None

    def list(self, *, limit: int = 100, offset: int = 0) -> list[UserRecord]:
        rows = self._db.query(
            "SELECT * FROM users ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
        )
        return [self._to_record(row) for row in rows]

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM users")
        return int(row["total"]) if row is not None else 0

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        status: UserStatus | None = None,
        updated_at: datetime | None = None,
    ) -> bool:
        assignments: list[str] = []
        params: list[Any] = []
        if display_name is not None:
            assignments.append("display_name = ?")
            params.append(display_name)
        if status is not None:
            assignments.append("status = ?")
            params.append(status.value)
        if updated_at is not None:
            assignments.append("updated_at = ?")
            params.append(updated_at.isoformat())
        if not assignments:
            return False
        params.append(user_id)
        return self._db.execute(
            f"UPDATE users SET {', '.join(assignments)} WHERE id = ?", params
        ) > 0


class WorkspaceRepository(Repository):
    """SQL access for ``workspaces`` and user-scoped listings."""

    @staticmethod
    def _to_record(row: Any) -> WorkspaceRecord:
        return WorkspaceRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            owner_id=int(row["owner_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def add(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO workspaces (name, owner_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    workspace.name,
                    workspace.owner_id,
                    workspace.created_at.isoformat(),
                    workspace.updated_at.isoformat(),
                ),
            )
        return workspace.model_copy(update={"id": int(cursor.lastrowid or 0)})

    def get(self, workspace_id: int) -> WorkspaceRecord | None:
        row = self._db.query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        return self._to_record(row) if row is not None else None

    def get_by_name(self, name: str) -> WorkspaceRecord | None:
        row = self._db.query_one("SELECT * FROM workspaces WHERE name = ?", (name,))
        return self._to_record(row) if row is not None else None

    def list_for_user(self, user_id: int) -> list[WorkspaceRecord]:
        rows = self._db.query(
            "SELECT w.* FROM workspaces w "
            "JOIN workspace_members m ON m.workspace_id = w.id "
            "WHERE m.user_id = ? ORDER BY w.name",
            (user_id,),
        )
        return [self._to_record(row) for row in rows]

    def update(self, workspace_id: int, *, name: str, updated_at: datetime) -> bool:
        return self._db.execute(
            "UPDATE workspaces SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at.isoformat(), workspace_id),
        ) > 0

    def delete(self, workspace_id: int) -> bool:
        return self._db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,)) > 0

    def count(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM workspaces")
        return int(row["total"]) if row is not None else 0


class WorkspaceMemberRepository(Repository):
    """SQL access for Workspace membership and roles."""

    @staticmethod
    def _to_record(row: Any) -> WorkspaceMemberRecord:
        return WorkspaceMemberRecord(
            workspace_id=int(row["workspace_id"]),
            user_id=int(row["user_id"]),
            role=WorkspaceRole(str(row["role"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def add(self, member: WorkspaceMemberRecord) -> WorkspaceMemberRecord:
        self._db.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                member.workspace_id,
                member.user_id,
                member.role.value,
                member.created_at.isoformat(),
            ),
        )
        return member

    def get(self, workspace_id: int, user_id: int) -> WorkspaceMemberRecord | None:
        row = self._db.query_one(
            "SELECT * FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        )
        return self._to_record(row) if row is not None else None

    def list(self, workspace_id: int) -> list[WorkspaceMemberRecord]:
        rows = self._db.query(
            "SELECT * FROM workspace_members WHERE workspace_id = ? ORDER BY user_id",
            (workspace_id,),
        )
        return [self._to_record(row) for row in rows]

    def list_workspace_ids(self, user_id: int) -> list[int]:
        rows = self._db.query(
            "SELECT workspace_id FROM workspace_members WHERE user_id = ? ORDER BY workspace_id",
            (user_id,),
        )
        return [int(row["workspace_id"]) for row in rows]

    def remove(self, workspace_id: int, user_id: int) -> bool:
        return self._db.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        ) > 0

    def remove_workspace(self, workspace_id: int) -> int:
        return self._db.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ?", (workspace_id,)
        )

    def count(self, workspace_id: int | None = None) -> int:
        if workspace_id is None:
            row = self._db.query_one("SELECT COUNT(*) AS total FROM workspace_members")
        else:
            row = self._db.query_one(
                "SELECT COUNT(*) AS total FROM workspace_members WHERE workspace_id = ?",
                (workspace_id,),
            )
        return int(row["total"]) if row is not None else 0


class ToolRiskLevel(StrEnum):
    """Risk classification for a trusted, code-registered Tool."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolMetadataRecord(BaseModel):
    """Global metadata for a code-registered Tool."""

    id: int | None = None
    name: str
    category: str = "general"
    description: str = ""
    enabled: bool = True
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkspaceToolRecord(BaseModel):
    """Workspace-level Tool enablement override."""

    workspace_id: int
    tool_name: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentToolRecord(BaseModel):
    """Agent-level Tool enablement override."""

    workspace_id: int
    agent_id: int
    tool_name: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolMetadataRepository(Repository):
    """SQL access for trusted Tool metadata."""

    @staticmethod
    def _to_record(row: Any) -> ToolMetadataRecord:
        return ToolMetadataRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            category=str(row["category"]),
            description=str(row["description"] or ""),
            enabled=bool(row["enabled"]),
            risk_level=ToolRiskLevel(str(row["risk_level"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def upsert(
        self,
        *,
        name: str,
        category: str,
        description: str,
        risk_level: ToolRiskLevel,
    ) -> ToolMetadataRecord:
        now = datetime.now(UTC)
        enabled = risk_level != ToolRiskLevel.HIGH
        self._db.execute(
            "INSERT INTO tools "
            "(name, category, description, enabled, risk_level, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "category = excluded.category, "
            "description = excluded.description, "
            "risk_level = excluded.risk_level, "
            "updated_at = excluded.updated_at",
            (
                name,
                category,
                description,
                int(enabled),
                risk_level.value,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        record = self.get(name)
        if record is None:  # pragma: no cover - just inserted
            raise RuntimeError(f"tool metadata missing after upsert: {name}")
        return record

    def get(self, name: str) -> ToolMetadataRecord | None:
        row = self._db.query_one("SELECT * FROM tools WHERE name = ?", (name,))
        return self._to_record(row) if row is not None else None

    def list(self) -> list[ToolMetadataRecord]:
        rows = self._db.query("SELECT * FROM tools ORDER BY name")
        return [self._to_record(row) for row in rows]


class WorkspaceToolRepository(Repository):
    """SQL access for Workspace Tool overrides."""

    def set_enabled(
        self, workspace_id: int, tool_name: str, *, enabled: bool
    ) -> WorkspaceToolRecord:
        now = datetime.now(UTC)
        self._db.execute(
            "INSERT INTO workspace_tools "
            "(workspace_id, tool_name, enabled, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(workspace_id, tool_name) DO UPDATE SET enabled = excluded.enabled",
            (workspace_id, tool_name, int(enabled), now.isoformat()),
        )
        return WorkspaceToolRecord(
            workspace_id=workspace_id,
            tool_name=tool_name,
            enabled=enabled,
            created_at=now,
        )

    def get(self, workspace_id: int, tool_name: str) -> WorkspaceToolRecord | None:
        row = self._db.query_one(
            "SELECT * FROM workspace_tools WHERE workspace_id = ? AND tool_name = ?",
            (workspace_id, tool_name),
        )
        if row is None:
            return None
        return WorkspaceToolRecord(
            workspace_id=int(row["workspace_id"]),
            tool_name=str(row["tool_name"]),
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def enabled_map(self, workspace_id: int) -> dict[str, bool]:
        rows = self._db.query(
            "SELECT tool_name, enabled FROM workspace_tools WHERE workspace_id = ?",
            (workspace_id,),
        )
        return {str(row["tool_name"]): bool(row["enabled"]) for row in rows}


class AgentToolRepository(Repository):
    """SQL access for Agent-level Tool overrides."""

    def set_enabled(
        self,
        workspace_id: int,
        agent_id: int,
        tool_name: str,
        *,
        enabled: bool,
    ) -> AgentToolRecord:
        now = datetime.now(UTC)
        self._db.execute(
            "INSERT INTO agent_tools "
            "(workspace_id, agent_id, tool_name, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(workspace_id, agent_id, tool_name) "
            "DO UPDATE SET enabled = excluded.enabled",
            (workspace_id, agent_id, tool_name, int(enabled), now.isoformat()),
        )
        return AgentToolRecord(
            workspace_id=workspace_id,
            agent_id=agent_id,
            tool_name=tool_name,
            enabled=enabled,
            created_at=now,
        )

    def enabled_map(self, workspace_id: int, agent_id: int) -> dict[str, bool]:
        rows = self._db.query(
            "SELECT tool_name, enabled FROM agent_tools "
            "WHERE workspace_id = ? AND agent_id = ?",
            (workspace_id, agent_id),
        )
        return {str(row["tool_name"]): bool(row["enabled"]) for row in rows}


__all__ = [
    "AgentToolRecord",
    "AgentToolRepository",
    "PLATFORM_SCHEMA",
    "ToolMetadataRecord",
    "ToolMetadataRepository",
    "ToolRiskLevel",
    "UserRecord",
    "UserRepository",
    "UserStatus",
    "WorkspaceMemberRecord",
    "WorkspaceMemberRepository",
    "WorkspaceRecord",
    "WorkspaceRepository",
    "WorkspaceToolRecord",
    "WorkspaceToolRepository",
    "WorkspaceRole",
]
