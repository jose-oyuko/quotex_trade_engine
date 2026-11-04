"""Slows down guessing: too many failed attempts lock that name (or address) for a while.

In memory on purpose: a restart clears it, which is also how the owner gets back in after locking
themselves out. An attacker can lock the owner out of the *username* for a few minutes, but never
get in; that is the usual trade-off and the better one for an account that moves money.
"""

from __future__ import annotations

import time
from collections.abc import Callable

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
MAX_TRACKED = 10_000  # bounded memory under an attack with endless different names


class LoginThrottle:
    def __init__(
        self,
        *,
        max_failures: int = MAX_FAILURES,
        lock_seconds: float = LOCK_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._lock = lock_seconds
        self._now = now
        self._failures: dict[str, tuple[int, float]] = {}  # key -> (count, time of last failure)

    def seconds_locked(self, key: str) -> int:
        """0 if `key` may try now, otherwise how many seconds remain."""
        entry = self._failures.get(key)
        if entry is None:
            return 0
        count, last = entry
        remaining = self._lock - (self._now() - last)
        if remaining <= 0:
            del self._failures[key]
            return 0
        return int(remaining) + 1 if count >= self._max else 0

    def failed(self, key: str) -> None:
        now = self._now()
        count, last = self._failures.get(key, (0, now))
        if now - last >= self._lock:
            count = 0
        if key not in self._failures and len(self._failures) >= MAX_TRACKED:
            self._failures.pop(next(iter(self._failures)))  # forget the oldest
        self._failures[key] = (count + 1, now)

    def succeeded(self, key: str) -> None:
        self._failures.pop(key, None)
