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

## Phases 16-18 — Trading sessions (automatic trading, decisions D-71 to D-73)

**Why (owner's request):** today every trade starts from a Telegram signal. The owner wants trading that starts
from a **schedule set on the dashboard**: in a time window, on one chosen asset, the system opens a **pair**
(CALL and PUT together), the loser recovers through the strategy, the winner ends; it repeats until the window
closes or a profit or loss target is hit. A second mode opens a new pair at every candle and lets the earlier
pairs keep running, with a limit on how many are open. Telegram signals are untouched.

**Words used here:** a *session* is the saved setup; a *run* is one occurrence of it (one window); a *pair* is
the CALL and PUT opened together; a *round* is one pair opening. (Not to be confused with the login sessions of
Phase 10.)

**Fixed by the owner:** one asset per session; one session running at a time; a stop never cuts a running chain,
it only stops new pairs; the first pair goes out at the start time; later pairs at candle boundaries; repeat =
once or chosen weekdays; a window missed while the app was off is skipped; a restart ends the run and does not
resume it. All other design choices are in D-71 to D-73.

**Not in these phases:** Telegram signals during a session, several assets in one session, a hard "end the
chains" loss limit, catching up on missed windows, trend filters (all suggestions for later, not scheduled).

### Phase 16 — Sessions, one pair at a time (backend)

**Goal:** a session can be saved, runs on its schedule, opens one pair at a time with the pause between pairs,
stops by the rules of D-72, and is controlled by the API. Tested on the fake Quotex and a manual clock.

**Scope**
- **Data** (migration `0005`): tables `trading_sessions` (name, enabled, hidden group id, asset, trade length,
  minimum payout, start time, end time, time zone, repeat kind and weekdays, profit target, loss limit, maximum
  pairs, pause between pairs) and `session_runs` (session, start and end, state, end reason, pairs opened,
  profit, account type). `groups.source` (`telegram` or `session`) and a nullable `telegram_chat_id` (a session's
  hidden group has none); `chains` get `session_run_id` and `pair_no`. Every existing row keeps its behaviour.
- **Session service and API:** create, edit, delete, enable or disable, list; *Start now*; *Stop*; list the runs.
  Validation in plain words: asset format, trade length is one Quotex offers, payout 0-100, targets above 0,
  start and end differ, at least one weekday for a repeating session, **no overlap with another enabled
  session** (D-73), a warning (not an error) when the start is not on a candle boundary of the trade length.
  Saving the strategy part writes the hidden group's settings (the existing rules for stakes and multipliers).
- **Scheduler** (`sessions/scheduler.py`): finds the next window of each enabled session from the clock and time
  zone; a minute before it, checks engine, connection, asset and payout; at the start time opens the first pair;
  runs the sequential mode (wait, then the first boundary at or after it); skips and records a round whose
  checks fail; ends the run for every reason in D-72; does not open a pair at or after the window end.
- **Pair:** both legs are checked before either is sent; both are handed to `ChainManager` as signals of the
  hidden group (their inbox rows are published first, marked as from a session); D-9 is not applied to them.
  A leg refused after the first was sent is recorded as a "lopsided pair".
- **Run accounting:** the profit of the run from the settled trades of its chains; target check at every
  settlement and before every pair; the run is `ended` when its last chain ends. Events on the event bus, so the
  database writer stores them like everything else.
- **Restart and engine control:** at start-up a run left in progress becomes `interrupted` and a *once* session
  that was running is finished; no run starts by itself inside an open window. Stopping the engine ends the run
  (`engine_stopped`). The kill switch ends it (`kill_switch`).
- **Telegram optional:** the engine starts with the Quotex login alone; the Settings page says the signal
  source is off. With the login present nothing changes for Telegram.
- **Docs:** API.md and `docs/openapi.json` regenerated, DOMAIN.md (sessions), OPERATIONS.md (how a session runs).

**Acceptance criteria**
- A session with a 23:00 start, on the manual clock, places its CALL and its PUT at 23:00:00, and nothing earlier
  (test).
- Sequential rule: with both chains still running no new pair opens; after both ended and the pause, the next
  pair goes out at the first boundary at or after it (tests with winning, losing and draw outcomes).
- Each stop reason ends the run without opening a pair, **lets the running chains finish**, and records the
  reason (one test per reason: window end, profit target, loss limit, maximum pairs, *Stop*, kill switch).
- A failed check (asset closed, payout below the minimum, not connected) sends **no** order and records why.
- Two enabled sessions with overlapping windows are refused on save, including across midnight and on repeating
  weekdays; *Start now* is refused while a run is active.
- A *once* session runs one window and never again; a weekday session runs on its days only; a window missed while
  the engine was off does not run (tests with the manual clock).
- Restart test: a run in progress becomes `interrupted`, its chains `unknown`, and nothing resumes.
- Engine start with the Quotex login only (fake) and no Telegram login works; a session trades.
- Telegram groups behave exactly as before: the existing D-9, D-70 and pipeline tests pass unchanged.
- The execution path is unchanged (the benchmark test) and the architecture-rule tests pass.
- Migration test: upgrade and downgrade, existing groups keep `source = telegram`.

### Phase 17 — Overlapping pairs: a pair at every candle (backend)

**Goal:** the second mode: a new pair at every candle boundary, whatever is still running, up to a chosen number
of open pairs.

**Scope:** the mode setting (`sequential` or `every_candle`) and `max_open_pairs` (at least 1) in the session, the
API and its validation; the scheduler places a pair at each boundary while fewer than the maximum are open, and
otherwise skips that boundary and records it; the open pairs are counted from the chains in memory (a pair is
open while one of its chains runs); chains of different pairs stay fully independent (stakes, steps, controls);
the stop rules of D-72 apply as before (running chains of all pairs finish); docs and `openapi.json`.

**Acceptance criteria**
- A pair opens at every boundary until the maximum is open (test: boundaries 23:00, 23:05, ... with losers kept
  running); at the maximum, the boundary is skipped and recorded; when a pair's last chain ends, the next boundary
  opens a pair again.
- The chains of different pairs do not influence each other: one chain reaching its last step, being ended by the
  owner or ending on a win leaves every other chain unchanged (tests).
- All stop reasons work with several pairs open; **every** running chain of **every** pair finishes.
- A boundary is never missed or doubled by a slow round (tests with delays on the manual clock).
- `sequential` behaves exactly as in Phase 16 (its tests pass unchanged).
- The execution path is unchanged (benchmark) and the opposite-pair and D-9 tests pass.

### Phase 18 — Sessions on the dashboard, and in the reports

**Goal:** everything is set and watched on the dashboard.

**Scope**
- **Sessions page:** list (state, next window, last result), create and edit form (asset, trade length, minimum
  payout, strategy and stakes with the same form parts as a group, window and time zone, repeat: once / every day
  / Monday to Friday / chosen days, mode and open-pair limit, pause, profit and loss targets, maximum pairs),
  enable or disable, delete, *Start now*, *Stop* (asks first; says that running chains finish).
- **Plain-words checks on the form:** the overlap error, the start-not-on-a-boundary warning, and the **worst
  case in figures**: the most a single pair can stake, times the open-pair limit, and that the loss limit does
  not cap the loss (D-72).
- **Live run panel:** state, time to the next pair or to the window end, profit against both targets, pairs
  opened and open now, skipped rounds with the reason, and the run's chains (the existing chain controls still
  work on each one). Updates arrive over the WebSocket like the rest of the dashboard.
- **History:** past runs with their end reason and profit.
- **Reports:** breakdown by session and a session filter, from the same queries as the other breakdowns.
- Docs: README, OPERATIONS (how to set a session up, step by step), TROUBLESHOOTING (a session did not start:
  the reasons it lists), FAILURE_MODES. The phase report lists the live checks to be done on the demo account
  (gap between the two legs of a pair, expiry of both legs, a full window).

**Acceptance criteria**
- A session can be created, edited, started, stopped and deleted from the dashboard (component and form tests);
  every refusal of the API is shown in words.
- The live panel follows a run on the fake backend: pairs, targets, the stop reason.
- The reports break down by session and agree with the Trades page totals (test on seeded data).
- `eslint`, `tsc --noEmit`, `vitest` and `npm run api:check` pass; no secret appears anywhere.

---

## Phases 19-21 — Deriv as a second broker (decisions D-74 to D-77)

**Why (owner's request):** connecting to Quotex keeps failing (Cloudflare check, unofficial library) and its orders
are confirmed one at a time. Deriv has an official API. The owner wants **both brokers at once**: each group and
each trading session picks Quotex or Deriv; strategies, chains, sessions, limits, dashboard and reports work the
same on both. On Deriv, forex Rise/Fall starts at 15 minutes; the 1- and 5-minute trades are on Deriv's
**synthetic indices** (Volatility 75 and the like), so both kinds of assets are in these phases.

**Fixed by the owner:** both brokers side by side; forex pairs and synthetic indices both supported, and Deriv
trades are started from trading sessions on the dashboard (no Telegram signals name synthetic indices, so the
signal parser is unchanged); Deriv's demo and real accounts each have their own token, the
demo/real switch picks which one is used, and real money still needs the owner's permission (D-15).

**Before Phase 19:** the owner checks on Deriv's website that Rise/Fall forex is offered in their region. Phase 19's
`npm run deriv:check` then shows, with a demo token, the forex pairs and synthetic indices offered, the Rise/Fall
trade lengths each allows, and sample payouts (EURUSD at 15 minutes, Volatility 75 at 1 and 5 minutes).

**Not in these phases:** Higher/Lower or touch contracts, tick-length trades (counted in ticks, not minutes), moving
existing groups to Deriv in bulk, concurrent orders on Quotex (suggestions for later, not scheduled).

### Phase 19 — The Deriv adapter (backend, not yet in the engine)

**Goal:** a Deriv adapter that does everything the Quotex adapter does, tested against a local fake Deriv server,
and a check script the owner runs on the demo account.

**Scope**
- `app/brokers/`: the adapter protocol as `BrokerAdapter` with its value types, and the shared adapter errors
  (`app/quotex/` keeps its names by re-exporting them). `Broker` enum in `app/domain/enums.py`.
- `app/deriv/`: `protocol.py` (messages, error codes to our errors, forex name mapping and synthetic index symbols), `connection.py` (one
  WebSocket, replies matched by `req_id`, subscriptions by id, `ping` every 30 s, reconnect with the backoff of
  `app/core/backoff.py`), `adapter.py` (`DerivAdapter`: connect and the account checks of D-76, balance stream,
  the assets (forex pairs and synthetic indices) with the trade lengths each allows, from `contracts_for`, payout from `proposal` streams, `place_order` with `buy`, `await_result` with
  `proposal_open_contract`), `fake.py` (`FakeDerivAdapter` for engine tests), `factory.py`.
- Settings fields for the app id and the two tokens (filled from the encrypted store).
- `npm run deriv:check` (`backend/scripts/deriv_check.py`): demo token only; account, the forex pairs and
  synthetic indices with their Rise/Fall trade lengths, sample payouts; `-- --order` places one 1.00 demo trade and prints its result.

**Acceptance criteria**
- Adapter tests against a local fake Deriv server: authorize and its refusal, a real token in the demo slot refused,
  a token with too many scopes refused, a buy and its result (won, lost, equal exit = lost), **two orders in flight
  answered in reverse order and matched correctly**, no confirmation = `OrderAckTimeoutError`, a lost connection
  and reconnect, an unknown or `_otc` asset refused before sending, a synthetic index (`R_75`) bought and settled at 1 minute, a
  forex pair at a length below its minimum refused before sending with the reason.
- Architecture test: only `app/deriv/` talks to Deriv.
- `ruff`, `mypy`, the whole test suite pass.
- The owner's `npm run deriv:check` output (and one `--order` result) is in the report; if it was not run, the
  report says so.

### Phase 20 — Two brokers in the engine (backend)

**Goal:** groups and sessions trade on their own broker, both at once, kept apart in limits and figures.

**Scope**
- Migration `0007`: `broker` on groups, trading sessions, chains, trades and balance snapshots (existing rows:
  `quotex`); indexes by broker and account type. Records, repositories, writer and recovery carry it.
- The engine holds one adapter per connected broker; the factory builds those with logins (at least one needed).
  The demo/real switch and the real-money permission apply to all. Stopping disconnects each adapter with a time
  limit (also fixes the shutdown that could hang, seen on 2026-11-13).
- Sessions on Deriv take their trade lengths from the asset (for example 1 and 5 minutes on a synthetic index,
  15 minutes and more on forex), not from the Quotex list; candle boundaries work the same.
- Executor, chain manager and session scheduler use the broker of the group or session; skip reasons for a broker
  that is not connected and an asset it does not offer.
- Risk: daily figures, global limits and exposure per broker and account type.
- Events and health: balance and connection per broker; the banner only for a broker that is in use.
- API: `broker` on groups, sessions, chains and trades; one balance per broker; `openapi.json` regenerated.

**Acceptance criteria**
- Engine tests with both fakes: a Quotex group and a Deriv group trade at once and their results, limits and
  figures stay apart; one broker down does not stop the other; a Deriv session on a synthetic index at M1 sends both legs of a pair together; a Deriv group's 1-minute
  forex signal is skipped with the minimum-length reason.
- Migration up and down; existing data reads as Quotex.
- `ruff`, `mypy`, the whole test suite pass.

### Phase 21 — Deriv on the dashboard, in the reports and in the guides

**Goal:** everything about Deriv is set and watched on the dashboard.

**Scope**
- Settings: a Deriv card (app id, demo token, real token, stored encrypted; "create tokens with Read and Trade
  only"); a *Check* button that shows the account without trading.
- Group and session forms: a Broker picker. For a Deriv session the asset is picked from Deriv's list, grouped as
  forex pairs and synthetic indices with their display names, and only the trade lengths that asset allows are
  offered; warnings for an `_otc` asset or a length Deriv does not offer.
- Live and Account pages: one balance and one connection badge per broker; chains and trades show the broker.
- Reports: a broker filter (each broker separately by default) and a *By broker* breakdown.
- Docs: ARCHITECTURE, DOMAIN, OPERATIONS (getting an app id and a token), TROUBLESHOOTING, FAILURE_MODES, API,
  README; CLAUDE.md rule 6 also covers `app/deriv/`.

**Acceptance criteria**
- Component and form tests for the card, the pickers, the balances and the report filter; every API refusal shown
  in words.
- Reports by broker agree with the Trades page totals (test on seeded data).
- `eslint`, `tsc --noEmit`, `vitest`, `npm run build` and `npm run api:check` pass; no secret appears anywhere.

## Phases 22-24 — Deriv on a shaky network, a switch per broker, faster results (decisions D-78 to D-82)

**Why (owner's request, 2026-11-18/19):**
- **The freeze.** On the Deriv demo the engine froze twice (06:40 and 22:17 local), each time when Deriv's
  connection dropped while trades were open: a Cloudflare restart on Deriv's side the first time, the PC's Wi-Fi
  losing the router the second. It then used a full CPU core, wrote nothing, answered nothing, and Ctrl+C could
  not stop it; the trades in flight were left `unknown` (9 so far, all with their Deriv contract id stored).
  Cause: in `DerivAdapter.await_result`, after the socket closes, the request to follow the contract fails at
  once ("nothing was sent"), the loop retries, and `_up` is still set because the code that clears it never gets
  to run: the loop never yields, so neither the reconnect nor the result time limit can run.
- **Chains should carry on when nothing was missed.** The owner's rule: when the connection (or the program)
  comes back before the chain's next trade was due, the chain continues as if nothing happened; it ends only
  when a trade time was already missed. No lateness margin (owner's choice: strict). A session run resumes after
  a restart while its window is open (owner's choice; amends D-73).
- **Start now** never reads the asset's payout on Deriv, so after a restart a manual run skips every round ("the
  payout of R_75 is not known").
- **A broker that is not used cannot be stopped.** Quotex keeps trying to log in every ~30 s (104 attempts on
  2026-11-18: DNS time-outs, Cloudflare 403, an email PIN), and the only way to stop it is to stop the engine.
- **Each martingale step starts later than the last.** Over 321 demo trades every step cost about 4.1 s (0.5 s
  for Deriv to confirm the order, 3.6 s from expiry until the result is known; the engine's own work is about
  1 ms), so step 7 starts about 28 s into its minute.

**Order:** Phase 22 (never freeze; continue chains), Phase 23 (a switch per broker), Phase 24 (faster results;
starts with a live measurement on the owner's demo, because the faster path must match Deriv's own result rule).

**Not in these phases:** moving to a VPS; changes to the PC's network (written into the guides instead); continuing
Quotex chains after a program restart (Quotex cannot be asked for a past trade's result reliably, so D-35 stays
for Quotex); concurrent Quotex orders.

### Phase 22 — Never freeze on a dropped connection; continue chains when nothing was missed (backend, guides)

**Goal:** a dropped Deriv connection or a program restart, at any moment and with any number of trades open,
costs only the time it lasts: the engine keeps answering, follows its open contracts again, records their real
results, and carries every chain on whose next trade was not missed.

**Scope**
- **The freeze (D-78).** `await_result` waits for the drop to be seen and for the next connection, never retrying
  in a loop that does not yield; the adapter marks itself down the moment the socket closes. Every other retry
  loop in `app/deriv/` and `app/quotex/` is checked for the same pattern and fixed where found.
- **The "missed" rule (D-79), for a reconnect inside a running engine (both brokers) and, on Deriv, for a
  restart.** A chain's next trade is due when its open trade expires (a martingale or flip step goes out as soon
  as the result is known); a session's next pair is due at its candle.
  - Back before the open trade expires: its contract is followed again, its result comes in as usual, and the
    chain continues.
  - Back after it expired: the trade still gets its real result from Deriv, but the step that was due during
    the outage is missed, so the chain ends with the reason "a step was due while the connection was down" (a
    loss on that last trade stays a loss: the strategy's recovery did not happen, and the report says so).
  - A step due while the broker is down is not sent late: it is a missed step (strict, no margin).
- **After a restart (amends D-35 for Deriv).** On start, every Deriv trade left `open` or `unknown` is looked up by
  its contract id and settled with Deriv's result. If the program came back before that trade's expiry, its
  chain is rebuilt from the database and continues; otherwise the chain ends as missed (above). Quotex trades
  keep D-35 (`unknown`, chain ends). The 9 Deriv trades left `unknown` on 2026-11-18 are settled this way at the
  first start (their chains stay ended).
- **Session runs resume (amends D-73).** After a restart, a run whose window is still open carries on until the
  window ends, with its counters (pairs opened, profit, limits) read back from the database; the rounds missed
  while the program was down count as skipped ("the program was not running"). A window that ended meanwhile
  ends the run as today.
- **A stall watchdog (D-80).** A thread outside the event loop checks every second that the loop still turns.
  After 10 s without a turn it logs `engine_stalled` with the loop's stack trace (then every 60 s while stalled).
  Ctrl+C asks for a normal stop; if the loop has not stopped within 15 s, the process ends anyway (the next start
  settles what was in flight, as above). It never restarts anything by itself.
- **Start now on Deriv.** Start now reads the payout before the first round, like a scheduled start does one
  minute ahead; a round that still finds no payout asks Deriv for it, so the next round can trade.
- **Guides:** TROUBLESHOOTING and FAILURE_MODES (the freeze, the missed rule, restarts, `engine_stalled`);
  OPERATIONS gets "a steadier connection on a home PC" (network cable instead of Wi-Fi, Wi-Fi power saving off
  on battery, a public DNS instead of the router's, a small UPS for the router).

**Acceptance criteria**
- Fake Deriv server closes with 1001 while 1, then 5, contracts are open, and the engine reconnects before they
  expire: the engine answers a health request within 1 s throughout, every trade is settled with the server's
  result, and every martingale chain sends its next step and continues. The same with a socket that dies
  without a close frame.
- The same drop, reconnecting after the expiry: the trades get their real results and their chains end as
  missed, with that reason.
- Restart tests (Deriv): a program stopped and started before an open trade's expiry continues its chain; one
  started after it ends the chain as missed with the trade's real result; a session run in its window resumes
  and counts the missed rounds as skipped; Quotex trades still end `unknown`.
- The watchdog: a deliberately blocked loop produces `engine_stalled` with a stack trace; Ctrl+C on a stalled
  loop ends the process within the time limit.
- Start now on a fresh Deriv connection trades from its first round.
- `ruff`, `mypy`, the whole test suite pass; migrations (if any) up and down; the guides are updated.
- Live (owner): a session on the demo, the Wi-Fi turned off and on once for a few seconds while trades are open
  (chains continue) and once for longer than a trade (chains end as missed); every trade has its real result.
  If not run, the report says so.

### Phase 23 — Turn a broker on or off without stopping the engine (backend and dashboard)

**Goal:** the owner switches Quotex or Deriv off while the engine runs (no more endless login attempts for a
broker not in use) and back on, from the dashboard.

**Scope (D-81)**
- **A switch per broker**, stored in the settings so it survives a restart. *Off*: that broker's connection is
  closed and its reconnect attempts stop at once; its badge says "Off". *On*: it connects (and logs in) at once.
  The other broker, Telegram and the dashboard are untouched. A broker can be on only if its login is stored.
- **Refused while in use:** switching a broker off is refused, with the reason in words, while it has open
  trades, active chains or a running session; the owner waits for them to finish (or stops the session first).
- **What uses an off broker:** a signal for a group on that broker is skipped ("Quotex is switched off"); a
  session on it cannot start (and a scheduled one is skipped with that reason); the forms still let it be picked,
  with a note.
- **Stop retrying what cannot fix itself.** When a login fails in a way more attempts cannot fix (Quotex asks for
  an email PIN; a refused password or token), the broker stops retrying and shows "needs you" with the reason,
  until the owner acts (enters the PIN, fixes the login, or switches it off and on). Network and Cloudflare errors
  keep retrying with the backoff, as now.
- **API and dashboard:** `PUT /brokers/{broker}` with `enabled`; the state in `/status` and the live events; a
  switch on each broker's card in Settings and on its badge's menu in the top bar; `openapi.json` regenerated.
- **Guides:** OPERATIONS, TROUBLESHOOTING, API.

**Acceptance criteria**
- Engine tests with both fakes: switching Quotex off while Deriv trades leaves Deriv trading; Quotex's connect
  loop stops (no more attempts) and starts again when switched on; switching off a broker with an open trade is
  refused with the reason; a Quotex signal while Quotex is off is skipped with the reason; the switch survives a
  restart; a PIN request stops the retries and shows "needs you".
- Component tests for the switches, the refusal and the "Off" / "needs you" badges.
- Backend and frontend checks pass (`ruff`, `mypy`, tests; `eslint`, `tsc`, `vitest`, build, `api:check`).
- Live (owner): Quotex switched off on the dashboard; the log shows no more Quotex attempts.

### Phase 24 — Settle faster, so martingale steps stop drifting (backend)

**Goal:** the time from a trade's expiry to its known result falls from about 3.6 s to about 1 s on `1HZ75V`,
so each step of a chain starts about 1.5 s after the previous one ends instead of 4.1 s.

**Scope**
- **Measure first.** `npm run deriv:check -- --order --timeline` (demo only) places a few 1.00 trades and prints
  the time of each contract update after expiry with its fields (`is_expired`, `exit_tick`, `exit_tick_time`,
  `status`, `is_sold`), and the asset's own price ticks around the expiry. The owner runs it; the output decides
  which of the two ways below is used, and is in the report.
- **The early result (D-82).** The engine acts on the result as soon as it is certain, instead of waiting for
  Deriv to mark the contract sold: either from the first contract update that carries the exit price, or from
  the asset's price stream (it compares the exit price with the entry price by Deriv's rule: equal is a loss).
  The profit is the contract's payout or minus the stake. Deriv's own result, when it comes, is still the one
  stored; if it ever differs from the early one, the trade is marked, logged (`deriv_early_result_mismatch`) and
  shown in the phase report, and the early path can be turned off in the settings.
- **The latency report** (`npm run latency`) gains "expiry → result" and "previous expiry → next step sent".

**Acceptance criteria**
- Tests against the fake server: the early result for won, lost and equal exit; Deriv's later result agrees and
  is stored; a disagreement is marked and logged; with the early path off, the engine waits as today.
- `ruff`, `mypy`, the whole test suite pass.
- Live (owner): a 30-minute session on `1HZ75V` on the demo; `npm run latency` shows the median "expiry →
  result" and "previous expiry → next step sent", against 3.6 s and 4.1 s before; no mismatch, or every one
  explained.

---

## Later backlog (not scheduled)

Telegram alerts to the owner; backtester over stored messages; more parsers + "test this message" tool;
early close of an individual open trade (`sell_option`,
only if Quotex allows it); strategy lab; PostgreSQL migration; hosted multi-user version (legal review
first); official API if Quotex ever offers one.
