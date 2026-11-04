"""Starts, stops and restarts the trading engine while the application keeps running (D-63).

The engine used to be built once, at start-up, if `ENGINE_ENABLED` said so. Now the owner starts and
stops it from the dashboard, as often as they like, and this class is the only thing that does it:
one at a time (a second request while one is in progress is refused, not queued), always in the same
order, and always leaving a state the dashboard can describe in words.

Starting builds a fresh engine, so nothing of the old one is reused: the risk guard, the chains and
the connections are all new, rebuilt from the database like after a restart (D-35). Stopping marks
whatever was in flight as `unknown` at once, which is what the next start would have done.

The engine itself is untouched by this: the path from a signal to an order is the same code.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum

import structlog

from app.core.clock import Clock
from app.core.errors import DomainError
from app.db.recovery import RecoveryState
from app.domain.enums import AccountType
from app.domain.ids import new_id
from app.domain.records import RiskEventRecord
from app.engine.engine import Engine
from app.engine.errors import EngineBusyError, EngineStartError, RealTradingInUseError
from app.engine.flags import EngineFlags
from app.engine.manager import RecoverySummary
from app.events.bus import EventBus
from app.events.types import RiskTripped

log = structlog.get_logger()

MAX_ERROR_LENGTH = 400


class EngineState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"  # the last start did not work; `error` says why


def _message(exc: BaseException) -> str:
    """Words for the owner. Our own errors are already that; for anything else the type is named."""
    text = str(exc) if isinstance(exc, DomainError) else f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())[:MAX_ERROR_LENGTH]


class EngineController:
    def __init__(
        self,
        *,
        build: Callable[[bool], Awaitable[Engine]],
        recovery: Callable[[], Awaitable[RecoveryState]],
        flush: Callable[[], Awaitable[object]],
        set_trading: Callable[[Engine | None], None],
        flags: EngineFlags,
        bus: EventBus,
        clock: Clock,
        desired: bool,
        real_allowed: bool,
    ) -> None:
        self._build = build
        self._recovery = recovery
        self._flush = flush
        self._set_trading = set_trading
        self._flags = flags
        self._bus = bus
        self._clock = clock
        self._desired = desired
        self._real_allowed = real_allowed
        self._engine: Engine | None = None
        self._state = EngineState.STOPPED
        self._error: str | None = None
        self._since: datetime | None = None
        self._busy = False

    # --- what the dashboard shows ---

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def since(self) -> datetime | None:
        return self._since

    @property
    def desired(self) -> bool:
        """The engine will be started when the application starts."""
        return self._desired

    @property
    def real_allowed(self) -> bool:
        return self._real_allowed

    @property
    def engine(self) -> Engine | None:
        return self._engine

    def _enter(self, state: EngineState, error: str | None = None) -> None:
        self._state = state
        self._error = error
        self._since = self._clock.now()
        log.info("engine_state", state=state.value, error=error)

    # --- the three actions ---

    def _begin(self) -> None:
        if self._busy:
            raise EngineBusyError("The engine is being started or stopped. Wait a moment.")
        self._busy = True

    async def start(self) -> RecoverySummary | None:
        """Build and start the engine. Does nothing if it is running. `EngineStartError` if it
        cannot start (the reason is also in `error` until the next attempt)."""
        self._begin()
        try:
            return await self._start()
        finally:
            self._busy = False

    async def stop(self) -> None:
        """Stop the engine (nothing is left open on our side: see the module docstring)."""
        self._begin()
        try:
            await self._stop(remember=True)
        finally:
            self._busy = False

    async def restart(self) -> RecoverySummary | None:
        self._begin()
        try:
            await self._stop(remember=False)
            return await self._start()
        finally:
            self._busy = False

    async def shutdown(self) -> None:
        """The application is closing: stop the engine but keep the owner's choice, so the next
        start of the application resumes it."""
        self._busy = True
        try:
            engine, self._engine = self._engine, None
            if engine is not None:
                self._set_trading(None)
                await engine.stop()
        finally:
            self._busy = False

    async def _start(self) -> RecoverySummary | None:
        if self._engine is not None:
            return None
        self._enter(EngineState.STARTING)
        engine: Engine | None = None
        try:
            engine = await self._build(self._real_allowed)
            await self._flush()  # the database must be up to date before it is read
            summary = await engine.start(await self._recovery())
        except Exception as exc:
            if engine is not None:
                with contextlib.suppress(Exception):
                    await engine.stop()
            message = _message(exc)
            log.warning("engine_start_failed", error=message, exc_info=True)
            self._enter(EngineState.FAILED, message)
            raise EngineStartError(message) from exc
        self._engine = engine
        self._set_trading(engine)
        self._desired = True
        await self._flags.set_desired(True)
        self._enter(EngineState.RUNNING)
        return summary

    async def _stop(self, *, remember: bool) -> None:
        engine = self._engine
        if engine is None:
            self._enter(EngineState.STOPPED)  # also clears an earlier failure
            if remember:
                self._desired = False
                await self._flags.set_desired(False)
            return
        self._enter(EngineState.STOPPING)
        error: str | None = None
        try:
            await engine.stop()
        except Exception as exc:
            error = f"It stopped, but not cleanly: {_message(exc)}"
            log.warning("engine_stop_failed", exc_info=True)
        finally:
            self._engine = None
            self._set_trading(None)
        # What was in flight can no longer be followed: say so now, as the next start would.
        await self._flush()
        engine.manager.recover(await self._recovery())
        if remember:
            self._desired = False
            await self._flags.set_desired(False)
        self._enter(EngineState.STOPPED, error)

    # --- real money ---

    async def set_real_allowed(self, allowed: bool) -> None:
        """The owner's permission to switch to the REAL account (decision D-15). Written to the risk
        log. Refused if it would be taken away while REAL is the account in use."""
        engine = self._engine
        if not allowed and engine is not None and engine.adapter.account_type is AccountType.REAL:
            raise RealTradingInUseError(
                "The REAL account is in use. Switch back to the demo account first."
            )
        if allowed == self._real_allowed:
            return
        await self._flags.set_allow_real(allowed)
        self._real_allowed = allowed
        if engine is not None:
            engine.adapter.set_real_allowed(allowed)
        now = self._clock.now()
        self._bus.publish(
            RiskTripped(
                occurred_at=now,
                risk_event=RiskEventRecord(
                    id=new_id(),
                    occurred_at=now,
                    kind="real_trading_allowed" if allowed else "real_trading_disallowed",
                    message=(
                        "The owner allowed real-money trading: the REAL account can be switched to"
                        if allowed
                        else "The owner switched real-money trading off"
                    ),
                    group_id=None,
                ),
            )
        )
        log.warning("real_trading_permission", allowed=allowed)
