"""Logging in to Deriv: from a token to a one-time WebSocket link (decisions D-74, D-76).

Deriv's current API has no `authorize` call on the socket. The owner's Personal Access Token and the
app id go in the headers of two REST calls: the account list (`GET options/accounts`), then a
one-time link for the chosen account (`POST options/accounts/{id}/otp`). The link is
`.../ws/demo?otp=...` or `.../ws/real?otp=...`, works once and expires within 120 s, so every
(re)connect asks for a new one.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.brokers.base import BrokerAccount
from app.brokers.errors import BrokerConnectionError, LoginRejectedError
from app.deriv.protocol import is_demo_account, socket_kind
from app.domain.enums import AccountType

DEFAULT_API_URL = "https://api.derivws.com/trading/v1/"


class DerivLogin:
    """The REST side of one token. `transport` lets tests answer without a network."""

    def __init__(
        self,
        *,
        token: str,
        app_id: str,
        api_url: str = DEFAULT_API_URL,
        timeout_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token.strip() or not app_id.strip():
            raise LoginRejectedError("The Deriv token and app id are both needed.")
        self._headers = {
            "Authorization": f"Bearer {token.strip()}",
            "Deriv-App-ID": app_id.strip(),
        }
        self._api_url = api_url.rstrip("/") + "/"
        self._timeout_s = timeout_s
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_url,
            headers=self._headers,
            timeout=self._timeout_s,
            transport=self._transport,
        )

    async def account(self, account_type: AccountType) -> BrokerAccount:
        """Which account the token opens for demo or real, from the account list alone: no
        socket is opened and nothing is traded (the dashboard's *Check* button). Raises like
        `socket_url`."""
        async with self._client() as client:
            accounts = _data(await self._call(client, "GET", "options/accounts"))
        found = _pick(accounts, account_type)
        currency = found.get("currency")
        return BrokerAccount(
            account_id=str(found["account_id"]),
            account_type=account_type,
            currency=str(currency) if currency else None,
            balance=_amount(found.get("balance")),
        )

    async def socket_url(self, account_type: AccountType) -> str:
        """A fresh one-time link to the socket of the token's demo or real account. Raises
        `LoginRejectedError` when Deriv refuses the token or has no such account, and
        `BrokerConnectionError` when it cannot be reached."""
        async with self._client() as client:
            accounts = _data(await self._call(client, "GET", "options/accounts"))
            account = _pick(accounts, account_type)
            account_id = str(account["account_id"])
            answer = _data(await self._call(client, "POST", f"options/accounts/{account_id}/otp"))
        url = answer.get("url") if isinstance(answer, Mapping) else None
        if not isinstance(url, str) or not url:
            raise BrokerConnectionError("Deriv did not send a link to its trading socket.")
        if socket_kind(url) is not account_type:
            raise LoginRejectedError(
                f"Deriv gave a link for the wrong kind of account (wanted {account_type.value}); "
                "nothing was opened."
            )
        return url

    async def _call(self, client: httpx.AsyncClient, method: str, path: str) -> httpx.Response:
        try:
            response = await client.request(method, path)
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(
                f"Could not reach Deriv ({type(exc).__name__}: {exc})."
            ) from exc
        if response.status_code in {401, 403}:
            raise LoginRejectedError(
                f"Deriv refused the token ({response.status_code}: {_message(response)}). Check "
                "the token and the app id, and that the token has the Trade permission."
            )
        if response.status_code >= 400:
            raise BrokerConnectionError(
                f"Deriv answered {response.status_code}: {_message(response)}."
            )
        return response


def _data(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError as exc:
        raise BrokerConnectionError("Deriv's answer was not JSON.") from exc
    if not isinstance(body, Mapping) or "data" not in body:
        raise BrokerConnectionError("Deriv's answer has no `data`.")
    return body["data"]


def _amount(value: object) -> Decimal | None:
    """A balance as Deriv sends it (a number or a numeric string); None when absent or odd."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01")) if amount.is_finite() else None


def _message(response: httpx.Response) -> str:
    try:
        errors = response.json().get("errors")
        return str(errors[0].get("message") or errors[0].get("code"))
    except (ValueError, AttributeError, IndexError, TypeError, KeyError):
        return response.reason_phrase or "no reason given"


def _pick(accounts: Any, account_type: AccountType) -> Mapping[str, Any]:
    """The token's demo account, or its one real account. Several real accounts are not guessed
    between: the owner is told which exist."""
    if not isinstance(accounts, list):
        raise BrokerConnectionError("Deriv's account list is not a list.")
    usable = [
        a
        for a in accounts
        if isinstance(a, Mapping)
        and a.get("account_id")
        and str(a.get("status") or "active").lower() == "active"
    ]
    wanted = [a for a in usable if is_demo_account(a) is (account_type is AccountType.DEMO)]
    if not wanted:
        raise LoginRejectedError(f"The token has no active {account_type.value} account on Deriv.")
    if account_type is AccountType.REAL and len(wanted) > 1:
        ids = ", ".join(str(a["account_id"]) for a in wanted)
        raise LoginRejectedError(
            f"The token reaches several real accounts ({ids}); use a token for one account only."
        )
    return wanted[0]
