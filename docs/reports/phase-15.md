# Phase 15 — Clean-up and documentation — Report

**Date:** 2026-11-04
**Status:** Done with open items: everything is built and tested on fakes, and the new import and the removed
switches were checked by hand on a real server. The live checks listed in section 7 have not been run.

## 1. Summary
The move of everything the owner types into the dashboard (Phases 10-15) is finished. This phase removed what
was left of the old way: `ENGINE_ENABLED` and `QUOTEX_ALLOW_REAL` no longer exist (the engine's "left running"
and the real-money permission live in the database and change only on the dashboard); the logins that used to
be written in `backend/.env` can be moved into the encrypted store, from the dashboard or with
`npm run env:import`; and the command-line tools now use the same stored logins as the dashboard. `.env.example`
and the README, operations guide, deployment guide and troubleshooting guide were rewritten for the new way.
This report also lists, for the whole of Phases 10-15, what is known to be limited and what has never been run
against the real services.

## 2. What was done

**Decision** — D-67 in `docs/DECISIONS.md`.

**Backend**
- `core/config.py`, `main.py`, `api/snapshot.py` — `engine_enabled` removed; `quotex_allow_real` kept as a field
  the application sets but with an environment name nobody would write, so an old `.env` line cannot allow real
  money; a new installation never starts the engine by itself.
- `services/env_import.py`, `api/routers/settings.py` — `GET /settings/env-logins` (which logins `.env` still holds
  and which are stored; no values) and `POST /settings/env-logins/import` (moves them; never overwrites a stored
  one; never edits `.env`).
- `scripts/env_import.py`, `npm run env:import` — the same from a terminal, plus tidying `.env` (each moved line
  becomes a comment holding no value, Windows line endings kept), retiring the two old switches, leaving the engine
  running if `ENGINE_ENABLED=true` was set and the dashboard never decided, never carrying real money over.
- `scripts/_store.py` — opens the encrypted store for the tools; `scripts/telegram_cli.py` stores its login there and
  uses the stored API id/hash/login; `scripts/quotex_diagnose.py` uses the stored logins; both fall back to `.env`
  and the old session file when there is no usable store.
- `scripts/start.py`, `scripts/demo_server.py` — the summary no longer talks about the removed switches; the demo
  leaves its own engine running through the same stored choice.

**Dashboard** — `EnvLoginsNotice` on the Settings page (names the old logins, moves them with one button, then asks
for the lines to be deleted).

**Docs** — `.env.example` (only bootstrap values, the key, and clearly marked starting values and old logins),
`README.md`, `docs/OPERATIONS.md` ("Moving old logins out of `.env`"), `docs/DEPLOYMENT.md` (first start and logins
on a server through the dashboard, the key step, two more checklist items), `docs/TROUBLESHOOTING.md`,
`docs/API.md`, `docs/DECISIONS.md`, `docs/STATUS.md`, `docs/openapi.json` and the generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| The old `.env` logins become an optional one-time import, then are ignored | ✅ | `test_the_dashboard_lists_what_env_still_holds_and_moves_it_without_a_value_showing`, `test_moving_never_overwrites_a_login_that_is_already_stored`, `test_the_engine_prefers_the_stored_copy_once_it_is_moved` (a stored login always wins), `test_the_command_moves_the_logins_tidies_the_file_and_leaves_the_engine_on`, `test_tidy_removes_the_values_and_keeps_everything_else_exactly` |
| `ENGINE_ENABLED` / `QUOTEX_ALLOW_REAL` leave `.env` | ✅ | `test_an_old_engine_or_real_money_line_in_env_changes_nothing` (file and environment variable), `test_a_new_installation_never_starts_the_engine_by_itself`; `.env.example` no longer lists them |
| Backups and `--no-secrets` explained for the encrypted store | ✅ | `OPERATIONS.md` (Backups), `DEPLOYMENT.md` (Backups on a server, the key, the checklist); tested in Phase 11 (`test_a_backup_without_secrets_has_no_stored_secret_or_session_in_any_file`) |
| The command-line logins read and write the same store | ✅ | `test_the_telegram_command_stores_its_login_where_the_dashboard_finds_it`, `test_the_tools_see_the_logins_stored_on_the_dashboard`, `test_without_a_usable_store_the_tools_use_env_as_before` |
| README, OPERATIONS, DEPLOYMENT, TROUBLESHOOTING, `.env.example` rewritten for the new way | ✅ | the files; `test_env_example.py` keeps `.env.example` and the code in step |
| Final report with the limitations | ✅ | section 7 and 10 below |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 239 files formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 129 source files; tsc --noEmit: clean
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      1203 passed, 0 failed (4 min 57 s)
$ frontend vitest     30 files, 385 tests, all passed
```

New tests: backend 17 (`test_env_import.py`) and 2 (config), several existing ones rewritten for the removed
switches; frontend 5 (`EnvLoginsNotice.test.tsx`).

## 5. Challenges and how they were resolved

1. **A real bug in my own command, found by its test.** `tidy` compared environment names (`QUOTEX_EMAIL`) with the
   store's names (`quotex_email`), so nothing would ever have been tidied. The test that checks the file after the
   command caught it; `tidy` now documents and uses the store names.
2. **Removing a setting that the adapter factories read.** `quotex_allow_real` could not simply be deleted. It stays
   as a field set by the application, with an environment alias nobody would write; the first attempt (an alias plus
   `populate_by_name`) still let `QUOTEX_ALLOW_REAL` through, which the new test showed, so the alias alone is used
   and the field is set with `model_copy`.
3. **Many tests started the engine through the old setting.** They now leave the engine on in the database, the way
   the owner would (`leave_engine_running` in `tests/api_support.py`); the demo does the same.
4. **The command-line tools must not touch a developer's real database in tests.** `quotex_diagnose` tests replace
   the store lookup; the store is tested separately on temporary databases.

## 6. Deviations from the plan
- The old `.env` logins are *kept working* (a stored one wins) rather than ignored outright, so an installation that
  has not moved yet does not break; "ignored" is true once moved.
- `quotex_diagnose` does not store a login made with a terminal PIN; the dashboard's Quotex login is the one the
  engine uses (D-66, D-67).
- New decision: D-67. No new dependency.

## 7. Could not be verified (the whole of Phases 10-15)
Everything below was built and tested against fakes and stand-ins only. **None of it has touched the real Quotex or
the real Telegram.**
- **Telegram:** a real login (code, two-step password, resend, flood wait), that the stored string session works
  after a restart, that logging out ends the session on Telegram's side, and the mapping of Telethon's error classes.
- **Quotex:** a real login with the library, the e-mailed PIN, that the stored session is accepted on the next start,
  and the Cloudflare refusal itself (the message is written for the library's `reason_phrase` crash).
- **Engine:** starting the real engine from the dashboard with real stored logins; real latency (the Phase 9 live
  check `npm run latency` is still outstanding).
- **Browser:** no page of the dashboard was opened in a real browser; component tests and a real server were used.
- **Server:** the VPS deployment steps (systemd, tunnel, first-run setup code from `journalctl`) were never followed on
  a real server.
- **PostgreSQL** and **Excel's** reading of the CSV, as before.

**How to test the whole new way yourself**, on the demo account, in order:
1. `npm run setup`, `npm start`. Create the owner account with the setup code from the window.
2. Settings: store the Quotex email and password; *Log in to Quotex* (type the PIN if asked).
3. Settings > Telegram: API id and hash from my.telegram.org, phone, code (and the password if any).
4. *Start the engine*: the three logins show where they come from; Quotex and Telegram turn green.
5. If your `backend/.env` still has old logins: the Settings page names them; *Move them…*, then delete the lines
   (or `npm run env:import`).
6. Stop the engine, quit, start again: the engine you left running comes back; one you stopped stays stopped.
7. Allow real money (password) only if you mean it; switch back to demo afterwards.

What I ran by hand (real server on a scratch database): a server with
`ENGINE_ENABLED=true`, `QUOTEX_ALLOW_REAL=true` and old logins (fake values) in its environment: the engine stayed
`stopped` with nothing wanted, real money stayed not allowed (`real_trading_allowed: false`), the Settings API
listed the four logins as in `.env` and not stored; moving them answered with their labels and no value, after which
the engine page listed them as `dashboard`, the database held the four names encrypted and **no plain password or
hash anywhere in the file**. (I did not run `npm run env:import` here: it edits the real `backend/.env`; it is
tested on temporary files and databases instead.)

## 8. Measurements
None this phase.

## 9. New dependencies / files of note
No new dependency. New: `backend/app/services/env_import.py`, `scripts/env_import.py`, `scripts/_store.py`,
`tests/integration/test_env_import.py`, `frontend/src/features/settings/EnvLoginsNotice.tsx`.

## 10. Known limitations and what is next

**Limitations of the dashboard-login work (Phases 10-15)**
- One owner only. The `users` table has a role and sessions belong to a user, so invitations can be added; an owner
  column on groups, chains, trades and the stored logins is *not* there yet (D-59).
- The login throttle and a half-made Telegram or Quotex login live in memory: a restart clears them.
- The key (`SECRET_KEY`) sits beside the database on the same machine (the owner's choice): it protects copies and
  backups, not a machine that is itself compromised.
- Settings saved on the dashboard (log detail, Quotex address, expiry mode) are used from the next start of the
  application, not live (D-62).
- A Quotex token that the library refreshes while the engine runs is not saved back (D-66); a Telegram session is
  saved once, at login (D-65).
- `/docs`, `/redoc` and `/openapi.json` (FastAPI's own pages) are still public.
- The dashboard is served over plain HTTP: reach a server only through the SSH tunnel.
- The Cloudflare block that stopped the Quotex login on the Linode server is **explained** now, not solved.

**Backlog ("Later")** — Telegram alerts to the owner; backtester over stored messages; more parsers and a "test this
message" tool; early close of one open trade; strategy lab; PostgreSQL migration; invitations and more than one user
(with the owner column above); an official API if Quotex ever offers one.

**Suggested next steps** — the live checks above, in this order: Telegram login, Quotex login, start the engine on
demo, one real signal on demo, then `npm run latency`; then the VPS deployment.

## 11. Git state
Committed and pushed by the agent after the checks above, with the owner's standing instruction (carry on to the
last phase, test after each, commit to GitHub). See `git log`.
