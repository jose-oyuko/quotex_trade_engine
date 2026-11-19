"""A switch per broker (decision D-81): the owner switches Quotex or Deriv off while the engine
runs, and back on; a login only the owner can fix stops the retries and waits ("needs you")."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.brokers.base import ConnectionState, TradeOutcome
from app.brokers.errors import LoginRejectedError
from app.db.recovery import RecoveryState
from app.domain.enums import Broker, SignalStatus, Strategy
from app.engine.errors import BrokerOffError, BrokerSwitchRefusedError
from tests.engine_support import EngineRig, GroupSpec, make_rig

D = Decimal
WON = TradeOutcome.WON
QX_GROUP, QX_CHAT = 1, -1001
DV_GROUP, DV_CHAT = 2, -1002
PIN = "Quotex asked for an email PIN. Log in to Quotex on the Settings page."


def rig_with_both(**kwargs: object) -> EngineRig:
    rig = make_rig(with_deriv=True, **kwargs)  # type: ignore[arg-type]
    rig.add_group(GroupSpec(QX_GROUP, QX_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",)))
    rig.add_group(
        GroupSpec(DV_GROUP, DV_CHAT, Strategy.MARTINGALE, "1.00", ("2.0",), broker=Broker.DERIV)
    )
    return rig


def empty() -> RecoveryState:
    return RecoveryState(groups=[], group_settings=[], open_chains=[], unsettled_trades=[])


async def start(rig: EngineRig) -> None:
    """Start the engine the way the application does (it connects the brokers itself)."""
    await rig.engine.start(empty())
    for _ in range(50):
        await asyncio.sleep(0)


def deriv(rig: EngineRig):  # type: ignore[no-untyped-def]
    assert rig.deriv is not None
    return rig.deriv


def ignored(rig: EngineRig) -> list[str]:
    return [s.reason or "" for s in rig.inbox() if s.status is SignalStatus.IGNORED]


async def test_switching_quotex_off_leaves_deriv_trading() -> None:
    rig = rig_with_both()
    await start(rig)
    assert rig.adapter.state is ConnectionState.CONNECTED

    await rig.engine.set_broker_enabled(Broker.QUOTEX, False)
    assert rig.adapter.state is ConnectionState.DISCONNECTED
    assert rig.engine.switched_off == {Broker.QUOTEX}

    rig.signal(QX_CHAT, "EURUSD CALL 1m")
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(deriv(rig).orders) == 1 and len(ignored(rig)) == 1)
    assert rig.adapter.orders == []
    assert ignored(rig) == ["Quotex is switched off"]
    await rig.stop()


async def test_switching_off_stops_the_login_attempts_and_on_starts_them_again() -> None:
    rig = rig_with_both()
    for _ in range(100_000):  # Quotex cannot be reached: it would retry for as long as it runs
        rig.adapter.fail_next_connect()
    await start(rig)
    assert rig.adapter.state is ConnectionState.CONNECTING

    await rig.engine.set_broker_enabled(Broker.QUOTEX, False)
    attempts = rig.adapter.connect_attempts
    for _ in range(200):
        await asyncio.sleep(0)
    assert rig.adapter.connect_attempts == attempts  # no more attempts
    assert rig.adapter.state is ConnectionState.DISCONNECTED

    rig.adapter._connect_failures.clear()  # the network is back
    await rig.engine.set_broker_enabled(Broker.QUOTEX, True)
    await rig.until(lambda: rig.adapter.state is ConnectionState.CONNECTED)
    assert rig.engine.switched_off == frozenset()
    await rig.stop()


async def test_a_broker_cannot_be_switched_off_while_it_has_an_open_trade() -> None:
    rig = rig_with_both(hold_results=True)
    await start(rig)
    deriv(rig).script_results(WON)
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(deriv(rig).orders) == 1)

    with pytest.raises(BrokerSwitchRefusedError, match="1 trade\\(s\\) are open on it"):
        await rig.engine.set_broker_enabled(Broker.DERIV, False)
    assert deriv(rig).state is ConnectionState.CONNECTED  # nothing was touched

    deriv(rig).settle_all()
    await rig.idle()
    await rig.engine.set_broker_enabled(Broker.DERIV, False)  # free now
    assert deriv(rig).state is ConnectionState.DISCONNECTED
    await rig.stop()


async def test_a_broker_without_a_login_cannot_be_switched_on() -> None:
    rig = make_rig()  # Quotex only
    await start(rig)
    with pytest.raises(BrokerSwitchRefusedError, match="its login is not stored"):
        await rig.engine.set_broker_enabled(Broker.DERIV, True)
    await rig.stop()


async def test_a_broker_switched_off_before_the_start_is_never_connected() -> None:
    rig = rig_with_both()
    rig.engine.set_switched_off({Broker.QUOTEX})
    await start(rig)
    assert rig.adapter.connect_attempts == 0
    assert deriv(rig).state is ConnectionState.CONNECTED
    assert Broker.QUOTEX not in rig.engine.brokers_in_use()
    await rig.stop()


async def test_a_session_on_an_off_broker_cannot_start_now() -> None:
    from tests.session_support import make_session_rig

    s = make_session_rig(with_deriv=True, broker=Broker.DERIV, asset="R_75", duration_s=60)
    await s.start()
    s.engine.set_switched_off({Broker.DERIV})
    with pytest.raises(BrokerOffError, match="Deriv is switched off"):
        s.scheduler.start_now(1)
    await s.stop()


async def test_a_pin_request_stops_the_retries_and_waits_for_the_owner() -> None:
    rig = rig_with_both()
    rig.adapter.fail_next_connect(LoginRejectedError(PIN))
    for _ in range(10):
        rig.adapter.fail_next_connect()  # would be retried, if anything retried
    await start(rig)

    assert rig.adapter.connect_attempts == 1  # asked once, then it waits for the owner
    assert rig.adapter.state is ConnectionState.DISCONNECTED
    assert rig.engine.login_problem(Broker.QUOTEX) == PIN
    assert deriv(rig).state is ConnectionState.CONNECTED  # Deriv is not affected

    # switching it off and on (after logging in with the PIN) tries again
    await rig.engine.set_broker_enabled(Broker.QUOTEX, False)
    assert rig.engine.login_problem(Broker.QUOTEX) is None  # an off broker has no problem shown
    rig.adapter._connect_failures.clear()
    await rig.engine.set_broker_enabled(Broker.QUOTEX, True)
    await rig.until(lambda: rig.adapter.state is ConnectionState.CONNECTED)
    assert rig.engine.login_problem(Broker.QUOTEX) is None
    await rig.stop()
