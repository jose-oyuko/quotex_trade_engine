"""Past prices from a broker, for backtests (decision D-84).

A `PriceHistory` opens a `PriceFeed` (one connection, used for one download and then closed); the
feed answers one page of ticks at a time. Only Deriv has one today (`app/deriv/history.py`); the
code that stores and replays prices sees only these types.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol

from app.brokers.errors import BrokerError


class PriceHistoryError(BrokerError):
    """The broker refused a request for past prices, or could not be reached. The message says
    which, in words. `retryable`: the network failed (a new connection may work), as opposed to a
    refusal that would only be repeated."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True, frozen=True)
class TickPage:
    """Ticks in time order: `times[i]` (epoch seconds) is the time of `quotes[i]`."""

    times: list[int] = field(default_factory=list)
    quotes: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.times)


@dataclass(slots=True, frozen=True)
class NamedAsset:
    """An asset as people know it: `asset` is our code (`1HZ75V`, `EURUSD`), `name` the broker's
    own name for it ("Volatility 75 (1s) Index", "EUR/USD"), `group` a family to sort by."""

    asset: str
    name: str
    group: str


class PriceFeed(Protocol):
    async def page(self, asset: str, *, start: int, end: int, count: int) -> TickPage:
        """The latest `count` ticks (at most) of `asset` between `start` and `end` (epoch
        seconds, both included), oldest first. Empty when there is none in that range. Raises
        `PriceHistoryError`."""
        ...

    async def assets(self) -> list[NamedAsset]:
        """Every asset the broker lists, with its name. Raises `PriceHistoryError`."""
        ...


class PriceHistory(Protocol):
    def open(self) -> AbstractAsyncContextManager[PriceFeed]:
        """A connection for one download. Raises `PriceHistoryError` if it cannot be opened."""
        ...
