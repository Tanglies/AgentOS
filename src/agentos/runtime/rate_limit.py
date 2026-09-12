"""Rate limiting abstractions and an in-process sliding-window implementation."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque


class RateLimiter(ABC):
    """Interface for workspace/API-key rate limiters."""

    @abstractmethod
    def allow(self, key: str, *, limit: int, window_seconds: float = 60.0) -> bool:
        """Return whether one request is allowed."""


class InMemorySlidingWindowRateLimiter(RateLimiter):
    """Thread-safe sliding-window limiter for a single process."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


__all__ = ["InMemorySlidingWindowRateLimiter", "RateLimiter"]
