"""The interface every Quotex adapter implements, and the value types it exchanges.

Everything the engine knows about Quotex goes through `QuotexAdapter` (decision D-6). Reads that the
hot path needs (`balance`, `payout`, `is_open`) are answered from memory and never wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.domain.enums import AccountType, Direction
from app.quotex.errors import InvalidOrderError


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class TradeOutcome(StrEnum):
    WON = "won"
    LOST = "lost"
    DRAW = "draw"


@dataclass(slots=True, frozen=True)
class BalanceSnapshot:
    account_type: AccountType
    balance: Decimal
    taken_at: datetime


@dataclass(slots=True, frozen=True)
class OrderAck:
    """Quotex accepted the order. The two timestamps are monotonic nanoseconds taken right before
    the order was sent and when its confirmation arrived (stored on the trade, ARCHITECTURE §4)."""

    order_id: str
    t_order_sent_ns: int
    t_order_acked_ns: int


@dataclass(slots=True, frozen=True)
class TradeResult:
    """`profit` is the net result in account currency: positive for a win, negative for a loss,
    zero for a draw. See `classify_profit` for the one ambiguity."""

    order_id: str
    outcome: TradeOutcome
    profit: Decimal


def classify_profit(profit: Decimal) -> TradeOutcome:
    """Map a profit figure to an outcome.

    pyquotex labels every profit <= 0 as "loss" and never reports a draw, so a refunded trade
    (profit 0) cannot be told apart from a lost one by the data it delivers. We follow the library:
    zero counts as LOST. Whether Quotex reports a real loss as a negative number is checked by the
    live diagnostic (docs/reports/phase-2.md).
    """
    if profit > 0:
        return TradeOutcome.WON
    return TradeOutcome.LOST


def validate_order(direction: Direction, duration_s: int, amount: Decimal) -> None:
    """The checks every adapter makes before sending anything. Raises `InvalidOrderError`."""
    if not isinstance(direction, Direction):
        raise InvalidOrderError(f"direction must be call or put, got {direction!r}")
    if not isinstance(duration_s, int) or isinstance(duration_s, bool) or duration_s <= 0:
        raise InvalidOrderError(
            f"duration must be a positive number of seconds, got {duration_s!r}"
        )
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise InvalidOrderError(f"amount must be a positive Decimal, got {amount!r}")
    if amount != amount.quantize(Decimal("0.01")):
        raise InvalidOrderError(f"amount {amount} has more than 2 decimal places")


class QuotexAdapter(Protocol):
    @property
    def state(self) -> ConnectionState: ...

    @property
    def account_type(self) -> AccountType: ...

    async def connect(self, *, retry_forever: bool = False) -> None:
        """Log in and open the connection. Raises `QuotexConnectionError` if it fails, unless
        `retry_forever` is set, in which case it keeps trying with backoff until it works or
        `disconnect()` is called."""
        ...

    async def disconnect(self) -> None: ...

    async def set_account_type(self, account_type: AccountType) -> None:
        """Switch between demo and real. REAL needs explicit permission (D-15)."""
        ...

    def set_real_allowed(self, allowed: bool) -> None:
        """Give or take back the permission for REAL (the owner's choice, made in the dashboard)."""
        ...

    def balance(self) -> BalanceSnapshot | None:
        """The latest known balance of the active account, from memory (None before the first)."""
        ...

    async def refresh_balance(self) -> BalanceSnapshot:
        """Wait for a balance if none is known yet, then return it."""
        ...

    def payout(self, asset: str, minutes: int) -> int | None:
        """Payout percent (0-100) for the asset, from memory; None if the asset is unknown.
        Raises `PayoutSanityError` if the data looks wrong."""
        ...

    def is_open(self, asset: str) -> bool:
        """True if the asset is known and open for trading, from memory."""
        ...

    async def prepare_asset(self, asset: str, duration_s: int) -> None:
        """Do the one-time per-asset work (price subscription) ahead of the first order, so that
        order does not pay for it. Safe to call repeatedly."""
        ...

    async def place_order(
        self, asset: str, direction: Direction, duration_s: int, amount: Decimal
    ) -> OrderAck:
        """Send an order and wait for Quotex to confirm it (not for its result)."""
        ...

    async def await_result(self, order_id: str, timeout_s: float) -> TradeResult:
        """Wait for the order to settle. Raises `ResultTimeoutError` after `timeout_s` seconds."""
        ...
