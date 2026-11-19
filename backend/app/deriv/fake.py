"""The fake broker under its Deriv name, with Deriv's own rules (decision D-77): trade lengths are
offered per asset, `_otc` pairs do not exist, and there is no draw (an equal exit is a loss)."""

from __future__ import annotations

import contextlib
import math
import zlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from decimal import Decimal

from app.brokers.base import AssetOffer, ConnectionState, TradeOutcome
from app.brokers.errors import DurationNotOfferedError
from app.brokers.fake import FakeBrokerAdapter
from app.brokers.history import PriceFeed, PriceHistoryError, TickPage
from app.deriv.protocol import (
    LengthRange,
    allows,
    deriv_symbol,
    describe_lengths,
    human_length,
)


class FakeDerivAdapter(FakeBrokerAdapter):
    """See `FakeBrokerAdapter`. `set_lengths("EURUSD", [LengthRange(900, 86400)])` limits the trade
    lengths of an asset; an asset without such a limit accepts any length."""

    COMPONENT = "deriv"
    LABEL = "Deriv"

    _lengths: dict[str, list[LengthRange]] | None = None  # made on the first `set_lengths`

    def set_lengths(self, asset: str, ranges: list[LengthRange]) -> None:
        if self._lengths is None:
            self._lengths = {}
        self._lengths[asset] = ranges

    def catalogue(self) -> list[AssetOffer]:
        """The assets added to the fake, as Deriv's list would show them."""
        if self.state is not ConnectionState.CONNECTED:
            return []
        lengths = self._lengths or {}
        return [
            AssetOffer(
                asset=asset,
                name=asset,
                market="forex" if deriv_symbol(asset) != asset else "synthetic_index",
                is_open=self.is_open(asset),
                lengths=None
                if asset not in lengths
                else tuple((r.min_s, r.max_s) for r in lengths[asset]),
            )
            for asset in sorted(self._assets)
        ]

    def is_open(self, asset: str) -> bool:
        return deriv_symbol(asset) is not None and super().is_open(asset)

    def payout(self, asset: str, minutes: int) -> int | None:
        """Like Deriv: a payout is known only once a price quote was asked for that asset and
        length (`prepare_asset`), and is forgotten when the connection is made again."""
        if not any(a == asset and d // 60 == minutes for a, d in self._prepared):
            return None
        return super().payout(asset, minutes)

    def order_refusal(self, asset: str, duration_s: int) -> str | None:
        """The same reasons, in the same words, as `DerivAdapter.order_refusal`."""
        if deriv_symbol(asset) is None:
            if asset.lower().endswith("_otc"):
                return f"{asset} is an OTC pair: Deriv has no OTC pairs"
            return f"{asset} is not traded on Deriv"
        ranges = (self._lengths or {}).get(asset)
        if ranges is not None and not allows(ranges, duration_s):
            return (
                f"Deriv does not offer {human_length(duration_s)} Rise/Fall on {asset}: it "
                f"offers {describe_lengths(ranges)}"
            )
        return None

    async def prepare_asset(self, asset: str, duration_s: int) -> None:
        self._require_connected()
        ranges = (self._lengths or {}).get(asset)
        if ranges is not None and not allows(ranges, duration_s):
            raise DurationNotOfferedError(
                f"Deriv does not offer {duration_s} s Rise/Fall on {asset} (it offers "
                f"{describe_lengths(ranges)}); order not sent"
            )
        await super().prepare_asset(asset, duration_s)

    def _next_result(
        self, asset: str, duration_s: int, amount: Decimal
    ) -> tuple[TradeOutcome, Decimal]:
        outcome, profit = super()._next_result(asset, duration_s, amount)
        if outcome is TradeOutcome.DRAW:  # Deriv has no draw on Rise/Fall
            return TradeOutcome.LOST, -amount
        return outcome, profit


class FakePriceFeed:
    """Made-up prices for the demo and for tests: a tick every second (every 2 s on `R_` indices),
    each a fixed function of the asset and the second, so the same range always gives the same
    ticks. `starts_at` is where the made-up history begins (like Deriv's oldest tick)."""

    def __init__(self, *, starts_at: int | None = None) -> None:
        self.starts_at = starts_at
        self.requests = 0

    async def page(self, asset: str, *, start: int, end: int, count: int) -> TickPage:
        self.requests += 1
        if deriv_symbol(asset) is None:
            raise PriceHistoryError(f"{asset} is not traded on Deriv, so it has no price history.")
        step = 2 if asset.startswith("R_") else 1
        first = max(start, self.starts_at or start)
        first += (-first) % step
        last = end - end % step
        if last < first:
            return TickPage()
        begin = max(first, last - (count - 1) * step)
        times = list(range(begin, last + 1, step))
        return TickPage(times, [fake_quote(asset, t) for t in times])


def fake_quote(asset: str, epoch: int) -> float:
    """A wavy price with noise, the same for the same asset and second."""
    seed = zlib.crc32(f"{asset}:{epoch}".encode())
    noise = (seed % 2001 - 1000) / 250.0
    return round(1000 + 30 * math.sin(epoch / 5000) + 8 * math.sin(epoch / 377) + noise, 2)


class FakePriceHistory:
    """`PriceHistory` over one `FakePriceFeed`; `fail_open` makes opening fail like a dead
    network."""

    def __init__(self, feed: FakePriceFeed | None = None) -> None:
        self.feed = feed or FakePriceFeed()
        self.fail_open: str | None = None

    def open(self) -> AbstractAsyncContextManager[PriceFeed]:
        return self._opened()

    @contextlib.asynccontextmanager
    async def _opened(self) -> AsyncIterator[PriceFeed]:
        if self.fail_open is not None:
            raise PriceHistoryError(self.fail_open)
        yield self.feed
