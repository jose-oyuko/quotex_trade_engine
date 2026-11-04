# Phase 13 — Telegram login in the dashboard — Report

**Date:** 2026-11-04
**Status:** Done with open items: built and tested on a fake Telegram, and the safe routes checked by hand on a
real server. A **real** Telegram login (a real code from Telegram) has **not** been run (section 7).

## 1. Summary
The Telegram login is now made on the dashboard (Settings > Telegram): the API id and hash, then the phone
number, then the code (with "send it another way"), then the two-step password if the account has one. A
half-made login survives a page reload. When it succeeds, the login is stored **encrypted in the database**
as a session text, not as a `.session` file, and the engine uses it. "Log out of Telegram" removes it and ends
it on Telegram's side. Wrong codes, expired codes, a wrong password, a bad phone number or API id, and
Telegram asking to wait are each explained in words. The command-line login still works as a fallback.

## 2. What was done

**Decision** — D-65 (a state machine in memory, one login at a time, engine stopped, string session stored
encrypted, the session and phone are the application's own entries) in `docs/DECISIONS.md`.

**Backend** (`backend/app/`)
- `services/telegram_login.py` — `TelegramLoginService`: status, start (phone), resend, code, password, cancel,
  logout; forgotten after ten minutes; Telegram's refusals turned into errors with words; nothing saved until
  success.
- `telegram/source.py`, `telethon_source.py`, `fake.py` — distinct errors (`CodeInvalidError`,
  `CodeExpiredError`, `PasswordInvalidError`, `FloodWaitLoginError(seconds)`, `PhoneInvalidError`,
  `ApiCredentialsError`); the real source can keep its login as text (`StringSession`), report it
  (`session_string`) and log out; the fake source can be scripted to fail.
- `telegram/factory.py` — the engine's source uses the stored session, then `TELEGRAM_SESSION`, then the old
  file; none of them: it says Telegram is not logged in. `new_login_source` for the dashboard's login.
- `vault/store.py` — new entries `telegram_api_id` (digits only), `telegram_phone`, `telegram_session`; the last
  two are *internal*: the application writes them, the secrets API can neither set nor list them. Entries have
  a `group`.
- `engine/logins.py` — the engine is built with the stored API id and session; the engine page lists "Telegram
  login" with where it comes from (dashboard, `.env`, an old login file, missing, unreadable).
- `api/routers/telegram.py`, `api/schemas/telegram.py` — `GET /telegram/login`, `POST /telegram/login/start|code|
  resend|password|cancel`, `POST /telegram/logout`; `api/errors.py` maps the new errors.
- `core/config.py`, `.env.example` — `TELEGRAM_SESSION` (masked in logs).

**Dashboard** (`frontend/src/features/settings/TelegramPanel.tsx`) — the API id and hash form, the phone, code,
password steps, logged-in view with a confirmed logout; the Quotex part of "Stored logins" is now "Quotex
login" (the Telegram entries moved to the Telegram box).

**Docs** — `OPERATIONS.md` (first-time logins rewritten), `TROUBLESHOOTING.md`, `API.md`, `DEPLOYMENT.md`,
`DECISIONS.md`, `docs/openapi.json` and the generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| The whole flow is tested with the fake source | ✅ | `test_api_telegram_login.py` (39 tests): code, resend, wrong code, expired code, two-step password, flood wait, bad phone, unreachable Telegram, steps out of order, cancel, expiry, logout |
| The half-finished login survives a page reload | ✅ | `test_a_half_made_login_is_still_there_after_a_page_reload_even_in_another_browser`; frontend `shows a half-made login after a reload, at the step it had reached` |
| The session is stored encrypted instead of a `.session` file | ✅ | `test_logging_in_with_a_code_stores_the_session_encrypted`; `test_nothing_secret_reaches_the_database_the_log_or_an_answer` (session, phone, password, hash, code: not in the database file and its write-ahead log, the log, or any answer) |
| Log out of Telegram | ✅ | `test_logging_out_removes_the_session_and_ends_it_on_telegram`, `..._works_even_if_telegram_cannot_be_reached`, `..._also_removes_the_file_the_command_line_login_made` |
| Flood waits and wrong codes explained in plain words | ✅ | `test_a_flood_wait_says_how_long_to_wait_and_keeps_the_state` ("5 minute(s)"), `test_a_wrong_code_can_be_retyped_without_starting_over`, `test_an_expired_code_ends_the_login_and_says_to_start_again`, and the matching frontend tests |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 228 files formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 123 source files; tsc --noEmit: clean (after fixing one
                      missing label the build caught)
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      full run: 1149 passed, 2 failed (see below)
$ frontend vitest     28 files, 369 tests, all passed
```

The two backend failures of the full run:
- `test_reports_performance`: report speed on 100,000 trades; the known speed failure of this PC (Phase 10 and 11
  reports); it uses none of this phase's code.
- `test_api_control::test_ending_a_chain_frees_the_group_now...`: failed once in the full run, then passed 3 of 3
  times alone (3-4 s each). It waits up to 4 s for a database write on a slow, busy PC; it does not touch the
  Telegram code. Treated as a timing flake of the test; not changed.

## 5. Challenges and how they were resolved

1. **The API must not know Telegram.** The architecture rules forbid the API layer from importing
   `app.telegram`, even for error types. The service (which may) translates Telegram's errors into its own, and
   the API maps those.
2. **A login must not collide with the engine.** Both would be connections of one account, so logging in or out
   is refused while the engine runs (409 `engine_running`), and the page says so.
3. **Telegram's own flood wait and expiry rules.** The real source used one error for everything; it now
   raises distinct ones (the wait carries its seconds), so the page can say "retype the code" or "start again" or
   "wait 5 minutes". Telethon itself cannot be run here, so this mapping is verified only by reading its error
   names (see section 7).
4. **A login that survives a reload but not a restart.** The conversation (Telegram's code hash) cannot be saved
   safely, so it lives in memory for ten minutes. A restart means asking for a new code.
5. **Existing tests assumed the old rules** (the factory builds a source from the API id alone, the secrets list
   had three entries, the engine's login list). Updated; the factory test now covers the three session sources.

## 6. Deviations from the plan
- The plan said "the session is stored encrypted instead of a `.session` file"; the old file is still read as a
  fallback (and removed on logout) so existing installations keep working until Phase 15.
- The phone number is stored (encrypted) after a successful login, only to show it hidden in the box.
- New decision: D-65. No new dependency (Telethon's `StringSession`).

## 7. Could not be verified
- A **real Telegram login** (a real code from Telegram, a real two-step password, a real flood wait). The tests
  use a fake source, and the mapping of Telethon's errors to ours (`PhoneCodeInvalidError`,
  `PhoneCodeExpiredError`, `PasswordHashInvalidError`, `FloodWaitError`, `SendCodeUnavailableError`,
  `PhoneNumberInvalidError`, `ApiIdInvalidError`) is written from Telethon's documentation and is untested
  against Telegram. Also not verified: that Telegram lists the string session among the devices and that
  `log_out` ends it, and that the stored string session keeps working after a restart.
- The page in a real browser.

**How to test it yourself** (this logs in with your real Telegram account; use a number you control):
1. `npm start`, open **Settings > Telegram**. Create the API id and hash at my.telegram.org (log in with your
   phone number, "API development tools", create an application) and type them in; press Save.
2. Type your number (`+254712345678` style) and press *Send me the code*. Look for a message from "Telegram"
   in your Telegram app; type the code. If you have two-step verification, type its password when asked.
3. It says **Logged in**. Reload the page: still logged in. Settings > Devices in your Telegram app lists a new
   session.
4. Prove the half-made login survives a reload: log out, start again, send the code, press F5 before typing it:
   the code box is still there.
5. Prove a wrong code is forgiving: type 00000: "That code is not right"; the right one still works.
6. Prove it is encrypted: with the app stopped, run the query from the Phase 11 report against `secrets`: you
   see `telegram_session` as `v1.…` text, not the login.
7. Start the engine (Settings > Trading engine): the list shows *Telegram login: stored here*; the Telegram
   connection badge turns green. Stop it, press **Log out of Telegram…**, confirm: the login box asks for a
   number again, and the session disappears from your Telegram devices.

What I ran by hand (real server, scratch database; **no Telegram contact was made**): `GET /telegram/login` →
`logged_out`, `configured: false`; `start` before the API id and hash were stored → 409
`telegram_not_configured` ("Create them at https://my.telegram.org…"); `code` with no login in progress → 409
`telegram_login_step`; a non-numeric API id → 422; `PUT /secrets/telegram_session` → 404 (the session cannot be set
from outside); `logout` when logged out → 200; `/engine` listed "Telegram login" as missing; `/secrets` listed
the Telegram id and hash in the `telegram` group and no session or phone.

## 8. Measurements
None this phase.

## 9. New dependencies / files of note
No new dependency. New: `backend/app/services/telegram_login.py`, `tests/integration/test_api_telegram_login.py`,
`frontend/src/features/settings/TelegramPanel.tsx`, `telegramFixtures.ts`.

## 10. Suggestions and open questions
- Phase 14 (the Quotex login, including the email PIN step, on the dashboard) is next.
- A string session is saved once, at login. If Telegram ever moves the account to another data centre the saved
  text goes stale and the owner would log in again; saving it again on engine stop is possible later.
- The login conversation is in memory: two application instances (not a supported setup) would not share it.

## 11. Git state
Committed and pushed by the agent after the checks above, with the owner's standing instruction (carry on to the
last phase, test after each, commit to GitHub). See `git log`.
