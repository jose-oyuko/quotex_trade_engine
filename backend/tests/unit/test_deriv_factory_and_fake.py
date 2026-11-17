"""Building the Deriv adapter from the settings, and the Deriv fake's own rules."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from app.brokers.base import TradeOutcome
from app.brokers.errors import (
    AssetClosedError,
    BrokerConnectionError,
    BrokerError,
    DurationNotOfferedError,
    RealAccountNotAllowedError,
)
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.deriv import DerivAdapter, FakeDerivAdapter
from app.deriv.factory import build_deriv_adapter
from app.deriv.protocol import LengthRange
from app.domain.enums import AccountType, Direction
from app.events.bus import EventBus
from app.events.types import ConnectionChanged

D = Decimal


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_the_app_id_and_the_demo_token_are_needed() -> None:
    tasks = TaskSupervisor()
    with pytest.raises(BrokerError, match="DERIV_APP_ID and DERIV_TOKEN_DEMO"):
        build_deriv_adapter(settings(), tasks=tasks, clock=SystemClock())
    with pytest.raises(BrokerError):
        build_deriv_adapter(
            settings(deriv_app_id="1", deriv_token_demo=SecretStr("  ")),
            tasks=tasks,
            clock=SystemClock(),
        )


def test_a_blank_app_id_line_counts_as_unset() -> None:
    assert settings(deriv_app_id="  ").deriv_app_id is None


def test_the_tokens_are_secrets_that_never_reach_a_log() -> None:
    values = settings(
        deriv_token_demo=SecretStr("demo-secret"), deriv_token_real=SecretStr("real-secret")
    ).secret_values()
    assert "demo-secret" in values and "real-secret" in values


async def test_the_built_adapter_starts_on_demo_and_knows_whether_real_is_possible() -> None:
    tasks = TaskSupervisor()
    adapter = build_deriv_adapter(
        settings(deriv_app_id="1", deriv_token_demo=SecretStr("t")),
        tasks=tasks,
        clock=SystemClock(),
    )
    assert isinstance(adapter, DerivAdapter) and adapter.account_type is AccountType.DEMO
    adapter.set_real_allowed(True)
    with pytest.raises(RealAccountNotAllowedError, match="no Deriv token"):
        await adapter.set_account_type(AccountType.REAL)

    both = build_deriv_adapter(
        settings(
            deriv_app_id="1",
            deriv_token_demo=SecretStr("t"),
            deriv_token_real=SecretStr("r"),
            _runtime_quotex_allow_real=True,
        ),
        tasks=tasks,
        clock=SystemClock(),
    )
    await both.set_account_type(AccountType.REAL)  # not connected: only remembered
    assert both.account_type is AccountType.REAL


async def test_the_built_adapter_asks_deriv_for_a_link_with_the_stored_token() -> None:
    seen: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"errors": [{"message": "bad token"}]})

    adapter = build_deriv_adapter(
        settings(deriv_app_id="77", deriv_token_demo=SecretStr("tok")),
        tasks=TaskSupervisor(),
        clock=SystemClock(),
        transport=httpx.MockTransport(refuse),
    )
    with pytest.raises(BrokerConnectionError, match="bad token"):
        await adapter.connect(retry_forever=True)  # a refused login is not retried
    assert len(seen) == 1
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert seen[0].headers["Deriv-App-ID"] == "77"


# ---- the fake ----------------------------------------------------------------------------------


async def test_the_fake_follows_deriv_s_rules() -> None:
    bus = EventBus()
    events = bus.subscribe(ConnectionChanged)
    fake = FakeDerivAdapter(clock=SystemClock(), bus=bus)
    fake.add_asset("EURUSD", payout=80)
    fake.add_asset("R_75", payout=95)
    fake.add_asset("GBPUSD_otc", payout=90)
    fake.set_lengths("EURUSD", [LengthRange(900, 86400)])
    await fake.connect()
    event = events.get_nowait()
    assert isinstance(event, ConnectionChanged) and event.component == "deriv"

    with pytest.raises(DurationNotOfferedError, match="15 min to 1 day"):
        await fake.place_order("EURUSD", Direction.CALL, 60, D("1.00"))
    with pytest.raises(AssetClosedError):  # no OTC pairs on Deriv
        await fake.place_order("GBPUSD_otc", Direction.CALL, 60, D("1.00"))
    assert fake.orders == []

    fake.script_results(TradeOutcome.DRAW)
    ack = await fake.place_order("R_75", Direction.CALL, 60, D("2.00"))
    result = await fake.await_result(ack.order_id, 1)
    assert (result.outcome, result.profit) == (TradeOutcome.LOST, D("-2.00"))  # no draws
    await fake.place_order("EURUSD", Direction.PUT, 900, D("1.00"))
    assert len(fake.orders) == 2
