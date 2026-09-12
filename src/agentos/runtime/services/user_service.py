"""User lifecycle service."""

from __future__ import annotations

from datetime import UTC, datetime

from agentos.core.exceptions import ConflictError, NotFoundError, ValidationError
from agentos.runtime.platform_repositories import (
    UserRecord,
    UserRepository,
    UserStatus,
)


class UserService:
    """Create and query platform users."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    def create(
        self,
        username: str,
        *,
        display_name: str = "",
        status: UserStatus = UserStatus.ACTIVE,
    ) -> UserRecord:
        cleaned = username.strip()
        if not cleaned:
            raise ValidationError("username must not be empty")
        if self._users.get_by_username(cleaned) is not None:
            raise ConflictError(
                f"username already exists: {cleaned}", details={"username": cleaned}
            )
        now = datetime.now(UTC)
        return self._users.add(
            UserRecord(
                username=cleaned,
                display_name=display_name.strip(),
                status=status,
                created_at=now,
                updated_at=now,
            )
        )

    def get(self, user_id: int) -> UserRecord:
        user = self._users.get(user_id)
        if user is None:
            raise NotFoundError(f"user not found: {user_id}", details={"user_id": user_id})
        return user

    def list(self, *, limit: int = 100, offset: int = 0) -> tuple[list[UserRecord], int]:
        return self._users.list(limit=limit, offset=offset), self._users.count()

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        status: UserStatus | None = None,
    ) -> UserRecord:
        self.get(user_id)
        self._users.update(
            user_id,
            display_name=display_name,
            status=status,
            updated_at=datetime.now(UTC),
        )
        return self.get(user_id)


__all__ = ["UserService"]
