# Development Phases

The agent executes **one phase at a time**. After each phase it stops, writes
`docs/reports/phase-<N>.md` (see `docs/REPORT_TEMPLATE.md`), updates `docs/STATUS.md`, and waits for
the owner. **No commits** unless the owner says so.

Every phase also has to satisfy the global "Definition of done" in `CLAUDE.md`.
Items marked *(live)* need a real Telegram/Quotex account; if you cannot run them, say so in the
report and provide the exact manual test steps for the owner instead of claiming success.

---

## Phase 0 — Foundation and tooling

**Goal:** an empty but properly wired project that builds, lints, tests and runs.

**Scope**
- Repo hygiene: `.gitignore` (venvs, `node_modules`, `data/`, `.env`, `*.session`, `session.json`,
  build output, caches), `.env.example`, `README.md` (what it is, how to run, security note).
- Backend: `backend/pyproject.toml` (Python 3.12), choose and record package manager (`uv` or pip);
  dependencies: fastapi, uvicorn, pydantic-settings, sqlalchemy[asyncio], aiosqlite, alembic,
  telethon, structlog (or stdlib logging with JSON formatter); dev: ruff, mypy, pytest,
  pytest-asyncio, httpx. Add **pyquotex as a pinned git dependency** (resolve the current upstream
  commit, record hash + date in `docs/DECISIONS.md` D-5) and confirm it installs on Python 3.12.
- App skeleton: `app/main.py` with lifespan, `core/config.py` (pydantic-settings), `core/logging.py`,
  `core/tasks.py` (supervised background-task helper), `GET /api/v1/health`.
  Default bind `127.0.0.1`; refuse non-loopback bind unless `ALLOW_PUBLIC_BIND=true`.
- Frontend: Vite + React + TypeScript (strict) scaffold, ESLint, Prettier, Vitest; dev proxy for
  `/api` and `/ws`; one page that calls `/health` and shows the result.
- Scripts (cross-platform where possible): run backend, run frontend, run tests, lint, type-check.

**Acceptance criteria**
- Fresh clone → documented setup steps → backend and frontend start; the page shows health OK.
- `ruff check`, `ruff format --check`, `mypy`, `pytest`, `eslint`, `tsc --noEmit`, `vitest` all pass.
- `pip`/`uv` can import `pyquotex` in the venv (import only; no network calls).
- Starting with `HOST=0.0.0.0` and no flag is refused with a clear message (test).
- No secrets or generated junk in the tree.

---

## Phase 1 — Database and domain models

**Goal:** persistent storage that cannot slow the trading path.

**Scope**
- Decide and record the money representation.
- SQLAlchemy 2.x async models + Alembic initial migration for: `groups`, `group_settings`,
  `signals`, `chains`, `trades` (including latency timestamps and `account_type`), `risk_events`,
  `balance_snapshots`, `app_settings`. Indexes for the dashboard/report queries.
- SQLite connection setup: WAL, `synchronous=NORMAL`, busy timeout, foreign keys on.
- Repository layer (thin, async) for each aggregate.
- `EventBus` (in-memory, typed events) and `DBWriter` (queue → batch → commit, graceful flush on
  shutdown, bounded queue with a documented overflow policy).
- Startup recovery query: load open chains and unsettled trades.

**Acceptance criteria**
- `alembic upgrade head` on an empty DB works; `alembic downgrade base` works.
- Tests: repositories CRUD; `DBWriter` batches and flushes on shutdown; event published → row exists.
- A benchmark test shows publishing 10,000 events does not block the publisher beyond a stated limit
  (record the number in the report).
- Schema uses no SQLite-only constructs (note anything unavoidable).

---

## Phase 2 — Quotex adapter

**Goal:** a clean, testable interface over the unofficial library, plus a fake for everything else.

**Scope**
- `app/quotex/base.py`: `QuotexAdapter` protocol — `connect`, `disconnect`, `account_type`/
  `set_account_type`, `balance` (cached snapshot + refresh), `payout(asset, minutes)`,
  `is_open(asset)`, `place_order(asset, direction, duration_s, amount) -> OrderAck`,
  `await_result(order_id, timeout) -> TradeResult`, connection-state events.
- `pyquotex_adapter.py` implementing it on pyquotex 1.1.0: host configurable (default `quotex.com`),
  session persisted in `data/`, reconnect with backoff, **no blocking calls on the loop**, server-time
  offset cached and warmed at startup, payout sanity checks (0–100), result awaited by event/poll ≤0.2 s.
- `fake.py`: deterministic and scriptable (win/loss sequences, delays, failures, disconnects).
- Read the actual 1.1.0 source to learn its real API; do not assume the old 1.0.3 behaviour.
- A small CLI/diagnostic script: connect to **demo**, print balance and one payout, optionally place
  one minimal demo order *(live)*.

**Acceptance criteria**
- Contract tests run against the fake and define the behaviour the real adapter must match.
- Unit tests for reconnect/backoff, timeout on missing result, payout sanity check.
- *(live)* Diagnostic script connects to demo, shows balance and payout; one demo order is placed and
  settled; **measured latency of `place_order` is recorded in the report** (and compared to the old
  bot's problem described in D-14).
- No module outside `app/quotex/` imports `pyquotex` (checked by a test or lint rule).

---

## Phase 3 — Telegram listener and parser

**Goal:** many groups in, structured signals out, every message recorded.

**Scope**
- `TelegramListener`: one Telethon client, session stored in `data/`, login flow documented
  (phone in international format `+<country code>…`, code, optional 2FA), list dialogs, subscribe to
  the chats of all enabled groups, add/remove subscriptions at runtime, reconnect handling.
- Parser interface `SignalParser` + registry (per-group parser choice). Port the existing parser from
  the old `trading_bot_V2.py` (read-only reference) with its formats, then fix weaknesses
  (`docs/DOMAIN.md` §4). Add `quotex` asset-name normalisation incl. OTC handling as a per-group option.
- `SignalPipeline`: parse → validate → dedupe (same message edited/forwarded) → emit `Signal` or an
  "ignored" record with a reason. **Every** received message is recorded in the signal inbox
  (off the hot path) with parsed/not-parsed/ignored status and reason.
- Entry-time handling: signals with an entry time are scheduled (timezone-aware; the old bot used
  naive local time and rolled the day with `day + 1`, which breaks at month end — do not repeat that).

**Acceptance criteria**
- Parser test suite from real example messages (collect them from the owner / `docs/fixtures`), covering
  every supported format and several non-signals. Messages from the owner's examples include:
  `💰5 minutes expiry USD/BDT;15:00;PUT 🟥 …` and `ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29`.
- Two groups can be listened to at once with different parsers (test with a fake Telegram source).
- Scheduling tests: month-end, midnight, DST-safe, past-time-today behaviour documented.
- *(live)* Login and message receipt from a test group are demonstrated, or the manual steps are given.

---

## Phase 4 — Strategy and chain engine

**Goal:** the heart of the system: per-group strategies, concurrent chains, fast execution.

**Scope**
- `strategies.py`: pure functions/classes implementing the rules in `docs/DOMAIN.md` §2
  (no_martingale, martingale, flip_every_loss, two_step_flip) — exhaustively unit-tested,
  including multi-step tables.
- `chain.py` state machine (`pending → open → won/lost → next step … → completed/exhausted/stopped/failed`).
- `ChainManager`: creates chains from signals, keeps them independent per `(group_id, asset)`, applies
  decision D-9, publishes events, persists through the event bus, recovers open chains on startup.
- `Executor` hot path exactly as in `docs/ARCHITECTURE.md` §4, with latency timestamps recorded.
- Result handling by awaitable event; follow-up created immediately on a loss.
- Wire Telegram → pipeline → manager → executor → adapter using the **fake adapter** end to end.

**Acceptance criteria**
- Strategy tables match `docs/DOMAIN.md` examples exactly (tests named after the examples).
- Integration test: three groups, mixed strategies, overlapping chains, scripted wins/losses with the
  fake adapter → correct directions, stakes, independence, and final states.
- Test: new signal during an active flip chain is ignored and recorded with a reason.
- Test: restart mid-chain recovers and continues correctly (or marks `unknown` safely).
- Latency test with the fake adapter shows the engine's own overhead (signal → `place_order` call) in
  microseconds/milliseconds; the figure goes in the report.
- No `sleep(duration + N)` or equivalent anywhere (grep check in the report).

---

## Phase 5 — Safety and control

**Goal:** the system can be limited and stopped quickly and safely.

**Scope**
- `RiskGuard` (in-memory, synchronous): max stake per trade, max concurrent trades, total exposure cap,
  per-group and global daily stop-loss and profit target, minimum payout per group, max chain length.
- Controls (engine-level, exposed via API in Phase 6): pause/resume group, **kill switch**
  (stop new orders, optionally stop all chains), *stop after current trade*, *skip to base / end chain*.
- A tripped limit publishes a `risk.tripped` event, is persisted, and states clearly what was blocked.
- Account-type guard: REAL requires an explicit setting; switching account type with open chains is refused.

**Acceptance criteria**
- Each limit has tests for "just below", "at", "above" the threshold.
- Kill switch test: no order can be placed after it is engaged (including follow-ups already queued).
- Daily limits reset at a documented time/timezone (tested).
- The hot-path overhead of `RiskGuard` is measured and reported.

---

## Phase 6 — API and realtime events

**Goal:** a stable, typed interface for the dashboard.

**Scope**
- REST routers under `/api/v1` (groups & settings CRUD, chains, trades, signals, controls, reports
  placeholders, app status), Pydantic request/response models, consistent error format, pagination
  and filtering for lists, OpenAPI schema.
- WebSocket `/ws`: snapshot on connect, then sequenced events; heartbeat; re-sync protocol;
  per-client bounded queue (a slow client must never slow the engine).
- Typed API client for the frontend (generated from OpenAPI or hand-written with matching types).
- Input validation and safe defaults; bind rules from Phase 0 still enforced.

**Acceptance criteria**
- API tests with `httpx.AsyncClient` for every endpoint (happy path + validation errors).
- WebSocket tests: snapshot, ordered events, gap detection, slow-consumer handling.
- OpenAPI schema committed to the working tree (or generated in a script) and the frontend types
  compile against it.

---

## Phase 7 — Dashboard v1 (React)

**Goal:** the live control room.

**Scope**
- App shell, routing, layout, error boundaries, loading/empty/error states, accessible components.
- **Live**: open chains with step progress, open trades with countdown, balance, connection status for
  Telegram/Quotex, signal → order latency.
- **Signal inbox**: every message, parse result and reason.
- **Groups**: add/edit/enable/disable groups; per-group strategy, base stake, max steps and a
  multiplier input per step (validated), payout minimum.
- **Controls**: pause group, stop-after-current, skip-to-base, kill switch (with confirmation),
  clear DEMO/REAL indicator everywhere.
- **History**: trades table with filters and pagination.
- Data via TanStack Query; WebSocket events update the cache; reconnect/re-sync handled.

**Acceptance criteria**
- Component tests for the forms (multiplier-per-step validation) and the controls (confirmation flow).
- A manual walkthrough script (steps + expected result) using the fake adapter in the report;
  screenshots if possible.
- `eslint`, `tsc`, `vitest`, and a production `vite build` pass; the bundle is served by FastAPI.
- Dashboard stays responsive with 500+ rows (virtualised or paginated).

---

## Phase 8 — Reports

**Goal:** answer "is this really working?"

**Scope**
- SQL aggregations: profit/loss, win rate, average payout, drawdown, by group / asset / strategy /
  hour of day / weekday; chain-depth distribution (how often chains reach each step and what they cost);
  streaks; expected-vs-actual; demo and real reported separately.
- Report endpoints with date range filters; CSV export.
- Dashboard report pages with charts (choose and record the chart library); clear labelling of sample
  size so small samples are not over-read.

**Acceptance criteria**
- Aggregation tests against a seeded database with hand-computed expected values.
- Report queries stay fast on a seeded database of 100k trades (record the timings).
- CSV export opens correctly in Excel (UTF-8 BOM / delimiters verified).

---

## Phase 9 — Hardening and packaging

**Goal:** dependable day-to-day use on the owner's PC, ready to move to a VPS.

**Scope**
- Reconnection and failure-mode review (Telegram drop, Quotex drop, DB locked, queue full); chaos tests
  with the fake adapter.
- Startup recovery verified end to end; graceful shutdown; log rotation.
- One-command start on Windows (script) and a documented VPS deployment (systemd/Docker optional,
  decide with the owner), environment-based configuration.
- Documentation: README, operations guide (login flows, domain change procedure for Quotex, backups of
  `data/`), troubleshooting (phone number format, DNS/`getaddrinfo` errors, session reset).
- Performance review: measure signal → order latency with the real adapter on demo *(live)* and report.

**Acceptance criteria**
- Failure-mode tests pass; documented behaviour for each failure.
- A clean-machine setup following the README works (describe how it was verified).
- Final report lists known limitations and the "Later" backlog.

---

## Phases 10-15 — Everything the owner types moves into the dashboard

**Why (owner's request, decision D-58):** logging in to Telegram and Quotex needs a terminal command,
and every setting needs an edit of `backend/.env` and a restart. From here the dashboard does it: the
logins are typed there and stored **encrypted in the database**, and settings such as "engine on" live in
the database. `.env` keeps only what the application needs *before* it can read the database (bind
address, data folder, environment) plus the **master key** that encrypts the stored logins.

Because the dashboard will then hold the keys to a trading account, **login comes first**: no secret is
accepted by the dashboard until a login protects it (D-59). One owner account (the admin) for now; the
design leaves room to invite more people later (see "Not in these phases" below).

The command-line logins (`npm run telegram:login`, `npm run quotex:diagnose`) stay as a fallback.

**Outcome: all six phases are done** (reports `docs/reports/phase-10.md` to `phase-15.md`; decisions D-58 to D-67).

### Phase 10 — Owner account and login

**Goal:** the API and the dashboard are behind a login. No secrets are stored yet.

**Scope**
- Tables `users` (id, username, password hash, role = `admin`, timestamps) and `auth_sessions`
  (hash of the session token, user, created / last seen / expires). Migration `0002`.
- First run: no account exists, so the application prints a one-time **setup code** in its log; the
  dashboard's setup page asks for the code, a username and a password. The first visitor cannot take it
  over without the code.
- Login, logout, "who am I", change password (which ends the other sessions). Passwords are hashed with
  scrypt in a worker thread (D-60); sessions are random tokens in an HttpOnly, SameSite=Strict cookie,
  only their hash is stored.
- Every API route and the WebSocket need a session, except `/health`, `/auth/*` and the static dashboard.
  Failed logins are throttled (per username and overall).
- Command `npm run owner:reset` (create the account, or reset its password, on the machine itself).
- Dashboard: setup page, login page, logout and change password; the app shows them instead of the
  pages when there is no session; a 401 from the API sends the owner back to the login.
- All existing tests keep passing (they log in through a helper); new tests for every rule above.

**Acceptance criteria**
- A request without a session gets 401 on every protected route and on `/ws`; with one it works.
- Setup works only with the right code and only while no account exists; then it is closed for good.
- Wrong password, unknown user and throttled attempts are tested; the error never says which part was wrong.
- A changed password ends the other sessions; logout ends this one.
- The password and the session token never appear in the database in clear, in a log line or in an API
  response (tests).

### Phase 11 — Encrypted store and settings in the database

**Scope:** the master key (`SECRET_KEY` in `.env`, generated by a command if missing) and a small
encryption layer; an encrypted `secrets` table (write-only through the API: it can say "set / not set",
never return a value); a `settings` service for the choices that today live in `.env` (log level, Quotex
host and time mode, ...), with a dashboard Settings page; `.env.example` shrinks to the bootstrap values.
**Acceptance:** a stored secret is unreadable without the key and does not appear in a backup made
`--no-secrets`; wrong or missing key gives a clear message, never a crash or wrong data; no endpoint ever
returns a secret.

### Phase 12 — Engine control from the dashboard

**Scope:** start and stop the engine (Quotex and Telegram together) at run time, with its state on the
dashboard; `ENGINE_ENABLED` and `QUOTEX_ALLOW_REAL` leave `.env` (demo or real is a setting that asks for
the password again and is written to the risk log). The engine is built from the stored logins.
**Acceptance:** start, stop and restart without restarting the application; no trade on REAL without the
confirmed switch; the execution path is unchanged (benchmark/test).

### Phase 13 — Telegram login in the dashboard

**Scope:** enter the API id and hash; phone, then the code (with the resend option), then the two-step
password; the session is stored encrypted instead of a `.session` file; log out of Telegram; flood waits
and wrong codes explained in plain words. **Acceptance:** the whole flow tested with the fake source;
the half-finished login survives a page reload.

### Phase 14 — Quotex login in the dashboard

**Scope:** enter email and password; the email PIN step; the session stored encrypted; the adapter reads
and writes it through the store (the library wants a file: the adapter gives it a private temporary one
and removes it); a clear message when Quotex answers with a block (HTTP 403) instead of the library's
crash. **Acceptance:** flow tested with the fake client; no credential left on disk after a login.

### Phase 15 — Clean-up and documentation

**Scope:** the old `.env` logins become an optional one-time import into the database, then are ignored;
backups and `--no-secrets` explained for the encrypted store; the command-line logins read and write the
same store; README, OPERATIONS, DEPLOYMENT, TROUBLESHOOTING and `.env.example` rewritten for the new way;
final report with the limitations.

### Not in these phases (decided: later)

Invitations and more than one user (D-59): the `users` table has a role and sessions belong to a user, so
this can be added. What it will need: an owner column on groups, chains, trades and the stored logins,
and invitation links. Deliberately **not** added now (YAGNI, and it touches every table and every query).

---

## Later backlog (not scheduled)

Telegram alerts to the owner; backtester over stored messages; more parsers + "test this message" tool;
early close of an individual open trade (`sell_option`,
only if Quotex allows it); strategy lab; PostgreSQL migration; hosted multi-user version (legal review
first); official API if Quotex ever offers one.
