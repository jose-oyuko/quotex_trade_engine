"""The engine: Telegram -> pipeline -> chain manager -> executor -> Quotex adapter, wired together.

This is only composition: every rule lives in the component it belongs to. Tests build it with the
fake Telegram source and the fake adapter; the application builds it with the real ones.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from app.core.backoff import BackoffPolicy
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.enums import AccountType
from app.domain.records import GroupRecord, GroupSettingsRecord
from app.engine.errors import AccountSwitchRefusedError, TelegramNotConnectedError
from app.engine.executor import RESULT_MARGIN_S, Executor
from app.engine.manager import ChainManager, RecoverySummary
from app.engine.risk import RiskGuard, RiskLimits
from app.events.bus import EventBus
from app.events.types import AccountChanged
from app.quotex.base import QuotexAdapter
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, PipelineConfig, SignalPipeline, Sleeper
from app.telegram.listener import ListenerState, TelegramListener
from app.telegram.source import DialogKind, TelegramSource

CHAT_LIST_TIMEOUT_S = 30.0  # listing chats is one request to Telegram; never wait longer than this


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
        adapter: QuotexAdapter,
        source: TelegramSource,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
        parsers: ParserRegistry | None = None,
        pipeline_config: PipelineConfig | None = None,
        sleep: Sleeper = asyncio.sleep,
        result_margin_s: float = RESULT_MARGIN_S,
        risk_limits: RiskLimits | None = None,
        telegram_backoff: BackoffPolicy | None = None,
    ) -> None:
        self.adapter = adapter
        self._source = source
        self._tasks = tasks
        self._bus = bus
        self._clock = clock
        self.guard = RiskGuard(clock=clock, bus=bus, limits=risk_limits)
        self.executor = Executor(
            adapter, guard=self.guard, clock=clock, bus=bus, result_margin_s=result_margin_s
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
        self.listener = TelegramListener(
            source,
            handler=self.pipeline.handle,
            bus=bus,
            clock=clock,
            tasks=tasks,
            backoff=telegram_backoff,
        )

    # --- groups (the API of Phase 6 will call these when a group is created or edited) ---

    def set_group(self, group: GroupRecord, settings: GroupSettingsRecord) -> None:
        route = GroupRoute.from_records(group, settings)
        self.pipeline.set_route(route)
        self.manager.set_group(settings)
        if group.enabled:
            self.listener.subscribe(group.telegram_chat_id)
        else:
            self.listener.unsubscribe(group.telegram_chat_id)

    def remove_group(self, group: GroupRecord) -> None:
        self.pipeline.remove_route(group.telegram_chat_id)
        self.listener.unsubscribe(group.telegram_chat_id)
        if group.id is not None:
            self.manager.remove_group(group.id)

    async def switch_account(self, account_type: AccountType) -> None:
        """Move between demo and real. Refused while any chain or trade is running (their stakes
        and results belong to the account they started on); real also needs QUOTEX_ALLOW_REAL."""
        if self.manager.active_chains() or self.guard.open_trades:
            raise AccountSwitchRefusedError(
                f"{len(self.manager.active_chains())} chain(s) and {self.guard.open_trades} "
                "trade(s) are still running: wait for them or end them first"
            )
        await self.adapter.set_account_type(account_type)
        self._bus.publish(AccountChanged(occurred_at=self._clock.now(), account_type=account_type))

    # --- Telegram chats (for the "choose a group" picker) ---

    async def list_chats(self, *, timeout_s: float | None = None) -> list[ChatChoice]:
        """The chats the logged-in Telegram account is in. Read-only, and it uses the connection the
        listener already has: asking never starts a second login on the same session file."""
        if self.listener.state is not ListenerState.CONNECTED:
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
        return self.manager.recover(recovery)

    async def start(self, recovery: RecoveryState) -> RecoverySummary:
        summary = self.load(recovery)
        # Connecting may take long (retries with backoff): it must not hold up start-up, and
        # orders placed before it succeeds are refused cleanly (the chain ends `failed`).
        self._tasks.spawn(self.adapter.connect(retry_forever=True), name="quotex-connect")
        self.listener.start()
        return summary

    async def stop(self) -> None:
        """Stop taking signals, stop the chains, then close the connections."""
        await self.listener.stop()
        await self.manager.stop()
        await self.adapter.disconnect()
