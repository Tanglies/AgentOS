"""Opaque keyset pagination cursors.

Offset pagination changes as new rows are inserted, which can duplicate or skip
records while a client walks a busy list.  Keyset cursors remember the last item
seen so the next page remains stable under concurrent writes.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from agentos.core.exceptions import ValidationError

_MAX_CURSOR_CHARS = 2048


@dataclass(frozen=True, slots=True)
class PaginationCursor:
    """Position of the last item returned by a keyset-paginated query."""

    created_at: datetime
    item_id: str
    order: Literal["asc", "desc"] = "desc"


def encode_cursor(cursor: PaginationCursor) -> str:
    """Encode a pagination position as a URL-safe opaque token."""
    payload = {
        "created_at": cursor.created_at.astimezone(UTC).isoformat(),
        "item_id": cursor.item_id,
        "order": cursor.order,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> PaginationCursor:
    """Decode and validate a cursor token produced by :func:`encode_cursor`."""
    if not token or len(token) > _MAX_CURSOR_CHARS:
        raise _invalid_cursor()
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(f"{token}{padding}".encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        created_at_value = payload["created_at"]
        item_id = payload["item_id"]
        order_value = payload["order"]
        if (
            not isinstance(created_at_value, str)
            or not isinstance(item_id, str)
            or not item_id
            or order_value not in {"asc", "desc"}
        ):
            raise ValueError("invalid cursor fields")
        created_at = datetime.fromisoformat(created_at_value)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        order = cast(Literal["asc", "desc"], order_value)
        return PaginationCursor(
            created_at=created_at.astimezone(UTC),
            item_id=item_id,
            order=order,
        )
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _invalid_cursor() from exc


def _invalid_cursor() -> ValidationError:
    """Build the stable validation error returned for malformed cursors."""
    return ValidationError("invalid pagination cursor", details={"parameter": "cursor"})


__all__ = ["PaginationCursor", "decode_cursor", "encode_cursor"]
