"""Downloading past prices (decision D-84): the real `DerivPriceHistory` over a real WebSocket
against the local fake Deriv's public socket, through `PriceHistoryService` and a real price
store."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.backtest.store import PriceStore
from app.brokers.history import PriceHistoryError
from app.core.clock import SystemClock
from app.core.tasks import TaskSupervisor
from app.deriv.fake import FakePriceFeed, FakePriceHistory
from app.deriv.history import DerivPriceHistory
from app.events.bus import EventBus
from app.events.types import JobChanged
from app.services.price_history import (
    AssetBusyError,
    DownloadRunningError,
    InvalidDownloadError,
    PriceHistoryService,
)
from tests.deriv_server import FakeDerivServer

T0 = 1_700_000_000  # 2023-11-14 22:13:20 UTC


def at(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@dataclass
class Rig:
    server: FakeDerivServer
    service: PriceHistoryService
    store: PriceStore
    events: list[JobChanged]

    def requests(self) -> list[dict[str, object]]:
        return self.server.sent("ticks_history")

    async def download(self, asset: str, start: int, end: int) -> str:
        row = await self.service.start(asset, at(start), at(end))
        await self.service.wait(10)
        found = await self.service.download(row.id)
        assert found is not None
        return found.state


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Rig]:
    server = FakeDerivServer()
    await server.start()
    tasks, bus = TaskSupervisor(), EventBus()
    store = PriceStore(tmp_path / "history.db")
    service = PriceHistoryService(
        store=store,
        history=DerivPriceHistory(
            server.public_url(),
            spawn=lambda coro, name: tasks.spawn(coro, name=name),
            timeout_s=2,
        ),
        bus=bus,
        tasks=tasks,
        clock=SystemClock(),
        pace_s=0,
        retry_s=0.01,
    )
    await service.prepare()
    events: list[JobChanged] = []
    subscription = bus.subscribe(JobChanged)

    async def collect() -> None:
        while True:
            event = await subscription.get()
            assert isinstance(event, JobChanged)
            events.append(event)

    collector = asyncio.create_task(collect())
    try:
        yield Rig(server, service, store, events)
    finally:
        collector.cancel()
        await tasks.shutdown()
        await server.stop()


def ticks(symbol: str, start: int, end: int, step: int = 1) -> list[tuple[int, float]]:
    return [(t, 1000 + (t % 97) / 10) for t in range(start, end + 1, step)]


async def test_more_than_one_page_is_downloaded_from_the_newest_to_the_oldest(rig: Rig) -> None:
    rig.server.history["R_75"] = ticks("R_75", T0, T0 + 24_000, step=2)  # 12,001 ticks
    assert await rig.download("R_75", T0, T0 + 24_000) == "done"
    times, _ = rig.store.load("R_75", 0, 2**40)
    assert len(times) == 12_001
    assert rig.store.coverage("R_75") == [(T0, T0 + 24_000)]
    asked = rig.requests()
    # 5000 + 5000 + 2001; each next page ends just before the oldest price of the one before,
    # and the last reached the start of the period, so nothing more is asked
    assert [int(str(r["end"])) for r in asked] == [T0 + 24_000, T0 + 14_001, T0 + 4_001]
    assert all(r["count"] == 5000 and r["style"] == "ticks" for r in asked)
    states = [e.state for e in rig.events]
    assert states[0] == "running" and states[-1] == "done"
    assert all(e.kind == "download" for e in rig.events)


async def test_a_page_smaller_than_asked_for_does_not_leave_a_hole(rig: Rig) -> None:
    rig.server.history["1HZ75V"] = ticks("1HZ75V", T0, T0 + 2_999)
    rig.server.history_page_cap = 1000  # Deriv answers fewer than `count`
    assert await rig.download("1HZ75V", T0, T0 + 2_999) == "done"
    assert len(rig.store.load("1HZ75V", 0, 2**40)[0]) == 3000


async def test_only_the_part_not_yet_stored_is_downloaded(rig: Rig) -> None:
    rig.server.history["R_75"] = ticks("R_75", T0, T0 + 4_000, step=2)
    assert await rig.download("R_75", T0 + 2_000, T0 + 4_000) == "done"
    rig.server.received.clear()
    assert await rig.download("R_75", T0, T0 + 4_000) == "done"
    assert {int(str(r["end"])) for r in rig.requests()} <= set(range(T0, T0 + 2_000))
    assert rig.store.coverage("R_75") == [(T0, T0 + 4_000)]
    rig.server.received.clear()
    assert await rig.download("R_75", T0, T0 + 4_000) == "done"
    assert rig.requests() == []  # all held already


async def test_the_start_of_deriv_s_history_is_reported(rig: Rig) -> None:
    rig.server.history["R_75"] = ticks("R_75", T0 + 7_200, T0 + 9_000, step=2)
    row = await rig.service.start("R_75", at(T0), at(T0 + 9_000))
    await rig.service.wait(10)
    found = await rig.service.download(row.id)
    assert found is not None and found.state == "done"
    assert found.note is not None
    assert "no R_75 prices from 2023-11-14 22:13 UTC" in found.note
    assert "history starts later" in found.note


async def test_a_dropped_connection_is_opened_again_and_the_download_goes_on(rig: Rig) -> None:
    rig.server.history["R_75"] = ticks("R_75", T0, T0 + 30_000, step=2)
    rig.server.history_answers_before_cut = 1
    assert await rig.download("R_75", T0, T0 + 30_000) == "done"
    assert len(rig.store.load("R_75", 0, 2**40)[0]) == 15_001
    assert rig.server.connections == 0  # the public socket is not counted as a login
    retried = [e.detail for e in rig.events if e.detail and "Trying again" in e.detail]
    assert retried == ["The connection to Deriv was lost. Trying again (1/5)."]
    # the 2nd request was cut; the new connection asked again from where the first had stopped
    ends = [int(str(r["end"])) for r in rig.requests()]
    assert ends[:3] == [T0 + 30_000, T0 + 20_001, T0 + 20_001]


async def test_a_connection_that_keeps_dropping_fails_and_keeps_what_was_stored(
    rig: Rig,
) -> None:
    rig.server.history["R_75"] = ticks("R_75", T0, T0 + 30_000, step=2)
    rig.server.history_answers_before_cut = 1
    row = await rig.service.start("R_75", at(T0), at(T0 + 30_000))
    for _ in range(300):
        if rig.store.coverage("R_75"):
            break
        await asyncio.sleep(0.01)
    rig.server.history_dead = True
    await rig.service.wait(10)
    found = await rig.service.download(row.id)
    assert found is not None
    assert found.state == "failed"
    assert found.error == "The connection to Deriv was lost."
    assert found.ticks == 5000
    assert rig.store.coverage("R_75") == [(T0 + 30_000 - 9_998, T0 + 30_000)]


async def test_deriv_s_refusal_and_an_asset_it_does_not_have_fail_with_the_reason(
    rig: Rig,
) -> None:
    rig.server.history_errors.append({"code": "RateLimit", "message": "Too many requests."})
    rig.server.history["R_75"] = ticks("R_75", T0, T0 + 100)
    row = await rig.service.start("R_75", at(T0), at(T0 + 100))
    await rig.service.wait(10)
    found = await rig.service.download(row.id)
    assert found is not None and found.state == "failed"
    assert found.error == "Deriv refused the request for R_75: Too many requests."

    row = await rig.service.start("EURUSD_otc", at(T0), at(T0 + 100))
    await rig.service.wait(10)
    found = await rig.service.download(row.id)
    assert found is not None
    assert found.error == "EURUSD_otc is not traded on Deriv, so it has no price history."


async def test_one_download_at_a_time_and_bad_periods_are_refused(tmp_path: Path) -> None:
    tasks = TaskSupervisor()
    service = PriceHistoryService(
        store=PriceStore(tmp_path / "h.db"),
        history=FakePriceHistory(),
        bus=EventBus(),
        tasks=tasks,
        clock=SystemClock(),
        pace_s=30,  # it waits after its first page, so it is still running below
    )
    await service.prepare()
    with pytest.raises(InvalidDownloadError, match="before the end"):
        await service.start("R_75", at(T0 + 10), at(T0))
    with pytest.raises(InvalidDownloadError, match="At most 31 days"):
        await service.start("R_75", at(T0), at(T0 + 32 * 86400))
    with pytest.raises(InvalidDownloadError, match="Choose an asset"):
        await service.start(" ", at(T0), at(T0 + 10))
    row = await service.start("R_75", at(T0), at(T0 + 86400))
    with pytest.raises(DownloadRunningError, match="R_75 is running"):
        await service.start("1HZ75V", at(T0), at(T0 + 10))
    with pytest.raises(AssetBusyError):
        await service.forget("R_75")
    await tasks.shutdown()
    assert row.state == "running"


async def test_cancel_stops_a_download_and_keeps_what_it_stored(tmp_path: Path) -> None:
    tasks, bus = TaskSupervisor(), EventBus()
    store = PriceStore(tmp_path / "h.db")
    feed = FakePriceFeed()
    service = PriceHistoryService(
        store=store,
        history=FakePriceHistory(feed),
        bus=bus,
        tasks=tasks,
        clock=SystemClock(),
        pace_s=30,
    )
    await service.prepare()
    row = await service.start("1HZ75V", at(T0), at(T0 + 86_399))
    for _ in range(200):  # the first page is stored, then it waits
        if feed.requests and (await service.download(row.id)).ticks:  # type: ignore[union-attr]
            break
        await asyncio.sleep(0.01)
    cancelled = await service.cancel(row.id)
    assert cancelled.state == "cancelled"
    assert cancelled.ticks == 5000
    assert service.running is None
    assert store.coverage("1HZ75V") == [(T0 + 86_399 - 4_999, T0 + 86_399)]
    assert store.missing("1HZ75V", T0, T0 + 86_399) == [(T0, T0 + 86_399 - 5_000)]
    await tasks.shutdown()


async def test_storing_many_prices_never_holds_the_event_loop(tmp_path: Path) -> None:
    """100,000 prices in 20 pages: the loop keeps answering (the file work is in a thread)."""
    tasks = TaskSupervisor()
    service = PriceHistoryService(
        store=PriceStore(tmp_path / "h.db"),
        history=FakePriceHistory(),
        bus=EventBus(),
        tasks=tasks,
        clock=SystemClock(),
        pace_s=0,
    )
    await service.prepare()
    worst = 0.0
    done = False

    async def heartbeat() -> None:
        nonlocal worst
        last = time.perf_counter()
        while not done:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            worst = max(worst, now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    row = await service.start("1HZ75V", at(T0), at(T0 + 99_999))
    await service.wait(60)
    done = True
    await beat
    found = await service.download(row.id)
    assert found is not None and found.state == "done" and found.ticks == 100_000
    assert worst < 0.1, f"the event loop was held for {worst * 1000:.0f} ms"
    await tasks.shutdown()


async def test_deriv_s_assets_come_with_their_names_and_the_list_is_kept(rig: Rig) -> None:
    names = await rig.service.names()
    assert ("R_75", "Volatility 75 Index") in [(a.asset, a.name) for a in names]
    assert ("EURUSD", "EUR/USD") in [(a.asset, a.name) for a in names]
    asked = len(rig.server.sent("active_symbols"))
    assert await rig.service.names() == names  # kept: Deriv is not asked again
    assert len(rig.server.sent("active_symbols")) == asked


async def test_without_deriv_the_last_list_of_names_is_kept(tmp_path: Path) -> None:
    history = FakePriceHistory()
    service = PriceHistoryService(
        store=PriceStore(tmp_path / "h.db"),
        history=history,
        bus=EventBus(),
        tasks=TaskSupervisor(),
        clock=SystemClock(),
    )
    history.fail_open = "Could not reach Deriv's price service."
    with pytest.raises(PriceHistoryError, match="Could not reach"):
        await service.names()
    history.fail_open = None
    first = await service.names()
    assert first[1].name == "Volatility 75 (1s) Index"
    service._names_at = -1e9  # long ago: it asks again
    history.fail_open = "Could not reach Deriv's price service."
    assert await service.names() == first
