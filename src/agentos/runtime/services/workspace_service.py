"""Workspace lifecycle and membership service."""

from __future__ import annotations

from datetime import UTC, datetime

from agentos.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from agentos.runtime.platform_repositories import (
    UserRepository,
    UserStatus,
    WorkspaceMemberRecord,
    WorkspaceMemberRepository,
    WorkspaceRecord,
    WorkspaceRepository,
    WorkspaceRole,
)
from agentos.runtime.services.user_service import UserService

ADMIN_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})


class WorkspaceService:
    """Tenant Workspace lifecycle with membership enforcement."""

    def __init__(
        self,
        workspaces: WorkspaceRepository,
        members: WorkspaceMemberRepository,
        *,
        users: UserRepository | UserService | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._members = members
        self._users = users

    def _require_user(self, user_id: int) -> None:
        if self._users is None:
            return
        user = self._users.get(user_id) if hasattr(self._users, "get") else None
        if user is None or user.status != UserStatus.ACTIVE:
            raise NotFoundError(f"user not found: {user_id}", details={"user_id": user_id})

    def _membership(self, workspace_id: int, user_id: int) -> WorkspaceMemberRecord:
        member = self._members.get(workspace_id, user_id)
        if member is None:
            raise NotFoundError(
                f"workspace not found: {workspace_id}",
                details={"workspace_id": workspace_id},
            )
        return member

    def create(self, *, name: str, owner_id: int) -> WorkspaceRecord:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("workspace name must not be empty")
        self._require_user(owner_id)
        if self._workspaces.get_by_name(cleaned) is not None:
            raise ConflictError(
                f"workspace already exists: {cleaned}", details={"name": cleaned}
            )
        now = datetime.now(UTC)
        workspace = self._workspaces.add(
            WorkspaceRecord(name=cleaned, owner_id=owner_id, created_at=now, updated_at=now)
        )
        if workspace.id is None:  # pragma: no cover - persisted record always has id
            raise RuntimeError("workspace persistence returned no id")
        self._members.add(
            WorkspaceMemberRecord(
                workspace_id=workspace.id,
                user_id=owner_id,
                role=WorkspaceRole.OWNER,
                created_at=now,
            )
        )
        return workspace

    def list(self, user_id: int) -> list[WorkspaceRecord]:
        return self._workspaces.list_for_user(user_id)

    def get(self, workspace_id: int, user_id: int) -> WorkspaceRecord:
        self._membership(workspace_id, user_id)
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise NotFoundError(
                f"workspace not found: {workspace_id}",
                details={"workspace_id": workspace_id},
            )
        return workspace

    def update(self, workspace_id: int, user_id: int, *, name: str) -> WorkspaceRecord:
        member = self._membership(workspace_id, user_id)
        if member.role not in ADMIN_ROLES:
            raise PermissionDeniedError("workspace update requires admin role")
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("workspace name must not be empty")
        existing = self._workspaces.get_by_name(cleaned)
        if existing is not None and existing.id != workspace_id:
            raise ConflictError(
                f"workspace already exists: {cleaned}", details={"name": cleaned}
            )
        self._workspaces.update(
            workspace_id, name=cleaned, updated_at=datetime.now(UTC)
        )
        return self.get(workspace_id, user_id)

    def delete(self, workspace_id: int, user_id: int) -> None:
        member = self._membership(workspace_id, user_id)
        if member.role != WorkspaceRole.OWNER:
            raise PermissionDeniedError("workspace deletion requires owner role")
        if workspace_id == 1:
            raise PermissionDeniedError("default workspace cannot be deleted")
        self._members.remove_workspace(workspace_id)
        self._workspaces.delete(workspace_id)

    def list_members(self, workspace_id: int, user_id: int) -> list[WorkspaceMemberRecord]:
        self._membership(workspace_id, user_id)
        return self._members.list(workspace_id)

    def add_member(
        self,
        workspace_id: int,
        user_id: int,
        *,
        member_user_id: int,
        role: WorkspaceRole = WorkspaceRole.MEMBER,
    ) -> WorkspaceMemberRecord:
        actor = self._membership(workspace_id, user_id)
        if actor.role not in ADMIN_ROLES:
            raise PermissionDeniedError("member management requires admin role")
        if role == WorkspaceRole.OWNER:
            raise ValidationError("owner role cannot be assigned through member API")
        self._require_user(member_user_id)
        if self._members.get(workspace_id, member_user_id) is not None:
            raise ConflictError(
                "user is already a workspace member",
                details={"workspace_id": workspace_id, "user_id": member_user_id},
            )
        return self._members.add(
            WorkspaceMemberRecord(
                workspace_id=workspace_id,
                user_id=member_user_id,
                role=role,
                created_at=datetime.now(UTC),
            )
        )

    def remove_member(self, workspace_id: int, user_id: int, *, member_user_id: int) -> None:
        actor = self._membership(workspace_id, user_id)
        if actor.role not in ADMIN_ROLES:
            raise PermissionDeniedError("member management requires admin role")
        target = self._members.get(workspace_id, member_user_id)
        if target is None:
            raise NotFoundError(
                "workspace member not found",
                details={"workspace_id": workspace_id, "user_id": member_user_id},
            )
        if target.role == WorkspaceRole.OWNER:
            raise PermissionDeniedError("workspace owner cannot be removed")
        self._members.remove(workspace_id, member_user_id)


__all__ = ["WorkspaceService"]
