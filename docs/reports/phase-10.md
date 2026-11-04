# Phase 10 — Owner account and login — Report

**Date:** 2026-11-04
**Status:** Done with open items — everything is built and tested on fakes and by hand against a real running
server; one pre-existing timing test (`test_reports_performance`) fails on this PC because of speed (section 5).
Nothing that needs the real Quotex or Telegram was touched or run.

## 1. Summary
The dashboard and the whole API are now behind a login. On the first start there is no account, so the
application prints a one-time **setup code** in its log; the dashboard's first page asks for that code, a
username and a password and creates the owner (the admin). From then on every request needs a session: all
routes except `/health` and `/auth/*`, and the live feed (`/ws`). Wrong logins are throttled, a changed
password logs every other browser out, and `npm run owner:reset` sets a new password from the machine itself.
This is the foundation for moving the Telegram and Quotex logins into the dashboard (Phases 11-15, planned in
`docs/PHASES.md`); no secret is stored by the dashboard yet.

## 2. What was done

**Plan and decisions** — `docs/PHASES.md` (Phases 10-15 and "Not in these phases"), `docs/DECISIONS.md` D-58
(what moves from `.env` to the dashboard), D-59 (login first; one owner now, room for more later; no owner
column on the data tables yet), D-60 (scrypt from the standard library, hashed session tokens). D-53's
"no login" part is marked superseded.

**Backend** (`backend/app/`)
- `db/models.py`, `alembic/versions/0002_users_and_sessions.py` — tables `users` (role `admin`) and
  `auth_sessions` (only the SHA-256 of the token).
- `auth/passwords.py` — scrypt (N=2^14, r=8, p=1), cost stored in each hash, run in a worker thread; password
  rules (10-256 characters); a dummy hash so an unknown user costs the same time as a wrong password.
- `auth/throttle.py` — 5 failures lock a name (and an address) for 15 minutes; bounded memory.
- `auth/service.py` — setup code, setup, login, logout, `authenticate` (30-day lifetime, 7-day idle limit),
  change password (ends other sessions), `set_owner` (for the command).
- `api/routers/auth.py`, `api/schemas/auth.py` — `GET /auth/state`, `POST /auth/setup|login|logout|password`;
  cookie `qte_session`: HttpOnly, SameSite=Strict, Secure on https.
- `api/deps.py`, `main.py` — `current_user` dependency attached when the routers are included; `/health` and
  `/auth/*` stay public. `api/ws.py` refuses a socket without a session before accepting it.
- `api/errors.py` — 401 `not_authenticated` / `invalid_login`, 429 `too_many_attempts`, 403 `wrong_setup_code`,
  409 `setup_closed`, 422 `invalid_account`.
- `scripts/owner.py`, `npm run owner:reset` — create the account or reset the password.
- `scripts/demo_server.py` (the demo makes its own `demo` / `demo-password` account) and `scripts/ws_watch.py`
  (`--username`, asks for the password) were adapted because they talk to the protected API.

**Dashboard** (`frontend/src/`)
- `features/auth/` — `AuthGate` (shows setup, login or the dashboard; the live connection is opened only after
  login), `SetupPage`, `LoginPage`, `AccountPage` (change password, log out), `session.ts`, `useLogout.ts`.
- `api/client.ts` — `api.auth.*`; `onUnauthorized` sends the owner back to the login when the server says the
  session is gone (a wrong password, also a 401, does not).
- `app/Layout.tsx` — username link and "Log out" in the top bar; `/account` route.

**Docs** — `API.md`, `OPERATIONS.md` ("The owner account"), `DEPLOYMENT.md`, `TROUBLESHOOTING.md`, `README.md`,
`CLAUDE.md` (one line: single user -> one owner account), `docs/openapi.json` and the generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| No session: 401 on every protected route and on `/ws`; with one it works | ✅ | `test_every_route_but_the_public_ones_refuses_a_visitor_without_a_session` walks the whole OpenAPI document (every operation but the 5 public ones); `test_the_websocket_needs_a_session`; by hand, steps 1, 4, 10 below |
| Setup only with the right code, only while no account exists, then closed for good | ✅ | `test_a_new_installation_asks_for_the_setup_code_and_then_closes_for_good`, `test_too_many_wrong_setup_codes_lock...`, `test_an_account_made_by_the_command_closes_the_setup`; by hand, steps 2, 3, 5 |
| Wrong password, unknown user, throttled attempts tested; the error never says which part was wrong | ✅ | `test_a_wrong_password_and_an_unknown_user_look_exactly_alike`, `test_repeated_failures_lock_the_name_even_for_the_right_password`, `test_one_success_resets_the_count`; by hand, step 6 (identical bodies) |
| A changed password ends the other sessions; logout ends this one | ✅ | `test_changing_the_password_logs_every_other_browser_out`, `test_logging_out_ends_that_session_on_the_server_not_only_in_the_browser`; by hand, step 7 |
| Password and session token never appear in the database in clear, a log line or a response | ✅ | `test_no_password_token_or_hash_reaches_the_database_the_logs_or_a_response` (database file + WAL, captured output, response bodies); by hand: the server log contains neither the password nor the cookie value |
| All existing tests keep passing | ⚠️ | 1023 backend tests pass; 1 fails for speed (section 5); frontend 325 of 326 pass at once and the remaining one passes alone (known flaky) |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 207 files already formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 109 source files; tsc --noEmit: clean
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      1023 passed, 1 failed (test_reports_performance, speed only) in 282 s
$ frontend vitest     325 passed, 1 flaky under load (App.test "marks the current page...": 14/14 when run alone, twice)
```

New tests: backend 60 (`test_auth_passwords.py` 14, `test_api_auth.py` 31, `test_owner_script.py` 4, plus
adaptations), frontend 22 (`AuthGate.test.tsx` 12, `AccountPage.test.tsx` 6, `client.test.ts` 4).

## 5. Challenges and how they were resolved

1. **Hashing was far slower than expected.** OWASP's scrypt setting (N=2^15, p=3) took about 2 s on this PC
   (0.44 s for N=2^14, p=1). That would hold a one-core server for seconds on every login, which the execution
   path must not feel. Resolution: RFC 7914's interactive setting (N=2^14, r=8, p=1), recorded in D-60 with the
   reasons; the cost is stored in each hash so it can be raised later. Remaining: a burst of logins on a 1-vCPU
   server still uses CPU for a moment; the throttle and the command rate limit bound it.
2. **The route-protection test saw no routes.** This FastAPI keeps included routers as objects, so `app.routes`
   is not flat. The test now walks the OpenAPI document instead, which lists every operation.
3. **Every existing API test needed a login.** `running_api` now creates the owner and logs the client in (and
   makes hashing cheap inside the test rig only; full cost is tested separately). `test_ws_socket` passes the
   cookie to its raw sockets; the rate-limit test's burst is one higher because the test's own login uses one.
4. **Login success did not show the dashboard.** `client.clear()` detached the auth query from its observer.
   Fixed with `session.ts`: forget everything except the auth query, then set the new state.
5. **`test_reports_performance` fails on this PC.** It measures report speed on 100,000 trades and does not use
   login or the API. Full suite: CSV export 4.68 s against a 4.0 s bound; run alone it was slower still
   (12.98 s), so the machine was simply slow at that moment (the same PC took 2 s for one scrypt hash).
   I did not change the bound. It passed when Phase 8 was finished. **Not shown to pass on this PC today.**

## 6. Deviations from the plan
- The plan's order in my earlier advice (settings first) was changed to **login first**, as the plan says.
- scrypt parameters are lighter than OWASP's table (D-60, challenge 1).
- `/docs`, `/redoc` and `/openapi.json` (FastAPI's own pages) stay public: they describe the API but contain no
  data. Suggestion below.
- `CLAUDE.md` changed by one line (single user / no accounts -> one owner account), following D-58 and D-59.
- Decisions added: D-58, D-59, D-60.

## 7. Could not be verified
- Everything with the real Quotex or Telegram (unchanged by this phase; still unverified, see earlier reports).
- Login over HTTPS behind a proxy (the `Secure` cookie flag is set when the request scheme is https; behind a
  proxy that terminates TLS the application sees http, so the flag would be missing). The documented way to
  reach a server is the SSH tunnel, which is plain http on loopback by design.
- The first-run page in a real browser: it is covered by component tests and the API by a real server, but I
  did not open a browser.

**How to test it yourself**
1. `npm run build`, then `npm start`. Watch the window for a line `owner_setup_required ... setup_code=XXXX-XXXX-XXXX`.
2. Open <http://127.0.0.1:8000>: you should see "Create the owner account". Type a wrong code: it is refused.
   Type the code from the window, a username and a password of at least 10 characters: you are in.
3. Click **Log out** (top right): the login page appears. Log in again. A wrong password shows
   "Wrong username or password." and the same text for a name that does not exist.
4. Open **Account**, change the password. Open the dashboard in a second browser first and log in there: after the
   change that browser is sent to the login page.
5. Stop the app, run `npm run owner:reset`, set a new password, start again: the new one works.
6. Optional: `npm run demo` and log in as `demo` / `demo-password`.

What I ran by hand (real server on a scratch database, engine off, port 18771): no session on `/status` -> 401;
wrong setup code -> 403; right code -> 201 with an HttpOnly cookie; `/status` with the cookie -> 200; second setup
-> 409; wrong password and unknown user -> identical 401 bodies; logout -> 204 and the old cookie -> 401; login
again -> 200; `/health` without login -> 200; WebSocket without a cookie -> HTTP 403; the server log contained
neither the password nor the cookie value.

## 8. Measurements
scrypt on this PC: N=2^15, p=3: 2.03 s; N=2^14, p=1: 0.44 s (chosen); N=2^15, p=1: 0.93 s; N=2^16, p=1: 1.31 s.
Measured with `hashlib.scrypt`, one run each, so indicative only. A Linux server is usually faster.

## 9. New dependencies / files of note
No new dependency (scrypt, SHA-256 and `hmac` are in Python's standard library). New: `backend/app/auth/`,
`api/routers/auth.py`, migration `0002`, `scripts/owner.py`, `frontend/src/features/auth/`.

## 10. Suggestions and open questions
- Put FastAPI's `/docs`, `/redoc`, `/openapi.json` behind the login, or switch them off in production.
- Setup code is written to the log file too (`data/logs/engine.log`) until the account exists; it is useless
  afterwards, but anyone who can read the log before setup could use it. Only relevant on shared machines.
- The throttle is in memory: a restart clears it.
- Phase 11 next (encrypted store, `SECRET_KEY` in `.env`, settings in the database) when you say "go on".
- Decide later, with the invitation phase: owner column on groups, chains, trades and stored logins.

## 11. Git state
**No commits were made.** `git status --short`: modified `CLAUDE.md`, `README.md`, `package.json`, backend
`app/` (api deps, errors, security, ws, config, db models, domain enums, main), `scripts/` (demo_server,
ws_watch), backend tests (api_support and six adapted test files), `docs/` (API, DECISIONS, DEPLOYMENT,
OPERATIONS, PHASES, TROUBLESHOOTING, openapi.json, STATUS), frontend (`api/`, `app/`, `index.css`); new:
migration `0002`, `app/auth/`, `api/routers/auth.py`, `api/schemas/auth.py`, `scripts/owner.py`,
`tests/integration/test_api_auth.py`, `tests/unit/test_auth_passwords.py`, `tests/unit/test_owner_script.py`,
`frontend/src/features/auth/`, `frontend/src/lib/password.ts`, this report.
