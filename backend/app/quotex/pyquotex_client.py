"""The only module that talks to the pyquotex library (decisions D-5, D-6, D-14).

It is deliberately small and free of decisions: it translates `QuotexClient` calls into library
calls, and library state into plain values. Everything here was written from reading pyquotex
1.1.0's source; what it does against the real Quotex servers is verified only by the live
diagnostic (`npm run quotex:diagnose`), see docs/reports/phase-2.md.

Why it does not simply call `Quotex.buy()` (measured by reading the source):
- `buy()` first calls `start_realtime_price()`, which polls for a price tick in 0.2 s steps, and
  `get_server_time()`, which downloads the profile over HTTP (`/api/v1/cabinets/digest`). That is
  at least one network round trip plus up to 0.2 s on every order. The adapter does the price
  subscription once per asset ahead of time (`prepare_asset`) and sends the order itself.
- The server-time offset it fetches is not used by the order message at all (expiry comes from the
  local clock), so skipping it changes nothing about what is sent.
- `buy()` waits `duration + 5` seconds for the confirmation; we wait `ack_timeout`.
- `check_win()` answers "loss" after a fixed 300 s, which is wrong for long expiries; we wait on the
  library's per-order result slot ourselves and raise a clear timeout instead.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import structlog
from pyquotex import config as qx_config
from pyquotex import expiration as qx_expiration
from pyquotex.network.login import Login
from pyquotex.qxtypes import ReconnectPolicy
from pyquotex.stable_api import Quotex
from pyquotex.utils.account_type import AccountType as QxAccountType

from app.domain.enums import Direction
from app.quotex.errors import (
    AssetClosedError,
    OrderAckTimeoutError,
    OrderRejectedError,
    QuotexConnectionError,
    ResultTimeoutError,
)
from app.quotex.parsing import profit_from_number

log = structlog.get_logger()

TimeMode = Literal["TIME", "TIMER"]
OtpCallback = Callable[[str], Awaitable[str]]
STALE_SESSION_MARKER = "rejected"  # substring of the library's "Websocket connection rejected."


async def refuse_pin(prompt: str) -> str:
    """Default for unattended use: `input()` would freeze the whole application, so a login that
    needs an email PIN fails with an explanation instead."""
    raise QuotexConnectionError(
        "Quotex asked for an email PIN. Log in to Quotex on the Settings page (it asks for the PIN "
        "there), then start the engine again."
    )


MAX_PAGE_TEXT = 300  # characters of a page's visible text put in a message
MAX_PAGE_HTML = 200_000  # characters of a page kept for the saved copy
KEEP_PAGES = 5  # saved copies kept in the diagnostics folder
# What a page says about itself when it is Cloudflare's check or a captcha, not Quotex's own page.
CLOUDFLARE_MARKERS = (
    "just a moment",
    "cf-chl",
    "challenge-platform",
    "cf-turnstile",
    "checking your browser",
    "attention required",
    "cloudflare",
)
CAPTCHA_MARKERS = ("recaptcha", "hcaptcha", "g-recaptcha")


@dataclass(slots=True, frozen=True)
class PageReport:
    """One page Quotex's website answered with while logging in."""

    step: str  # what was being asked: "the sign-in page", "the login form"
    status: int | None
    url: str
    title: str | None
    text: str  # the visible words, short
    html: str  # the whole page, kept only to save a copy for the owner

    @property
    def looks_like(self) -> str | None:
        """What the page says it is, from its own markers (never a guess about the account)."""
        haystack = f"{self.title or ''} {self.text} {self.html}".lower()
        if any(marker in haystack for marker in CLOUDFLARE_MARKERS):
            return "a Cloudflare check (not Quotex's own page)"
        if any(marker in haystack for marker in CAPTCHA_MARKERS):
            return "a page that asks for a captcha"
        return None


def _visible_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return " ".join(html_lib.unescape(page).split())


def _scrub(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 3:
            text = text.replace(secret, "***")
    return text


def page_report(step: str, response: Any, secrets: Sequence[str]) -> PageReport | None:
    """What a response says, with the owner's email and password taken out of it."""
    if response is None:
        return None
    try:
        body = str(response.text)
    except Exception:
        body = ""
    body = _scrub(body, secrets)
    found = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    title = " ".join(html_lib.unescape(found.group(1)).split()) if found else None
    status = getattr(response, "status_code", None)
    return PageReport(
        step=step,
        status=int(status) if isinstance(status, int) else None,
        url=str(getattr(response, "url", "")).split("?")[0],
        title=title or None,
        text=_visible_text(body)[:MAX_PAGE_TEXT],
        html=body[:MAX_PAGE_HTML],
    )


class PageCapture:
    """Records what Quotex's website answers while the library logs in, so a refusal can say what
    really came back instead of the library's "Unknown error".

    The library keeps no trace of the pages it gets, so for the length of the `with` block the two
    methods that receive them are wrapped; the wrappers hand every response on unchanged and put
    the originals back afterwards, whatever happens. One at a time (logins are one at a time, and
    the engine is stopped while one runs)."""

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        self._secrets = tuple(secrets)
        self.pages: list[PageReport] = []
        self._original: dict[str, Any] = {}

    def _record(self, step: str, response: Any) -> None:
        try:
            report = page_report(step, response, self._secrets)
        except Exception:
            log.warning("quotex_page_capture_failed", exc_info=True)
            return
        if report is not None:
            self.pages.append(report)

    def __enter__(self) -> PageCapture:
        capture = self
        original_get: Any = Login.get_sign_page
        original_success: Any = Login.success_login

        async def get_sign_page(login: Any, *args: Any, **kwargs: Any) -> Any:
            response = await original_get(login, *args, **kwargs)
            capture._record("the sign-in page", response)
            return response

        async def success_login(login: Any, *args: Any, **kwargs: Any) -> Any:
            capture._record("the login form's answer", getattr(login, "response", None))
            return await original_success(login, *args, **kwargs)

        self._original = {"get_sign_page": original_get, "success_login": original_success}
        for name, wrapper in (
            ("get_sign_page", get_sign_page),
            ("success_login", success_login),
        ):
            setattr(Login, name, wrapper)  # the library's class, for the length of the block
        return self

    def __exit__(self, *exc: object) -> None:
        if self._original:
            for name, original in self._original.items():
                setattr(Login, name, original)
            self._original = {}

    def describe(self) -> str | None:
        """The last page Quotex answered with, in a sentence; None if no page was seen."""
        if not self.pages:
            return None
        page = self.pages[-1]
        parts = [f"Quotex's website answered {page.step} with HTTP {page.status or '?'}"]
        parts.append(f"from {page.url or 'an unknown address'}")
        if page.title:
            parts.append(f'titled "{page.title}"')
        sentence = ", ".join(parts)
        if page.text:
            sentence += f'. The page says: "{page.text}"'
        kind = page.looks_like
        sentence += f". That looks like {kind}." if kind else "."
        return sentence

    def save(self, directory: Path) -> Path | None:
        """Keep the last page for the owner to open in a browser (without their email or password).
        The newest few are kept. Returns where, or None if there was no page or it could not be
        written."""
        if not self.pages:
            return None
        page = self.pages[-1]
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            path = directory / f"quotex-login-{stamp}.html"
            note = (
                f"<!-- saved by the application: {page.step}, HTTP {page.status}, {page.url}. "
                "Your email and password were taken out. -->\n"
            )
            path.write_text(note + page.html, encoding="utf-8")
            for old in sorted(directory.glob("quotex-login-*.html"))[:-KEEP_PAGES]:
                old.unlink(missing_ok=True)
        except OSError:
            log.warning("quotex_page_save_failed", exc_info=True)
            return None
        return path


def with_page_report(message: str, capture: PageCapture, directory: Path | None) -> str:
    """`message` followed by what Quotex really answered, and where the page was saved."""
    seen = capture.describe()
    if seen is None:
        return message
    log.warning(
        "quotex_login_page",
        status=capture.pages[-1].status,
        url=capture.pages[-1].url,
        title=capture.pages[-1].title,
    )
    saved = capture.save(directory) if directory is not None else None
    tail = f" The page was saved as {saved}: open it in a browser to see it." if saved else ""
    return f"{message} {seen}{tail}"


def explain_connect_error(exc: Exception, capture: PageCapture | None = None) -> str:
    """Words for an error the library raised while connecting. Its own crash on a refused sign-in
    page ("... has no attribute 'reason_phrase'") really means Quotex's website did not answer
    the request normally. With a `capture`, the message says what it did answer; without one, it
    names the usual cause: Cloudflare, which guards the site, refusing this address."""
    text = f"{type(exc).__name__}: {exc}"
    if "reason_phrase" in text and capture is not None and capture.describe() is not None:
        return (
            "Quotex's website did not return its normal sign-in page, so the login could not "
            "start. This is not a wrong password."
        )
    if "reason_phrase" in text:
        return (
            "Quotex's website refused the request before the login (an HTTP error such as 403). "
            "This is not a wrong password: Quotex sits behind Cloudflare, which often refuses "
            "requests from server and VPN addresses. Try from another connection or computer; "
            "if it works from your own PC at home, run the engine there."
        )
    return text


class PyQuotexClient:
    def __init__(
        self,
        *,
        email: str,
        password: str,
        host: str,
        data_dir: Path,
        time_mode: TimeMode = "TIME",
        otp_callback: OtpCallback = refuse_pin,
        wss_url_override: str | None = None,
        session: str | None = None,
    ) -> None:
        """`session` is the login made on the dashboard (text, kept encrypted by the application).
        The library only reads a file, so it is given one in a private temporary folder that is
        emptied as soon as the connection is made and removed on close: the login is never left on
        disk. Without it, the library uses `data_dir` as before (the command-line login)."""
        self._session_text = session
        self._workdir: Path | None = None
        self._email = email
        self._password = password
        self._host = host
        self._data_dir = data_dir
        self._time_mode = time_mode
        self._otp_callback = otp_callback
        self._wss_url_override = wss_url_override
        self._q: Quotex | None = None
        self.server_time_offset_s: int | None = None

    def _quotex(self) -> Quotex:
        if self._q is None:
            raise QuotexConnectionError("not connected")
        return self._q

    def _api(self) -> Any:
        api = self._quotex().api
        if api is None:
            raise QuotexConnectionError("not connected")
        return api

    # ---- connection --------------------------------------------------------------------------

    def _prepare_folder(self) -> Path:
        """Where the library keeps its session file: a private temporary folder when the login
        comes from the dashboard, else the data folder (the command-line login)."""
        if self._session_text is None:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            return self._data_dir
        if self._workdir is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="qte-quotex-"))  # private to this user
        qx_config.base_dir = self._workdir
        try:
            entry = json.loads(self._session_text)
        except ValueError as exc:
            raise QuotexConnectionError(
                "The stored Quotex login is damaged: log in again."
            ) from exc
        if isinstance(entry, dict):
            qx_config.update_session(self._email, entry)
        return self._workdir

    def _scrub_session_file(self) -> None:
        """Take the login (cookies, token) off the disk the moment it is no longer needed there."""
        if self._workdir is not None:
            (self._workdir / "session.json").unlink(missing_ok=True)

    async def connect(self, *, demo: bool) -> None:
        folder = self._prepare_folder()
        # The library writes session.json (cookies + token) into `config.base_dir`, which it
        # initialises to the current working directory. Point it at a folder we control.
        qx_config.base_dir = folder
        q = Quotex(
            email=self._email,
            password=self._password,
            host=self._host,
            lang="en",
            root_path=str(folder),
            on_otp_callback=self._otp_callback,
            # One owner for reconnecting: the adapter (backoff, events, fresh login if needed).
            reconnect_policy=ReconnectPolicy(enabled=False),
            wss_url_override=self._wss_url_override,
        )
        q.set_account_mode("PRACTICE" if demo else "REAL")
        self._q = q
        capture = PageCapture((self._email, self._password))
        diagnostics = self._data_dir / "diagnostics"
        try:
            with capture:
                ok, reason = await q.connect()
        except QuotexConnectionError:
            raise
        except Exception as exc:
            message = explain_connect_error(exc, capture)
            raise QuotexConnectionError(with_page_report(message, capture, diagnostics)) from exc
        finally:
            self._scrub_session_file()
        if not ok:
            if STALE_SESSION_MARKER in str(reason).lower():
                self._forget_stored_token()
                raise QuotexConnectionError(str(reason))
            raise QuotexConnectionError(with_page_report(str(reason), capture, diagnostics))

    def _forget_stored_token(self) -> None:
        """A rejected session token would otherwise be loaded again by every later attempt (the
        library only forgets it in memory), so the stored one is cleared to force a fresh login."""
        q = self._quotex()
        session = dict(q.session_data)
        session["token"] = None
        qx_config.update_session(self._email, session)
        log.warning("quotex_session_token_cleared")

    async def warm_up(self) -> None:
        q = self._quotex()
        await q.get_instruments()
        await q.get_all_assets()  # fills the asset-code table the price subscription needs
        try:
            profile = await q.get_profile()
            offset = getattr(profile, "offset", None)
            self.server_time_offset_s = int(offset) if offset is not None else None
        except Exception:
            log.warning("quotex_profile_unavailable", exc_info=True)
        if q.api is not None and q.api.account_balance is None:
            await self.wait_for_balance(10.0)

    async def close(self) -> None:
        try:
            if self._q is not None:
                q, self._q = self._q, None
                await q.close()
        finally:
            if self._workdir is not None:
                shutil.rmtree(self._workdir, ignore_errors=True)
                self._workdir = None

    def is_connected(self) -> bool:
        from pyquotex.global_value import AuthStatus, WebsocketStatus

        api = self._q.api if self._q is not None else None
        return (
            api is not None
            and api.state.status == WebsocketStatus.CONNECTED
            and api.state.auth_status == AuthStatus.AUTHENTICATED
        )

    def active_account_is_demo(self) -> bool:
        api = self._quotex().api
        return api is not None and api.account_type == QxAccountType.DEMO

    async def change_account(self, *, demo: bool) -> None:
        await self._quotex().change_account("PRACTICE" if demo else "REAL")

    # ---- reads from memory -------------------------------------------------------------------

    def balance_payload(self) -> Mapping[str, Any] | None:
        api = self._q.api if self._q is not None else None
        return None if api is None else api.account_balance

    def instruments(self) -> Sequence[Sequence[Any]]:
        api = self._q.api if self._q is not None else None
        return [] if api is None else api.instruments or []

    async def wait_for_balance(self, timeout_s: float) -> None:
        api = self._api()
        try:
            await api.slots.balance.wait(timeout=timeout_s)
        except TimeoutError as exc:
            raise QuotexConnectionError("timed out waiting for the balance") from exc

    # ---- trading -----------------------------------------------------------------------------

    async def prepare_asset(self, asset: str, duration_s: int, timeout_s: float) -> None:
        q = self._quotex()
        if asset not in q.codes_asset:
            raise AssetClosedError(f"{asset} is not in Quotex's instrument list")
        await q.start_candles_stream(asset, duration_s)
        api = self._api()
        deadline = time.monotonic() + timeout_s
        while not api.realtime_price.get(asset):
            if time.monotonic() > deadline:
                raise QuotexConnectionError(f"no price ticks received for {asset}")
            await asyncio.sleep(0.05)

    async def buy(
        self,
        asset: str,
        direction: Direction,
        duration_s: int,
        amount: Decimal,
        ack_timeout_s: float,
    ) -> str:
        api = self._api()
        # Reset the shared confirmation state *before* sending, so an answer that arrives
        # immediately cannot be wiped out afterwards. The adapter's lock guarantees we are alone.
        api.buy_id = None
        api.buy_successful = None
        api.slots.buy_confirm.clear()
        await api.buy(
            float(amount),
            asset,
            direction.value,
            duration_s,
            qx_expiration.get_timestamp(),
            self._time_mode == "TIME",
            self._time_mode,
        )
        try:
            confirmation = await api.slots.buy_confirm.wait(timeout=ack_timeout_s)
        except TimeoutError as exc:
            raise OrderAckTimeoutError(
                f"no confirmation from Quotex within {ack_timeout_s:g}s; "
                "the order may have been placed"
            ) from exc
        if isinstance(confirmation, dict) and "error" in confirmation:
            raise OrderRejectedError(str(confirmation["error"]))
        order_id = confirmation.get("id") if isinstance(confirmation, dict) else None
        if order_id is None:
            raise OrderRejectedError("Quotex confirmed the order without an id")
        return str(order_id)

    async def wait_result(self, order_id: str, timeout_s: float) -> Decimal:
        api = self._api()
        key = str(order_id)
        try:
            cached = api.listinfodata.get(key)
            if cached and cached.get("game_state") == 1:  # already settled before we asked
                return profit_from_number(cached.get("profit", 0))
            try:
                result = await api.slots.win_result(key).wait(timeout=timeout_s)
            except TimeoutError as exc:
                raise ResultTimeoutError(
                    f"order {order_id} did not settle within {timeout_s:g}s"
                ) from exc
            return profit_from_number(result.get("profit", 0) if result else 0)
        finally:
            api.slots.release_win_result(key)
            api.listinfodata.delete(key)
            api.listinfodata.delete(order_id)
