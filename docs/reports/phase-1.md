# Phase 1 — Database and domain models — Report

**Date:** 2026-11-01
**Status:** Done

## 1. Summary
The application now has persistent storage that cannot slow the trading path. There is a database
schema (8 tables) with a reversible Alembic migration, a thin repository layer, an in-memory
`EventBus`, and a `DBWriter` that turns events into rows in the background. Publishing an event takes
about one microsecond (10,000 events in ~11 ms), whatever the database is doing. On startup the app
checks the database is migrated, loads what was in flight (open chains, unsettled trades), and
`/health` now shows the database and writer status. I also found and fixed a logging problem that
could have frozen trading for ~10 seconds on any logged error (section 5, item 2).

## 2. What was done
- **Domain** (`app/domain/`): `enums.py` (account type, direction, strategy, chain/trade/signal
  status), `records.py` (plain immutable records for every table; `GroupSettingsRecord` rejects wrong
  multiplier counts, non-positive stakes, payout outside 0–100), `ids.py` (in-memory UUIDs).
- **Schema** (`app/db/models.py`, migration `alembic/versions/0001_initial_schema.py`): `groups`,
  `group_settings`, `signals` (the inbox), `chains`, `trades` (with `account_type` and the five
  latency checkpoints `t_msg_received_ns` … `t_order_acked_ns`), `risk_events`, `balance_snapshots`,
  `app_settings`. Indexes for the dashboard/report queries (e.g. trades by account + settled time,
  by group + account + settled time, by chain + step). Settings are snapshotted on each chain.
- **Column types** (`app/db/types.py`): `Money` (integer cents ↔ `Decimal`), `UTCDateTime` (always
  timezone-aware UTC), `DecimalList` (multipliers as exact strings).
- **SQLite setup** (`app/db/engine.py`): WAL, `synchronous=NORMAL`, 5 s busy timeout, foreign keys on.
- **Repositories** (`app/db/repositories/`): groups (+settings), signals, chains, trades, risk events,
  balance snapshots, app settings. They take and return records, never ORM objects; lists are paged
  and capped at 1,000 rows.
- **Events** (`app/events/`): typed events (`signal.received`, `chain.started/advanced/ended`,
  `trade.opened/settled`, `risk.tripped`, `balance.updated`, `connection.changed`) and `EventBus`
  with bounded per-subscriber queues. `publish` never waits.
- **DBWriter** (`app/db/writer.py`): subscriber → batches (up to 500) → one transaction each;
  flushes everything queued on shutdown; retries a failed batch event by event; counts
  written/failed/dropped. Policy documented in the file and in D-24.
- **Recovery** (`app/db/recovery.py`): `load_recovery_state` returns groups, settings, open chains
  and unsettled trades.
- **App wiring** (`app/main.py`, `app/api/health.py`): lifespan opens the database, refuses to start
  if it is not migrated, starts the writer, loads recovery state; on shutdown the writer drains first.
  `/health` gained `database`, `events_published` and `writer` (queue depth, written, failed, dropped).
- **Scripts:** `npm run db:upgrade`, `npm run db:downgrade`; `setup` now also migrates.
- **Fixes found on the way:** log-formatting freeze (D-25); `core/logging.py`.
- **Docs:** D-22 (money), D-23 (ids), D-24 (overflow policy), D-25 (logging); README; architecture
  layout.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `alembic upgrade head` on an empty DB works; `alembic downgrade base` works | ✅ | `test_migrations.py` (4 tests incl. up→down→up); manual run below |
| Tests: repositories CRUD | ✅ | `test_repositories.py` — 31 tests. Signals, trades and balance rows have no delete **on purpose** (audit trail); groups and app settings do |
| Tests: `DBWriter` batches and flushes on shutdown | ✅ | `test_a_burst_is_written_in_batches` (450 events → ≤6 commits), `test_shutdown_flushes_everything_still_queued` |
| Tests: event published → row exists | ✅ | `test_published_events_become_rows` (all 7 persisted event kinds), `test_event_published_while_running_is_in_the_database_after_shutdown` (through the real app lifespan) |
| Benchmark: publishing 10,000 events does not block beyond a stated limit; number in report | ✅ | Limit: 250 ms for 10,000. Measured: **10.1–11.1 ms (≈1.0–1.1 µs per event)**, section 8 |
| Schema uses no SQLite-only constructs (note anything unavoidable) | ✅ | `test_schema_uses_only_portable_column_types`. Notes in section 6 |
| Startup recovery query: load open chains and unsettled trades | ✅ | `test_recovery.py` (2 tests) and `test_open_chains_are_loaded_at_startup` |
| SQLite connection setup: WAL, `synchronous=NORMAL`, busy timeout, foreign keys | ✅ | `test_sqlite_setup.py` (5 tests) |

## 4. Checks run

```
$ npm run check                      (repo root)
ruff check                           All checks passed
ruff format --check                  53 files already formatted
eslint / prettier --check            clean
mypy (strict, 32 source files)       Success: no issues found
tsc --noEmit                         clean
pytest                               109 passed in 11.77s
vitest                               3 passed
vite build                           built in 818 ms
```
No `time.sleep`, `requests` or `input(` anywhere in `backend/app` (grep).

## 5. Challenges and how they were resolved
1. **A test caught a real bug in the writer** — logging a failed event used `event=` as a keyword,
   which structlog already uses for the message, so the log call itself crashed and killed the writer
   task. Fixed (`event_name=`), and the writer loop now survives any unexpected error in a batch
   (`test_one_bad_record_does_not_take_its_batch_down`).
2. **Logging an error could freeze the event loop for ~10 seconds** — cause: structlog's default
   "rich" traceback prints local variables; for one database error it took 9.5 s (0.04 s with plain
   text). It also cannot be printed on a Windows console using cp1252. Resolution: plain tracebacks in
   `core/logging.py` (D-25) and in the test setup. Measured before/after, above. Remaining risk: none
   known; any new log call with `exc_info` is now cheap.
3. **Autogenerated migration would depend on app code** — Alembic wrote our custom column types into
   the migration. Resolution: `render_item` in `alembic/env.py` writes plain SQLAlchemy types, so old
   migrations keep working when app code changes. A post-write hook formats new migrations with ruff.
4. **ruff mistook our `backend/alembic/` folder for the alembic library** when sorting imports.
   Resolution: marked `alembic` as third-party in `pyproject.toml`.
5. **Shell heredocs failed twice** (quote handling); I used the file-writing tool instead. No effect on
   the result.

## 6. Deviations from the plan
- **UUIDs for most primary keys instead of auto-increment** (D-23): required by D-4, otherwise each new
  chain/trade would need a database round-trip.
- **Money as integer cents** (D-22) — the decision the phase asked for.
- **App wiring and `/health` additions** (lifespan, refusing an unmigrated database, new health
  fields): not listed in the Phase 1 scope, but `ARCHITECTURE.md` §10 and the conventions ("lifecycle
  in lifespan") require them and they make the phase testable by hand. Say if you would rather have
  had these in a later phase.
- **Portability notes (nothing SQLite-only, but these differ per database):** UUIDs are `CHAR(32)` on
  SQLite and native `UUID` on PostgreSQL; JSON is stored as text on SQLite; timestamps lose their zone
  on SQLite, so `UTCDateTime` always stores UTC and re-attaches it. The only SQLite-specific code is
  the four `PRAGMA`s in `engine.py`, guarded by a dialect check. `groups.id` is a plain `Integer`
  primary key so SQLite auto-increments it.
- No `events` audit table (listed as optional in `ARCHITECTURE.md` §6) — not needed yet.
- New decisions: **D-22, D-23, D-24, D-25** in `docs/DECISIONS.md`.

## 7. Could not be verified
- **Behaviour on PostgreSQL.** Only SQLite was run. The schema avoids SQLite-only features and is
  covered by the portability test, but nothing was executed on PostgreSQL.
- **Graceful shutdown with Ctrl+C on a running server.** The flush on shutdown is tested through the
  app lifespan, but I stopped the live server by killing the process, not with Ctrl+C. To check by
  hand: start `npm run backend`, press Ctrl+C, and look for the log line `shutdown`.

## 8. Measurements
Measured on this PC (Windows, SQLite file on local disk). Command:
`npm run test:backend -- tests/integration/test_event_throughput.py -s`.

| What | Result |
|---|---|
| Publish 10,000 events (DBWriter + a second, never-reading subscriber attached) | 10.1–11.1 ms total, ≈1.0–1.1 µs per event. Limit set: 250 ms |
| Slowest single publish while the writer was actively writing | 31–115 µs (limit asserted: 5 ms) |
| Background writing speed of DBWriter | ≈370–540 rows/s (1,000 rows in 1.8–2.7 s) |

The write speed is far above real load (a few trades per minute plus inbox messages), and a 10,000-event
burst would take ~20 s to reach the database while the queue (100,000) holds it. It could be made
faster by combining rows per batch; I did not, because nothing needs it (see Suggestions).

## 9. New dependencies / files of note
No new dependencies (alembic, sqlalchemy, aiosqlite were added in Phase 0).
- `backend/app/domain/` — enums, ids, records (the vocabulary of the system)
- `backend/app/db/` — `models.py`, `types.py`, `engine.py`, `repositories/`, `writer.py`,
  `recovery.py`, `migrations.py`
- `backend/app/events/` — `types.py`, `bus.py`
- `backend/alembic/` + `alembic.ini` — migrations (`versions/0001_initial_schema.py`)
- `backend/tests/` — `conftest.py`, `factories.py`, 8 new test files

## 10. Suggestions and open questions
- **Frontend toolchain upgrade:** you are on Node 26 now, so Vite 8 / Vitest 5 / etc. (D-21) are
  possible. I did not do it (outside Phase 1). Say when, and I will do it as a small separate chore.
- **Writer speed:** if inbox volume ever grows, merge rows per batch (one SELECT for the whole batch)
  and coalesce repeated updates of the same chain/trade. Not needed now.
- **Stale unsettled trades after a crash:** recovery only *loads* them; deciding whether to settle
  from Quotex history or mark `unknown` is Phase 4 work, as planned.
- **Health endpoint calls the database** (`SELECT 1`) on every request. Fine for a local dashboard;
  if it is polled very often later, cache the result.

## 10a. Follow-up after owner review (2026-11-02)
The owner accepted the app wiring and asked for the frontend toolchain upgrade. Done: Vite 8.3.5,
plugin-react 6, Vitest 5, jest-dom 7, jsdom 30, react-hooks plugin 7, react-refresh plugin 0.5,
globals 17, @types/node 26. Kept on purpose: React 18, TypeScript 5.9, ESLint 9. Results: eslint,
prettier, `tsc`, Vitest (3 tests) and `vite build` pass; no more `EBADENGINE` warnings; dev server and
`/api` proxy verified against the live backend (health through port 5173 returned the same JSON as
port 8000). The stricter new Vite found one real mistake from Phase 0: `strict` was listed twice in
`frontend/tsconfig.node.json`; removed. README now says Node 22 LTS or newer.

## 11. Git state
**No commits were made and nothing was staged.** Your Phase 0 commit `3463839` is the latest.
`git status --short` shows modified: `README.md`, `backend/app/api/health.py`,
`backend/app/core/{config,logging}.py`, `backend/app/main.py`, `backend/pyproject.toml`,
`backend/tests/unit/test_tasks.py`, `backend/tests/unit/test_health.py`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `docs/STATUS.md`, `package.json`; new: `backend/alembic.ini`, `backend/alembic/`,
`backend/app/{db,domain,events}/`, `backend/app/core/clock.py`, `backend/tests/{conftest,factories}.py`,
`backend/tests/integration/`, three new unit test files, `docs/reports/phase-1.md`.
`backend/uv.lock` is unchanged. The local database `backend/data/` was removed after my manual run.

---

## 12. How to test it yourself

All commands from the repository root (`quotex_trade_engine/`). I ran each of these myself first; the
results shown are what I saw.

**1. Everything at once (about 1 minute)**
```
npm run check
```
Expect: `109 passed` (backend), `3 passed` (frontend), no errors from lint/type checks, build finishes.

**2. The app refuses to start without a database**
```
npm run backend
```
Expect: it stops with `DatabaseNotMigratedError: The database is missing or out of date. Run
npm run db:upgrade …`. (This creates an empty file `backend/data/quotex.db`; the next step fills it.)

**3. Create the database**
```
npm run db:upgrade
```
Expect: `Running upgrade  -> 0001, initial schema`.

**4. Start the app and look at the health report**
```
npm run backend
```
In a second terminal (PowerShell):
```
curl http://127.0.0.1:8000/api/v1/health
```
Expect JSON containing `"database":"ok"` and `"writer":{"queue_depth":0,"written":0,"failed":0,"dropped":0}`.
In the backend log you should see `recovery_loaded groups=0 open_chains=0 unsettled_trades=0`.
Stop it with Ctrl+C and look for the `shutdown` log line (this is the check I could not do).

**5. See the tables**
```
uv run --directory backend python -c "import sqlite3; c=sqlite3.connect('data/quotex.db'); print(sorted(r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")))"
```
Expect: `alembic_version, app_settings, balance_snapshots, chains, group_settings, groups, risk_events,
signals, trades`.

**6. The migration works backwards and forwards** (this deletes the data in the file, fine at this stage)
```
npm run db:downgrade
npm run db:upgrade
```
Expect: `Running downgrade 0001 -> , initial schema`, then `Running upgrade  -> 0001, initial schema`;
step 5 shows only `alembic_version` after the downgrade and all nine names after the upgrade.

**7. Watch the event → database pipeline being tested**
```
npm run test:backend -- tests/integration/test_writer.py -v
```
Expect 9 tests with readable names, all `PASSED`, e.g. `test_published_events_become_rows`,
`test_shutdown_flushes_everything_still_queued`, `test_a_full_queue_drops_new_events_and_counts_them`.

**8. See the speed numbers**
```
npm run test:backend -- tests/integration/test_event_throughput.py -s
```
Expect three `[benchmark]` lines: publishing 10,000 events in roughly 10–15 ms, the slowest single
publish well under 1 ms, and the writer's rows-per-second. The test fails if 10,000 events take over
250 ms.

**9. Money and time safety**
```
npm run test:backend -- tests/unit/test_column_types.py -v
```
Expect: floats refused, three decimal places refused, naive (zone-less) datetimes refused,
`12.34` stored as `1234`.

**Clean-up:** to start again from nothing, delete the folder `backend/data/` (it is git-ignored).

---

_After writing this report: update `docs/STATUS.md`, give the owner a short summary, and stop._
