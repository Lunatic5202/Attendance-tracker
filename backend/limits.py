"""Lightweight in-process fixed-window rate limiting.

Only the public, unauthenticated scan endpoint is rate limited (see
``scan_attendance`` in ``backend.main``). Admin login is deliberately excluded.
This limiter is per-process; if the app is ever run behind multiple workers put
a shared store (Redis, Mongo) behind the same ``check``/``retry_after`` API.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict


class RateLimiter:
    """Fixed-window counter keyed by an arbitrary client identifier."""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = max(1, limit)
        self.window = window_seconds
        self._hits: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit for ``key``.

        Returns ``(allowed, retry_after_seconds)``. ``retry_after`` is 0 when
        the request is allowed.
        """
        now = time.monotonic()
        with self._lock:
            count, reset_at = self._hits.get(key, (0, now + self.window))
            if now >= reset_at:
                count, reset_at = 0, now + self.window
            count += 1
            self._hits[key] = (count, reset_at)
            if len(self._hits) > 10_000:
                self._prune(now)
        if count > self.limit:
            return False, max(1, int(reset_at - now + 0.999))
        return True, 0

    def _prune(self, now: float) -> None:
        for key in [k for k, (_, reset) in self._hits.items() if now >= reset]:
            self._hits.pop(key, None)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


scan_limiter = RateLimiter(
    limit=_env_int("SCAN_RATE_LIMIT", 10),
    window_seconds=_env_int("SCAN_RATE_WINDOW", 60),
)
