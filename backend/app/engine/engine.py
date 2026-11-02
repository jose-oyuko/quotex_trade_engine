"""The engine: Telegram -> pipeline -> chain manager -> executor -> Quotex adapter, wired together.

This is only composition: every rule lives in the component it belongs to. Tests build it with the
fake Telegram source and the fake adapter; the application builds it with the real ones.
"""

from __future__ import annotations

import asyncio

from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.records import GroupRecord, GroupSettingsRecord
from app.engine.executor import RESULT_MARGIN_S, Executor
from app.engine.manager import ChainManager, RecoverySummary
from app.events.bus import EventBus
from app.quotex.base import QuotexAdapter
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, PipelineConfig, SignalPipeline, Sleeper
from app.telegram.listener import TelegramListener
from app.telegram.source import TelegramSource


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
    ) -> None:
        self.adapter = adapter
        self._tasks = tasks
        self.executor = Executor(adapter, clock=clock, bus=bus, result_margin_s=result_margin_s)
        self.manager = ChainManager(executor=self.executor, bus=bus, clock=clock, tasks=tasks)
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
            source, handler=self.pipeline.handle, bus=bus, clock=clock, tasks=tasks
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

    # --- life cycle ---

    def load(self, recovery: RecoveryState) -> RecoverySummary:
        """Rebuild the in-memory state from the database: groups first, then flag what was in
        flight when we last stopped."""
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
