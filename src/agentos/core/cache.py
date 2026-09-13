"""Small bounded TTL cache for process-local optional optimizations."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Entry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    """A bounded least-recently-used cache with per-entry expiry."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return a live value and refresh its LRU position."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return entry.value

    def set(self, key: K, value: V) -> None:
        """Store a value and evict the least-recently-used entry when full."""
        self._entries.pop(key, None)
        self._entries[key] = _Entry(value=value, expires_at=self._clock() + self._ttl_seconds)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["TTLCache"]
