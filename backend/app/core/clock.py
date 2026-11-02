"""Time sources, injectable so tests can control time."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC wall-clock time (for stored timestamps)."""
        ...

    def monotonic_ns(self) -> int:
        """Monotonic nanoseconds (for latency measurements; meaningless across restarts)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ns(self) -> int:
        return time.perf_counter_ns()
