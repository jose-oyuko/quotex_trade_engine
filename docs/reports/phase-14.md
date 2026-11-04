# Phase 14 — Quotex login in the dashboard — Report

**Date:** 2026-11-04
**Status:** Done with open items: built and tested on a fake login and a stand-in for the library, and the
safe routes checked by hand on a real server. A **real** Quotex login from the dashboard (and the real Cloudflare
refusal) has **not** been run (section 7).

## 1. Summary
The Quotex login is now made on the dashboard (Settings > Quotex login): with the email and password stored
there, one button logs in; when Quotex e-mails a PIN, the box asks for it and finishes the login with it. The
resulting session is stored **encrypted in the database**, and the engine uses it. The library only understands a
session *file*, so it is given one in a private temporary folder that is emptied as soon as it is no longer
needed and removed afterwards: **no Quotex credential is left on disk**. A refused login says why in words, and
the library's crash on Quotex's refused sign-in page (the `reason_phrase` error behind the Cloudflare 403) is now
reported as what it means instead of as a crash.

## 2. What was done

**Decision** — D-66 in `docs/DECISIONS.md`.

**Backend** (`backend/app/`)
- `quotex/pyquotex_login.py` — `PyQuotexLogin`: logs in through the library in a private temporary folder, asks
  for the PIN through a callback, reads the saved session back as text, removes the folder whatever happens.
- `quotex/pyquotex_client.py` — the engine's connection can take a stored session: it is written to a private
  folder, deleted the moment the connection is made, folder removed on close (without one, the data folder is used
  as before); `explain_connect_error` turns the library's `reason_phrase` crash into a sentence; the "PIN needed"
  message now points at the dashboard.
- `quotex/base.py`, `fake.py`, `factory.py` — `LoginRequest` / `QuotexLogin` seam, `FakeQuotexLogin` for tests,
  `new_quotex_login`; the adapter factory passes the stored session on.
- `services/quotex_login.py` — `QuotexLoginService`: one background login at a time, the PIN handed over through a
  future, status safe after a reload, five-minute PIN limit, engine-stopped rule, logout.
- `services/login_errors.py` — the errors the Telegram and Quotex logins share (moved out of the Telegram service).
- `api/routers/quotex.py`, `api/schemas/quotex.py` — `GET /quotex/login`, `POST /quotex/login/start|pin|cancel`,
  `POST /quotex/logout`; errors mapped in `api/errors.py`.
- `vault/store.py` — the internal entry `quotex_session`; `engine/logins.py` — the engine is built with it and the
  engine page lists "Quotex login" (not required: without it the email and password are used);
  `core/config.py` / `.env.example` — `QUOTEX_SESSION` (masked in logs).

**Dashboard** (`frontend/src/features/settings/QuotexPanel.tsx`) — log in, the PIN box with Quotex's own wording,
"talking to Quotex" with Cancel, logged-in view with a confirmed removal; the engine box shows optional logins
without alarm.

**Docs** — `OPERATIONS.md`, `TROUBLESHOOTING.md` (the Cloudflare sentence, PIN, reset), `API.md`, `DECISIONS.md`,
`docs/openapi.json` and the generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| The flow is tested with the fake client | ✅ | `test_api_quotex_login.py` (22 tests): plain login, PIN, wrong PIN, non-digit PIN, PIN timeout, cancel, replace, refused login, Cloudflare wording, engine running, logout, unreadable session, secrets |
| No credential is left on disk after a login | ✅ | `test_quotex_session_files.py` (12): the private folder and the session file are gone after a successful login, a refused one, a crash and a login with no token; for the engine the session file is deleted once connected and the folder removed on close, even after a failed connection; `test_no_password_pin_or_session_reaches_the_database_the_log_or_an_answer` also searches the data folder |
| The session is stored encrypted and read through the store | ✅ | `test_logging_in_stores_the_session_encrypted_and_uses_the_stored_credentials`, `test_the_engine_is_built_with_the_stored_session` |
| A clear message for a block (HTTP 403) instead of the library's crash | ✅ (message) / ⏸ (real Cloudflare) | `test_the_librarys_crash_on_a_blocked_sign_in_page_is_explained`, `test_cloudflares_refusal_is_explained_in_words_not_a_crash`; not seen against the real site (section 7) |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 235 files formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 128 source files; tsc --noEmit: clean
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      full run: 1184 passed, 1 failed (an architecture rule, fixed, see below); the file was
                      re-run afterwards: 13 passed. The full suite was not run a second time (over 5 minutes here).
$ frontend vitest     29 files, 380 tests, all passed
```

The failure of the full run: `test_within_the_quotex_package_only_the_client_module_imports_pyquotex`. It says the
library may be imported by one module only; the dashboard login is a second library-facing module on purpose
(`pyquotex_login.py`, D-66). The rule now names both and still forbids any other. (The 100,000-trade speed test
passed in this run.)

New tests: backend 34 (`test_api_quotex_login.py` 22, `test_quotex_session_files.py` 12); frontend 11
(`QuotexPanel.test.tsx`) plus adapted ones.

## 5. Challenges and how they were resolved

1. **The library wants a file.** Its session lives in `session.json` under a module-level folder setting, which a
   second login or connection could overwrite. Resolution: each login or connection makes its own private
   temporary folder, sets the setting, and (for logins) is serialised by the one-at-a-time rule and the
   engine-stopped rule. The folder is removed in a `finally`, and the file is deleted as soon as the connection
   is up.
2. **The login waits for the PIN in the middle of one call.** A request/response API cannot wait for a person. The
   login therefore runs as a background task and the PIN reaches it through a future; the status call tells the
   page which step it is at, so a reload keeps the PIN box.
3. **A wrong PIN is not a retry.** The library reports it as a failed login, not as "type the PIN again", so a
   wrong PIN ends that login (Quotex sends a new PIN when it is started again). The page says so.
4. **A timeout inside the library was being wrapped** into a generic error; the PIN timeout now keeps its meaning
   ("not typed in time").
5. **Existing tests assumed no `Quotex login` entry** in the engine's list and a `PIN needed` message that pointed
   at the command line; updated.

## 6. Deviations from the plan
- The plan said the adapter "gives the library a private temporary file". It is a private temporary *folder* (the
  library takes a folder), emptied once connected and removed on close.
- A token the library refreshes while the engine runs is not saved back to the store (D-66, "known limit").
- The command-line `quotex:diagnose` is unchanged and keeps its own `session.json` (Phase 15 decides its future).
- New decision: D-66. No new dependency.

## 7. Could not be verified
- A **real Quotex login** from the dashboard (the real library, the real PIN e-mail, a real refusal): the tests use
  a fake login and a stand-in for the library's `Quotex` class. That the library behaves as read in its source (it
  keeps its session in `session.json` under `config.base_dir` and asks for the PIN through `on_otp_callback`) is
  verified by reading it, not by running it against Quotex.
- That the stored session is accepted by Quotex on the next start (and how long it lasts).
- The Cloudflare block itself: the sentence is written for the library's `reason_phrase` crash; whether that is the
  exact error a real block produces is the finding of the earlier diagnosis (HTTP 403 `cf-mitigated: challenge`
  seen with plain `curl`), not re-checked here.
- The page in a real browser.

**How to test it yourself** (this logs in to Quotex with your real **demo** credentials):
1. `npm start`, open **Settings**. Under *Quotex email and password* store your Quotex email and password.
2. In the *Quotex login* box press **Log in to Quotex**. Either it says **Logged in**, or it says Quotex wants a
   PIN: open the e-mail from Quotex, type the digits and press *Send the PIN*.
3. If it says Quotex's website refused the request (Cloudflare), that is the real block, described in words; it is
   not your password.
4. Reload the page while it waits for the PIN: the PIN box is still there.
5. Type letters as the PIN: it is refused without ending the login. Cancel: back to the log-in button.
6. After *Logged in*: look in `backend/data/` for any `session.json` created by this login: there must be none
   (a file there comes from `npm run quotex:diagnose`, not from the dashboard). Also check your system temp folder
   for `qte-quotex-*` folders: there must be none.
7. Prove it is encrypted: with the app stopped, query `secrets` as in the Phase 11 report; there is no
   `quotex_session` in the listing API, but the table holds `v1.…` text, not the token.
8. Start the engine: the engine box lists *Quotex login: stored here*, and the Quotex badge turns green.

What I ran by hand (real server, scratch database; **no Quotex contact was made**): `GET /quotex/login` -> `logged_out`,
`configured: false`; `start` with no email and password stored -> 409 `quotex_not_configured` (nothing is sent to
Quotex); `pin` when none is wanted -> 409 `quotex_login_step`; `PUT /secrets/quotex_session` -> 404; `logout` when
logged out -> 200; `/engine` listed "Quotex login" as missing and *not required* while the five required logins
were listed as missing; no `qte-quotex-*` folder was left in the temp directory.

## 8. Measurements
None this phase.

## 9. New dependencies / files of note
No new dependency. New: `backend/app/quotex/pyquotex_login.py`, `services/quotex_login.py`,
`services/login_errors.py`, `api/routers/quotex.py`, `tests/integration/test_api_quotex_login.py`,
`tests/unit/test_quotex_session_files.py`, `frontend/src/features/settings/QuotexPanel.tsx`.

## 10. Suggestions and open questions
- **Phase 15** (clean-up and documentation) is next, and decides what happens to `ENGINE_ENABLED`,
  `QUOTEX_ALLOW_REAL`, the command-line logins and the old `.env` logins.
- The Cloudflare problem on servers is **not** solved by this phase; it only explains itself now. Testing from the
  real server with the dashboard login is the next real evidence.
- Saving a refreshed token back (see D-66) would reduce how often Quotex asks for a PIN after restarts.

## 11. Git state
Committed and pushed by the agent after the checks above, with the owner's standing instruction (carry on to the
last phase, test after each, commit to GitHub). See `git log`.
