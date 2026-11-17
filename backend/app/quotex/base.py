"""The Quotex side of the adapter interface: the broker interface under its Quotex name, and what
logging in to Quotex needs. The interface itself lives in `app.brokers.base` (decision D-74)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.brokers.base import (
    BalanceSnapshot,
    BrokerAdapter,
    ConnectionState,
    OrderAck,
    TradeOutcome,
    TradeResult,
    classify_profit,
    validate_order,
)

QuotexAdapter = BrokerAdapter

__all__ = [
    "BalanceSnapshot",
    "ConnectionState",
    "LoginRequest",
    "OrderAck",
    "PinAsker",
    "QuotexAdapter",
    "QuotexLogin",
    "TradeOutcome",
    "TradeResult",
    "classify_profit",
    "validate_order",
]


type PinAsker = Callable[[str], Awaitable[str]]


@dataclass(slots=True, frozen=True)
class LoginRequest:
    """What logging in to Quotex needs. `ask_pin` is called with Quotex's own wording when it emails
    a PIN, and returns the digits the owner typed; it may wait as long as it likes."""

    email: str
    password: str
    host: str
    ask_pin: PinAsker
    diagnostics_dir: Path | None = None  # where a refused login's page is saved


class QuotexLogin(Protocol):
    async def run(self) -> str:
        """Log in and return the session as text (to be stored encrypted). Raises
        `QuotexConnectionError` with a message for the owner if it cannot."""
        ...
