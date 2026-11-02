# Phase 3 — Telegram listener and parser — Report

**Date:** 2026-11-02
**Status:** Done with open items — everything that can be tested offline passes, and the real Telegram
library was checked as far as it can go without your account. **The live checks (login, receiving a
message from a real group) are yours to do** (section 12, steps 5-7), because they need your Telegram
API id/hash and your phone.

## 1. Summary
Messages from Telegram groups now travel through a complete, tested path: a `TelegramListener` keeps one
connection alive and delivers the messages of the subscribed groups; a `SignalPipeline` parses each one
with the group's chosen parser, names the asset the way Quotex does, works out *when* to trade, drops
duplicates, stale messages and edits, and either hands a validated `Signal` to the engine (Phase 4) or
records why it did not. Every message of a routed group is written to the signal inbox exactly once,
through the event bus and the DB writer, never on the way to the order. The old bot's parser was ported
as `legacy_v1` and tightened: it no longer guesses a direction, matches whole words only, rejects
look-alike "pairs", and ignores the channel's "gale" lines. Entry times are timezone-aware and safe at
midnight, month end and daylight-saving changes. Nothing is traded by this phase: there is no engine yet.

## 2. What was done
- **Parsers** (`app/signals/parsers/`): `SignalParser` interface, a `ParserRegistry` (a group names its
  parser in its settings) and `legacy_v1` covering the five formats in `docs/DOMAIN.md` §4. Fixes to the
  old parser's known weaknesses: see D-30.
- **Asset names** (`signals/assets.py`): `otc` / `none` / `auto` per group instead of the old guess from
  the letters of the pair.
- **Entry times** (`signals/scheduling.py`, `signals/timezones.py`): the zone is the one in the message
  ("Time Zone: UTC -3") or the group's (`UTC-3`, `UTC+5:30` or an IANA name such as `Africa/Nairobi`);
  nearest-occurrence rule; rules for late, early, far-ahead and non-existent times in D-31.
- **Pipeline** (`signals/pipeline.py`): routes by chat id, then stale check, edit/replay check, parse,
  asset naming, optional "known asset" check (the Quotex instrument list will plug in here), entry-time
  verdict, duplicate check, hand-over. A future entry time is parked on a supervised timer and delivered
  at that moment; if the group is disabled meanwhile, the stored row is replaced with "ignored".
- **Telegram** (`app/telegram/`): `TelegramSource` interface; `TelethonSource` (the only module importing
  Telethon); `FakeTelegramSource`; `TelegramListener` (connect, subscribe and unsubscribe while running,
  reconnect with backoff, `connection.changed` events, clean stop); `login.py` (phone, code, optional
  two-step password, never reads the console itself); `factory.py`.
- **Settings:** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (secret), `TELEGRAM_PHONE`; blank values mean unset.
- **Tools** (all read-only; nothing is sent to Telegram or Quotex):
  `npm run telegram:login`, `npm run telegram:dialogs`, `npm run telegram:listen -- --chat <id>`,
  `npm run signal:try -- "<message>"`.
- **Housekeeping:** the backoff helper moved from `app/quotex/` to `app/core/backoff.py` (both
  integrations use it); `tzdata` added (Windows has no time-zone database of its own).
- **Docs:** decisions D-30…D-33, ARCHITECTURE layout, README "Telegram and signals", `.env.example`.

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Parser tests from real example messages, every supported format, several non-signals, incl. the owner's two examples | ✅ with a caveat (below) | `tests/unit/test_legacy_parser.py`: 16 signal cases (`owner-example-labelled-one-line`, `owner-example-minutes-expiry`, …) and 20 non-signal cases, 55 tests in all. `tests/signal_messages.py` |
| Two groups listened to at once with different parsers (fake Telegram source) | ✅ | `test_two_groups_are_listened_to_at_once_with_different_parsers` |
| Scheduling: month end, midnight, DST, past-time-today documented | ✅ | `tests/unit/test_scheduling.py` (22 tests: 30/31-day months, Feb 28 and 29, year end, midnight both ways, New York spring-forward gap and fall-back repeat, exact tolerance limits); behaviour written up in D-31 and the module docstring |
| Every received message recorded in the signal inbox with status and reason, off the hot path | ✅ | `tests/integration/test_signal_inbox.py` (fake Telegram → listener → pipeline → bus → DB writer → SQLite); `test_the_engine_gets_the_signal_before_the_bookkeeping_is_published` |
| *(live)* Login and message receipt from a test group | ⏸ not verifiable by me | Steps 5-7 in section 12 |

**Caveat on "real example messages":** I only have the two examples written in `docs/PHASES.md` and the
formats in `docs/DOMAIN.md`; the other test messages are my variations of those formats (different
emojis, spacing, markdown, units). No real channel posts were available to me. Please send real
messages (steps 4 and 7 make that easy) so they can be added as test cases.

## 4. Checks run
```
$ npm run check
ruff check: All checks passed!   ruff format: 107 files already formatted
mypy (strict): Success: no issues found in 60 source files
pytest: 457 passed
vitest: 3 passed        tsc + vite build: built in 257 ms
```
Also run: mutation checks (section 5, item 3) and the manual steps of section 12 that need no account.

## 5. Challenges and how they were resolved
1. **A test found a real bug in the daylight-saving handling** — the first version dropped a
   non-existent time (02:30 in the skipped hour) from the candidates and silently used *yesterday's*
   02:30, reporting "23 hours ago" instead of "does not exist". Fixed: the nearest occurrence is chosen
   first, and only then checked for existence (`scheduling.py`).
2. **The real Telegram library, without an account:** connecting with a dummy id worked (2.4 s, creates
   a session file) but Telegram's reply to a wrong API id was a raw library error. A wrong id/hash is
   the most likely first-time mistake, so it is now translated into a plain instruction.
3. **Are the tests any good?** I broke the code on purpose in 15 different ways (removed a word boundary,
   ignored the gap, off-by-one on the late limit, no duplicate check, no stale check, ignored the
   message's own time zone, forgot to reset the backoff, handed over after the bookkeeping, a disabled
   group still trading at its entry time, …) and ran the tests each time. In the first round of 13, 11
   were caught and 2 survived: "once a message was a signal, edits never trade again" was masked by the
   duplicate check, and re-applying subscriptions on every connect turned out to be dead code. I
   strengthened the first test and deleted the second. In a second round the strengthened test and two
   further breakages (hand-over after the bookkeeping, a disabled group still trading) were all caught.
4. **Heredoc quoting** in my shell broke twice; I used file-writing tools instead. No effect on the code.
5. **Incident — I triggered a Quotex login by mistake.** To re-check the blank-credential handling I ran
   `npm run quotex:diagnose` after you had filled in `backend/.env`. It really logged in, Quotex sent a
   PIN email to your address, and the script ended at the PIN prompt (no input available). Demo-only,
   no order, nothing else happened. **You can ignore that email.** I will not run that script again
   without asking.

## 6. Deviations from the plan
- **Not wired into the running app.** The listener and pipeline are complete and tested, but
  `app/main.py` does not start them: nothing consumes signals until Phase 4, and groups cannot be created
  until the Phase 6 API. `telegram:listen` runs the real listener and pipeline today without the app.
  I think starting it from the lifespan belongs to Phase 4, when there is a consumer.
- **Additions beyond the scope list, all small and in service of its goals:** the stale-message guard,
  the duplicate window and the edit rules (the scope says "dedupe (same message edited/forwarded)"); the
  `signal:try` tool (the "how to test it manually" request); the `telegram:*` scripts (the scope says
  "login flow documented" and "list dialogs").
- **New decisions:** D-30, D-31, D-32, D-33.

## 7. Could not be verified
Everything below needs your Telegram account or Quotex; steps are in section 12.
- Logging in for real (phone, code, two-step password), and what Telegram does with *your* account. The
  "where was the code sent" wording and the `sms` resend were added after you reported not seeing the
  code; they are tested with the fake, but not against Telegram itself.
- Receiving messages from a real group, and that chat ids from `telegram:dialogs` match what arrives.
- Reconnection after a real network drop (tested with the fake; Telethon's own retry is not exercised).
- The stale-message threshold against your PC's clock (if the PC clock is more than ~2 min ahead of
  Telegram's, every message would be ignored as stale; the inbox row would say so).
- That your groups' real posts match the formats (see the caveat in section 3).

## 8. Measurements
Measured on this PC by pushing 20,000 messages (a mix of all test signals and non-signals) through
`SignalPipeline.handle`, including the inbox event:

| | |
|---|---|
| median | 42 µs per message |
| 99th percentile | 312 µs |
| worst of 20,000 | 15 ms (one outlier, probably a garbage collection) |

So parsing and deciding adds well under a millisecond to the path between "message received" and
"order sent". The real Telegram delivery delay (network) is not included and not under our control.
The Telethon connect to Telegram took 2.4 s (once, at start-up).

## 9. New dependencies / files of note
- `tzdata 2026.6` — time-zone database for `zoneinfo` on Windows (without it `Africa/Nairobi` fails).
  Telethon (already a dependency) is now actually used.
- `app/signals/pipeline.py` (the pipeline), `app/signals/parsers/legacy_v1.py` (the parser),
  `app/signals/scheduling.py` (entry times), `app/telegram/listener.py` and `telethon_source.py`,
  `scripts/telegram_cli.py`, `scripts/parse_message.py`, `tests/signal_messages.py` (the example
  messages: **add real ones here**).

## 10. Suggestions and open questions
- **Real messages.** Send me (or paste into `tests/signal_messages.py`) real posts from your groups,
  including ones that were *not* signals. This is the single most valuable input for this phase.
- **Lists of signals in one message** (several `PAIR;TIME;DIRECTION` lines): only the first is used and
  the inbox says so. If your groups post lists, a later change could schedule all of them.
- **Missed messages while offline:** Telethon can replay them (`catch_up`). I left it off until it can be
  tried live; the stale guard already prevents late trades. It would make the inbox complete.
- **Scheduled signals are in memory only** (D-31): a restart before the entry time forgets them.
  Phase 5 (safety) may want to persist and recover them.
- **Payout and known-asset checks** plug into `SignalPipeline(is_known_asset=…)` and the Phase 4 executor;
  the Quotex adapter already has `is_open`.
- **Default expiry:** a message with no stated expiry is assumed to be 60 s (the old bot's behaviour). If
  you would rather ignore those, say so and it becomes a one-line change.
- Decision for you: the limits (30 s late, 1 h ahead, 120 s stale, 5 min duplicate window) are fixed
  constants for now. Tell me if any group needs different ones and I will make them group settings.

## 11. Git state
**I made no commits and staged nothing.** Your latest commit already contains Phase 2. Changed and new
files (`git status --short`): modified `.env.example`, `README.md`, `package.json`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `docs/STATUS.md`, `backend/app/core/config.py`, `backend/pyproject.toml`,
`backend/uv.lock`, `backend/app/quotex/pyquotex_adapter.py` and three quotex tests (import path of the
moved backoff helper), `tests/unit/test_architecture_rules.py`; moved `app/quotex/backoff.py` →
`app/core/backoff.py`; new `app/signals/`, `app/telegram/`, `scripts/telegram_cli.py`,
`scripts/parse_message.py` and nine test files. `backend/.env` (git-ignored) got blank `TELEGRAM_*`
lines; your Quotex lines were not touched.

## 12. How to test it yourself
Steps 1-4 need no account. I ran steps 1-4 myself before writing this (results in sections 4 and 8);
steps 5-7 need your Telegram account and I could not run them.

**1. Everything at once**
```
npm run check
```
Expect: lint and types clean, `457 passed` (backend), `3 passed` (frontend), build OK.

**2. The parser and the pipeline, with readable test names**
```
cd backend
uv run pytest tests/unit/test_legacy_parser.py tests/unit/test_scheduling.py tests/unit/test_signal_pipeline.py tests/unit/test_telegram_listener.py -v
```
Expect every line `PASSED`. The names say what each one proves (for example
`test_a_time_inside_the_spring_forward_gap_does_not_exist`).

**3. Try messages yourself (no Telegram needed)**
```
npm run signal:try -- "EURUSD PUT 1m" --suffix otc
```
Expect `Status : parsed`, `Trade  : PUT EURUSD_otc for 60 s`, `Hand-over: now`.
```
npm run signal:try -- "great day team"
```
Expect `Status : not_parsed` with a reason. For messages with emojis save them in a UTF-8 file and use
`--file message.txt`. To see how an entry time is judged at a chosen moment:
```
npm run signal:try -- --file message.txt --suffix auto --tz UTC-3 --now 2026-11-01T07:20:00+00:00
```
(with the "ENTRY: 07:29" example in `message.txt` and `--tz UTC`: `scheduled`; with `--now …T09:00:00+00:00`:
`ignored … already passed`).

**4. Collect real messages**
Copy 10-20 real posts from your groups (signals and non-signals) into text files and run step 3 on each.
Anything shown as `not_parsed` that *is* a signal is a format I need to add: send it to me.

**5. LIVE — create the Telegram API id (once)**
Open https://my.telegram.org → log in with your phone → *API development tools* → create an app (any
name). Put the numbers in `backend/.env`: `TELEGRAM_API_ID=…` and `TELEGRAM_API_HASH=…`.
(Optional: `TELEGRAM_PHONE=+254…`.) Success: `npm run telegram:dialogs` now says `Not logged in` instead of
`Cannot start`.

**6. LIVE — log in, then list your chats**
```
npm run telegram:login
npm run telegram:dialogs
```
Type your phone number as `+<country code><number>` (no leading 0). The script then says where Telegram
sent the code (usually a message from the chat named "Telegram" in your Telegram app). If you cannot
see it, type `sms` instead of the code to ask Telegram to send it another way. Then your two-step
password if you have one (typing is hidden). Success: `[ok] logged in`
and, for the second command, a table of your chats with their ids (channels and supergroups look like
`-1001234567890`). Wrong code or password gives a plain message, not a crash.

**7. LIVE — receive and parse a real group's messages (trades nothing)**
```
npm run telegram:listen -- --chat -1001234567890 --suffix auto --tz UTC-3
```
Use the group's id from step 6 (and its real time zone). Success: it prints `Listening to 1 chat(s)`;
then each new message in that group appears as `[parsed]`, `[not_parsed]` or `[ignored]` with a reason, and a
`=> SIGNAL …` line for every real signal. Add a second `--chat` to listen to two groups. Stop with
Ctrl+C. Send me one `parsed` line and any `not_parsed` message that should have been a signal.

**Clean-up:** to forget the Telegram login, delete `backend/data/telegram.session`.
