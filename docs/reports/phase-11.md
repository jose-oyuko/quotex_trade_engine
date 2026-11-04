# Phase 11 — Encrypted store and settings in the database — Report

**Date:** 2026-11-04
**Status:** Done with open items: everything is built and tested on fakes and by hand against a real running
server; `test_reports_performance` (a speed test unrelated to this phase) fails on this slow PC today (section 4).
Nothing that needs the real Quotex or Telegram was touched.

## 1. Summary
The dashboard now has a **Settings** page. Three things that used to be lines in `backend/.env` (log detail,
the Quotex address, the trade expiry mode) are changed there and stored in the database. The page also has
**Stored logins** (Quotex email, Quotex password, Telegram API hash): what you type is stored
**encrypted** with a key kept in `backend/.env`, and is never shown again; the page only says whether each is
stored and readable. `npm start` creates the key for you the first time. A backup made with `--no-secrets`
now also empties the stored secrets and login sessions out of its copy of the database. **The trading
engine does not use the stored logins yet** (it still reads `backend/.env`); switching it over is Phases
12-14.

## 2. What was done

**Plan and decisions** — D-61 (AES-256-GCM, key in `.env`, the name bound to the value) and D-62 (dashboard
settings are read once, at start) in `docs/DECISIONS.md`.

**Backend** (`backend/app/`)
- `vault/crypto.py` — AES-256-GCM; each value has a fresh nonce and its name as authenticated data; a missing or
  malformed key is reported when something is stored or read, not at start-up.
- `vault/key.py` — creates `SECRET_KEY` in `.env` only when there is none; never replaces one; keeps the other
  lines and their (Windows) line endings.
- `vault/store.py` — `SecretStore`: status (set / readable), put, delete, and `get` for the application's own use.
  Three names are accepted: `quotex_email`, `quotex_password`, `telegram_api_hash`.
- `services/app_config.py` — `ConfigService`: the three settings; database > `.env` > default; checked; a damaged
  stored value is ignored with a log line.
- `api/routers/settings.py`, `api/schemas/settings.py` — `GET/PUT /settings`, `GET /secrets`,
  `PUT/DELETE /secrets/{name}`. No endpoint returns a value.
- `db/models.py`, `alembic/versions/0003_secrets.py` — table `secrets` (name, ciphertext, timestamps).
- `core/config.py` — `secret_key` setting (masked in logs); `normalise_quotex_host` shared with the new service.
- `main.py` — reads the stored settings once at start-up and runs everything (and the engine builder) with them.
- `scripts/backup.py` — `--no-secrets` empties `secrets` and `auth_sessions` in the copy and VACUUMs it.
- `scripts/secret_key.py`, `npm run key:create`; `scripts/start.py` adds the key on first start (and says so).
- `.env.example` — `SECRET_KEY` documented; the three moved settings are now commented-out starting values.
- Dependency: `cryptography` 50.0.2.

**Dashboard** (`frontend/src/features/settings/`) — `SettingsPage` (route `/settings`, "Settings" in the
menu), `SettingsForm`, `SecretsPanel` (set / replace / remove with confirmation; explains a missing, malformed
or wrong key).

**Docs** — `API.md`, `OPERATIONS.md` ("Settings and stored logins", backups), `DEPLOYMENT.md`, `TROUBLESHOOTING.md`,
`FAILURE_MODES.md`, `README.md`, `PHASES.md` unchanged (the plan held), `docs/openapi.json` and generated types.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| A stored secret is unreadable without the key | ✅ | `test_a_wrong_key_is_an_error_never_a_wrong_answer`, `test_a_different_key_makes_the_value_unreadable_never_wrong_and_it_can_be_replaced`; the value is not in the database file, its write-ahead log, any answer or the log (`test_the_value_is_not_in_the_database_file_the_log_or_any_answer`) |
| It does not appear in a backup made with `--no-secrets` | ✅ | `test_a_backup_without_secrets_has_no_stored_secret_or_session_in_any_file` (database and write-ahead modes; searches every byte of the backup folder); mutation check: without the VACUUM or the table list it fails |
| Wrong or missing key: a clear message, never a crash or wrong data | ✅ | `test_without_a_key_nothing_can_be_stored_and_the_reason_is_clear` (503 `secret_key_missing`, names the fix), `test_a_malformed_key_is_reported_not_a_crash`, authenticated decryption (`test_damaged_or_foreign_stored_text_is_unreadable_not_a_crash`) |
| No endpoint ever returns a secret | ✅ | `test_the_documented_operations_do_not_include_a_way_to_read_a_value` (no GET of one secret; no `value` in any response model), plus every answer checked for the value in the tests above |
| Settings from the dashboard replace `.env` lines and are used | ✅ | `test_what_was_saved_is_what_the_application_uses_after_a_restart`, `test_the_engine_is_built_with_the_stored_settings` |
| `.env.example` shrinks to the bootstrap values | ⚠️ partly | The three moved settings are now commented-out starting values and `SECRET_KEY` is added. The Quotex and Telegram logins and `ENGINE_ENABLED` stay in the file: the engine still reads them from there until Phases 12-14, so removing them now would break trading. |

## 4. Checks run

```
$ npm run lint        ruff check: All checks passed; ruff format: 220 files formatted; eslint + prettier: clean
$ npm run typecheck   mypy: Success: no issues found in 117 source files; tsc --noEmit: clean
$ npm run api:check   docs/openapi.json and src/api/schema.d.ts are up to date
$ npm run build       dashboard builds
$ backend pytest      full run: 1080 passed, 2 failed in 11 min 26 s (see below)
$ frontend vitest     26 files, 338 tests, all passed
```

The two backend failures:
- `test_reports_performance` (100,000-trade report speed; uses no login, API or secrets): fails on speed, as it
  did in the Phase 10 run. Not shown to pass on this PC today.
- `test_ws_watch::test_it_prints_what_a_real_server_sends`: a timing assumption of mine from Phase 10 (it
  allowed 0.5 s for a connection that now takes about 0.4 s on this slow PC, and it assumed the first line on
  stdout was its own). Fixed: it now allows 2 s and ignores the application's own log lines. Run again afterwards:
  6 passed. The full suite was not re-run after that one fix (it takes over 11 minutes here).

New tests: backend 58 (`test_vault.py` 22, `test_api_secrets.py` 15, `test_api_settings.py` 17,
backup 3, start script 1); frontend 12 (`SettingsPage.test.tsx`).

## 5. Challenges and how they were resolved

1. **A test found a real bug in the key writer.** Reading `.env` as text silently turns Windows line endings
   into plain ones, so adding the key rewrote the owner's whole file with different line endings. Resolution:
   `vault/key.py` reads and writes bytes; `test_other_lines_and_their_line_endings_are_kept` covers it.
2. **Stored settings had to be read before the application is built, but logging starts before the
   database is open.** Resolution: logging starts with `.env`'s level and is set up again if the stored one
   differs.
3. **`npm start` must not write to the owner's real `.env` during tests.** `prepare()` now takes the `.env`
   path as a required argument (tests pass a temporary one).
4. **Two of my first mutation checks "survived"** because the mutations changed nothing. I replaced them with
   real ones (readable regardless of the key; a `value` field added to the response model); both are caught.
   All 9 real mutations were caught (no VACUUM, secrets not scrubbed, name not bound, fixed nonce, key
   overwritten, settings order reversed, readable ignoring the key, value leaking in the schema).

## 6. Deviations from the plan
- The three settings and the secrets list are small on purpose: only what already existed as `.env` choices
  (log detail, Quotex address, expiry mode) and the three secrets the next phases need. `ENGINE_ENABLED` and
  `QUOTEX_ALLOW_REAL` move in Phase 12; the Telegram API id and the sessions in Phases 13-14.
- The Settings page can already store the Quotex and Telegram logins, although nothing reads them yet; the page
  says so. It lets the encryption be tried out before the engine depends on it.
- `npm start` creates the key by itself (the plan said "a command"; both exist).
- New decisions: D-61, D-62. New dependency: `cryptography`.

## 7. Could not be verified
- Nothing needing real Quotex or Telegram was run (none of it is used by this phase).
- The Settings page in a real browser: component tests and a real server were used, I did not open a browser.
- That the stored values will work as the engine's logins: that is Phase 12.

**How to test it yourself**
1. `npm start`. If `backend/.env` had no key, the window says "Created SECRET_KEY in backend/.env ...". Open
   `backend/.env` and see the new `SECRET_KEY=` line (do not share it; make a copy of the file).
2. Log in, open **Settings**. You see Log detail, Quotex address, Trade expiry mode, each with where its value
   comes from.
3. Change *Log detail* to `DEBUG` and **Save**: "Saved. A saved setting is used from the next start". It now
   says *set here*. Press **Go back to INFO** and it returns to its earlier source. Type a bad Quotex address
   such as `not a host!` and Save: it is refused with a reason and nothing changes.
4. Under **Stored logins**, press **Set** on *Quotex password*, type anything, **Save**: it says *Stored* and the
   box is gone; the value is nowhere on the page. **Replace** and **Remove** (asks first) work too.
5. Prove it is encrypted: with the app stopped, run
   `uv run --directory backend python -c "import sqlite3; print(sqlite3.connect('backend/data/quotex.db').execute('select name, ciphertext from secrets').fetchall())"`
   You should see text starting `v1.` and not the password.
6. Prove the key matters: stop the app, in `backend/.env` change a character in `SECRET_KEY` (keep a copy of the
   real line!), start again: the page shows *Stored, cannot be read*, nothing crashes. Put the real line back and
   it reads again.
7. Prove the safe backup: `npm run backup -- --no-secrets`, then run the command from step 5 against the new
   `backups/quotex-.../quotex.db`: it prints `[]`.

What I ran by hand (real server, scratch database, engine off): a server with a fresh `SECRET_KEY` and
database: with no login, `/settings` and `/secrets` answered 401; after setup, `/settings` listed the three settings;
saving `log_level=DEBUG` was stored (`config.log_level` in `app_settings`) and a bad Quotex address was refused (422,
nothing saved); `PUT /secrets/quotex_password` answered `is_set: true, readable: true` and no value; the database held
`v1.Qog1d5...` (71 characters), not the password; neither the password nor the key appeared in the server log (only
`secret_stored name=quotex_password`). After a restart with a **different** key the session still worked, the secret
read `readable: false` (no crash, no wrong data) and the log level was DEBUG (72 debug lines), proving the stored
setting is applied at start. `backup --no-secrets` gave a copy with 0 secrets, 0 sessions, the user kept, and the
ciphertext not in the file.

## 8. Measurements
None this phase.

## 9. New dependencies / files of note
`cryptography` 50.0.2 (AES-GCM; why: the standard library has no authenticated encryption). New:
`backend/app/vault/`, `services/app_config.py`, `api/routers/settings.py`, `scripts/secret_key.py`,
migration `0003`, `frontend/src/features/settings/`.

## 10. Suggestions and open questions
- **Phase 12 next** (engine start/stop and demo/real from the dashboard, the engine built from the stored logins)
  when you say "go on".
- The key sits beside the database on the same machine (your choice). It protects copies of the database and
  backups, not a machine that is itself compromised. If that ever matters, a key typed at start-up is the stronger
  (less convenient) option.
- A backup of the database without `--no-secrets` carries the encrypted values: keep it apart from `backend/.env`.
- `/docs` and `/openapi.json` are still public (see the Phase 10 report).

## 11. Git state
**No commits were made.** New: `backend/app/vault/`, `services/app_config.py`, `api/routers/settings.py`,
`api/schemas/settings.py`, `scripts/secret_key.py`, migration `0003`, `tests/unit/test_vault.py`,
`tests/integration/test_api_secrets.py`, `tests/integration/test_api_settings.py`, `frontend/src/features/settings/`,
this report. Modified: `.env.example`, `README.md`, `package.json`, `backend/pyproject.toml` and `uv.lock`
(`cryptography`), `core/config.py`, `main.py`, `api/deps.py`, `api/errors.py`, `db/models.py`, `scripts/backup.py`,
`scripts/start.py`, several tests, `docs/` (API, DECISIONS, DEPLOYMENT, FAILURE_MODES, OPERATIONS, TROUBLESHOOTING,
openapi.json, STATUS), frontend (`api/`, `app/`, `index.css`). Phase 10's changes are also still uncommitted.
