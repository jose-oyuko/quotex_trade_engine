"""Two brokers in one engine (decision D-75): each group and session trades on its own broker, both
at once, and their results, limits and figures stay apart. Fake Quotex and fake Deriv side by side.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers.base import TradeOutcome
from app.db.recovery import RecoveryState
from app.deriv.fake import FakeDerivAdapter
from app.domain.enums import AccountType, Broker, ChainStatus, Direction, SignalStatus, Strategy
from app.engine import engine as engine_module
from app.engine.errors import AccountSwitchRefusedError
from app.engine.risk import RiskLimits
from app.quotex.fake import FakeQuotexAdapter
from tests.engine_support import EngineRig, GroupSpec, make_rig
from tests.session_support import make_session_rig

D = Decimal
WON, LOST = TradeOutcome.WON, TradeOutcome.LOST
QX_GROUP, QX_CHAT = 1, -1001
DV_GROUP, DV_CHAT = 2, -1002


def two_broker_rig(**kwargs: object) -> EngineRig:
    rig = make_rig(with_deriv=True, **kwargs)  # type: ignore[arg-type]
    rig.add_group(GroupSpec(QX_GROUP, QX_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",)))
    rig.add_group(
        GroupSpec(DV_GROUP, DV_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",), broker=Broker.DERIV)
    )
    return rig


def deriv(rig: EngineRig):  # type: ignore[no-untyped-def]
    assert rig.deriv is not None
    return rig.deriv


def ignored(rig: EngineRig) -> list[str]:
    return [s.reason or "" for s in rig.inbox() if s.status is SignalStatus.IGNORED]


async def test_a_quotex_group_and_a_deriv_group_trade_at_once_and_their_results_stay_apart() -> (
    None
):
    rig = two_broker_rig(hold_results=True)
    await rig.start()
    rig.adapter.script_results(WON)
    deriv(rig).script_results(LOST, WON)

    rig.signal(QX_CHAT, "EURUSD CALL 1m")
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(rig.adapter.orders) == 1 and len(deriv(rig).orders) == 1)

    # each order went to its own broker, and nothing crossed over
    assert [(o.asset, o.duration_s) for o in rig.adapter.orders] == [("EURUSD", 60)]
    assert [(o.asset, o.duration_s) for o in deriv(rig).orders] == [("GBPUSD", 900)]
    rig.adapter.settle_all()
    deriv(rig).settle_all()  # the Deriv loss: its martingale step goes to Deriv too
    await rig.until(lambda: len(deriv(rig).orders) == 2)
    deriv(rig).settle_all()
    await rig.idle()

    quotex_trades, deriv_trades = rig.trades("EURUSD"), rig.trades("GBPUSD")
    assert {t.broker for t in quotex_trades} == {Broker.QUOTEX}
    assert {t.broker for t in deriv_trades} == {Broker.DERIV}
    assert [t.stake for t in deriv_trades] == [D("1.00"), D("2.00")]
    chains = rig.chains()
    assert chains["EURUSD"].broker is Broker.QUOTEX and chains["GBPUSD"].broker is Broker.DERIV

    guard = rig.engine.guard
    assert guard.day_pnl(AccountType.DEMO, broker=Broker.QUOTEX) == D("0.80")
    assert guard.day_pnl(AccountType.DEMO, broker=Broker.DERIV) == D("-1.00") + D("1.62")  # 81 %
    assert guard.day_pnl(AccountType.DEMO, QX_GROUP, broker=Broker.DERIV) == D(0)
    await rig.stop()


async def test_the_daily_stop_loss_counts_each_broker_on_its_own() -> None:
    rig = two_broker_rig(limits=RiskLimits(daily_stop_loss=D("1.00")))
    await rig.start()
    deriv(rig).script_results(LOST)
    rig.signal(DV_CHAT, "GBPUSD CALL 15m")  # loses 1.00: Deriv is at its stop-loss, so the
    await rig.until(lambda: len(rig.risk_events()) == 1)  # martingale step is not sent
    await rig.idle()
    assert rig.engine.guard.day_pnl(AccountType.DEMO, broker=Broker.DERIV) == D("-1.00")

    rig.signal(DV_CHAT, "EURUSD CALL 15m")  # still blocked on Deriv
    rig.signal(QX_CHAT, "EURUSD CALL 1m")  # Quotex has lost nothing: it trades
    await rig.until(lambda: len(rig.risk_events()) == 2 and len(rig.adapter.orders) == 1)
    await rig.idle()

    assert len(rig.adapter.orders) == 1
    assert len(deriv(rig).orders) == 1  # nothing more on Deriv
    blocked = [e.risk_event for e in rig.risk_events()]
    assert [e.kind for e in blocked] == ["daily_stop_loss", "daily_stop_loss"]
    assert all("on Deriv" in e.message for e in blocked)
    await rig.stop()


async def test_one_broker_down_does_not_stop_the_other() -> None:
    rig = two_broker_rig()
    await rig.start()
    await deriv(rig).disconnect()

    rig.signal(DV_CHAT, "GBPUSD CALL 15m")
    rig.signal(QX_CHAT, "EURUSD CALL 1m")
    await rig.until(lambda: len(ignored(rig)) == 1 and len(rig.adapter.orders) == 1)
    await rig.idle()

    assert len(rig.adapter.orders) == 1 and deriv(rig).orders == []
    assert ignored(rig) == ["Deriv is not connected"]
    assert rig.chains()["EURUSD"].status is ChainStatus.COMPLETED
    await rig.stop()


async def test_a_deriv_groups_one_minute_forex_signal_is_skipped_with_the_minimum_length() -> None:
    rig = two_broker_rig()
    await rig.start()

    rig.signal(DV_CHAT, "EURUSD CALL 1m")
    await rig.until(lambda: len(ignored(rig)) == 1)
    await rig.idle()

    assert deriv(rig).orders == [] and rig.adapter.orders == []
    assert ignored(rig) == [
        "Deriv does not offer 1 min Rise/Fall on EURUSD: it offers 15 min to 365 days"
    ]
    # the same rule, as the chain manager reads it, for an asset Deriv does not trade at all
    refusal = rig.engine.executor.refusal(Broker.DERIV, "EURUSD_otc", 900)
    assert refusal == "EURUSD_otc is an OTC pair: Deriv has no OTC pairs"
    await rig.stop()


async def test_a_group_on_a_broker_without_a_login_is_skipped_and_says_so() -> None:
    rig = make_rig()  # Quotex only
    rig.add_group(GroupSpec(DV_GROUP, DV_CHAT, Strategy.NO_MARTINGALE, broker=Broker.DERIV))
    await rig.start()
    rig.signal(DV_CHAT, "EURUSD CALL 15m")
    await rig.until(lambda: len(ignored(rig)) == 1)
    assert rig.adapter.orders == []
    assert ignored(rig) == ["Deriv is not set up: its login is missing"]
    await rig.stop()


async def test_a_deriv_session_on_a_synthetic_index_sends_both_legs_of_a_pair_together() -> None:
    s = make_session_rig(
        with_deriv=True, broker=Broker.DERIV, asset="R_75", duration_s=60, hold_results=True
    )
    await s.start()
    await s.timers.advance_to(datetime(2026, 11, 1, 11, 0, tzinfo=UTC))
    await s.timers.settle()
    dv = s.rig.deriv
    assert dv is not None
    await s.rig.until(lambda: len(dv.orders) == 2)

    # both legs are out while neither has a result: the second never waited for the first
    assert [(o.asset, o.direction, o.duration_s) for o in dv.orders] == [
        ("R_75", Direction.CALL, 60),
        ("R_75", Direction.PUT, 60),
    ]
    assert s.adapter.orders == []  # nothing on Quotex
    assert {c.broker for c in s.chains()} == {Broker.DERIV}
    assert s.run().pairs_opened == 1
    await s.stop()


async def test_a_deriv_session_whose_length_the_asset_does_not_offer_skips_its_rounds() -> None:
    s = make_session_rig(with_deriv=True, broker=Broker.DERIV, asset="EURUSD", duration_s=300)
    await s.start()
    await s.timers.advance_to(datetime(2026, 11, 1, 11, 0, tzinfo=UTC))
    await s.timers.settle()
    run = s.run()
    assert run.pairs_opened == 0 and run.rounds_skipped >= 1
    assert (
        run.note == "Deriv does not offer 5 min Rise/Fall on EURUSD: it offers 15 min to 365 days"
    )
    await s.stop()


# --- one switch, one permission, for every broker ---


async def test_the_demo_real_switch_moves_every_broker_or_none() -> None:
    rig = two_broker_rig()
    await rig.start()
    rig.adapter.set_real_allowed(True)  # Deriv is not allowed: it cannot follow
    with pytest.raises(AccountSwitchRefusedError, match="Deriv cannot switch to real"):
        await rig.engine.switch_account(AccountType.REAL)
    assert rig.adapter.account_type is AccountType.DEMO  # Quotex went back
    assert deriv(rig).account_type is AccountType.DEMO

    rig.engine.set_real_allowed(True)
    await rig.engine.switch_account(AccountType.REAL)
    assert {a.account_type for a in rig.engine.adapters.values()} == {AccountType.REAL}
    assert rig.engine.account_type is AccountType.REAL
    await rig.stop()


# --- stopping never hangs ---


class StuckAdapter(FakeQuotexAdapter):
    """A broker that never finishes closing, like the Quotex reconnect seen on 2026-11-13."""

    async def disconnect(self) -> None:
        await asyncio.Event().wait()


async def test_stopping_gives_up_on_a_broker_that_does_not_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_module, "DISCONNECT_TIMEOUT_S", 0.05)
    rig = make_rig(with_deriv=True)
    stuck = StuckAdapter(clock=rig.clock, bus=rig.bus)
    rig.engine.adapters[Broker.QUOTEX] = stuck  # type: ignore[index]
    rig.engine.executor._adapters[Broker.QUOTEX] = stuck
    await rig.engine.start(_empty_recovery())
    await asyncio.wait_for(rig.engine.stop(), 2)  # returns: the stuck broker is given up on
    assert deriv(rig).state.value == "disconnected"  # the other one still closed properly
    await rig.tasks.shutdown()


class RetryingAdapter(FakeDerivAdapter):
    """A broker whose login keeps failing and retrying (Cloudflare refusing Quotex, 2026-11-13)."""

    stopped_trying = False

    async def connect(self, *, retry_forever: bool = False) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped_trying = True


async def test_stopping_ends_a_login_that_is_still_retrying() -> None:
    rig = make_rig()
    retrying = RetryingAdapter(clock=rig.clock, bus=rig.bus)
    rig.engine.adapters[Broker.DERIV] = retrying  # type: ignore[index]
    await rig.engine.start(_empty_recovery())
    await asyncio.sleep(0)
    await asyncio.wait_for(rig.engine.stop(), 2)
    assert retrying.stopped_trying  # its retry loop does not outlive the engine
    assert rig.engine._connecting == {}
    await rig.tasks.shutdown()


def _empty_recovery() -> RecoveryState:
    return RecoveryState(groups=[], group_settings=[], open_chains=[], unsettled_trades=[])


# --- which brokers are in use (for the "not connected" banner) ---


async def test_the_brokers_in_use_are_those_of_enabled_groups_and_sessions() -> None:
    rig = make_rig(with_deriv=True)
    assert rig.engine.brokers_in_use() == set()
    rig.add_group(GroupSpec(QX_GROUP, QX_CHAT, Strategy.NO_MARTINGALE))
    assert rig.engine.brokers_in_use() == {Broker.QUOTEX}
    s = make_session_rig(with_deriv=True, broker=Broker.DERIV, asset="R_75", duration_s=60)
    assert s.engine.brokers_in_use() == {Broker.DERIV}
    await rig.tasks.shutdown()
    await s.rig.tasks.shutdown()
