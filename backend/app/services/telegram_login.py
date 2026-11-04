"""Logging in to Telegram from the dashboard: phone number, code, and (if the account has it) the
two-step verification password. The result is a session kept encrypted in the database (D-65).

The login is a conversation with Telegram of several steps, so it lives here, in memory, as a small
state machine: the page can be reloaded, or opened in another browser, and shows the step the login
is at. It is not saved anywhere until it succeeds, and it is forgotten after ten minutes, when
Telegram's code is stale anyway (and whenever the application restarts).

Only one login at a time, and only while the engine is stopped: the engine and a login would
otherwise both be a connection of the same account.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import structlog

from app.core.clock import Clock
from app.core.config import Settings
from app.engine.controller import EngineController, EngineState
from app.engine.logins import login_items
from app.services.login_errors import EngineRunningError, LoginProblem, WrongStepError
from app.telegram.login import normalise_phone
from app.telegram.source import (
    ApiCredentialsError,
    CodeExpiredError,
    CodeInvalidError,
    FloodWaitLoginError,
    PasswordInvalidError,
    PasswordRequiredError,
    PhoneInvalidError,
    TelegramError,
    TelegramLoginError,
    TelegramSource,
)
from app.vault.errors import VaultError
from app.vault.store import SecretStore

log = structlog.get_logger()

LOGIN_LIFETIME = timedelta(minutes=10)
MAX_RESENDS = 2
STEP_TIMEOUT_S = 40.0  # one call to Telegram; never wait longer than this

type SourceFactory = Callable[[int, str, str | None], TelegramSource]


class LoginState(StrEnum):
    LOGGED_OUT = "logged_out"
    CODE_SENT = "code_sent"
    PASSWORD_NEEDED = "password_needed"  # noqa: S105 - a step name, not a password
    LOGGED_IN = "logged_in"


class TelegramLoginProblem(LoginProblem):
    """Base of the errors the Telegram login steps raise; the messages are for the owner."""


class NotConfiguredError(TelegramLoginProblem):
    """The API id and hash are not stored yet."""


class CodeWrongError(TelegramLoginProblem):
    """The code was wrong: type it again."""


class CodeStaleError(TelegramLoginProblem):
    """The code expired: the login starts again."""


class PasswordWrongError(TelegramLoginProblem):
    """The two-step verification password was wrong: type it again."""


class RefusedError(TelegramLoginProblem):
    """Telegram refused this step (phone, API id/hash...); the message says what to change."""


class MustWaitError(TelegramLoginProblem):
    """Telegram asks to wait before another attempt."""

    def __init__(self, seconds: int) -> None:
        minutes = max(1, round(seconds / 60))
        super().__init__(
            f"Telegram asks you to wait before trying again: about {minutes} minute(s) "
            f"({seconds} seconds)."
        )
        self.seconds = seconds


@dataclass(slots=True, frozen=True)
class LoginStatus:
    state: LoginState
    configured: bool  # the API id and hash are stored (or in .env)
    phone_hint: str | None  # the number with the middle hidden
    delivery: str | None  # where Telegram says it sent the code
    resends_left: int
    problem: str | None  # why a stored login cannot be used
    engine_running: bool


def hide_phone(phone: str) -> str:
    """`+254712345678` -> `+254•••••678`."""
    if len(phone) <= 7:
        return phone
    return phone[:4] + "•" * (len(phone) - 7) + phone[-3:]


@dataclass(slots=True)
class _Attempt:
    source: TelegramSource
    phone: str
    delivery: str
    started: datetime
    resends: int = 0
    password_needed: bool = False


class TelegramLoginService:
    def __init__(
        self,
        *,
        vault: SecretStore,
        settings: Callable[[], Settings],
        source_factory: SourceFactory,
        controller: Callable[[], EngineController | None],
        clock: Clock,
    ) -> None:
        self._vault = vault
        self._settings = settings
        self._make_source = source_factory
        self._controller = controller
        self._clock = clock
        self._attempt: _Attempt | None = None
        self._lock = asyncio.Lock()

    # --- what the page shows ---

    def _engine_running(self) -> bool:
        controller = self._controller()
        return controller is not None and controller.state in (
            EngineState.RUNNING,
            EngineState.STARTING,
            EngineState.STOPPING,
        )

    async def _expire(self) -> None:
        attempt = self._attempt
        if attempt is not None and self._clock.now() - attempt.started > LOGIN_LIFETIME:
            await self._drop()

    async def _drop(self) -> None:
        attempt, self._attempt = self._attempt, None
        if attempt is not None:
            with contextlib.suppress(Exception):
                await attempt.source.disconnect()

    async def status(self) -> LoginStatus:
        await self._expire()
        settings = self._settings()
        items = {i.label: i for i in await login_items(settings, self._vault)}
        configured = items["Telegram API id"].present and items["Telegram API hash"].present
        login = items["Telegram login"]
        problem = (
            "The stored Telegram login cannot be read (SECRET_KEY is not the key it was stored "
            "with). Log in again."
            if login.source == "unreadable"
            else None
        )
        attempt = self._attempt
        if attempt is not None:
            state = LoginState.PASSWORD_NEEDED if attempt.password_needed else LoginState.CODE_SENT
            return LoginStatus(
                state=state,
                configured=configured,
                phone_hint=hide_phone(attempt.phone),
                delivery=attempt.delivery,
                resends_left=MAX_RESENDS - attempt.resends,
                problem=problem,
                engine_running=self._engine_running(),
            )
        return LoginStatus(
            state=LoginState.LOGGED_IN if login.present else LoginState.LOGGED_OUT,
            configured=configured,
            phone_hint=await self._stored_phone_hint() if login.present else None,
            delivery=None,
            resends_left=0,
            problem=problem,
            engine_running=self._engine_running(),
        )

    async def _stored_phone_hint(self) -> str | None:
        try:
            phone = await self._vault.get("telegram_phone")
        except VaultError:
            return None
        return hide_phone(phone) if phone else None

    # --- the steps ---

    async def _credentials(self) -> tuple[int, str]:
        """The API id and hash: stored in the dashboard, else `.env`."""
        settings = self._settings()
        try:
            stored_id = await self._vault.get("telegram_api_id")
            stored_hash = await self._vault.get("telegram_api_hash")
        except VaultError as exc:
            raise NotConfiguredError(str(exc)) from exc
        api_id = int(stored_id) if stored_id else settings.telegram_api_id
        api_hash = stored_hash or (
            settings.telegram_api_hash.get_secret_value() if settings.telegram_api_hash else ""
        )
        if api_id is None or not api_hash.strip():
            raise NotConfiguredError(
                "The Telegram API id and hash are not stored yet. Create them at "
                "https://my.telegram.org ('API development tools') and enter them first."
            )
        return api_id, api_hash.strip()

    def _must_be_stopped(self) -> None:
        if self._engine_running():
            raise EngineRunningError(
                "Stop the trading engine first: it is using the Telegram login now."
            )

    async def start(self, phone_text: str) -> LoginStatus:
        """Step 1: ask Telegram to send a code to this number."""
        async with self._lock:
            self._must_be_stopped()
            try:
                phone = normalise_phone(phone_text)
            except TelegramLoginError as exc:
                raise RefusedError(str(exc)) from exc
            api_id, api_hash = await self._credentials()
            await self._drop()  # a new number starts again
            source = self._make_source(api_id, api_hash, None)
            try:
                async with asyncio.timeout(STEP_TIMEOUT_S):
                    await source.connect()
                    delivery = await source.request_code(phone)
            except BaseException as exc:
                with contextlib.suppress(Exception):
                    await source.disconnect()
                raise self._translate(exc) from exc
            self._attempt = _Attempt(source, phone, delivery, self._clock.now())
            log.info("telegram_login_code_sent")
        return await self.status()

    async def resend(self) -> LoginStatus:
        """Ask Telegram to send the same code another way (SMS, a call)."""
        async with self._lock:
            attempt = self._current(LoginState.CODE_SENT)
            if attempt.resends >= MAX_RESENDS:
                raise RefusedError("Telegram has no other way left to send the code. Start again.")
            try:
                async with asyncio.timeout(STEP_TIMEOUT_S):
                    attempt.delivery = await attempt.source.resend_code(attempt.phone)
            except BaseException as exc:
                raise self._translate(exc) from exc
            attempt.resends += 1
        return await self.status()

    async def submit_code(self, code: str) -> LoginStatus:
        """Step 2: the code Telegram sent. May lead to the password step, or finish the login."""
        async with self._lock:
            attempt = self._current(LoginState.CODE_SENT)
            try:
                async with asyncio.timeout(STEP_TIMEOUT_S):
                    await attempt.source.sign_in(attempt.phone, code.strip())
            except PasswordRequiredError:
                attempt.password_needed = True
                return await self.status()
            except CodeExpiredError as exc:
                await self._drop()
                raise CodeStaleError(
                    "That code has expired. Start again: Telegram will send a new one."
                ) from exc
            except BaseException as exc:
                raise self._translate(exc) from exc
            await self._finish(attempt)
        return await self.status()

    async def submit_password(self, password: str) -> LoginStatus:
        """Step 3, only for an account with two-step verification."""
        async with self._lock:
            attempt = self._current(LoginState.PASSWORD_NEEDED)
            try:
                async with asyncio.timeout(STEP_TIMEOUT_S):
                    await attempt.source.sign_in_password(password)
            except BaseException as exc:
                raise self._translate(exc) from exc
            await self._finish(attempt)
        return await self.status()

    async def cancel(self) -> LoginStatus:
        async with self._lock:
            await self._drop()
        return await self.status()

    async def log_out(self) -> LoginStatus:
        """Forget the login here, and end it on Telegram's side if Telegram can be reached."""
        async with self._lock:
            self._must_be_stopped()
            await self._drop()
            try:
                session = await self._vault.get("telegram_session")
                api_id, api_hash = await self._credentials()
            except (VaultError, TelegramLoginProblem):
                session = None
            if session:
                source = self._make_source(api_id, api_hash, session)
                try:
                    async with asyncio.timeout(STEP_TIMEOUT_S):
                        await source.connect()
                        await source.log_out()
                except Exception:
                    # The login is removed here either way; Telegram will show the session in its
                    # list of devices until the owner ends it there.
                    log.warning("telegram_logout_not_confirmed", exc_info=True)
                finally:
                    with contextlib.suppress(Exception):
                        await source.disconnect()
            await self._vault.delete("telegram_session", internal_ok=True)
            await self._vault.delete("telegram_phone", internal_ok=True)
            self._remove_session_file()
            log.info("telegram_logged_out")
        return await self.status()

    # --- helpers ---

    def _remove_session_file(self) -> None:
        """The file the command-line login makes: it is the same login, so it goes too."""
        path = self._settings().telegram_session_path
        with contextlib.suppress(OSError):
            path.with_name(path.name + ".session").unlink(missing_ok=True)

    def _current(self, step: LoginState) -> _Attempt:
        attempt = self._attempt
        if attempt is None or self._clock.now() - attempt.started > LOGIN_LIFETIME:
            raise WrongStepError(
                "There is no login in progress (it may have timed out). Start again."
            )
        if (step is LoginState.PASSWORD_NEEDED) != attempt.password_needed:
            raise WrongStepError("That is not the step this login is at. Reload the page.")
        return attempt

    async def _finish(self, attempt: _Attempt) -> None:
        session = attempt.source.session_string()
        if not session:
            raise RefusedError("Telegram accepted the login but gave no session. Try again.")
        await self._vault.put("telegram_session", session, internal_ok=True)
        await self._vault.put("telegram_phone", attempt.phone, internal_ok=True)
        await self._drop()
        log.info("telegram_logged_in")

    @staticmethod
    def _translate(exc: BaseException) -> Exception:
        """Telegram's refusals as errors with words for the owner."""
        if isinstance(exc, FloodWaitLoginError):
            return MustWaitError(exc.seconds)
        if isinstance(exc, CodeInvalidError):
            return CodeWrongError("That code is not right. Check it and type it again.")
        if isinstance(exc, PasswordInvalidError):
            return PasswordWrongError("That two-step verification password is not right.")
        if isinstance(exc, (PhoneInvalidError, ApiCredentialsError, TelegramLoginError)):
            return RefusedError(str(exc))
        if isinstance(exc, TimeoutError):
            return RefusedError("Telegram did not answer in time. Try again in a moment.")
        if isinstance(exc, TelegramError):
            return RefusedError(f"Could not reach Telegram: {exc}")
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            raise exc
        log.warning("telegram_login_unexpected_error", exc_info=exc)
        return RefusedError("Something went wrong talking to Telegram. See the log and try again.")
