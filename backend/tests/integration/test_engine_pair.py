"""The opposite pair (decision D-70): a flip group that allows it runs a second chain, for the
opposite direction on the same asset, next to the first. Nothing else gets past decision D-9."""

from __future__ import annotations

from collections import Counter

import pytest

from app.domain.enums import ChainStatus, Direction, SignalStatus, Strategy, TradeStatus
from app.domain.records import ChainRecord
from app.events.types import ChainAdvanced, ChainEnded, ChainStarted
from app.quotex.base import TradeOutcome
from tests.engine_support import EngineRig, GroupSpec, make_rig

CALL, PUT = Direction.CALL, Direction.PUT
WON, LOST = TradeOutcome.WON, TradeOutcome.LOST
G1 = -1001

PAIR = GroupSpec(1, G1, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0", "3.0"), allow_opposite_pair=True)
NO_PAIR = GroupSpec(1, G1, Strategy.FLIP_EVERY_LOSS, "1.00", ("2.0", "3.0"))


def by_chain(rig: EngineRig) -> dict[object, ChainRecord]:
    """The latest record of every chain, by chain id (two chains share an asset here)."""
    latest: dict[object, ChainRecord] = {}
    for event in rig.collect():
        if isinstance(event, ChainStarted | ChainAdvanced | ChainEnded):
            latest[event.chain.id] = event.chain
    return latest


def reasons(rig: EngineRig) -> list[str]:
    return [
        r.reason for r in rig.inbox() if r.status is SignalStatus.IGNORED and r.reason is not None
    ]


async def start_pair(rig: EngineRig) -> None:
    rig.signal(G1, "EURUSD CALL 1m")
    rig.signal(G1, "EURUSD PUT 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 2)


async def test_two_opposite_signals_on_one_asset_run_as_two_separate_chains() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    rig.adapter.script_results(LOST, WON, WON)  # the CALL loses, the PUT wins, the recovery wins

    await start_pair(rig)
    call, put = rig.adapter.orders
    assert (call.direction, put.direction) == (CALL, PUT)
    assert (call.amount, put.amount) == (1, 1)  # each is a base-stake first trade
    assert len(rig.engine.manager.active_chains(1)) == 2
    assert reasons(rig) == []

    rig.adapter.settle(put.order_id)  # the winner ends its own chain only
    await rig.until(lambda: len(rig.engine.manager.active_chains(1)) == 1)
    assert len(rig.adapter.orders) == 2  # the other chain has not moved
    [running] = rig.engine.manager.active_chains(1)
    assert (running.step, running.spec.origin_direction) == (0, CALL)

    rig.adapter.settle(call.order_id)  # the loser goes into its recovery: the flip, at step 1
    await rig.until(lambda: len(rig.adapter.orders) == 3)
    recovery = rig.adapter.orders[2]
    assert (recovery.direction, recovery.amount) == (PUT, 2)  # flipped CALL, base x 2.0
    rig.adapter.settle(recovery.order_id)
    await rig.idle()

    final = {c.origin_direction: c for c in by_chain(rig).values()}
    assert (final[PUT].status, final[PUT].step) == (ChainStatus.COMPLETED, 0)
    assert (final[CALL].status, final[CALL].step) == (ChainStatus.COMPLETED, 1)
    assert Counter(rig.statuses("EURUSD")) == {TradeStatus.WON: 2, TradeStatus.LOST: 1}
    await rig.stop()


async def test_each_chain_of_a_pair_follows_its_own_steps() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    rig.adapter.script_results(LOST, LOST, LOST, LOST)  # everything loses until the chains run out

    await start_pair(rig)
    call, put = rig.adapter.orders
    rig.adapter.settle(call.order_id)
    await rig.until(lambda: len(rig.adapter.orders) == 3)
    rig.adapter.settle(put.order_id)
    await rig.until(lambda: len(rig.adapter.orders) == 4)
    rig.adapter.settle(rig.adapter.orders[2].order_id)  # the CALL chain, step 1 -> step 2
    await rig.until(lambda: len(rig.adapter.orders) == 5)

    shapes = [(o.direction, o.amount) for o in rig.adapter.orders]
    # the CALL chain goes CALL, PUT, CALL with 1, 2, 3; the PUT chain goes PUT, CALL with 1, 2:
    # no step, stake or counter is shared
    assert shapes == [(CALL, 1), (PUT, 1), (PUT, 2), (CALL, 2), (CALL, 3)]
    await rig.stop()


async def test_ending_one_chain_of_a_pair_leaves_the_other_running() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    await start_pair(rig)

    chains = {c.spec.origin_direction: c for c in rig.engine.manager.active_chains(1)}
    rig.engine.manager.end_chain(chains[CALL].id)
    assert rig.engine.manager.active_chains(1) == [chains[PUT]] and chains[PUT].active

    rig.engine.manager.stop_after_current(chains[PUT].id)  # asks nothing of the ended chain
    assert chains[PUT].stop_requested and not chains[CALL].stop_requested
    await rig.stop()


async def test_a_third_signal_is_ignored_while_a_pair_runs() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    await start_pair(rig)

    rig.signal(G1, "GBPUSD CALL 1m")
    rig.signal(G1, "EURUSD CALL 2m")  # even the same asset, with a direction a chain already has
    await rig.until(lambda: len(reasons(rig)) == 2)

    assert all(r.startswith("chain active") and "pair of chains" in r for r in reasons(rig))
    assert len(rig.adapter.orders) == 2
    assert len(rig.engine.manager.active_chains(1)) == 2
    await rig.stop()


async def test_only_the_opposite_direction_on_the_same_asset_may_join() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    await rig.until(lambda: len(rig.adapter.orders) == 1)

    rig.signal(G1, "EURUSD CALL 5m")  # the same direction: not a pair
    rig.signal(G1, "GBPUSD PUT 1m")  # the opposite direction, but another asset: not a pair
    await rig.until(lambda: len(reasons(rig)) == 2)
    assert all("opposite direction on the same asset" in r for r in reasons(rig))
    assert len(rig.adapter.orders) == 1 and len(rig.engine.manager.active_chains(1)) == 1

    rig.signal(G1, "EURUSD PUT 1m")  # now the right one
    await rig.until(lambda: len(rig.adapter.orders) == 2)
    assert len(rig.engine.manager.active_chains(1)) == 2
    await rig.stop()


async def test_a_group_without_the_pair_still_runs_one_chain_at_a_time() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(NO_PAIR)
    await rig.start()
    rig.signal(G1, "EURUSD CALL 1m")
    rig.signal(G1, "EURUSD PUT 1m")
    await rig.until(lambda: len(reasons(rig)) == 1)

    assert "ignores new signals until chain" in reasons(rig)[0]
    assert len(rig.adapter.orders) == 1
    await rig.stop()


async def test_after_one_chain_ends_the_survivor_can_be_paired_again() -> None:
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    rig.adapter.script_results(LOST, WON)
    await start_pair(rig)
    put = rig.adapter.orders[1]
    rig.adapter.settle(put.order_id)  # the PUT chain is over; the CALL chain is still running
    await rig.until(lambda: len(rig.engine.manager.active_chains(1)) == 1)

    rig.signal(G1, "EURUSD PUT 2m")  # opposite to the surviving CALL chain (not a duplicate)
    await rig.until(lambda: len(rig.adapter.orders) == 3)
    assert len(rig.engine.manager.active_chains(1)) == 2  # two at most, never three
    rig.signal(G1, "EURUSD PUT 3m")
    await rig.until(lambda: len(reasons(rig)) == 1)
    assert len(rig.adapter.orders) == 3
    await rig.stop()


class RecordingLog:
    """Stands in for the manager's logger (structlog's own capture misses a logger that an earlier
    test already bound)."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def info(self, event: str, **fields: object) -> None:
        self.entries.append({"event": event, **fields})


async def test_the_gap_between_the_two_orders_of_a_pair_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingLog()
    monkeypatch.setattr("app.engine.manager.log", recorder)
    rig = make_rig(hold_results=True)
    rig.add_group(PAIR)
    await rig.start()
    await start_pair(rig)
    await rig.until(lambda: any(e["event"] == "opposite_pair_sent" for e in recorder.entries))
    [entry] = [e for e in recorder.entries if e["event"] == "opposite_pair_sent"]
    assert entry["asset"] == "EURUSD" and entry["group_id"] == 1
    assert isinstance(entry["gap_ms"], float) and entry["gap_ms"] >= 0
    await rig.stop()
