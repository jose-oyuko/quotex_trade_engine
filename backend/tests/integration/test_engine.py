"""Phase 4 end to end: fake Telegram -> pipeline -> chain manager -> executor -> fake Quotex."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.domain.enums import ChainStatus, Direction, SignalStatus, Strategy, TradeStatus
from app.events.types import TradeOpened
from app.quotex.base import TradeOutcome
from app.quotex.errors import OrderAckTimeoutError
from tests.engine_support import EngineRig, GroupSpec, make_rig

D = Decimal
CALL, PUT = Direction.CALL, Direction.PUT
WON, LOST, DRAW = TradeOutcome.WON, TradeOutcome.LOST, TradeOutcome.DRAW
G1, G2, G3 = -1001, -1002, -1003

FLIP = GroupSpec(1, G1, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0", "3.0"))
MARTINGALE = GroupSpec(2, G2, Strategy.MARTINGALE, "2.00", ("2", "2"))
TWO_STEP = GroupSpec(3, G3, Strategy.TWO_STEP_FLIP, "1.00", ("2", "2", "2"))


async def settle_and_follow(
    rig: EngineRig, asset: str, next_result: TradeOutcome | None, expected_orders: int
) -> None:
    """Settle the asset's latest order; script the result its follow-up will get, and wait for it.

    Results are decided when an order is *placed*, so the next one must be scripted before the
    settlement that triggers the follow-up.
    """
    if next_result is not None:
        rig.adapter.script_results(next_result)
    rig.settle_last(asset)
    await rig.until(lambda: len(rig.orders(asset)) == expected_orders)


def shape(rig: EngineRig, asset: str) -> list[tuple[str, str]]:
    return [(o.direction.value, f"{o.amount:.2f}") for o in rig.orders(asset)]


async def test_three_groups_with_mixed_strategies_and_overlapping_chains() -> None:
    rig = make_rig(hold_results=True)
    for spec in (FLIP, MARTINGALE, TWO_STEP):
        rig.add_group(spec)
    await rig.start()
    # Results of the first four orders, in placement order: EURUSD, GBPUSD, USDJPY, AUDUSD.
    rig.adapter.script_results(LOST, WON, LOST, LOST)

    rig.signal(G1, "EURUSD CALL 1m")  # flip_every_loss
    rig.signal(G2, "GBPUSD PUT 1m")  # martingale
    rig.signal(G3, "USDJPY CALL 1m")  # two_step_flip
    rig.signal(G2, "AUDUSD CALL 1m")  # martingale again: its own, overlapping chain
    rig.signal(G1, "NZDUSD CALL 1m")  # flip chain still running: must be ignored
    await rig.until(lambda: len(rig.adapter.orders) == 4)

    assert shape(rig, "EURUSD") == [("call", "1.00")]
    assert shape(rig, "GBPUSD") == [("put", "2.00")]
    assert shape(rig, "USDJPY") == [("call", "1.00")]
    assert shape(rig, "AUDUSD") == [("call", "2.00")]
    assert rig.orders("NZDUSD") == []
    assert len(rig.engine.manager.active_chains(2)) == 2  # two chains open in one group at once
    assert len(rig.engine.manager.active_chains()) == 4

    await settle_and_follow(rig, "EURUSD", LOST, 2)  # PUT 2.00
    rig.settle_last("GBPUSD")  # won: chain ends, no follow-up
    await settle_and_follow(rig, "USDJPY", LOST, 2)  # CALL 2.00
    await settle_and_follow(rig, "AUDUSD", WON, 2)  # CALL 4.00
    await settle_and_follow(rig, "USDJPY", LOST, 3)  # PUT 2.00
    await settle_and_follow(rig, "EURUSD", WON, 3)  # CALL 3.00
    await settle_and_follow(rig, "USDJPY", LOST, 4)  # PUT 2.00
    rig.settle_last("EURUSD")
    rig.settle_last("AUDUSD")
    rig.settle_last("USDJPY")
    await rig.idle()

    # directions and stakes follow the document's tables, per chain, independently
    assert shape(rig, "EURUSD") == [("call", "1.00"), ("put", "2.00"), ("call", "3.00")]
    assert shape(rig, "GBPUSD") == [("put", "2.00")]
    assert shape(rig, "USDJPY") == [
        ("call", "1.00"),
        ("call", "2.00"),
        ("put", "2.00"),
        ("put", "2.00"),
    ]
    assert shape(rig, "AUDUSD") == [("call", "2.00"), ("call", "4.00")]

    chains = rig.chains()
    final = {a: (c.status, c.step, c.consecutive_losses) for a, c in chains.items()}
    assert final == {
        "EURUSD": (ChainStatus.COMPLETED, 2, 2),
        "GBPUSD": (ChainStatus.COMPLETED, 0, 0),
        "USDJPY": (ChainStatus.EXHAUSTED, 3, 4),
        "AUDUSD": (ChainStatus.COMPLETED, 1, 1),
    }
    assert {a: c.group_id for a, c in chains.items()} == {
        "EURUSD": 1,
        "GBPUSD": 2,
        "USDJPY": 3,
        "AUDUSD": 2,
    }
    assert rig.statuses("USDJPY") == [TradeStatus.LOST] * 4
    assert rig.statuses("EURUSD") == [TradeStatus.LOST, TradeStatus.LOST, TradeStatus.WON]
    assert rig.engine.manager.active_chains() == []

    ignored = [r for r in rig.inbox() if r.status is SignalStatus.IGNORED]
    assert [r.asset for r in ignored] == ["NZDUSD"]
    await rig.stop()


async def test_a_new_signal_during_an_active_flip_chain_is_ignored_and_says_why() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()

    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    rig.signal(G1, "GBPUSD PUT 1m")
    await rig.until(lambda: any(r.status is SignalStatus.IGNORED for r in rig.inbox()))

    rows = [r for r in rig.inbox() if r.asset == "GBPUSD"]
    assert [r.status for r in rows] == [SignalStatus.PARSED, SignalStatus.IGNORED]
    assert rows[0].id == rows[1].id  # the same inbox row, updated
    assert rows[1].reason is not None and rows[1].reason.startswith("chain active")
    assert rows[1].raw_text == "GBPUSD PUT 1m" and rows[1].telegram_message_id is not None
    assert len(rig.adapter.orders) == 1

    rig.settle_last("EURUSD")  # a win ends the chain and releases the group
    await rig.idle()
    rig.signal(G1, "USDJPY CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 2)
    rig.adapter.settle_all()
    await rig.idle()
    await rig.stop()


async def test_a_win_resets_everything_to_the_base_stake() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST, WON, WON)
    rig.signal(G1, "EURUSD CALL 1m")  # L then W: two trades
    await rig.idle()
    rig.signal(G1, "GBPUSD CALL 1m")  # next signal starts at base again
    await rig.idle()
    assert [o.amount for o in rig.adapter.orders] == [D("1.00"), D("2.00"), D("1.00")]
    await rig.stop()


async def test_a_draw_ends_the_chain_without_a_follow_up() -> None:
    rig = make_rig()
    rig.add_group(MARTINGALE)
    await rig.start()
    rig.adapter.script_results(DRAW)
    rig.signal(G2, "EURUSD CALL 1m")
    await rig.idle()
    assert len(rig.adapter.orders) == 1
    assert rig.chains()["EURUSD"].status is ChainStatus.COMPLETED
    assert rig.statuses("EURUSD") == [TradeStatus.DRAW]
    await rig.stop()


async def test_no_martingale_places_one_trade_per_signal() -> None:
    rig = make_rig()
    rig.add_group(GroupSpec(4, -1004, Strategy.NO_MARTINGALE, "1.50"))
    await rig.start()
    rig.adapter.script_results(LOST, LOST)
    rig.signal(-1004, "EURUSD CALL 1m")
    rig.signal(-1004, "GBPUSD CALL 1m")
    await rig.idle()
    assert [(o.asset, o.amount) for o in rig.adapter.orders] == [
        ("EURUSD", D("1.50")),
        ("GBPUSD", D("1.50")),
    ]
    assert {c.status for c in rig.chains().values()} == {ChainStatus.EXHAUSTED}
    await rig.stop()


# --- things going wrong ---


async def test_a_refused_first_order_fails_the_chain_and_frees_the_group() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.set_open("EURUSD", False)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()

    chain = rig.chains()["EURUSD"]
    assert chain.status is ChainStatus.FAILED
    assert chain.end_reason is not None and "AssetClosedError" in chain.end_reason
    [trade] = rig.trades("EURUSD")
    assert trade.status is TradeStatus.FAILED and trade.broker_order_id is None
    assert rig.adapter.orders == []

    rig.signal(G1, "GBPUSD CALL 1m")  # the group is not blocked by the broken chain
    await rig.idle()
    assert len(rig.orders("GBPUSD")) == 1
    await rig.stop()


async def test_a_follow_up_that_cannot_be_placed_fails_the_chain_and_frees_the_group() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.adapter.set_open("EURUSD", False)  # closes before the loss is known
    rig.settle_last("EURUSD")
    await rig.idle()

    chain = rig.chains()["EURUSD"]
    assert (chain.status, chain.step, chain.consecutive_losses) == (ChainStatus.FAILED, 1, 1)
    assert rig.statuses("EURUSD") == [TradeStatus.LOST, TradeStatus.FAILED]
    assert rig.engine.manager.active_chains() == []
    await rig.stop()


async def test_an_order_without_confirmation_is_unknown_and_never_retried() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.fail_next_order(OrderAckTimeoutError("no confirmation in 10 s"))
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()

    assert rig.chains()["EURUSD"].status is ChainStatus.UNKNOWN
    [trade] = rig.trades("EURUSD")
    assert trade.status is TradeStatus.UNKNOWN
    assert trade.error is not None and "no confirmation" in trade.error
    assert rig.adapter.orders == []  # a retry would have been recorded
    await rig.stop()


async def test_a_result_that_never_arrives_makes_the_trade_and_chain_unknown() -> None:
    # Timeout = duration + margin; a negative margin makes the 5 s trade time out in 0.05 s.
    rig = make_rig(hold_results=True, result_margin_s=-4.95)
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 5s")
    await rig.idle()

    assert rig.chains()["EURUSD"].status is ChainStatus.UNKNOWN
    [trade] = rig.trades("EURUSD")
    assert trade.status is TradeStatus.UNKNOWN
    assert trade.error is not None and "no result in time" in trade.error
    assert len(rig.adapter.orders) == 1  # placed once, not placed again
    await rig.stop()


async def test_a_group_without_settings_ignores_signals_with_a_reason() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.engine.manager.remove_group(1)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: any(r.status is SignalStatus.IGNORED for r in rig.inbox()))
    assert rig.adapter.orders == []
    ignored = [r for r in rig.inbox() if r.status is SignalStatus.IGNORED]
    assert ignored[0].reason == "group has no strategy settings"
    await rig.stop()


async def test_a_chain_cannot_trade_on_a_different_account_than_it_started_on() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.adapter._account_type = rig.adapter.account_type.__class__.REAL
    rig.settle_last("EURUSD")
    await rig.idle()

    chain = rig.chains()["EURUSD"]
    assert chain.status is ChainStatus.FAILED
    assert chain.end_reason is not None and "account changed" in chain.end_reason
    assert len(rig.adapter.orders) == 1
    await rig.stop()


# --- what gets recorded ---


async def test_trades_carry_their_latency_stamps_payout_and_profit() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST, WON)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()

    first, second = rig.trades("EURUSD")
    stamps = [
        first.t_msg_received_ns,
        first.t_parsed_ns,
        first.t_decided_ns,
        first.t_order_sent_ns,
        first.t_order_acked_ns,
    ]
    assert all(s is not None for s in stamps)
    assert stamps == sorted(stamps)  # type: ignore[type-var]
    # a follow-up has no message of its own, but is stamped from the moment the loss was known
    assert second.t_msg_received_ns is None and second.t_parsed_ns is None
    assert second.t_decided_ns is not None and second.t_order_sent_ns is not None
    assert second.t_decided_ns > (first.t_order_acked_ns or 0)

    assert first.payout_pct == 80
    assert (first.status, first.profit) == (TradeStatus.LOST, D("-1.00"))
    assert (second.status, second.profit) == (TradeStatus.WON, D("1.60"))
    assert first.opened_at is not None and first.expires_at == first.opened_at + timedelta(
        seconds=60
    )
    assert first.settled_at is not None and first.broker_order_id is not None
    await rig.stop()


async def test_each_trade_is_recorded_as_pending_before_the_order_is_sent() -> None:
    """A crash between sending and the confirmation must leave a trace for recovery to find."""
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()
    opened = [e.trade.status for e in rig.collect() if isinstance(e, TradeOpened)]
    assert opened == [TradeStatus.PENDING, TradeStatus.OPEN]
    await rig.stop()


async def test_chain_events_tell_the_whole_story() -> None:
    rig = make_rig()
    rig.add_group(FLIP)
    await rig.start()
    rig.adapter.script_results(LOST, WON)
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.idle()
    names = [e.name for e in rig.collect() if e.name.startswith(("chain.", "trade."))]
    assert names == [
        "chain.started",
        "trade.opened",  # step 0 pending
        "trade.opened",  # step 0 open
        "chain.advanced",  # pending -> open
        "trade.settled",  # lost
        "chain.advanced",  # step 1
        "trade.opened",
        "trade.opened",
        "trade.settled",  # won
        "chain.ended",
    ]
    await rig.stop()


async def test_stopping_the_engine_leaves_open_trades_open_for_recovery() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(FLIP)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)
    await rig.stop()

    assert rig.statuses("EURUSD") == [TradeStatus.OPEN]  # the truth: we stopped watching it
    assert rig.chains()["EURUSD"].status is ChainStatus.OPEN
    assert rig.engine.manager.active_chains() == []
