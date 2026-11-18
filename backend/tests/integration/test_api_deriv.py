"""Deriv on the dashboard (Phase 21): its logins stored encrypted, the *Check* button, and the asset
list for the session form. Nothing here reaches Deriv: the check is answered by a stand-in."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx

from app.brokers.base import BrokerAccount
from app.brokers.errors import BrokerConnectionError, BrokerError, LoginRejectedError
from app.core.clock import SystemClock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.deriv.fake import FakeDerivAdapter
from app.deriv.protocol import LengthRange
from app.domain.enums import AccountType, Broker
from app.engine.engine import Engine
from app.engine.logins import login_items, resolve_settings
from app.events.bus import EventBus
from app.main import EngineBuilder
from app.quotex.fake import FakeQuotexAdapter
from app.telegram.fake import FakeTelegramSource
from app.vault.crypto import generate_key
from tests.api_support import running_api

API = "/api/v1"
KEY = generate_key()
TOKEN = "deriv-demo-token-not-real"
REAL_TOKEN = "deriv-real-token-not-real"


class Checker:
    """Stands in for Deriv's account list: records what it was given, answers or fails."""

    def __init__(self, error: BrokerError | None = None) -> None:
        self.error = error
        self.seen: list[tuple[str | None, str | None, AccountType]] = []

    async def __call__(self, settings: Settings, account_type: AccountType) -> BrokerAccount:
        token = (
            settings.deriv_token_demo
            if account_type is AccountType.DEMO
            else (settings.deriv_token_real)
        )
        self.seen.append(
            (
                settings.deriv_app_id,
                None if token is None else token.get_secret_value(),
                account_type,
            )
        )
        if self.error is not None:
            raise self.error
        number = "VRTC100" if account_type is AccountType.DEMO else "CR200"
        return BrokerAccount(number, account_type, "USD", Decimal("10000.00"))


async def store_deriv(client: httpx.AsyncClient, *, real: bool = False) -> None:
    put = client.put
    assert (await put(f"{API}/secrets/deriv_app_id", json={"value": "4321"})).status_code == 200
    assert (await put(f"{API}/secrets/deriv_token_demo", json={"value": TOKEN})).status_code == 200
    if real:
        response = await put(f"{API}/secrets/deriv_token_real", json={"value": REAL_TOKEN})
        assert response.status_code == 200


# --- the logins, stored encrypted -------------------------------------------------------------


async def test_deriv_s_logins_are_stored_encrypted_in_their_own_part_of_the_page(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await store_deriv(rig.client, real=True)
        listed = await rig.client.get(f"{API}/secrets")
        items = {i["name"]: i for i in listed.json()["items"]}
        for name in ("deriv_app_id", "deriv_token_demo", "deriv_token_real"):
            assert items[name]["group"] == "deriv"
            assert items[name]["is_set"] and items[name]["readable"]
        assert TOKEN not in listed.text and REAL_TOKEN not in listed.text
        assert await rig.app.state.vault.get("deriv_token_demo") == TOKEN


async def test_the_engine_uses_the_stored_deriv_logins_before_env_ones(tmp_path: Path) -> None:
    async with running_api(
        tmp_path, secret_key=KEY, deriv_app_id="1111", deriv_token_demo="env-token"
    ) as rig:
        await store_deriv(rig.client)
        resolved = await resolve_settings(
            rig.app.state.settings, rig.app.state.vault, allow_real=False
        )
        assert resolved.deriv_app_id == "4321"  # plain text, as `Settings` keeps it
        assert resolved.deriv_token_demo is not None
        assert resolved.deriv_token_demo.get_secret_value() == TOKEN
        assert resolved.deriv_token_real is None


async def test_the_engine_panel_says_deriv_s_logins_come_from_the_dashboard(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path, secret_key=KEY) as rig:
        await store_deriv(rig.client)
        items = {i.label: i for i in await login_items(rig.app.state.settings, rig.app.state.vault)}
        assert items["Deriv app id"].source == "dashboard"
        assert items["Deriv demo token"].present and items["Deriv demo token"].source == "dashboard"
        assert items["Deriv real token"].source == "missing"
        assert not items["Deriv real token"].required
        # Deriv can trade, so Quotex's login is no longer needed (decision D-75)
        assert not items["Quotex email"].required and not items["Quotex password"].required


async def test_deriv_s_env_logins_can_be_moved_into_the_store(tmp_path: Path) -> None:
    async with running_api(
        tmp_path, secret_key=KEY, deriv_app_id="4321", deriv_token_demo=TOKEN
    ) as rig:
        listed = (await rig.client.get(f"{API}/settings/env-logins")).json()["items"]
        assert [(i["label"], i["in_env"]) for i in listed if i["label"].startswith("Deriv")] == [
            ("Deriv app id", True),
            ("Deriv demo token", True),
            ("Deriv real token", False),
        ]
        response = await rig.client.post(f"{API}/settings/env-logins/import")
        assert response.json()["imported"] == ["Deriv app id", "Deriv demo token"]
        assert TOKEN not in response.text
        assert await rig.app.state.vault.get("deriv_app_id") == "4321"


# --- the Check button -------------------------------------------------------------------------


async def test_the_check_shows_which_account_the_demo_token_opens(tmp_path: Path) -> None:
    checker = Checker()
    async with running_api(tmp_path, secret_key=KEY, deriv_checker=checker) as rig:
        await store_deriv(rig.client)
        response = await rig.client.post(f"{API}/deriv/check", json={"account_type": "demo"})
        assert response.status_code == 200, response.text
        assert response.json() == {
            "account_id": "VRTC100",
            "account_type": "demo",
            "currency": "USD",
            "balance": "10000.00",
        }
        assert checker.seen == [("4321", TOKEN, AccountType.DEMO)]
        assert TOKEN not in response.text


async def test_the_check_of_the_real_token_uses_the_real_token(tmp_path: Path) -> None:
    checker = Checker()
    async with running_api(tmp_path, secret_key=KEY, deriv_checker=checker) as rig:
        await store_deriv(rig.client, real=True)
        response = await rig.client.post(f"{API}/deriv/check", json={"account_type": "real"})
        assert response.json()["account_id"] == "CR200"
        assert checker.seen == [("4321", REAL_TOKEN, AccountType.REAL)]


async def test_a_check_without_a_stored_token_says_what_is_missing(tmp_path: Path) -> None:
    checker = Checker()
    async with running_api(tmp_path, secret_key=KEY, deriv_checker=checker) as rig:
        response = await rig.client.post(f"{API}/deriv/check", json={})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "deriv_not_configured"
        assert "app id" in response.json()["error"]["message"]

        await store_deriv(rig.client)
        response = await rig.client.post(f"{API}/deriv/check", json={"account_type": "real"})
        assert response.status_code == 409
        assert "real token is not stored" in response.json()["error"]["message"]
        assert checker.seen == []  # Deriv is never asked without a token


async def test_a_refused_or_unreachable_check_is_said_in_words(tmp_path: Path) -> None:
    refused = Checker(LoginRejectedError("Deriv refused the token (401: Invalid token)."))
    async with running_api(tmp_path, secret_key=KEY, deriv_checker=refused) as rig:
        await store_deriv(rig.client)
        response = await rig.client.post(f"{API}/deriv/check", json={})
        assert response.status_code == 422
        assert response.json()["error"] == {
            "code": "deriv_login_refused",
            "message": "Deriv refused the token (401: Invalid token).",
            "details": None,
        }
    down = Checker(BrokerConnectionError("Could not reach Deriv (ConnectError: no route)."))
    async with running_api(tmp_path / "2", secret_key=KEY, deriv_checker=down) as rig:
        await store_deriv(rig.client)
        response = await rig.client.post(f"{API}/deriv/check", json={})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "deriv_unreachable"


async def test_the_deriv_routes_need_a_login(tmp_path: Path) -> None:
    async with running_api(tmp_path, secret_key=KEY, logged_in=False) as rig:
        assert (await rig.client.post(f"{API}/deriv/check", json={})).status_code == 401
        assert (await rig.client.get(f"{API}/deriv/assets")).status_code == 401


# --- the asset list -----------------------------------------------------------------------------


def both_brokers() -> EngineBuilder:
    def build(settings: Settings, bus: EventBus, tasks: TaskSupervisor) -> Engine:
        clock = SystemClock()
        quotex = FakeQuotexAdapter(clock=clock, bus=bus)
        deriv = FakeDerivAdapter(clock=clock, bus=bus)
        deriv.add_asset("EURUSD", payout=81)
        deriv.set_lengths("EURUSD", [LengthRange(900, 365 * 86400)])
        deriv.add_asset("R_75", payout=88)
        return Engine(
            adapters={Broker.QUOTEX: quotex, Broker.DERIV: deriv},
            source=FakeTelegramSource(clock),
            bus=bus,
            clock=clock,
            tasks=tasks,
        )

    return build


async def test_without_the_engine_there_is_no_list_and_the_reason_is_given(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        body = (await rig.client.get(f"{API}/deriv/assets")).json()
        assert body == {
            "available": False,
            "reason": "The trading engine is not running.",
            "items": [],
        }


async def test_with_only_quotex_the_list_says_deriv_is_not_set_up(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True) as rig:
        body = (await rig.client.get(f"{API}/deriv/assets")).json()
        assert body["available"] is False and "Deriv is not set up" in body["reason"]


async def test_the_list_gives_deriv_s_assets_with_the_lengths_they_allow(tmp_path: Path) -> None:
    async with running_api(tmp_path, with_engine=True, builder=both_brokers()) as rig:

        async def listed() -> bool:
            body = (await rig.client.get(f"{API}/deriv/assets")).json()
            return bool(body["available"])

        await rig.eventually(listed)
        body = (await rig.client.get(f"{API}/deriv/assets")).json()
        assert body["reason"] is None
        assert body["items"] == [
            {
                "asset": "EURUSD",
                "name": "EURUSD",
                "market": "forex",
                "is_open": True,
                "lengths": [{"min_s": 900, "max_s": 365 * 86400}],
            },
            {
                "asset": "R_75",
                "name": "R_75",
                "market": "synthetic_index",
                "is_open": True,
                "lengths": None,  # not known yet
            },
        ]

        status = (await rig.client.get(f"{API}/status")).json()
        assert status["brokers"] == ["quotex", "deriv"]
