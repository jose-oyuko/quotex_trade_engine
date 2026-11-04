"""FastAPI application and lifespan. Later phases start the engine from the lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, ws
from app.api.deps import current_user
from app.api.errors import install_error_handlers
from app.api.hub import Hub
from app.api.openapi import build_openapi
from app.api.routers import auth, chains, control, groups, reports, telegram, trades
from app.api.routers import settings as settings_router
from app.api.schemas.common import ErrorBody
from app.api.security import SecurityMiddleware, TokenBucket
from app.api.snapshot import SnapshotBuilder
from app.api.static import mount_frontend
from app.auth.service import AuthService
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.tasks import TaskSupervisor
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import schema_is_current
from app.db.recovery import load_recovery_state
from app.db.writer import DBWriter
from app.engine.engine import Engine
from app.engine.factory import build_engine
from app.events.bus import EventBus
from app.services.app_config import ConfigService
from app.services.groups import GroupService
from app.services.live import LiveState
from app.services.risk_settings import RiskSettingsService
from app.signals.parsers.registry import ParserRegistry
from app.vault.crypto import Cipher
from app.vault.store import SecretStore

VERSION = "0.1.0"
log = structlog.get_logger()


type EngineBuilder = Callable[[Settings, EventBus, TaskSupervisor], Engine]


class DatabaseNotMigratedError(RuntimeError):
    """The database file is missing tables or is behind the code."""


def create_app(
    settings: Settings | None = None, *, engine_builder: EngineBuilder = build_engine
) -> FastAPI:
    """Build the application. Tests pass their own settings (and a fake-backed engine builder)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(
            settings.log_level,
            json_output=settings.environment == "production",
            log_file=settings.log_path if settings.log_to_file else None,
            max_bytes=settings.log_max_mb * 1024 * 1024,
            backups=settings.log_backups,
            secrets=settings.secret_values(),
        )
        log.info("startup", environment=settings.environment, host=settings.host)

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(settings.database_url)
        if not await schema_is_current(engine):
            await engine.dispose()
            raise DatabaseNotMigratedError(
                "The database is missing or out of date. Run `npm run db:upgrade` "
                "(or `alembic upgrade head` in backend/) and start again."
            )
        session_factory = create_session_factory(engine)
        writer = DBWriter(app.state.bus, session_factory, app.state.tasks)
        writer.start()
        app.state.engine = engine
        app.state.writer = writer
        app.state.session_factory = session_factory

        recovery = await load_recovery_state(session_factory)
        app.state.recovery = recovery

        # What the owner saved in the dashboard wins over `.env` (decision D-58); read once, here.
        clock = SystemClock()
        config = ConfigService(settings, session_factory, clock)
        cfg = await config.effective()
        if cfg.log_level != settings.log_level:
            configure_logging(
                cfg.log_level,
                json_output=cfg.environment == "production",
                log_file=cfg.log_path if cfg.log_to_file else None,
                max_bytes=cfg.log_max_mb * 1024 * 1024,
                backups=cfg.log_backups,
                secrets=cfg.secret_values(),
            )
        app.state.settings = cfg
        app.state.config = config
        app.state.vault = SecretStore(
            session_factory,
            Cipher(cfg.secret_key.get_secret_value() if cfg.secret_key else None),
            clock,
        )

        # The live picture and the WebSocket hub listen from before the engine starts, so they see
        # every event it publishes, recovery's included.
        live = LiveState(recovery.app_settings)
        snapshots = SnapshotBuilder(
            settings=cfg, version=VERSION, live=live, engine=lambda: app.state.trading
        )
        hub = Hub(
            bus=app.state.bus,
            live=live,
            snapshots=snapshots,
            clock=clock,
            tasks=app.state.tasks,
            client_queue=cfg.ws_client_queue,
            heartbeat_s=cfg.ws_heartbeat_s,
        )
        hub.start()
        app.state.live = live
        app.state.snapshots = snapshots
        app.state.hub = hub
        app.state.groups = GroupService(
            session_factory, clock, lambda: app.state.trading, ParserRegistry().names
        )
        app.state.auth = AuthService(session_factory, clock)
        await app.state.auth.prepare()
        app.state.risk_settings = RiskSettingsService(
            app.state.bus, clock, live, lambda: app.state.trading
        )
        log.info(
            "recovery_loaded",
            groups=len(recovery.groups),
            open_chains=len(recovery.open_chains),
            unsettled_trades=len(recovery.unsettled_trades),
        )

        if cfg.engine_enabled:
            try:
                trading = engine_builder(cfg, app.state.bus, app.state.tasks)
                summary = await trading.start(recovery)
            except Exception:
                # e.g. a missing login: leave nothing half-started behind, then say what is wrong
                await hub.stop()
                await writer.stop()
                await app.state.tasks.shutdown()
                await engine.dispose()
                raise
            app.state.trading = trading
            log.info(
                "engine_started",
                chains_marked_unknown=summary.chains_marked_unknown,
                trades_marked_unknown=summary.trades_marked_unknown,
            )
        else:
            log.info("engine_disabled", hint="set ENGINE_ENABLED=true in backend/.env to start it")

        yield

        # Shutdown runs in reverse order of startup: the engine stops first (it publishes the last
        # events), then the writer drains its queue, so those events still reach the database.
        if app.state.trading is not None:
            await app.state.trading.stop()
        await hub.stop()
        await writer.stop()
        await app.state.tasks.shutdown()
        await engine.dispose()
        log.info("shutdown")

    app = FastAPI(
        title="Quotex Trade Engine",
        version=VERSION,
        lifespan=lifespan,
        responses={status: {"model": ErrorBody} for status in (404, 409, 422, 429, 500, 503)},
    )
    app.state.settings = settings
    app.state.tasks = TaskSupervisor()
    app.state.bus = EventBus()
    app.state.engine = None
    app.state.writer = None
    app.state.trading = None
    app.state.session_factory = None
    app.state.live = None
    app.state.snapshots = None
    app.state.hub = None
    app.state.groups = None
    app.state.risk_settings = None
    app.state.auth = None
    app.state.config = None
    app.state.vault = None

    development = settings.environment == "development"
    app.add_middleware(
        SecurityMiddleware,
        check_host=not settings.allow_public_bind,
        extra_origins=frozenset({settings.cors_origin}) if development else frozenset(),
        bucket=TokenBucket(settings.api_command_rate_per_s, settings.api_command_burst),
    )
    if development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.cors_origin],
            allow_methods=["*"],
            allow_headers=["Content-Type"],
        )

    install_error_handlers(app)
    # Public: the health check and the login routes. Everything else needs a logged-in owner, and
    # `tests/integration/test_api_auth.py` fails if a route is added without that protection.
    for public in (health.router, auth.router):
        app.include_router(public, prefix="/api/v1")
    for router in (
        groups.router,
        chains.router,
        trades.trades_router,
        trades.signals_router,
        control.router,
        reports.router,
        telegram.router,
        settings_router.router,
    ):
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(current_user)])
    app.include_router(ws.router)  # checks the session itself, before accepting
    mount_frontend(app, settings.frontend_dir)  # last: it answers every other path
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
