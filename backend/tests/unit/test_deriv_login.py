"""From a token to a one-time socket link (app/deriv/login.py), with Deriv's REST answers mocked."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.brokers.errors import BrokerConnectionError, LoginRejectedError
from app.deriv.login import DerivLogin
from app.domain.enums import AccountType

API = "https://api.example/trading/v1/"
ACCOUNTS = [
    {"account_id": "VRTC100", "currency": "USD", "status": "active"},
    {"account_id": "CR200", "currency": "USD", "status": "active"},
]


def deriv(
    accounts: Any = ACCOUNTS,
    *,
    status: int = 200,
    link: Callable[[str], str] | None = None,
    seen: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(
                status,
                json={
                    "errors": [
                        {
                            "status": status,
                            "code": "Unauthorized",
                            "message": "Invalid or missing authentication",
                        }
                    ]
                },
            )
        path = request.url.path
        if request.method == "GET" and path.endswith("/options/accounts"):
            return httpx.Response(200, json={"data": accounts})
        if request.method == "POST" and path.endswith("/otp"):
            account = path.split("/")[-2]
            kind = "demo" if account.startswith("VR") else "real"
            url = link(account) if link else f"wss://ws.example/options/ws/{kind}?otp=one-{account}"
            return httpx.Response(200, json={"data": {"url": url}})
        return httpx.Response(404, json={"errors": [{"message": "no such route"}]})

    return httpx.MockTransport(handle)


def login(transport: httpx.MockTransport) -> DerivLogin:
    return DerivLogin(token=" tok-123 ", app_id="4321", api_url=API, transport=transport)


async def test_the_demo_link_is_asked_for_the_demo_account_with_the_token_and_app_id() -> None:
    seen: list[httpx.Request] = []
    url = await login(deriv(seen=seen)).socket_url(AccountType.DEMO)
    assert url == "wss://ws.example/options/ws/demo?otp=one-VRTC100"
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/trading/v1/options/accounts"),
        ("POST", "/trading/v1/options/accounts/VRTC100/otp"),
    ]
    assert seen[0].headers["Authorization"] == "Bearer tok-123"
    assert seen[0].headers["Deriv-App-ID"] == "4321"


async def test_the_real_link_is_asked_for_the_real_account() -> None:
    url = await login(deriv()).socket_url(AccountType.REAL)
    assert url.endswith("/ws/real?otp=one-CR200")


async def test_the_account_kind_is_read_from_account_type_when_deriv_sends_it() -> None:
    accounts = [
        {"account_id": "A1", "account_type": "real"},
        {"account_id": "A2", "account_type": "demo"},
    ]

    def link(account: str) -> str:
        return f"wss://ws.example/ws/{'demo' if account == 'A2' else 'real'}?otp=x"

    assert (await login(deriv(accounts, link=link)).socket_url(AccountType.DEMO)).endswith(
        "/ws/demo?otp=x"
    )


async def test_a_refused_token_is_a_login_problem_not_a_network_one() -> None:
    with pytest.raises(LoginRejectedError, match="401"):
        await login(deriv(status=401)).socket_url(AccountType.DEMO)


async def test_no_account_of_the_wanted_kind_is_said_plainly() -> None:
    with pytest.raises(LoginRejectedError, match="no active real account"):
        await login(deriv([ACCOUNTS[0]])).socket_url(AccountType.REAL)
    with pytest.raises(LoginRejectedError, match="no active demo account"):
        await login(deriv([{**ACCOUNTS[0], "status": "disabled"}])).socket_url(AccountType.DEMO)


async def test_several_real_accounts_are_not_guessed_between() -> None:
    accounts = [*ACCOUNTS, {"account_id": "CR300", "status": "active"}]
    with pytest.raises(LoginRejectedError, match="CR200, CR300"):
        await login(deriv(accounts)).socket_url(AccountType.REAL)


async def test_a_link_to_the_wrong_kind_of_account_is_never_used() -> None:
    transport = deriv(link=lambda _: "wss://ws.example/ws/real?otp=x")
    with pytest.raises(LoginRejectedError, match="wrong kind of account"):
        await login(transport).socket_url(AccountType.DEMO)


async def test_server_errors_and_odd_answers_are_connection_problems() -> None:
    with pytest.raises(BrokerConnectionError, match="500"):
        await login(deriv(status=500)).socket_url(AccountType.DEMO)
    with pytest.raises(BrokerConnectionError, match="not a list"):
        await login(deriv({"no": "list"})).socket_url(AccountType.DEMO)

    def bad(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"no data": 1}))

    with pytest.raises(BrokerConnectionError, match="no `data`"):
        await login(httpx.MockTransport(bad)).socket_url(AccountType.DEMO)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    with pytest.raises(BrokerConnectionError, match="Could not reach Deriv"):
        await login(httpx.MockTransport(unreachable)).socket_url(AccountType.DEMO)


def test_a_token_and_an_app_id_are_both_needed() -> None:
    with pytest.raises(LoginRejectedError):
        DerivLogin(token=" ", app_id="1")
    with pytest.raises(LoginRejectedError):
        DerivLogin(token="t", app_id="")


# --- the dashboard's Check button (Phase 21): the account list only ---


async def test_the_check_reads_the_account_from_the_list_without_asking_for_a_link() -> None:
    seen: list[httpx.Request] = []
    accounts = [
        {"account_id": "VRTC100", "currency": "USD", "status": "active", "balance": "10000"},
        {"account_id": "CR200", "currency": "EUR", "status": "active", "balance": 12.5},
    ]
    demo = await login(deriv(accounts, seen=seen)).account(AccountType.DEMO)
    assert (demo.account_id, demo.account_type, demo.currency) == (
        "VRTC100",
        AccountType.DEMO,
        "USD",
    )
    assert str(demo.balance) == "10000.00"
    real = await login(deriv(accounts)).account(AccountType.REAL)
    assert (real.account_id, real.currency, str(real.balance)) == ("CR200", "EUR", "12.50")
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/trading/v1/options/accounts")]


async def test_the_check_copes_with_a_list_without_balance_or_currency() -> None:
    found = await login(deriv([{"account_id": "VRTC100", "balance": "n/a"}])).account(
        AccountType.DEMO
    )
    assert found.currency is None and found.balance is None


async def test_the_check_refuses_like_the_login_does() -> None:
    with pytest.raises(LoginRejectedError, match="401"):
        await login(deriv(status=401)).account(AccountType.DEMO)
    with pytest.raises(LoginRejectedError, match="no active real account"):
        await login(deriv([ACCOUNTS[0]])).account(AccountType.REAL)
