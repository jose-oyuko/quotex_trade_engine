# Phase 25 — The growing flip strategy — Report

**Date:** 2026-11-19
**Status:** Done; not yet run on your demo account (section 7)

## 1. Summary

"Growing flip" is a fifth strategy (decision D-83), next to Martingale, Flip every loss and Two-step flip. Each
step goes the same way as the chain's first trade, or the opposite way, in blocks of 1, 1, 2, 2, 3:
- **from Buy:** Buy, Sell, Buy, Buy, Sell, Sell, Buy, Buy, Buy;
- **from Sell:** the mirror.

In a trading session the pair's two legs go out on the same candle in opposite directions, as before. The
CALL leg follows the first line and the PUT leg the mirror.

A win ends the chain, and a loss sends the next step at once at base × that step's multiplier. After 9 trades
(8 steps) the chain is lost (`exhausted`), like the other strategies. It can be chosen for sessions and for
Telegram groups.

## 2. What was done

- **Backend:**
  - `Strategy.GROWING_FLIP` (`growing_flip`).
  - In `app/engine/strategies.py`: the pattern `GROWING_FLIP_PATTERN`, the step directions, and
    `max_steps_of()` (8 for growing flip).
  - It is a flip strategy (`FLIP_STRATEGIES`), so a Telegram group keeps D-9 and D-70: one chain at a time, or
    the opposite pair if allowed.
  - The group and session API refuse more than 8 steps for it (422: "growing flip has at most 8 steps (9
    trades in all)").
  - No migration: the strategy is stored as plain text with no check on its value.
  - `openapi.json` and the dashboard types were regenerated.
- **Dashboard:**
  - "Growing flip" in the group and session strategy pickers, with a description of the pattern.
  - The forms refuse a 9th step in words.
  - The reports' strategy filter lists it.
- **Guides:** DOMAIN §2 (the table and a worked example), OPERATIONS (trading sessions), DECISIONS (D-83).

## 3. Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Directions for steps 0-8 from Buy and from Sell | ✅ | `test_growing_flip_from_buy_goes_in_blocks_of_1_1_2_2_3`, `test_growing_flip_from_sell_is_the_mirror`, `test_a_put_signal_mirrors_a_call_signal[growing_flip]` |
| Stakes follow the multipliers; the 9th loss ends the chain; more than 8 steps refused | ✅ | `test_growing_flip_stakes_follow_the_multipliers_and_stop_after_nine_trades`, the API refusal tests for groups and sessions |
| Session pair: the CALL leg sends Buy, Sell, Buy, Buy…, the PUT leg the mirror, each step as soon as the loss is known | ✅ | `test_a_growing_flip_pair_mirrors_its_two_legs_step_by_step` (9 losses on each leg; both chains end `exhausted`) |
| Form tests: the choice, the 8-step limit, the description | ✅ | `groupSchema.test.ts`, `sessionSchema.test.ts` (growing flip) |
| All checks pass | ✅ | Section 4 |
| Demo self-test | ✅ (partly) | Section 4 |

## 4. Checks run

```
$ uv run ruff check . ; ruff format --check . ; mypy     clean
$ uv run pytest --deselect tests/integration/test_reports_performance.py
                                      1554 passed
$ npm run typecheck ; lint ; format:check                 clean
$ npx vitest run                      38 files, 475 tests passed
$ npm run build ; npm run api:check   built ; schema.d.ts is up to date
```

**Demo** (`npm run demo`, fake brokers):
- A Growing flip session on Deriv R_75 with 9 steps was refused (422); with 8 steps it was saved.
- *Start now* opened the pair: two `growing_flip` chains, one CALL and one PUT.

The demo's fake brokers make every follow-up win, so they cannot show a losing chain step by step. That is
what the engine test above does, with 9 losses on each leg.

## 5. Challenges and how they were resolved

None of note. The strategy fits the existing step rule; only the 8-step limit is new.

## 6. Deviations from the plan

None.

## 7. Could not be verified (your check, demo account)

1. On the Sessions page, edit your Deriv session (or add one):
   - set **Strategy: Growing flip**;
   - set 8 steps (or fewer) with their multipliers;
   - save, then start it.
2. **Expected:**
   - each pair opens a CALL and a PUT on the same candle;
   - on the Live page, a losing CALL chain goes Buy, Sell, Buy, Buy, Sell, Sell, Buy, Buy, Buy, and a
     losing PUT chain goes the mirror, each step right after the loss;
   - a win ends the chain;
   - after the 9th loss the chain shows "all 9 trade(s) lost".

## 8. Measurements

None (nothing on the order path changed).

## 9. New dependencies / files of note

No new dependencies or files. The tests were added to the existing test files.

## 10. Suggestions and open questions

- With 8 steps the stakes grow quickly. For example, with multipliers of 2 the 9th trade is base × 256 (the
  multipliers are per step, not cumulative, so you choose them). The worst case shown on the session form
  helps judge it before saving.

## 11. Git state

Committed with your permission ("build it and commit when tested"): see STATUS for the hash.
