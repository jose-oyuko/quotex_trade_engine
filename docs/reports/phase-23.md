# Phase 23 — Turn a broker on or off without stopping the engine — Report

**Date:** 2026-11-19
**Status:** Done; the live check (Quotex switched off on your PC) is still to be run (section 7)

## 1. Summary

Each broker now has an on/off switch on the Settings page (*Brokers*). Switching Quotex off closes its
connection and stops its login attempts at once, while Deriv, Telegram and the dashboard carry on. It stays off
after a restart. Signals and sessions on an off broker are skipped, and the reason says so. Switching a broker
off is refused, in words, while it has open trades, running chains or a running session.

When Quotex asks for an e-mailed PIN, it no longer retries every 30 seconds forever. It stops and shows
"needs you", with the reason, on the top bar, on Settings and in the health check.

## 2. What was done

**Backend**
- `app/engine/engine.py`:
  - The engine keeps the set of switched-off brokers and never connects one at start.
  - `set_broker_enabled(broker, enabled)` switches a broker while the engine runs. Off cancels its login
    loop and disconnects it (10 s limit). On connects at once.
  - Switching off is refused while the broker has open trades, chains or a running session.
  - Switching on is refused without a stored login.
  - `login_problem(broker)` gives the "needs you" reason. `brokers_in_use()` leaves off brokers out.
- `app/engine/executor.py`: a signal for an off broker is skipped: "Quotex is switched off".
- `app/sessions/scheduler.py`:
  - *Start now* on an off broker is refused (`BrokerOffError`, 409 `broker_off`).
  - A scheduled round is skipped with "Deriv is switched off".
  - The scheduler can say which broker its running session uses.
- `app/engine/controller.py`, `app/engine/flags.py`, `app/main.py`:
  - The switch is stored as `broker.<name>.enabled`, can be set with the engine stopped, and is applied
    every time the engine starts.
- **"Needs you":**
  - `login_problem` on the broker protocol; the Quotex, Deriv and fake adapters all set it.
  - Quotex's PIN request (`refuse_pin`) is now a `LoginRejectedError`, so the Quotex adapter stops
    retrying it, as Deriv already did for a refused token.
- **API:**
  - `GET /brokers` and `PUT /brokers/{broker}` (`app/api/routers/brokers.py`).
  - `/status` gains `brokers_off` and `broker_problems`.
  - `/health` no longer reports an off broker as "not connected", and reports "Quotex needs you: …".
  - `docs/openapi.json` and `frontend/src/api/schema.d.ts` were regenerated.

**Dashboard**
- `features/settings/BrokersPanel.tsx`: the *Brokers* card shows each broker's state in words ("connected",
  "switched off", "needs you", …) with a *Switch … off / on* button, the reason a broker needs you, and any
  refusal in words.
- `app/Layout.tsx`: the top-bar badge says "Quotex: off" or "Quotex: needs you", with the reason as its
  tooltip.

**Guides:** OPERATIONS (Controls), TROUBLESHOOTING ("Quotex keeps trying…", "needs you"), FAILURE_MODES (a new
row), API.md (the two endpoints, the new status fields), DECISIONS (D-81 and how it was settled).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Quotex off while Deriv trades: Deriv keeps trading | ✅ | `test_switching_quotex_off_leaves_deriv_trading` |
| Quotex's login loop stops when switched off and starts again when switched on | ✅ | `test_switching_off_stops_the_login_attempts_and_on_starts_them_again` (the attempt count stays the same after switching off) |
| Switching off a broker with an open trade is refused with the reason | ✅ | `test_a_broker_cannot_be_switched_off_while_it_has_an_open_trade` |
| A Quotex signal while Quotex is off is skipped with the reason | ✅ | `test_switching_quotex_off_leaves_deriv_trading` ("Quotex is switched off") |
| The switch survives a restart | ✅ | `test_the_switch_is_remembered_when_the_engine_starts_again`, `test_a_broker_switched_off_before_the_start_is_never_connected` |
| A PIN request stops the retries and shows "needs you" | ✅ | `test_a_pin_request_stops_the_retries_and_waits_for_the_owner`, `test_a_pin_request_shows_as_needs_you` |
| Component tests for the switches, the refusal, and the "Off" / "needs you" badges | ✅ | `BrokersPanel.test.tsx` (5), `App.test.tsx` ("off" / "needs you") |
| Backend and frontend checks pass | ✅ | Section 4 |
| Live (owner): Quotex off, no more attempts in the log | ⏸ | Section 7 |

## 4. Checks run

```
$ uv run ruff check . ; ruff format --check . ; mypy     clean (153 source files)
$ uv run pytest --deselect tests/integration/test_reports_performance.py
                                      1530 passed, 1 failed (test_engine_brokers: it compared a list
                                      that is now a dict; fixed, the file then passed 11/11)
$ npm run typecheck ; npm run lint ; npm run format:check   clean
$ npx vitest run                      38 files, 472 tests passed
$ npm run build                       built
$ npm run api:check                   schema.d.ts is up to date
```

**Self-test on `npm run demo`** (fake brokers, port 8011, signals every 2 s):
- Both brokers were connected.
- `PUT /brokers/quotex {"enabled": false}` → 200. Quotex showed "off" and its connection "disconnected";
  `/status` showed `brokers_off: ["quotex"]`.
- Over 12 s, the Quotex signals were skipped with "Quotex is switched off". `/health` stayed `ok`, with no
  problems listed.
- Switching it on reconnected Quotex. Deriv stayed connected throughout.

## 5. Challenges and how they were resolved

1. **The Settings page tests broke (12 of them).** The page now also asks for `/brokers`. Those tests did
   not mock it, so an extra error box confused their "alert" checks. Added the broker list to their shared
   mock routes (`makeBrokers()` in `test/fixtures.ts`).
2. **The PIN was an ordinary connection error,** so it was retried every ~30 s (104 attempts on 2026-11-18).
   It is now a login refusal, which the adapter does not retry.

## 6. Deviations from the plan

- **The top-bar badge has no menu.** The switch is on the Settings page (*Brokers*); the badge shows "off" or
  "needs you" with the reason as its tooltip. One place to change it is simpler; a menu can follow if wanted.
- **A scheduled session on an off broker** starts its run and skips every round with "Deriv is switched off",
  rather than not starting at all, so its history says why nothing traded. *Start now* is refused. Recorded
  under "D-81 settled in Phase 23".

## 7. Could not be verified (owner's live check)

1. Run `npm start` and log in.
2. Settings → **Brokers** → **Switch Quotex off**. **Expected:**
   - the top bar shows "Quotex: off";
   - the log (`backend/data/logs/engine.log`) shows `broker_switched_off` and **no more**
     `quotex_reconnect_failed` lines;
   - Deriv keeps trading.
3. Restart the app. **Expected:** Quotex stays off, and the log has `broker_off broker=quotex` and no Quotex
   login attempt.
4. Optional: while a Deriv trade is open, try **Switch Deriv off**. **Expected:** it is refused, saying how many
   trades are open.
5. Optional: if Quotex asks for a PIN when switched on, the top bar shows "Quotex: needs you". Log in on the
   Settings page with the PIN, then switch Quotex off and on.

## 8. Measurements

None (nothing on the order path changed; the off check is one set lookup before a chain starts).

## 9. New dependencies / files of note

- No new dependencies.
- New files:
  - `backend/app/api/routers/brokers.py`, `backend/app/api/schemas/brokers.py`.
  - `frontend/src/features/settings/BrokersPanel.tsx` and its test.
  - `backend/tests/integration/test_engine_broker_switch.py` (7 tests), `test_api_brokers.py` (5 tests).

## 10. Suggestions and open questions

- **Phase 24 (faster results) is next.** It starts with a live measurement on your Deriv demo
  (`deriv:check --order --timeline`), which places a few 1.00 demo trades. I will build the script and then
  ask you to run it, or to let me run it, before designing the early result.

## 11. Git state

Committed with the owner's standing permission ("commit every major milestone, after testing"): see STATUS for
the hash.
