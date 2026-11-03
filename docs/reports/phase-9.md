# Phase 9 — Hardening and packaging — Report

**Date:** 2026-11-02
**Status:** Done with open items — every failure mode that can be provoked offline is tested and
documented, and a copy of the project set up from the README starts and answers. Everything that needs the
real Quotex or Telegram (including the live latency measurement) has **not** been run (section 7).

## 1. Summary
The application now survives the things that go wrong in daily use, and says so when they do. A locked or
unreachable database no longer loses history (the writer waits it out for up to ten minutes); logs rotate
and hide passwords; `/health` and a dashboard banner name each problem in plain words. A "chaos" test
throws random trouble at the whole engine and checks that the books balance; it found one real bug (events
for a chain could arrive "ended" before "started"), now fixed. Crash and restart are tested end to end on a
real database file. For daily use there is `npm start` (and `start.bat`), `npm run backup` (with restore)
and `npm run latency`. The documentation is complete: README, operations guide, troubleshooting, failure
modes and a VPS deployment guide.

## 2. What was done

**Failure handling** (`backend/app/`)
- `db/writer.py` — transient database errors (locked, unreachable, disk full) are retried with backoff for
  up to 10 minutes; other errors are isolated record by record; shutdown gives up after three attempts (D-50).
- `core/logging.py`, `core/config.py`, `main.py` — rotating JSON log file `data/logs/engine.log` (10 MB x 5)
  and masking of the Quotex password and Telegram hash (D-51). New settings `LOG_TO_FILE`, `LOG_MAX_MB`,
  `LOG_BACKUPS`.
- `api/health.py` — `status` (`ok` / `degraded`) and `problems` in sentences (D-52).
- `engine/manager.py` — chain events are published in order (`_announce`, D-54).
- `engine/engine.py` — the Telegram reconnect backoff can be injected (so tests need no real waiting).

**Dashboard** — `HealthBanner` above the header, polling `/health` every 15 s.

**Packaging** (`backend/scripts/`, root)
- `start.py`, `start.bat`, `npm start` — checks Node, installs and builds the dashboard only when needed,
  upgrades the database, checks the port, prints a summary with no secrets, starts and opens the browser.
  Each failure explains what to do.
- `backup.py`, `npm run backup` — consistent online backup, integrity check, manifest, `--no-secrets`,
  `--keep`, restore that keeps the replaced database (D-56).
- `latency_report.py`, `npm run latency` — signal-to-order, decision-to-order and order-to-ack percentiles
  from the timestamps every trade stores.

**Documentation**
- `README.md` rewritten (quick start for a new machine, configuration, features, development).
- `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md`, `docs/FAILURE_MODES.md`, `docs/DEPLOYMENT.md`.
- `docs/DECISIONS.md` D-50 to D-56, `docs/ARCHITECTURE.md` (observability, secrets), `.env.example`
  (new settings, and a test that keeps it in step with the code).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Failure-mode tests pass | ✅ (on fakes) | `test_writer_outage.py` (7), `test_connection_loss.py` (5), `test_restart.py` (4), `test_chaos.py` (14 seeds + ordering), `test_health_degraded.py` — all in the 963 passing |
| Documented behaviour for each failure | ✅ | `docs/FAILURE_MODES.md`: a table plus a section per failure, each naming its tests |
| A clean-machine setup following the README works (describe how it was verified) | ⚠️ partly | See "Clean-machine check" below: done on this PC, in a copy of the project with no `.env` and no data. Not a different, empty computer. |
| Final report lists known limitations and the "Later" backlog | ✅ | Section 10 |
| Startup recovery, graceful shutdown, log rotation | ✅ | `test_restart.py`, `test_writer_outage.py::..shutdown..`, `test_logging.py` (rotation and masking) |
| One-command Windows start | ✅ | `npm start` / `start.bat`; `test_start_script.py` (14) and the clean-copy run below |
| Documented VPS deployment | ⚠️ written, not run | `docs/DEPLOYMENT.md` says plainly it has not been followed on a real server |
| Operations guide, troubleshooting | ✅ | `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md` |
| Latency measured with the real adapter on demo | ⏸ not verifiable here | Tool built and tested (`npm run latency`); steps in section 7 |

### Clean-machine check (what was and was not done)
Because Phase 9 was not committed yet, a `git clone` would have lacked it. Instead the files git would
commit (tracked plus new, minus everything ignored: no `.env`, no `data/`, no sessions) were copied to a new
folder, `C:\qte_clean`, and the README was followed there:

1. `npm run setup` → exit 0 (about 90 s: `uv sync` including `pyquotex` from GitHub, `npm install`,
   database created). `npm install` printed "npm audit" notices about the frontend dependencies; not
   looked into (suggestion 3).
2. `npm start -- --prepare-only` → built the dashboard, upgraded the database, printed the summary
   (`Trading: OFF`, `Account: demo only`, "no backend/.env: defaults are used"), "Everything is ready".
3. `npm start -- --no-browser` on port 18765 → `/api/v1/health` returned `status: ok`, `problems: []`;
   `/` and `/reports` returned the dashboard (200); a request with `Host: evil.example` was refused
   (`host_not_allowed`); a second `npm start` said "Port 18765 is already in use. Is the app already
   running?"; the JSON log file appeared and began with `startup`.
4. `npm run backup` while it ran → `integrity: ok`, row counts printed. `npm run latency` → "No timed
   trades yet".
5. The server was ended and the port checked free.

Limits of this check: the same PC (Node, uv and a warm package cache were already there); no real logins
(none were configured, on purpose); the stop was a forced process end, so the real Ctrl+C path was not
exercised in a real process (it is tested in-process, `test_a_graceful_shutdown_is_quick_...`).

## 4. Checks run

```
$ npm run check
api:check      docs/openapi.json is up to date; src/api/schema.d.ts is up to date
ruff check     All checks passed!      ruff format --check: clean
mypy (strict)  Success: no issues found in 101 source files
pytest         963 passed in 153.42s   (Phase 8: 881)
vitest         22 files, 294 tests passed   (Phase 8: 290)
eslint, prettier, tsc --noEmit: clean
vite build     built in 522ms          exit code 0
```

**Mutation checks** (each change applied to the code and the relevant tests run; a test must fail):
writer not retrying, writer patience ignored, secrets not masked, "retrying" not reported, connections
ignored in health, prune keeping everything, prune deleting folders it did not make, secrets always
included in backups, dashboard never rebuilt, port check skipped, the stop-path `_announce` removed —
all 11 **killed**. One further mutation survived: removing the `_announce` call at the top of `_drive`.
It is an equivalent mutant: the start is also published by a scheduled call (`call_soon`) that always
runs first, so the call in `_drive` is a second safety net, not a behaviour. Left in on purpose.

## 5. Challenges and how they were resolved

1. **The chaos test found an ordering bug** — ending a chain in the very moment it started (kill switch,
   "skip to base") could publish `chain.ended` before `chain.started`, so the database held an end with no
   start. Fix: hold the start event until the chain is driven and publish it first when ending (D-54).
   Regression test fails without the fix. Remaining risk: none known.
2. **A re-saved limit could lift a stop-loss** (Phase 5, found earlier) — not Phase 9, but the chaos test
   guards the same invariant: today's result equals the stored profits.
3. **Restart tests read too early** — the writer is a moment behind, so the first read saw `open`. Tests now
   poll until the database shows the expected state.
4. **A damaged database gave a raw SQLite error** in backup and restore. Now it is reported as a failed
   integrity check, nothing partial is left, and the original is untouched (tests with a deliberately
   scribbled file).
5. **Start-up failed in a very deep folder** — in my first clean-machine attempt the scratch folder path was
   about 190 characters and `curl_cffi` could not load its DLL ("filename or extension is too long"). Not a
   code bug; documented in TROUBLESHOOTING (move the project to a short path) and the check repeated in
   `C:\qte_clean`.
6. **Stopping the background server left its Python process running** — stopping the `npm` wrapper does not
   stop the child. I ended that one process (the one listening on my scratch port) by hand.
7. **A test of the old health shape failed** (`test_health_reports_database_and_writer` did not expect
   `retrying`/`status`); updated to the new shape and extended.

## 6. Deviations from the plan
- **Docker not provided** (D-53): the plan said "systemd/Docker optional, decide with the owner". I chose
  systemd plus an SSH tunnel and wrote down why; say if you want a Dockerfile.
- **Clean-machine check used a copy of the would-be-committed tree**, not `git clone` (see above).
- New decisions: **D-50** writer retry, **D-51** log file and masking, **D-52** degraded health, **D-53**
  VPS approach, **D-54** event order, **D-55** missed Telegram signals are not fetched later, **D-56** backups.

## 7. Could not be verified
All of it runs on fakes. Nothing here has touched the real Quotex or Telegram.

1. **Signal → order latency with the real adapter.** After some demo trades: `npm run latency`
   (`-- --account demo --days 7`). Success: medians for "signal → order" (and its 95th/99th percentile) are
   well under a second, with "order → ack" dominated by Quotex's network time. Send me the table. It
   excludes the delivery from Telegram's servers to you.
2. **Real reconnect behaviour.** On demo with `ENGINE_ENABLED=true`: disconnect the internet for 30 s, then
   reconnect. Success: the banner appears for both services and clears by itself; a signal posted during the
   gap is not traded; the next one is. Pull the cable *with a trade open*: it should still settle, or become
   `unknown` and be listed as such.
3. **Crash on a real run.** End the process from Task Manager during an open demo trade, then `npm start`.
   Success: the trade and its chain show `unknown`; a `risk.tripped` event is logged; the kill switch (if it
   was on) is still on.
4. **Ctrl+C in the real `npm start`**: the log should end with a `shutdown` line within a few seconds.
5. **A VPS deployment**: nobody has followed `docs/DEPLOYMENT.md`. In particular whether `uv run` passes
   SIGINT to the application under systemd (the guide gives a fallback).
6. **Real Excel opening a CSV** (Phase 8), and the **PostgreSQL branch** of `reports/sql.py` (Phase 8) are
   still unverified.
7. Everything listed as pending in the earlier reports (Phases 2 to 8), mainly the live Telegram and Quotex
   steps.

## 8. Measurements
No latency figures from the real adapter exist yet (see 1 above). Timings seen offline:
- Full backend test suite: 153 s (963 tests, including 14 seeded chaos runs).
- `npm run setup` on a machine with a cold project folder: about 90 s.
- Backup of an empty database: well under a second. The reports on 100,000 trades (Phase 8) stay between
  about 0.2 and 2.6 s.

## 9. New dependencies / files of note
No new dependencies.
- `backend/scripts/start.py`, `backup.py`, `latency_report.py`; `start.bat`; `npm start|backup|latency`.
- `frontend/src/app/HealthBanner.tsx` (+ test).
- Tests: `integration/test_writer_outage.py`, `test_chaos.py`, `test_restart.py`, `test_connection_loss.py`,
  `test_health_degraded.py`; `unit/test_logging.py`, `test_backup_script.py`, `test_latency_report.py`,
  `test_start_script.py`, `test_env_example.py`.
- Docs: `docs/OPERATIONS.md`, `TROUBLESHOOTING.md`, `FAILURE_MODES.md`, `DEPLOYMENT.md`.

## 10. Known limitations, suggestions and the "Later" backlog

**Known limitations**
- Unofficial Quotex library: it can break, and automated trading may break Quotex's rules.
- No login on the dashboard; relies on the loopback bind and, on a server, an SSH tunnel.
- Credentials and session files are stored unencrypted in `backend/data/` (and in backups unless
  `--no-secrets`).
- A signal posted while Telegram is disconnected is lost to the system (D-55); an order wanted while Quotex
  is down fails instead of waiting (by design: late entry is worse).
- A database outage longer than 10 minutes, or one that fills the 100,000-event queue, loses history
  (reported loudly; trades are still on Quotex's own history).
- After a crash or restart, open trades become `unknown` and must be checked on Quotex by hand (the
  application cannot read Quotex's history).
- Win/loss comes from the library, which cannot report draws (D-29).
- Single user, single machine, SQLite.
- Windows deep-folder DLL problem (TROUBLESHOOTING).
- Only fakes have been exercised; real-service failure modes are only assumed (FAILURE_MODES, last section).

**Suggestions (not built)**
1. A one-line "run on demo for N days" checklist in the dashboard before enabling real money.
2. A scheduled backup on Windows (Task Scheduler entry for `npm run backup -- --no-secrets`).
3. Look at the `npm audit` notices from `npm install` (frontend dev dependencies); not examined.
4. A Dockerfile, if you want one (D-53).

**Later backlog** (from `docs/PHASES.md`, unchanged and not scheduled): Telegram alerts to the owner;
backtester over stored messages; more parsers and a "test this message" tool; encrypted credential storage
and a dashboard login; early close of an individual open trade (`sell_option`, only if Quotex allows it);
strategy lab; PostgreSQL migration; hosted multi-user version (legal review first); official API if Quotex
ever offers one.

**Open questions for you**
- Do you want Docker after all, or is systemd plus an SSH tunnel enough?
- Should a signal that was missed during a Telegram outage ever be fetched and (if recent) traded? (D-55)

## 11. How to test it yourself
Everything below is safe: no real logins, no real money. The first five I have already run (section 3).

1. `npm run check` — everything green (963 backend, 294 frontend tests).
2. `npm run setup`, then `npm start -- --prepare-only` — prints the summary and "Everything is ready".
3. `npm start` — the dashboard opens; Live, Signals, Groups, History, Reports all load; no red banner.
4. `npm run backup` while it runs, then look in `backups/`; `npm run latency` says "No timed trades yet".
5. Start a second `npm start`: it says the port is in use.
6. `npm run build` then `npm run demo`, open <http://127.0.0.1:8000>: simulated trades arrive; on the Live
   page try the kill switch; `npm run latency` will not read the demo database unless you point it there:
   `npm run latency -- --database backend/data/demo/quotex.db` shows real timings of the *simulated* path.
7. Break something on purpose: open `backend/data/quotex.db` in a database viewer that locks it while
   `npm start` runs, and watch the banner; close it and watch the banner clear.
8. Read [docs/FAILURE_MODES.md](../FAILURE_MODES.md) and check the live steps in section 7 on demo.

## Addendum: Telegram chat picker (requested after Phase 9)
The owner expected the add-group form to list their Telegram groups by name instead of asking for the
numeric chat id. Added (D-57): `GET /api/v1/telegram/chats` (through the running engine's Telegram
connection) and a **Choose from my Telegram chats** button on the add-group form, with search, groups
that already exist greyed out, and clear messages when the engine is off or Telegram is not connected.
Tests: `test_api_telegram_chats.py` (8) and `TelegramChatPicker.test.tsx` (9); 11 deliberate breakages
all caught. Not verified against the real Telegram: the list is only exercised on the fake source.
To try it yourself: with `ENGINE_ENABLED=true` and a connected Telegram, open Groups, Add a group,
press the button, and check that your groups and channels appear with the right names.

## 12. Git state
Committed by the agent after this report, with the owner's permission given for this session (message
`feat: hardening and packaging (Phase 9)`). Not pushed. A stray scratch folder `C:\qte_clean` (the
clean-machine copy, with its own virtual environment) remains outside the repository; the agent was not
allowed to delete it, so you can delete it yourself.
