"""Deriv's past prices, for backtests (decision D-84).

Deriv's public socket (`.../options/ws/public`) answers `ticks_history` without a token or an
account, so a download never uses the owner's logins. Each download opens a connection of its own
and closes it at the end: the trading engine's connection is never used or slowed.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager

import structlog

from app.brokers.errors import BrokerError
from app.brokers.history import PriceFeed, PriceHistoryError, TickPage
from app.deriv.connection import DerivConnection, Spawn
from app.deriv.protocol import deriv_symbol, error_of, parse_ticks_history, ticks_history_request

log = structlog.get_logger()


class DerivPriceFeed:
    def __init__(self, connection: DerivConnection, timeout_s: float) -> None:
        self._connection = connection
        self._timeout_s = timeout_s

    async def page(self, asset: str, *, start: int, end: int, count: int) -> TickPage:
        symbol = deriv_symbol(asset)
        if symbol is None:
            raise PriceHistoryError(f"{asset} is not traded on Deriv, so it has no price history.")
        try:
            reply = await self._connection.request(
                ticks_history_request(symbol, start=start, end=end, count=count),
                timeout_s=self._timeout_s,
            )
        except TimeoutError as exc:
            raise PriceHistoryError("Deriv did not answer in time.", retryable=True) from exc
        except BrokerError as exc:
            raise PriceHistoryError("The connection to Deriv was lost.", retryable=True) from exc
        if (problem := error_of(reply)) is not None:
            raise PriceHistoryError(f"Deriv refused the request for {asset}: {problem[1]}")
        times, quotes = parse_ticks_history(reply)
        return TickPage(times, quotes)


class DerivPriceHistory:
    def __init__(self, url: str, *, spawn: Spawn, timeout_s: float = 20.0) -> None:
        self._url = url
        self._spawn = spawn
        self._timeout_s = timeout_s

    def open(self) -> AbstractAsyncContextManager[PriceFeed]:
        return self._opened()

    @contextlib.asynccontextmanager
    async def _opened(self) -> AsyncIterator[PriceFeed]:
        try:
            connection = await DerivConnection.open(
                self._url, spawn=self._spawn, timeout_s=self._timeout_s
            )
        except TimeoutError as exc:
            raise PriceHistoryError(
                "Deriv's price service did not answer in time.", retryable=True
            ) from exc
        except Exception as exc:  # websockets raises OSError, InvalidURI, InvalidStatus ...
            raise PriceHistoryError(
                f"Could not reach Deriv's price service ({type(exc).__name__}: {exc}).",
                retryable=True,
            ) from exc
        log.info("deriv_history_connected")
        try:
            yield DerivPriceFeed(connection, self._timeout_s)
        finally:
            await connection.close()
