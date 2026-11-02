# Phase 6 — API and realtime events — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes. Like Phases 2–5 it has
only run against the fake Quotex and fake Telegram (section 7).

## 1. Summary
The backend now has a complete, typed interface for the dashboard. A REST API under `/api/v1` covers
groups (create, edit, delete, pause), chains, trades, the signal inbox, risk limits, the kill switch,
the account in use and a status page; a WebSocket at `/ws` pushes everything that happens, live, as
numbered messages that start with a snapshot. A dashboard that is slow or disconnected can never slow
the engine. The API's description (`docs/openapi.json`) is generated from the code, and the frontend's
types and a typed client are generated/written from it, so the two sides cannot drift apart without
`npm run check` failing. The API also protects itself against other web pages in your own browser
(section 2, "Safety of the API itself"). Writing it exposed one real bug from Phase 5, now fixed (section 5).

## 2. What was done

**REST API** (`backend/app/api/routers/`, guide in `docs/API.md`)
- Groups: list/create/read/replace/delete, pause/resume, per-group risk limits. Creating or editing a
  group tells the running engine at once (a new group trades without a restart; a disabled one stops).
- Chains (list with filters, detail with trades and the originating message, `stop-after-current`,
  `end`), trades, signals, risk events: all paged (`items/total/limit/offset`), filters as query
  parameters, newest first.
- Risk: `GET /risk`, `PUT /risk/limits`, `GET/PUT /groups/{id}/risk`, kill switch (`POST`/`DELETE`),
  account (`GET`/`PUT`), `GET /status`, extended `GET /health`, and `GET /reports/summary` as a 501
  placeholder for Phase 8.
- One error format everywhere (`app/api/errors.py`); validation errors name the field and never echo
  the value; unexpected errors are a plain 500 with no trace.
- **Limits can be set without the engine** (that is the safe order: limits first, engine second).
  Commands that need the running engine answer 503 `engine_not_running`.

**WebSocket** (`app/api/hub.py`, `ws.py`, `events.py`, `snapshot.py`, `services/live.py`)
- `LiveState` is rebuilt from events only; the hub turns each event into a numbered message and
  updates `LiveState` in the same synchronous step. First frame is a `snapshot`, then events with
  consecutive numbers, heartbeats carrying the latest number, `resync` on request.
- Per-client bounded queue (1,000): an overflowing client gets a fresh snapshot instead of the events
  it could not take. Protocol in `docs/API.md` and decision D-40.
- New event `account.changed` (published by `Engine.switch_account`) so the DEMO/REAL indicator can
  update live.

**Safety of the API itself** (`app/api/security.py`, decision D-41)
- Only loopback host names are served (defeats DNS rebinding); changes and WebSockets from another
  web page's `Origin` are refused (otherwise any site you open could press your kill switch); request
  bodies are limited to 64 KiB; commands are rate limited. All tested.

**Typed frontend client** (`frontend/src/api/`)
- `schema.d.ts` generated from `docs/openapi.json` (`npm run api:generate`), `types.ts` (names),
  `client.ts` (every endpoint, `ApiError`), `live.ts` (`LiveSocket`: gap detection, resync,
  reconnect with backoff and jitter, dead-connection watchdog). The WebSocket messages are in the
  OpenAPI document too, so they are typed like everything else.

**Tooling and docs**
- `npm run api:export | api:types | api:generate | api:check | api:watch` (the last prints the live feed).
- `docs/API.md` (new), D-39…D-42, ARCHITECTURE layout and API section, README, `.env.example`.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| API tests with `httpx.AsyncClient` for every endpoint (happy path + validation errors) | ✅ | `tests/integration/test_api_groups.py`, `test_api_history.py`, `test_api_control.py`, `test_api_errors_security.py`. `tests/unit/test_openapi.py::test_the_api_offers_exactly_the_expected_operations` lists all 27 operations, so a new endpoint cannot be added without touching the tests |
| WebSocket tests: snapshot | ✅ | `test_ws_socket.py::test_a_dashboard_gets_a_snapshot_then_the_events_in_order`, `…_that_connects_later_sees_the_chain_that_is_already_running`; `test_ws_hub.py::test_a_new_client_gets_a_snapshot_first…` |
| WebSocket tests: ordered events | ✅ | consecutive `seq`, event order signal → chain → trade → settled → ended (`test_ws_socket.py`), `test_ws_hub.py::test_events_after_the_snapshot_follow_with_consecutive_numbers`, `…_does_not_use_up_a_number` |
| WebSocket tests: gap detection | ✅ | server side: `resync` request and heartbeat carrying the latest number (`test_ws_hub.py`, `test_ws_socket.py::test_asking_for_a_resync…`); client side: `live.test.ts` ("detects a gap…", "asks for a new snapshot when a heartbeat shows it missed events", duplicates, events before a snapshot) |
| WebSocket tests: slow-consumer handling | ✅ | `test_ws_hub.py::test_a_client_that_falls_behind_gets_a_fresh_snapshot…` (bounded queue, snapshot instead of lost events), `…_a_slow_client_costs_the_publisher_nothing` (5,000 events, queue stays ≤ 5), `test_ws_socket.py::test_a_dashboard_that_reads_too_slowly_loses_events_not_the_engine` (real socket; engine finished all 4 orders) |
| OpenAPI schema committed (or generated by a script) and the frontend types compile against it | ✅ | `docs/openapi.json` committed; `test_openapi.py::test_the_committed_openapi_document_is_current`; `frontend/src/api/schema.d.ts` generated from it; `npm run api:check` and `tsc` in `npm run check` |
| Input validation and safe defaults; bind rules from Phase 0 still enforced | ✅ | bounded/typed request models (`test_invalid_groups_are_refused_with_the_field_named`, `test_limits_are_validated`), host/origin/size/rate guards (`test_api_errors_security.py`), `test_config.py` (Phase 0 bind rule) still passes |

## 4. Checks run
```
$ npm run check
api:check  docs/openapi.json is up to date. / src/api/schema.d.ts is up to date.
ruff check: All checks passed!   ruff format: 162 files already formatted   eslint + prettier: clean
mypy (strict): Success: no issues found in 93 source files    tsc --noEmit: clean
pytest: 742 passed        vitest: 45 passed        vite build: built
```
Mutation checks (I broke the code on purpose and confirmed a test fails): **31 backend breakages**
(hub numbering/queue/snapshot/heartbeat, event mapping, live state, host/origin/size/rate guards,
group and risk services, chain commands, the Phase 5 day-total fix, WebSocket resync/size limit,
repository filters, error mapping, snapshot, account announcement): 29 caught. The 2 survivors were
(a) the hub's "skip events already inside the snapshot" test, which turned out to be unreachable code
(removed), and (b) the `Content-Length` pre-check of the body limit, which only saves reading the body
(the streaming counter gives the identical 413, so no test can tell them apart; kept as the cheaper
path). **15 frontend breakages** of `LiveSocket` (gap/duplicate/heartbeat/backoff/jitter/watchdog/
resync/wss): 14 caught, the 15th was again dead code (removed). Two of these runs also made me
tighten tests (a heartbeat-then-late-event case).

## 5. Challenges and how they were resolved
1. **A Phase 5 bug found while exposing limits through the API.** `RiskGuard.set_limits` started the
   day's profit-and-loss from zero, so saving the limits again after the daily stop-loss was reached
   would have lifted the stop-loss. Fixed with a 48-hour in-memory ledger from which the day's totals
   are rebuilt (decision D-42); two regression tests added.
2. **`FastAPI` hides its routes.** The installed FastAPI wraps included routers lazily, so listing
   `app.routes` found nothing. The "exactly these operations" test reads them from the generated
   OpenAPI document instead.
3. **A body-size error looked like a different error.** An over-long body without a `Content-Length`
   made FastAPI answer 400 ("error parsing the body") instead of 413. The middleware now hands the
   app an empty end of body and replaces whatever it answers with the 413.
4. **My first tests used `http://test` as the host**, which the new host check (rightly) refuses. The
   old health tests now use `http://127.0.0.1`.
5. **A dead safety net in the hub.** Mutation testing showed that the per-client "skip events already
   in the snapshot" check could never trigger (the queue is emptied when the snapshot is taken), so it
   was removed rather than kept as untested code.
6. **A flaky test, found by the mutation run.** `test_the_kill_switch_can_end_the_running_chains_at_once`
   failed in 2 of 6 standalone runs: it read the chain from the database before the writer had stored
   it (the API answered 404) and indexed into the error body. The code was right, the test did not
   allow for "not stored yet". Fixed; the whole API/WebSocket test set was then run 4 times in a row
   (96 tests each, all green) and the control tests 12 times.

## 6. Deviations from the plan
- **Endpoint names:** `ARCHITECTURE.md` mentioned `skip-to-base`; it is `POST /chains/{id}/end`
  (ending the chain frees the group, so the next signal starts at base stake). Documented in D-39.
- **Risk limits work without the engine**, the other controls do not (D-39). Not in the plan; it
  follows from "limits first, then enable".
- **Browser protections (D-41) and the 64 KiB / rate limits** go beyond the phase text but are required
  by the security checklist in `CONVENTIONS.md`.
- New decisions: **D-39, D-40, D-41, D-42.**

## 7. Could not be verified
Everything real, as before: the API has only run against the fake Quotex and Telegram.
- **The browser itself.** The Origin/Host rules and the WebSocket were tested with real sockets and
  hand-written headers, not with a real browser page; Phase 7 will exercise them from the dashboard.
  *Manual check:* with the backend running, open any other website, press F12 → Console and run
  `fetch('http://127.0.0.1:8000/api/v1/kill-switch', {method:'POST'})`; it must fail (CORS) and
  `engine.guard.kill_switch` must not change; the log shows nothing placed.
- **The engine with real components** (as in earlier phases).

## 8. Measurements
Measured on this PC (real clock, `scratchpad` script, 20,000 events):

| | median | 99th percentile |
|---|---|---|
| `bus.publish` with only the DB writer subscribed | 0.8 µs | 2.6 µs |
| `bus.publish` with the WebSocket hub and 5 dashboards connected | 1.2 µs | 2.7 µs |

So the dashboards add about **0.4 µs** to every event the engine publishes (the hub does its work in its
own task, after `publish` has returned). The hub itself handled **~26,000 events/s** (39 µs per event
including JSON for 5 clients); a busy trading day is a few events per second. The Phase 5 order path
(signal → `place_order`, ~96 µs) is unchanged: the engine never calls anything in `api/`.

## 9. New dependencies / files of note
- `openapi-typescript` 7.13 (frontend, dev only) — generates the types from the OpenAPI document.
  `npm audit` reports moderate "minimatch" advisories in dev tooling (ESLint, this generator); nothing
  of it is in the bundle. No new backend dependencies (`httpx` and `websockets` were already dev dependencies).
- New: `backend/app/api/{errors,security,hub,ws,events,snapshot,openapi,deps,views}.py`,
  `api/routers/`, `api/schemas/`, `app/services/{live,groups,risk_settings}.py`,
  `scripts/{export_openapi,ws_watch}.py`, `docs/API.md`, `docs/openapi.json`,
  `frontend/src/api/{schema.d.ts,types,client,live}.ts`, `frontend/scripts/api-types.mjs`.

## 10. Suggestions and open questions
- **A way to find Telegram chat ids from the dashboard** (`GET /telegram/dialogs`): today you need
  `npm run telegram:dialogs`. Not built (not in scope).
- **List of parsers** for the group form (`GET /parsers`); there is only `legacy_v1` today.
- **Refuse to switch to REAL while no stop-loss or max stake is set** (also suggested in Phase 5).
- **No login:** still true. The Origin/Host rules protect against other web pages, not against another
  program on this PC.
- The kill switch and pauses need the engine to be running; with the engine off they answer 503. Say if
  you would rather they could also be stored while it is off.

## 11. Git state
Committed as `feat: API and realtime events (Phase 6)` once checks passed (see `git log`).

## 12. How to test it yourself
No account needed.

**1. Everything:** `npm run check` (expect all green, backend and frontend counts above).

(I ran steps 2–4 myself against a throwaway database on port 8011 with `curl`: group created, invalid stake refused with the field named, limits stored and read back, both hostile requests answered 403, kill switch answered 503 without the engine, and `api:watch` showed the snapshot. The server was stopped afterwards.)

**2. Try the API in the browser** (engine off, nothing is contacted):
```
npm run backend
```
Open <http://127.0.0.1:8000/docs>. Try `POST /groups` ("Try it out", the example body is valid except
the chat id), then `GET /groups`, `PUT /risk/limits` with `{"max_stake": "5.00", "daily_stop_loss": "20.00"}`,
`GET /risk` and `GET /status`. Send something invalid (stake `0`) and read the error.

**3. Watch the live feed:** in a second terminal run `npm run api:watch`. You see a `snapshot`, then
`#N heartbeat` lines every 15 s; change a limit in the browser page and a `controls.changed` line appears.

**4. The protections:** `curl -i -X POST -H "Origin: http://evil.example" http://127.0.0.1:8000/api/v1/risk/limits -H "Content-Type: application/json" -d "{}"`
must answer `403 origin_not_allowed`; `curl -i -H "Host: evil.example" http://127.0.0.1:8000/api/v1/health` must answer 403.

**5. Engine paths** (kill switch, chain commands, WebSocket events during real trades) run in the test
suite on the fakes: `uv run pytest tests/integration/test_api_control.py tests/integration/test_ws_socket.py -v`
(from `backend/`).
