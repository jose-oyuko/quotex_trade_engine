"""The engine: Telegram -> pipeline -> chain manager -> executor -> broker adapters, wired together,
with the trading-session scheduler (D-71) feeding the same chain manager from a timer.

This is only composition: every rule lives in the component it belongs to. Tests build it with the
fake Telegram source and fake adapters; the application builds it with the real ones. Without a
Telegram source (none is logged in) the engine runs with signals off: trading sessions still work.

There is one adapter per broker that has a login, Quotex and Deriv side by side (decision D-75).
They share one demo/real switch and one real-money permission.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import structlog

from app.brokers.base import BrokerAdapter
from app.brokers.errors import BrokerError
from app.core.backoff import BackoffPolicy
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.enums import AccountType, Broker, GroupSource
from app.domain.ids import new_id
from app.domain.records import GroupRecord, GroupSettingsRecord, RiskEventRecord, SessionRecord
from app.engine.errors import AccountSwitchRefusedError, TelegramNotConnectedError
from app.engine.executor import RESULT_MARGIN_S, Executor
from app.engine.manager import ChainManager, RecoverySummary
from app.engine.risk import RiskGuard, RiskLimits
from app.events.bus import EventBus
from app.events.types import AccountChanged, RiskTripped
from app.sessions.scheduler import TICK_S, SessionConfig, SessionScheduler
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, PipelineConfig, SignalPipeline, Sleeper
from app.telegram.listener import ListenerState, TelegramListener
from app.telegram.source import DialogKind, TelegramSource

CHAT_LIST_TIMEOUT_S = 30.0  # listing chats is one request to Telegram; never wait longer than this
DISCONNECT_TIMEOUT_S = 10.0  # the longest one broker may take to close when the engine stops

log = structlog.get_logger()


@dataclass(slots=True, frozen=True)
class ChatChoice:
    """A Telegram group or channel the owner could take signals from."""

    chat_id: int
    title: str
    kind: Literal["group", "channel"]


class Engine:
    def __init__(
        self,
        *,
        adapter: BrokerAdapter | None = None,
        adapters: Mapping[Broker, BrokerAdapter] | None = None,
        source: TelegramSource | None,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
        parsers: ParserRegistry | None = None,
        pipeline_config: PipelineConfig | None = None,
        sleep: Sleeper = asyncio.sleep,
        result_margin_s: float = RESULT_MARGIN_S,
        risk_limits: RiskLimits | None = None,
        telegram_backoff: BackoffPolicy | None = None,
        session_sleep: Sleeper | None = None,
        session_tick_s: float = TICK_S,
    ) -> None:
        brokers: dict[Broker, BrokerAdapter] = dict(adapters or {})
        if adapter is not None:  # the one-broker shorthand (tests): it is Quotex
            brokers.setdefault(Broker.QUOTEX, adapter)
        if not brokers:
            raise ValueError("the engine needs at least one broker")
        self.adapters: Mapping[Broker, BrokerAdapter] = brokers
        self._connecting: list[asyncio.Task[None]] = []
        self._enabled_groups: set[int] = set()  # Telegram groups that are switched on
        self._source = source
        self._tasks = tasks
        self._bus = bus
        self._clock = clock
        self.guard = RiskGuard(clock=clock, bus=bus, limits=risk_limits)
        self.executor = Executor(
            brokers, guard=self.guard, clock=clock, bus=bus, result_margin_s=result_margin_s
        )
        self.manager = ChainManager(
            executor=self.executor, guard=self.guard, bus=bus, clock=clock, tasks=tasks
        )
        self.pipeline = SignalPipeline(
            bus=bus,
            clock=clock,
            parsers=parsers or ParserRegistry(),
            tasks=tasks,
            on_signal=self.manager.on_signal,
            config=pipeline_config,
            sleep=sleep,
        )
        self.listener: TelegramListener | None = (
            None
            if source is None
            else TelegramListener(
                source,
                handler=self.pipeline.handle,
                bus=bus,
                clock=clock,
                tasks=tasks,
                backoff=telegram_backoff,
            )
        )
        self.scheduler = SessionScheduler(
            manager=self.manager,
            guard=self.guard,
            executor=self.executor,
            bus=bus,
            clock=clock,
            tasks=tasks,
            sleep=session_sleep or sleep,
            tick_s=session_tick_s,
        )

    @property
    def account_type(self) -> AccountType:
        """The account every broker is on (one switch for all)."""
        return self.executor.account_type

    def brokers_in_use(self) -> set[Broker]:
        """The brokers an enabled group or session trades on (for the "not connected" banner)."""
        used = {self.manager.group_broker(g) for g in self._enabled_groups}
        used |= {c.session.broker for c in self.scheduler.sessions() if c.session.enabled}
        return used

    @property
    def telegram_enabled(self) -> bool:
        """False when no Telegram login was available: signals are off, sessions still run."""
        return self.listener is not None

    # --- groups (the API of Phase 6 will call these when a group is created or edited) ---

    def set_group(self, group: GroupRecord, settings: GroupSettingsRecord) -> None:
        self.manager.set_group(settings, group.broker)
        if group.id is not None and group.source is GroupSource.TELEGRAM:
            if group.enabled:
                self._enabled_groups.add(group.id)
            else:
                self._enabled_groups.discard(group.id)
        if group.source is GroupSource.SESSION or group.telegram_chat_id is None:
            return  # a session's hidden group has no chat: only its strategy settings matter
        self.pipeline.set_route(GroupRoute.from_records(group, settings))
        if self.listener is None:
            return
        if group.enabled:
            self.listener.subscribe(group.telegram_chat_id)
        else:
            self.listener.unsubscribe(group.telegram_chat_id)

    def remove_group(self, group: GroupRecord) -> None:
        if group.telegram_chat_id is not None:
            self.pipeline.remove_route(group.telegram_chat_id)
            if self.listener is not None:
                self.listener.unsubscribe(group.telegram_chat_id)
        if group.id is not None:
            self.manager.remove_group(group.id)
            self._enabled_groups.discard(group.id)

    # --- trading sessions (the API calls these when a session is saved, edited or deleted) ---

    def set_session(self, session: SessionRecord, settings: GroupSettingsRecord) -> None:
        self.scheduler.set_session(SessionConfig(session, settings))

    def remove_session(self, session_id: int) -> None:
        self.scheduler.remove_session(session_id)

    async def switch_account(self, account_type: AccountType) -> None:
        """Move between demo and real. Refused while any chain or trade is running (their stakes
        and results belong to the account they started on); real also needs the owner's
        permission."""
        if self.scheduler.active_run is not None:
            raise AccountSwitchRefusedError(
                "a trading session is running: stop it (and let its chains finish) first"
            )
        if self.manager.active_chains() or self.guard.open_trades:
            raise AccountSwitchRefusedError(
                f"{len(self.manager.active_chains())} chain(s) and {self.guard.open_trades} "
                "trade(s) are still running: wait for them or end them first"
            )
        await self._switch_all(account_type)
        now = self._clock.now()
        self._bus.publish(AccountChanged(occurred_at=now, account_type=account_type))
        if account_type is AccountType.REAL:  # the one switch that moves real money: on the record
            self._bus.publish(
                RiskTripped(
                    occurred_at=now,
                    risk_event=RiskEventRecord(
                        id=new_id(),
                        occurred_at=now,
                        kind="switched_to_real",
                        message="The account was switched to REAL money: trades now use real funds",
                        group_id=None,
                    ),
                )
            )

    async def _switch_all(self, account_type: AccountType) -> None:
        """Every broker moves, or none does: a broker that cannot (no real login, no permission)
        refuses the switch, and the ones already moved go back."""
        moved: list[tuple[BrokerAdapter, AccountType]] = []
        for broker, adapter in self.adapters.items():
            before = adapter.account_type
            try:
                await adapter.set_account_type(account_type)
            except BrokerError as exc:
                for done, previous in reversed(moved):
                    with contextlib.suppress(BrokerError):
                        await done.set_account_type(previous)
                if len(self.adapters) == 1:
                    raise
                raise AccountSwitchRefusedError(
                    f"{broker.label} cannot switch to {account_type.value}: {exc}"
                ) from exc
            moved.append((adapter, before))

    def set_real_allowed(self, allowed: bool) -> None:
        for adapter in self.adapters.values():
            adapter.set_real_allowed(allowed)

    # --- Telegram chats (for the "choose a group" picker) ---

    async def list_chats(self, *, timeout_s: float | None = None) -> list[ChatChoice]:
        """The chats the logged-in Telegram account is in. Read-only, and it uses the connection the
        listener already has: asking never starts a second login on the same session file."""
        if (
            self.listener is None
            or self._source is None
            or self.listener.state is not ListenerState.CONNECTED
        ):
            raise TelegramNotConnectedError("Telegram is not connected")
        async with asyncio.timeout(CHAT_LIST_TIMEOUT_S if timeout_s is None else timeout_s):
            dialogs = await self._source.list_dialogs()
        return [
            ChatChoice(
                chat_id=d.chat_id,
                title=d.title,
                kind="group" if d.kind is DialogKind.GROUP else "channel",
            )
            for d in dialogs
            if d.kind is not DialogKind.USER  # signals come from groups and channels
        ]

    # --- life cycle ---

    def load(self, recovery: RecoveryState) -> RecoverySummary:
        """Rebuild the in-memory state from the database: groups first, then flag what was in
        flight when we last stopped."""
        self.guard.load(recovery.app_settings, recovery.recent_settled_trades)
        settings = {s.group_id: s for s in recovery.group_settings}
        for group in recovery.groups:
            if group.id is not None and group.id in settings:
                self.set_group(group, settings[group.id])
        for session in recovery.sessions:
            if session.group_id in settings:
                self.set_session(session, settings[session.group_id])
        self.scheduler.recover(recovery.unfinished_runs)
        return self.manager.recover(recovery)

    async def start(self, recovery: RecoveryState) -> RecoverySummary:
        summary = self.load(recovery)
        # Connecting may take long (retries with backoff): it must not hold up start-up, and
        # signals that come before it succeeds are skipped ("... is not connected").
        for broker, adapter in self.adapters.items():
            self._connecting.append(
                self._tasks.spawn(adapter.connect(retry_forever=True), name=f"{broker}-connect")
            )
        if self.listener is not None:
            self.listener.start()
        self.scheduler.start()
        return summary

    async def stop(self) -> None:
        """Stop opening pairs, stop taking signals, stop the chains, then close the connections."""
        await self.scheduler.stop()
        if self.listener is not None:
            await self.listener.stop()
        await self.manager.stop()
        # A broker still trying to log in is told to stop first (otherwise its retry loop would
        # outlive the engine), then each one closes, with a time limit: Ctrl+C must never hang.
        for task in self._connecting:
            task.cancel()
        for broker, adapter in self.adapters.items():
            try:
                await asyncio.wait_for(adapter.disconnect(), DISCONNECT_TIMEOUT_S)
            except TimeoutError:
                log.warning("broker_disconnect_timeout", broker=broker.value)
            except Exception:
                log.warning("broker_disconnect_failed", broker=broker.value, exc_info=True)
        if self._connecting:
            await asyncio.gather(*self._connecting, return_exceptions=True)
            self._connecting.clear()
