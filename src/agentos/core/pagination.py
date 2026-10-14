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
_KEYSET_VERSION = 2


@dataclass(frozen=True, slots=True)
class PaginationCursor:
    """Position of the last item returned by a keyset-paginated query."""

    created_at: datetime
    item_id: str
    order: Literal["asc", "desc"] = "desc"


@dataclass(frozen=True, slots=True)
class KeysetCursor:
    """Position of the last item in a list ordered by a non-time sort key.

    Lists ordered by a human-readable key (for example Agent ``name``) cannot
    use :class:`PaginationCursor`, which is anchored on ``created_at``.  The
    cursor carries the raw sort key plus the unique item id as a tie-breaker.
    """

    key: str
    item_id: str
    order: Literal["asc", "desc"] = "asc"


def encode_cursor(cursor: PaginationCursor) -> str:
    """Encode a pagination position as a URL-safe opaque token."""
    payload = {
        "created_at": cursor.created_at.astimezone(UTC).isoformat(),
        "item_id": cursor.item_id,
        "order": cursor.order,
    }
    return _encode_payload(payload)


def decode_cursor(token: str) -> PaginationCursor:
    """Decode and validate a cursor token produced by :func:`encode_cursor`."""
    payload = _decode_payload(token)
    try:
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
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_cursor() from exc


def encode_keyset_cursor(cursor: KeysetCursor) -> str:
    """Encode a sort-key position as a URL-safe opaque token."""
    payload: dict[str, object] = {
        "v": _KEYSET_VERSION,
        "key": cursor.key,
        "item_id": cursor.item_id,
        "order": cursor.order,
    }
    return _encode_payload(payload)


def decode_keyset_cursor(token: str) -> KeysetCursor:
    """Decode and validate a token produced by :func:`encode_keyset_cursor`.

    Tokens written by the time-based codec carry no version marker and are
    rejected here, so a cursor can never be replayed against the wrong list.
    """
    payload = _decode_payload(token)
    try:
        if payload["v"] != _KEYSET_VERSION:
            raise ValueError("unsupported cursor version")
        key = payload["key"]
        item_id = payload["item_id"]
        order_value = payload["order"]
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(item_id, str)
            or not item_id
            or order_value not in {"asc", "desc"}
        ):
            raise ValueError("invalid cursor fields")
        order = cast(Literal["asc", "desc"], order_value)
        return KeysetCursor(key=key, item_id=item_id, order=order)
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_cursor() from exc


def ensure_cursor_order(
    cursor_order: str,
    requested_order: str,
) -> None:
    """Reject a cursor reused with a different sort direction."""
    if cursor_order != requested_order:
        raise ValidationError(
            "cursor order does not match the requested order",
            details={"parameter": "cursor"},
        )


def _encode_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_payload(token: str) -> dict[str, object]:
    if not token or len(token) > _MAX_CURSOR_CHARS:
        raise _invalid_cursor()
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(f"{token}{padding}".encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _invalid_cursor() from exc
    if not isinstance(payload, dict):
        raise _invalid_cursor()
    return payload


def _invalid_cursor() -> ValidationError:
    """Build the stable validation error returned for malformed cursors."""
    return ValidationError("invalid pagination cursor", details={"parameter": "cursor"})


__all__ = [
    "KeysetCursor",
    "PaginationCursor",
    "decode_cursor",
    "decode_keyset_cursor",
    "encode_cursor",
    "encode_keyset_cursor",
    "ensure_cursor_order",
]
