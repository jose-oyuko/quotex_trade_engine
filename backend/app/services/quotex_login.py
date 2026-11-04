"""Logging in to Quotex from the dashboard: the stored email and password, and, when Quotex
e-mails a PIN to confirm a login from a new place, the PIN (decision D-66).

Unlike Telegram's, this login is one long call into the library that *waits* for the PIN part-way
through. So it runs as a background task, and the PIN the owner types is handed to it through a
future. The state is kept in memory (a reload shows the step it is at); a login nobody finishes is
dropped after five minutes. Only while the engine is stopped, and one at a time.

What the owner gets is a session, stored encrypted; the password stays where it was stored. Nothing
is written to disk (see `app.quotex.pyquotex_login`).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import structlog

from app.core.clock import Clock
from app.core.config import Settings
from app.core.tasks import TaskSupervisor
from app.engine.controller import EngineController, EngineState
from app.quotex.base import LoginRequest, QuotexLogin
from app.quotex.errors import QuotexError
from app.services.login_errors import EngineRunningError, LoginProblem, WrongStepError
from app.vault.errors import VaultError
from app.vault.store import SecretStore

log = structlog.get_logger()

PIN_WAIT_S = 300.0  # how long a login waits for the PIN before giving up
STEP_WAIT_S = 90.0  # how long one request waits for the login to reach its next step

type LoginFactory = Callable[[LoginRequest], QuotexLogin]


class LoginState(StrEnum):
    LOGGED_OUT = "logged_out"
    WORKING = "working"  # talking to Quotex
    PIN_NEEDED = "pin_needed"
    LOGGED_IN = "logged_in"


class QuotexNotConfiguredError(LoginProblem):
    """The email and password are not stored yet."""


class PinInvalidError(LoginProblem):
    """The PIN is not digits only."""


class NoPinWantedError(WrongStepError):
    """Quotex is not asking for a PIN now (the login may have ended or timed out)."""


@dataclass(slots=True, frozen=True)
class QuotexLoginStatus:
    state: LoginState
    configured: bool  # an email and a password are stored (or in .env)
    pin_prompt: str | None  # Quotex's own wording of what it wants
    message: str | None  # why the last login did not work
    engine_running: bool


class QuotexLoginService:
    def __init__(
        self,
        *,
        vault: SecretStore,
        settings: Callable[[], Settings],
        login_factory: LoginFactory,
        controller: Callable[[], EngineController | None],
        tasks: TaskSupervisor,
        clock: Clock,
    ) -> None:
        self._vault = vault
        self._settings = settings
        self._make_login = login_factory
        self._controller = controller
        self._tasks = tasks
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._pin: asyncio.Future[str] | None = None
        self._prompt: str | None = None
        self._message: str | None = None
        self._changed = asyncio.Event()

    # --- what the page shows ---

    def _engine_running(self) -> bool:
        controller = self._controller()
        return controller is not None and controller.state in (
            EngineState.RUNNING,
            EngineState.STARTING,
            EngineState.STOPPING,
        )

    async def _credentials(self) -> tuple[str, str] | None:
        settings = self._settings()
        try:
            email = await self._vault.get("quotex_email")
            password = await self._vault.get("quotex_password")
        except VaultError:
            return None
        email = email or (settings.quotex_email.get_secret_value() if settings.quotex_email else "")
        password = password or (
            settings.quotex_password.get_secret_value() if settings.quotex_password else ""
        )
        if not email.strip() or not password:
            return None
        return email.strip(), password

    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def status(self) -> QuotexLoginStatus:
        if self._running():
            state = LoginState.PIN_NEEDED if self._pin is not None else LoginState.WORKING
        else:
            try:
                stored = await self._vault.has("quotex_session")
            except VaultError:
                stored = False
            state = LoginState.LOGGED_IN if stored else LoginState.LOGGED_OUT
        return QuotexLoginStatus(
            state=state,
            configured=await self._credentials() is not None,
            pin_prompt=self._prompt if state is LoginState.PIN_NEEDED else None,
            message=self._message if state is not LoginState.LOGGED_IN else None,
            engine_running=self._engine_running(),
        )

    # --- the steps ---

    def _signal(self) -> None:
        self._changed.set()

    async def _wait_for_change(self) -> None:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(STEP_WAIT_S):
                await self._changed.wait()

    async def start(self) -> QuotexLoginStatus:
        """Log in with the stored email and password. Returns when the login needs the PIN, has
        finished, or has been going on for a while (the page asks again)."""
        if self._engine_running():
            raise EngineRunningError(
                "Stop the trading engine first: it is using the Quotex login now."
            )
        credentials = await self._credentials()
        if credentials is None:
            raise QuotexNotConfiguredError(
                "Store your Quotex email and password first (above), then log in."
            )
        await self._stop_running()
        self._message = None
        self._prompt = None
        self._changed = asyncio.Event()
        email, password = credentials

        async def ask_pin(prompt: str) -> str:
            loop = asyncio.get_running_loop()
            self._pin = loop.create_future()
            self._prompt = prompt.strip().rstrip(":").strip() or "Enter the PIN Quotex e-mailed you"
            self._signal()
            try:
                async with asyncio.timeout(PIN_WAIT_S):
                    return await self._pin
            finally:
                self._pin = None

        request = LoginRequest(
            email=email, password=password, host=self._settings().quotex_host, ask_pin=ask_pin
        )
        self._task = self._tasks.spawn(self._run(self._make_login(request)), name="quotex-login")
        await self._wait_for_change()
        return await self.status()

    async def _run(self, login: QuotexLogin) -> None:
        try:
            session = await login.run()
            await self._vault.put("quotex_session", session, internal_ok=True)
            self._message = None
            log.info("quotex_logged_in")
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            self._message = (
                "The PIN was not typed in time. Log in again: Quotex will send a new one."
            )
        except QuotexError as exc:
            self._message = str(exc)
            log.warning("quotex_login_failed", error=str(exc)[:200])
        except VaultError as exc:
            self._message = f"The login worked but could not be stored: {exc}"
        except Exception:
            log.warning("quotex_login_unexpected_error", exc_info=True)
            self._message = "Something went wrong logging in to Quotex. See the log and try again."
        finally:
            self._pin = None
            self._prompt = None
            self._signal()

    async def submit_pin(self, pin: str) -> QuotexLoginStatus:
        """The PIN Quotex e-mailed. The login carries on; the answer says how it ended (or that it
        is still going)."""
        pending = self._pin
        if pending is None or pending.done() or not self._running():
            raise NoPinWantedError("Quotex is not asking for a PIN now. Log in again.")
        cleaned = pin.strip()
        if not cleaned.isdigit():
            raise PinInvalidError("The PIN is digits only. Check the e-mail from Quotex.")
        self._changed = asyncio.Event()
        pending.set_result(cleaned)
        await self._wait_for_change()
        return await self.status()

    async def _stop_running(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._pin = None
        self._prompt = None

    async def cancel(self) -> QuotexLoginStatus:
        await self._stop_running()
        self._message = None
        return await self.status()

    async def log_out(self) -> QuotexLoginStatus:
        """Forget the stored login (the next engine start logs in with the password again)."""
        if self._engine_running():
            raise EngineRunningError(
                "Stop the trading engine first: it is using the Quotex login now."
            )
        await self._stop_running()
        await self._vault.delete("quotex_session", internal_ok=True)
        self._message = None
        log.info("quotex_logged_out")
        return await self.status()
