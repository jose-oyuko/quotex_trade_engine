"""Telegram and Quotex dropping while the engine runs: what is lost, what is not, and healing."""

from __future__ import annotations

import asyncio

from app.core.backoff import BackoffPolicy
from app.domain.enums import ChainStatus, SignalStatus, Strategy, TradeStatus
from app.events.types import ConnectionChanged
from tests.engine_support import GroupSpec, make_rig

PLAIN = GroupSpec(1, -1001, Strategy.NO_MARTINGALE, "1.00")


async def wait_for(check, seconds: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    """Real waiting: the reconnect backoff is a real (very short) timer."""
    async with asyncio.timeout(seconds):
        while not check():  # noqa: ASYNC110  (polling a condition of a fake, on purpose)
            await asyncio.sleep(0.005)


FAST = BackoffPolicy(base_s=0.01, cap_s=0.05, jitter=0.0)


async def test_a_telegram_drop_loses_only_what_was_said_meanwhile_and_heals_by_itself() -> None:
    rig = make_rig(telegram_backoff=FAST)
    rig.add_group(PLAIN)
    await rig.start()
    rig.signal(-1001, "EURUSD CALL 1m")
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["EURUSD"]

    rig.source.connect_failures = 2  # and the first two attempts to come back fail as well
    calls_before = rig.source.connect_calls
    rig.source.lose_connection()
    # While Telegram is away nothing can be received: a message sent now is simply not delivered
    # to us (the owner trades it by hand; documented in docs/FAILURE_MODES.md).
    assert rig.source.emit(-1001, "GBPUSD CALL 1m", message_id=50) is False

    await wait_for(lambda: rig.source.connect_calls >= calls_before + 3)  # two failures, a success
    assert await rig.engine.listener.wait_until_connected(5)  # it reconnected on its own
    rig.signal(-1001, "USDJPY CALL 1m")  # the subscriptions came back with it
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["EURUSD", "USDJPY"]  # no GBPUSD, no duplicates

    states = [(e.component, e.connected) for e in rig.collect() if isinstance(e, ConnectionChanged)]
    telegram = [connected for component, connected in states if component == "telegram"]
    assert (
        telegram[0] is True and False in telegram and telegram[-1] is True
    )  # the dashboard saw it
    await rig.stop()


async def test_a_trade_open_when_telegram_drops_is_not_disturbed() -> None:
    rig = make_rig(hold_results=True, telegram_backoff=FAST)
    rig.add_group(GroupSpec(1, -1001, Strategy.MARTINGALE, "1.00", ("2.0",)))
    await rig.start()
    rig.signal(-1001, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    calls_before = rig.source.connect_calls
    rig.source.lose_connection()
    await wait_for(lambda: rig.source.connect_calls > calls_before)
    assert await rig.engine.listener.wait_until_connected(5)
    rig.adapter.settle_all()  # the result still arrives and is handled
    await rig.idle()
    assert rig.statuses("EURUSD") == [TradeStatus.WON]
    assert rig.chains()["EURUSD"].status is ChainStatus.COMPLETED
    await rig.stop()


async def test_an_order_while_quotex_is_down_fails_cleanly_and_the_group_works_again_after() -> (
    None
):
    rig = make_rig()
    rig.add_group(GroupSpec(1, -1001, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0",)))
    await rig.start()
    rig.adapter.simulate_connection_loss()
    rig.signal(-1001, "EURUSD CALL 1m")
    await rig.idle()
    [trade] = rig.trades("EURUSD")
    assert trade.status is TradeStatus.FAILED and "NotConnectedError" in (trade.error or "")
    assert rig.chains()["EURUSD"].status is ChainStatus.FAILED  # no retry, no half-open chain
    assert rig.adapter.orders == []  # nothing was sent

    rig.adapter.simulate_connection_restored()
    rig.signal(-1001, "GBPUSD CALL 1m")  # the group was released: a flip group is not stuck
    await rig.idle()
    assert [o.asset for o in rig.adapter.orders] == ["GBPUSD"]
    await rig.stop()


async def test_a_quotex_drop_while_a_trade_is_open_does_not_disturb_the_waiting_chain() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(GroupSpec(1, -1001, Strategy.MARTINGALE, "1.00", ("2.0", "3.0")))
    await rig.start()
    rig.signal(-1001, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    rig.adapter.simulate_connection_loss()
    rig.adapter.simulate_connection_restored()
    rig.adapter.settle_all()  # the adapter delivers the result once it is back
    await rig.idle()
    assert rig.statuses("EURUSD") == [TradeStatus.WON]
    assert rig.chains()["EURUSD"].status is ChainStatus.COMPLETED
    assert len(rig.adapter.orders) == 1
    await rig.stop()


async def test_a_signal_that_the_pipeline_could_not_use_is_still_in_the_inbox() -> None:
    rig = make_rig()
    rig.add_group(PLAIN)
    await rig.start()
    rig.adapter.set_open("EURUSD", False)
    rig.signal(-1001, "EURUSD CALL 1m")
    await rig.idle()
    inbox = rig.inbox()
    assert [r.status for r in inbox] == [SignalStatus.PARSED]  # received and understood...
    assert rig.statuses("EURUSD") == [TradeStatus.FAILED]  # ...refused by the broker, visibly
    await asyncio.sleep(0)
    await rig.stop()
