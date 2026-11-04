"""User lifecycle service."""

from __future__ import annotations

from datetime import UTC, datetime

from agentos.core.exceptions import ConflictError, NotFoundError, ValidationError
from agentos.core.pagination import (
    KeysetCursor,
    encode_keyset_cursor,
    ensure_cursor_order,
    ensure_cursor_row_id,
)
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

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        cursor: KeysetCursor | None = None,
    ) -> tuple[list[UserRecord], int, str | None]:
        """Return a page of users and an id-based cursor when more rows exist."""
        after_id = None
        if cursor is not None:
            ensure_cursor_order(cursor.order, "asc")
            key_id = ensure_cursor_row_id(cursor.key)
            item_id = ensure_cursor_row_id(cursor.item_id)
            if key_id != item_id:
                raise ValidationError(
                    "invalid pagination cursor",
                    details={"parameter": "cursor"},
                )
            after_id = item_id

        offset = 0 if cursor is not None else (page - 1) * page_size
        records = self._users.list(
            limit=page_size + 1,
            offset=offset,
            after_id=after_id,
        )
        next_cursor = None
        if len(records) > page_size:
            last = records[page_size - 1]
            if last.id is None:  # pragma: no cover - persisted users always have ids
                raise RuntimeError("user persistence returned no id")
            next_cursor = encode_keyset_cursor(
                KeysetCursor(key=str(last.id), item_id=str(last.id), order="asc")
            )
        return records[:page_size], self._users.count(), next_cursor

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
