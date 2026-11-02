"""The thin seam between the adapter's logic and the unofficial library.

`PyQuotexAdapter` (all the decisions: state, reconnect, safety checks, caching) talks to Quotex only
through this small interface. The one real implementation, `PyQuotexClient`, is the only code that
touches pyquotex; tests drive the adapter with a scripted fake of this interface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol

from app.domain.enums import Direction


class QuotexClient(Protocol):
    """One connection attempt's worth of library state. A fresh client is made per (re)connect."""

    async def connect(self, *, demo: bool) -> None:
        """Log in (reusing the stored session when possible) and open the websocket.
        Raises `QuotexConnectionError`."""
        ...

    async def warm_up(self) -> None:
        """Fetch what the hot path later reads from memory: instruments, asset codes, profile
        (server-time offset) and the first balance."""
        ...

    async def close(self) -> None: ...

    def is_connected(self) -> bool:
        """Websocket up and authenticated. Answered from memory."""
        ...

    def active_account_is_demo(self) -> bool:
        """Which account the connection really uses."""
        ...

    async def change_account(self, *, demo: bool) -> None: ...

    def balance_payload(self) -> Mapping[str, Any] | None:
        """Latest balance message ({"demoBalance": ..., "liveBalance": ...}), from memory."""
        ...

    def instruments(self) -> Sequence[Sequence[Any]]:
        """Latest instrument rows, from memory."""
        ...

    async def wait_for_balance(self, timeout_s: float) -> None: ...

    async def prepare_asset(self, asset: str, duration_s: int, timeout_s: float) -> None:
        """Subscribe to the asset's price stream and wait for the first tick."""
        ...

    async def buy(
        self,
        asset: str,
        direction: Direction,
        duration_s: int,
        amount: Decimal,
        ack_timeout_s: float,
    ) -> str:
        """Send the order and wait for Quotex's confirmation; returns Quotex's order id.
        Raises `OrderRejectedError` (not placed) or `OrderAckTimeoutError` (may exist)."""
        ...

    async def wait_result(self, order_id: str, timeout_s: float) -> Decimal:
        """Wait until the order is settled; returns the profit. Raises `ResultTimeoutError`."""
        ...
