"""Exponential backoff with jitter, as a pure function so tests need no real waiting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class BackoffPolicy:
    base_s: float = 1.0
    cap_s: float = 30.0
    jitter: float = 0.1  # +-10 %

    def __post_init__(self) -> None:
        if self.base_s <= 0 or self.cap_s < self.base_s or not 0 <= self.jitter < 1:
            raise ValueError("invalid backoff policy")


def backoff_delay(attempt: int, policy: BackoffPolicy, rng: Callable[[], float]) -> float:
    """Seconds to wait before retry number `attempt` (0 = first retry).
    `rng` returns a float in [0, 1)."""
    delay = min(policy.cap_s, policy.base_s * 2**attempt)
    factor = 1 + (rng() * 2 - 1) * policy.jitter
    return float(delay * factor)
