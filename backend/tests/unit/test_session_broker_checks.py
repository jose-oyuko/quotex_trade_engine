"""Saving a session checks the asset and trade length against its broker (decision D-75): Deriv's
trade lengths come from the asset, once the running engine knows them."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.deriv.fake import FakeDerivAdapter
from app.deriv.protocol import LengthRange
from app.domain.enums import Broker, RepeatKind, Strategy
from app.services.sessions import InvalidSessionError, SessionService, SessionValues
from tests.signal_support import ManualClock


def values(**overrides: Any) -> SessionValues:
    fields: dict[str, Any] = {
        "name": "Deriv",
        "enabled": True,
        "asset": "EURUSD",
        "duration_s": 300,
        "start_time": time(11),
        "end_time": time(12),
        "timezone": "UTC",
        "repeat": RepeatKind.WEEKDAYS,
        "weekdays": (0,),
        "pause_s": 0,
        "profit_target": None,
        "loss_limit": None,
        "max_pairs": None,
        "strategy": Strategy.FLIP_EVERY_LOSS,
        "base_stake": Decimal("1.00"),
        "max_steps": 0,
        "multipliers": (),
        "min_payout_pct": 0,
        "broker": Broker.DERIV,
        **overrides,
    }
    return SessionValues(**fields)


def service(adapter: FakeDerivAdapter | None) -> SessionService:
    executor = SimpleNamespace(adapter=lambda b: adapter if b is Broker.DERIV else None)
    engine = SimpleNamespace(executor=executor)
    return SessionService(None, ManualClock(), lambda: engine)  # type: ignore[arg-type]


async def test_a_length_the_connected_broker_does_not_offer_is_refused_on_save() -> None:
    deriv = FakeDerivAdapter(clock=ManualClock())
    deriv.add_asset("EURUSD", payout=81)
    deriv.set_lengths("EURUSD", [LengthRange(900, 365 * 86400)])
    svc = service(deriv)
    svc._check_offered(values())  # not connected: nothing is known yet, it is saved
    await deriv.connect()
    with pytest.raises(InvalidSessionError, match="it offers 15 min to 365 days"):
        svc._check_offered(values())
    svc._check_offered(values(duration_s=900))  # 15 minutes is offered


def test_without_the_engine_the_session_is_saved_and_the_rounds_say_why() -> None:
    svc = SessionService(None, ManualClock(), lambda: None)  # type: ignore[arg-type]
    svc._check_offered(values())
    service(None)._check_offered(values())  # an engine without Deriv


@pytest.mark.parametrize("asset", ["R_75", "1HZ100V", "EURUSD", "frxXAUUSD"])
def test_deriv_names_are_accepted(asset: str) -> None:
    SessionService._check_asset(values(asset=asset))


@pytest.mark.parametrize("asset", ["EURUSD_otc", "R 75", "x"])
def test_otc_pairs_and_malformed_names_are_refused_for_deriv(asset: str) -> None:
    with pytest.raises(InvalidSessionError):
        SessionService._check_asset(values(asset=asset))


# --- the "not connected" banner, per broker (health) ---


def test_a_broker_that_is_down_is_named_and_one_that_is_up_is_not() -> None:
    from app.api.health import _problems

    up, down = SimpleNamespace(connected=True), SimpleNamespace(connected=False)
    problems = _problems(
        database="ok",
        writer=None,
        engine_running=True,
        telegram=up,
        brokers={Broker.QUOTEX: up, Broker.DERIV: down},
    )
    assert problems == ["Deriv is not connected: no trade can be placed on it until it is."]
    assert (
        _problems(database="ok", writer=None, engine_running=True, telegram=up, brokers={}) == []
    )  # a broker nothing uses is not in the list it is given
