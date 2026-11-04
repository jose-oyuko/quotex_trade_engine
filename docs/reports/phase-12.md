# Phase 12 — Engine control from the dashboard — Report

**Date:** 2026-11-04
**Status:** Done with open items: built and tested on fakes and by hand against a real server with no
logins; starting the **real** engine from the dashboard (a real Quotex and Telegram login) is not verified
(section 7).

## 1. Summary
The owner now starts, stops and restarts the trading engine (Quotex and Telegram together) from the
dashboard's **Settings** page, while the application keeps running. The page shows the engine's state
(stopped, starting, running, stopping, could not start), says why a start failed, and lists the logins the
engine would use and where each comes from. The engine is built with the logins stored in the dashboard
first and `backend/.env` second. What the owner left (running or not) is remembered, so a running engine
comes back by itself when the application starts. Real-money trading is now a dashboard decision: allowing
it and switching to the REAL account each ask for the owner's password again and are written to the risk
log. The path from a signal to an order is the same code as before.

## 2. What was done

**Decisions** — D-63 (the engine's life cycle belongs to the owner and is remembered) and D-64 (real money:
the permission and the switch each need the password) in `docs/DECISIONS.md`.

**Backend** (`backend/app/`)
- `engine/controller.py` — `EngineController`: start / stop / restart, one at a time (a second request is 409),
  a fresh engine each start, recovery read only after the writer stored everything (`db/writer.py:wait_idle`),
  what was in flight marked `unknown` at stop, the owner's permission for real money.
- `engine/flags.py` — what the owner decided, in `app_settings` (`engine.desired`, `engine.allow_real`).
- `engine/logins.py` — the engine is built with stored logins first, `.env` second; a stored login that cannot
  be read stops the start (no silent fallback); `login_items` says where each login comes from, no values.
- `api/routers/engine.py`, `api/schemas/engine.py` — `GET /engine`, `POST /engine/start|stop|restart`.
- `api/routers/control.py` — `PUT /account` needs the password to go to REAL; `PUT /account/real-trading`.
- `auth/service.py` — `confirm_password` (shares the lock with other password attempts).
- `engine/engine.py` — switching to REAL writes the risk event `switched_to_real`.
- `quotex/` — `set_real_allowed` on the adapters (the real and the fake one) and the protocol.
- `main.py` — builds the controller, starts the engine only if the owner left it running (a failed start no
  longer stops the application), stops it on shutdown without changing the owner's choice.
- `api/snapshot.py`, `api/health.py`, `api/schemas/status.py` — the engine's `state` and `error` in `/status`,
  the WebSocket snapshot and `/health` (a failed start is listed as a problem).
- `scripts/start.py` — the start-up summary no longer talks about `.env` logins or `ENGINE_ENABLED`.
- Clearer messages for missing logins (they point at the dashboard).

**Dashboard** (`frontend/src/features/settings/`) — `EnginePanel` (start, stop with confirmation, restart,
state, error, logins), the real-money section with `PasswordConfirm` (allow, stop allowing, switch to REAL,
back to demo); the Live page now links to Settings instead of telling the owner to edit `.env`.

**Docs** — `API.md`, `OPERATIONS.md` ("The trading engine"), `FAILURE_MODES.md`, `TROUBLESHOOTING.md`,
`DEPLOYMENT.md`, `README.md`, `.env.example` (the two settings are now only starting values),
`docs/openapi.json` and the generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Start, stop and restart without restarting the application | ✅ | `test_the_engine_can_be_started_stopped_and_started_again_without_restarting_the_app`, `test_restart_builds_a_new_engine_and_leaves_no_task_behind` (3 restarts: no task piled up), by hand (below) |
| No trade on REAL without the confirmed switch | ✅ | `test_real_money_is_off_until_the_owner_allows_it_with_the_password`, `test_switching_to_the_real_account_needs_the_permission_and_the_password_again`, `test_the_permission_survives_a_restart_but_the_engine_always_starts_on_demo`; existing `test_switching_to_real_is_refused_unless_it_was_switched_on_in_the_settings` |
| The engine is built from the stored logins | ✅ | `test_the_engine_uses_the_stored_logins_before_the_env_ones`, `test_a_stored_login_that_cannot_be_read_stops_the_start_it_is_not_swapped_for_env` |
| The execution path is unchanged | ✅ | No file of the signal-to-order path changed (`signals/`, `engine/executor.py`, `engine/chain.py`, `engine/manager.py` untouched); the engine, latency and risk-overhead tests pass unchanged; the controller only builds, starts and stops the engine |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 226 files formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 122 source files; tsc --noEmit: clean
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      full run: 1107 passed, 3 failed (all three were tests that assumed the old rules; fixed,
                      see below). The three files were re-run afterwards: 25 passed. The full suite was not
                      run a third time (about 4 minutes here).
$ frontend vitest     27 files, 352 tests, all passed
```

The three failures of the full run, all expected consequences of the new rules and fixed in the tests:
- `test_api_telegram_chats`: the message now points at the Settings page instead of `ENGINE_ENABLED`.
- `test_restart::test_a_graceful_shutdown...`: the engine was left running, so the next start of the application
  starts it again and flags the chain; the test now reads the stored state straight from the database first.
- `test_architecture_rules`: the new life-cycle modules (`controller`, `flags`, `logins`) read the database
  when the engine is started or stopped. The rule keeps the signal-to-order path free of the database, and now
  also fails if anything on that path imports those modules.

New tests: backend 29 (`test_api_engine.py`) plus changes to 8 existing ones; frontend 14 (`EnginePanel.test.tsx`)
plus adapted ones.

## 5. Challenges and how they were resolved

1. **A restart must not read a half-written database.** The old engine's last events are still in the writer's
   queue when it stops. Resolution: `DBWriter.wait_idle()` before the recovery is read; a test restarts with a
   chain in flight and checks it ends exactly once as `unknown` and the new engine places nothing.
2. **A start used to be allowed to stop the whole application** (a missing login raised out of start-up). That
   no longer makes sense when the owner fixes it in the dashboard. A failed start now leaves the application up
   with the engine `failed` and the reason shown (one old test was rewritten for it).
3. **Two requests at once.** A second start/stop while one is in progress is refused (409), not queued, so the
   owner never ends up with a stop that quietly follows a start. Tested with a held build.
4. **Open chains after a stop.** They would have stayed listed on the dashboard for an engine that no longer
   follows them. Stopping now marks them `unknown` at once (the same wording and risk events as after a crash).
5. **Existing tests assumed the old rules** (the exact shape of the engine status, switching to REAL with no
   password, a start-up error). They were updated to the new rules; each is listed in the diff.

## 6. Deviations from the plan
- `ENGINE_ENABLED` and `QUOTEX_ALLOW_REAL` are not removed yet: they stay as the starting value for an
  installation that never decided on the dashboard, so nothing breaks for existing setups. Phase 15 removes them.
- The Telegram API id still comes from `.env` (it is not a secret; Phase 13 moves it).
- New decisions: D-63, D-64.

## 7. Could not be verified
- Nothing needing the real Quotex or Telegram was run: the tests use the fake adapter and fake Telegram source.
  So *starting the real engine from the dashboard* (a real login, a real connection) is **not** verified.
- The dashboard in a real browser (component tests and a real server were used).

**How to test it yourself** (use a normal `npm start`; the demo has its own fake engine):
1. Open **Settings**: the *Trading engine* box says **Stopped** and, if a login is missing, lists it and the
   **Start the engine** button is greyed out. Store a Quotex email and password and the Telegram API hash under
   *Stored logins* (any text) and put `TELEGRAM_API_ID=123` in `backend/.env`.
2. Press **Start the engine**: it will try the real Quotex login with what you typed, so this step needs your
   **real demo credentials**; with made-up ones it shows **Could not start** with Quotex's reason, which is
   itself the test of the failure path. Fix the login and press it again.
3. When it runs: **Restart** works; **Stop the engine** asks first and says what happens to open trades.
4. Quit the application and start it again: an engine you left running starts by itself; one you stopped stays
   stopped.
5. *Allow real-money trading…* asks for your password; a wrong one is refused. After allowing, *Switch to the
   REAL account…* asks again. (Do not do the last step unless you mean it; **Switch back to the demo account**
   needs no password.) Open the risk log (History/Reports) to see the entries.

What I ran by hand (real server, scratch database, the fake engine is not available outside tests, so the real
builder was used): a server with no logins and no key
beyond a scratch one: `/engine` answered `stopped` and listed the four missing logins; `POST /engine/start` answered
409 `engine_start_failed` with the reason ("The Quotex email and password are not set. Store them under Settings >
Stored logins ..."), the state became `failed`, `/health` turned `degraded` and listed the same sentence, and
`kill-switch` answered 503 "Start it on the Settings page"; `POST /engine/stop` cleared the failure. `PUT
/account/real-trading` without a password was 422, with a wrong one 401, with the right one 200; the risk log then
held `real_trading_allowed`; switching to REAL with the engine stopped was refused (503). No Quotex or Telegram
connection was made.

## 8. Measurements
None this phase.

## 9. New dependencies / files of note
No new dependency. New: `backend/app/engine/controller.py`, `flags.py`, `logins.py`, `api/routers/engine.py`,
`api/schemas/engine.py`, `tests/integration/test_api_engine.py`, `frontend/src/features/settings/EnginePanel.tsx`,
`PasswordConfirm.tsx`.

## 10. Suggestions and open questions
- Phase 13 (Telegram login in the dashboard) is next.
- A stopped engine leaves Quotex trades running to their expiry: the application only marks them `unknown`.
  Closing a trade early (`sell_option`) stays in the "Later" backlog.
- The engine's state is read when the page loads and after each action; two browsers open at once will not see
  each other's change until they refresh (single-owner use makes this rare).

## 11. Git state
Committed and pushed by the agent after the checks above, with the owner's standing instruction ("go on from phase 12 till the end, test everything after the phase and then commit them to github"). See `git log`.
