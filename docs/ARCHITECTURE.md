# Architecture

## 1. Goals

1. Live dashboard: track every trade, manage chains (stop, skip, pause), see balance and health.
2. Listen to **many Telegram groups**, each with its own strategy; handle many trades at once.
3. Reports that show whether a strategy really works (per group / asset / strategy / hour, chain depth).
4. Execution as close to real time as possible.
5. Persistent data (database) that never slows the trading path.

Non-goals for now: user accounts, multi-tenant hosting, mobile app, other brokers.

## 2. Components

```
                       ┌──────────────────────── one Python process (FastAPI, asyncio) ───────────────────────┐
 Telegram groups ──►   │ TelegramListener ──► SignalPipeline ──► ChainManager ──► Executor ──► QuotexAdapter ─┼──► Quotex
   (Telethon)          │   (many chats)        (parse, filter,     (per group/      (hot path)    (only module   │
                       │                        route to group)     asset chains)                 using pyquotex)│
                       │                              │                 │              │                       │
                       │                              └───────► EventBus (in-memory) ◄┘                       │
                       │                                            │            │                            │
                       │                                   DBWriter (queue)   WebSocket hub                    │
                       │                                            │            │                            │
                       │                                         SQLite       REST API                         │
                       └────────────────────────────────────────────┼────────────┼───────────────────────────┘
                                                                    │            ▼
                                                                    │     React + Vite dashboard (browser)
                                                                    ▼
                                                              Reports (read queries)
```

| Component | Responsibility |
|---|---|
| `TelegramListener` | One Telethon client; subscribes to the chats of all enabled groups; emits raw messages with a receive timestamp. |
| `SignalPipeline` | Parses messages (pluggable parsers), applies filters (payout, duplicates, entry time), resolves the group, emits `Signal`. Persists every message (signal inbox) off the hot path. |
| `ChainManager` | Owns all open **chains**. A chain = the original signal trade plus its follow-ups. Keyed by `(group_id, asset)`. Applies the group's strategy to decide the next step (direction, stake). |
| `Executor` | The hot path: take a decided trade, check limits, send the order through the adapter, then await the result and hand it back to the `ChainManager`. |
| `QuotexAdapter` | The only module that imports `pyquotex`. Interface in `app/quotex/base.py`; real implementation and a `FakeQuotexAdapter` for tests/demos. |
| `RiskGuard` | Global and per-group limits (max stake, max concurrent trades, exposure cap, daily stop-loss / profit target, kill switch). Consulted synchronously and from memory only. |
| `EventBus` | In-memory publish/subscribe. Every state change is an event (`signal.received`, `trade.opened`, `trade.settled`, `chain.advanced`, `chain.ended`, `risk.tripped`, `connection.changed` …). |
| `DBWriter` | Subscribes to events, batches them, writes to the database in a background task. Never awaited by the hot path. |
| `WebSocket hub` | Subscribes to events, pushes them to connected dashboards. |
| `REST API` | Commands (start/stop, pause group, stop chain …), configuration CRUD, history and report queries. |
| `Reports` | Read-only SQL aggregations over the stored trades/chains. |

## 3. Process model

- **One OS process, one asyncio event loop.** Telethon, the Quotex adapter, FastAPI and the engine all
  run on the same loop (FastAPI `lifespan` starts and stops the engine). This avoids inter-process
  messaging on the hot path.
- **Nothing may block the loop.** No `requests`, no synchronous DB calls, no `time.sleep`, no
  heavy CPU work. If a library is synchronous (parts of pyquotex do blocking HTTP), wrap it with
  `asyncio.to_thread` or isolate it in the adapter and **warm it up at startup**.
  *(Lesson from the old bot: a blocking profile request inside every `buy()` caused seconds of lag
  and froze the websocket.)*
- Background tasks are created through one helper that keeps a reference, logs exceptions and
  cancels cleanly on shutdown. No fire-and-forget `create_task` whose errors vanish.

## 4. The execution path (hot path)

```
Telegram message ─► parse ─► route to group ─► RiskGuard check (memory) ─► decide stake/direction (memory)
                 ─► adapter.place_order()  ─► ack ─► publish event  ... (everything else is async, after this)
```

Rules:

- Everything the hot path needs is **already in memory**: group config, strategy state, balance
  snapshot, payout table, server-time offset, asset open/closed flags. These are refreshed by
  background tasks and by websocket pushes, never fetched inline.
- **No database call** on the hot path. State changes are published as events; `DBWriter` persists them.
- **No logging at INFO volume with string formatting of big objects** on the hot path; use structured
  logs with cheap fields.
- Record monotonic timestamps at each step: `msg_received`, `parsed`, `decided`, `order_sent`,
  `order_acked`. Store them on the trade. The dashboard shows "signal → order" latency.
- **Wait for results by event, not by sleeping.** Trade settlement is awaited through the adapter's
  result future/event (poll interval ≤ 0.2 s inside the adapter, never a fixed `sleep(duration + N)`),
  with a timeout of `duration + 60 s` that raises a clear error.
- A follow-up trade is created the moment a loss is known; it does not wait for the previous trade's
  bookkeeping, the balance lookup or the database.

## 5. Concurrency model

- Each **group** has its own settings (strategy, base stake, max steps, multipliers, payout minimum,
  enabled flag). Settings are loaded into memory and updated in memory when edited.
- A **chain** is an object with its own state: `group_id`, `asset`, `origin_direction`, `step`,
  `consecutive_losses`, `status`. Chains are independent: two groups, or two assets in one group, can
  have chains running at the same time without sharing loss counters (the old bot had one global
  counter — that is exactly what this design removes).
- **Signals arriving while a flip-strategy chain is running for the same group are ignored**
  (decision D-9). For plain martingale / no-martingale they open their own chain.
- Each chain is driven by its own asyncio task (or an event-driven state machine) so a slow chain
  never delays another.
- A global `asyncio.Lock`-free design is preferred: state is mutated only on the event loop thread,
  so plain Python objects are safe as long as no `await` happens between a read and its dependent write
  (document any exception).

## 6. Persistence

- **SQLite in WAL mode**, accessed with SQLAlchemy 2.x async (`aiosqlite`). Alembic migrations.
- Schema is portable: no SQLite-only types or SQL; money stored as integer minor units or `Numeric`
  (decide in Phase 1, record in DECISIONS).
- Core tables (see `docs/DOMAIN.md` for fields): `groups`, `group_settings`, `signals` (inbox),
  `chains`, `trades`, `events` (optional audit), `balance_snapshots`, `risk_events`, `app_settings`.
- Writes are asynchronous (queue → batch → commit). Reads for the dashboard/reports use short
  read sessions and never block the writer for long.
- **Crash recovery:** on startup, load chains/trades that were open. Trades past their expiry are
  settled from Quotex history if possible, otherwise marked `unknown` and surfaced on the dashboard
  — never silently dropped.
- Demo and real data are separated by an `account_type` column on trades and chains, and every
  report filters on it.

## 7. API surface (built in Phase 6; the complete guide is `docs/API.md`)

- REST under `/api/v1`, JSON, typed with Pydantic models, versioned. Examples:
  `GET /health`, `GET/PUT /groups`, `POST /groups/{id}/pause`, `GET /chains?status=open`,
  `POST /chains/{id}/stop-after-current`, `POST /chains/{id}/end` (the dashboard's "skip to base"),
  `POST /kill-switch`, `GET /trades`, `GET /signals`, `GET /reports/summary` (Phase 8) …
- **WebSocket** `/ws` streams events to the dashboard. On connect the server sends a snapshot
  (open chains, balance, connection state), then incremental events with sequence numbers so the
  client can detect gaps and re-sync. Each client has its own bounded queue (decision D-40).
- All commands are idempotent where possible and return the new state.
- No authentication in v1 (single user, bound to `127.0.0.1` by default). The server must **refuse
  to bind to a public interface without an explicit setting**, because the API can place trades.

## 8. Frontend structure

- React 18 + Vite + TypeScript (strict). Server state via **TanStack Query**; live events via one
  WebSocket client that updates the Query cache (no duplicated state). Local UI state in components or
  a small store (Zustand) only when needed.
- Feature-based folders: `features/trades`, `features/chains`, `features/groups`, `features/signals`,
  `features/reports`, `features/risk`; shared `components/`, `lib/`, `api/` (typed client generated or
  hand-written from the OpenAPI schema).
- Charts: one chart library, chosen in Phase 8 and recorded in DECISIONS.
- In production the built frontend is served by FastAPI as static files (one process, one port).

## 9. Configuration and secrets

- Settings via `pydantic-settings`: environment variables / `.env` (git-ignored). Examples in `.env.example`.
- Secrets: Telegram API id/hash and session, Quotex email/password. Stored in a local data directory
  (`data/`, git-ignored). Encrypted storage is a "later" item; until then file permissions + git-ignore
  and a loud note in the README.
- Never log secrets; redact in error reports.

## 10. Observability

- Structured logging (JSON in production, readable in development) with correlation ids:
  `signal_id`, `chain_id`, `trade_id`.
- `/health` reports: Telegram connected, Quotex connected, DB writable, queue depth, last event time.
- Latency timestamps per trade (section 4) are first-class data, not log lines.

## 11. Repository layout (target; created progressively by the phases)

```
quotex_trade_engine/
├── CLAUDE.md
├── docs/                      # this documentation, STATUS.md, reports/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini  alembic/
│   ├── app/
│   │   ├── main.py            # FastAPI app + lifespan
│   │   ├── core/              # config, logging, background-task helper, clock
│   │   ├── domain/            # enums, ids, plain records (what the DB stores); no framework imports
│   │   ├── db/                # engine, session, models, column types, repositories, writer,
│   │   │                      #   recovery query, migration helpers
│   │   ├── quotex/            # base.py (interface), pyquotex_adapter.py (logic), pyquotex_client.py (the only
│   │   │                      #   pyquotex importer), client.py (seam), fake.py, parsing.py, errors.py
│   │   ├── telegram/          # source.py (interface), telethon_source.py (the only Telethon importer),
│   │   │                      #   fake.py, listener.py (connection + subscriptions), login.py, factory.py
│   │   ├── signals/           # models.py, parsers/ (base, registry, legacy_v1), assets.py,
│   │   │                      #   scheduling.py (entry times), timezones.py, pipeline.py
│   │   ├── engine/            # strategies.py (pure rules), chain.py (state machine), executor.py (the
│   │   │                      #   hot path), manager.py (chains, D-9, recovery), engine.py (wiring),
│   │   │                      #   risk.py (RiskGuard, limits, kill switch), errors.py,
│   │   │                      #   factory.py (real components)
│   │   ├── events/            # bus.py, event types
│   │   ├── services/          # live.py (LiveState, rebuilt from events), groups.py, risk_settings.py
│   │   ├── api/               # routers/, schemas/, hub.py + ws.py (/ws), errors.py, security.py,
│   │   │                      #   snapshot.py, events.py, openapi.py, deps.py, views.py
│   │   └── reports/           # queries.py
│   ├── data/                  # git-ignored: sqlite file, sessions, logs (owner decision, Phase 0)
│   └── tests/                 # unit/, integration/, fixtures/
├── frontend/
│   ├── package.json  vite.config.ts  tsconfig.json  eslint config
│   └── src/ (api/, features/, components/, lib/, app/)
├── .env.example
├── .gitignore
└── README.md
```
