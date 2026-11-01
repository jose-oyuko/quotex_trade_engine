# Domain Reference

Terms and exact rules. Tests must be named after the examples here.

## 1. Vocabulary

- **Group** — a Telegram group/channel the owner listens to, with its own settings.
- **Signal** — a parsed trade instruction: `asset`, `direction` (`call`/`put`), `duration_s`,
  optional `entry_time`.
- **Chain** — the original signal trade plus its automatic follow-ups after losses.
- **Step** — position in a chain. Step 0 = the original signal trade; step *k* = the *k*-th follow-up.
- **Base stake** — the amount of step 0. **Multiplier list** — `m1…mN`, one value per follow-up step.
- **Max steps (N)** — number of follow-ups allowed. A chain has at most `N + 1` trades.
- **Direction** — `call` (BUY/UP) or `put` (SELL/DOWN).

## 2. Strategies (per group)

Let `k` = consecutive losses in the chain so far (`k ≥ 1` when choosing a follow-up), `origin` = the
direction of the original signal, `stake(k) = base × m_k` (multiplier index `k` is 1-based;
if the list is shorter than `N`, the owner-facing validation must reject it — never silently reuse).

| Strategy | Direction of follow-up `k` | Stake of follow-up `k` | Chain ends |
|---|---|---|---|
| `no_martingale` | no follow-ups | `base` always | after every trade |
| `martingale` | same as `origin` | `base × m_k` | first win, or after the limit below |
| `flip_every_loss` | flip when `k` is odd: `origin` flipped, `origin`, flipped, … | `base × m_k` | first win, or after follow-up `N` loses |
| `two_step_flip` | flip when `(k // 2)` is odd: `origin, origin, flipped, flipped, origin, …` | `base × m_k` | first win, or after follow-up `N` loses |

A win at any step ends the chain and resets everything to base. After the final follow-up loses, the
chain ends as `exhausted` and the system returns to base for the next signal.

> Legacy detail of the old bot (do not copy blindly): its plain `martingale` stopped after `max` losses,
> i.e. one trade fewer than the flip strategies, and could fire an extra base-stake trade at the end.
> In the new system **all martingale-family strategies use the same rule: original + N follow-ups**,
> and no trade is placed after the chain is exhausted.

### Worked examples (base 100, N = 3, multipliers [2.0, 2.5, 3.0], origin = CALL, every trade loses)

`flip_every_loss`
| Trade | Direction | Stake |
|---|---|---|
| step 0 | CALL | 100 |
| step 1 | PUT | 200 |
| step 2 | CALL | 250 |
| step 3 | PUT | 300 |
→ chain `exhausted`.

`two_step_flip`
| Trade | Direction | Stake |
|---|---|---|
| step 0 | CALL | 100 |
| step 1 | CALL | 200 |
| step 2 | PUT | 250 |
| step 3 | PUT | 300 |
→ with N = 4 the next would be CALL at `base × m4`. Chain `exhausted` after step N loses.

`martingale`: CALL 100 → CALL 200 → CALL 250 → CALL 300.

Win at step 2 of `flip_every_loss`: CALL 100 (L) → PUT 200 (L) → CALL 250 (W) → chain `completed`, next signal starts at base.

An 8-step chain (N = 8) simply needs eight multipliers; the setup UI collects one per step.

## 3. Chain rules

- The follow-up uses the **same asset and the same expiry** as the original signal.
- A follow-up is placed **immediately** when the loss is known.
- Chains are keyed by `(group_id, asset)`; unrelated chains never share counters.
- While a `flip_*` chain is active for a group, **new signals from that group are ignored** and recorded
  as `ignored: chain active` (D-9). `martingale` and `no_martingale` open independent chains.
- Chain statuses: `pending`, `open`, `completed` (won), `exhausted` (all steps lost), `stopped`
  (owner action), `failed` (could not place an order), `unknown` (could not determine the result).
- Owner controls: **stop after current trade** (no further steps), **skip to base / end chain**,
  **pause group** (new signals ignored), **kill switch** (no new orders at all).
- If a follow-up order cannot be placed, the chain becomes `failed`, the group is released, and the
  event is surfaced — signals are never ignored forever because of a broken chain.

## 4. Signal formats and parser notes

Formats handled by the old parser (to be ported, then tested on real messages):

1. `ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29` (with/without emojis, "ENTRY CONFIRMED" header)
2. `💰5 minutes expiry USD/BDT;15:00;PUT 🟥 …` (duration, pair, entry time, direction)
3. `USD/INR;03:30;PUT 🟥` (pair; time; direction, expiry may appear elsewhere in the message)
4. `GBP/CHF; 18:16; CALL🟩`
5. `EUR/USD CALL 60s` / `EURUSD PUT 1m`

Mapping: `BUY`/`UP`/`CALL` → `call`; `SELL`/`DOWN`/`PUT` → `put`. Duration in seconds
(`M5` / `5 minutes` → 300).

Known weaknesses to fix while porting:
- A word of 6+ letters after "expiry" (e.g. "Signal") was accepted as a pair → validate against known
  asset codes / the instrument list.
- Plural units ("5 minutes", "5-minute") and word boundaries around `PUT`/`BUY` (matched inside "input").
- Always appending `.OTC` / `_otc` → make it a per-group option (weekend/OTC vs real market).
- Naive local time and `day + 1` rollover for entry times → timezone-aware, month-safe.
- The message may state a time zone ("Time Zone: UTC -3"); treat the signal's entry time as that zone
  when present, otherwise use the group's configured zone.
- Gale lines ("1ST GALE — TIME TO 19:00") are channel-side martingale hints: **ignore them**; our own
  strategy decides follow-ups. Record them in the inbox only.
- Duplicate/edited messages must not create duplicate trades.

Quotex asset naming used by the library: `EURUSD` for real, `EURUSD_otc` for OTC; the library can try
the alternate name (`force_open`) when one is closed.

## 5. Configuration shape (per group; stored in the database)

```
group_id, telegram_chat_id, title, enabled,
parser: "legacy_v1" (more later),
asset_suffix_mode: "otc" | "none" | "auto",
timezone: "UTC-3" | IANA name,
strategy: "no_martingale" | "martingale" | "flip_every_loss" | "two_step_flip",
base_stake: decimal > 0,
max_steps: int >= 0,
multipliers: [decimal > 0] with len == max_steps,
min_payout_pct: 0–100,
```
Global: `account_type` (demo/real), max stake, max concurrent trades, exposure cap, daily stop-loss,
daily profit target, kill-switch state.

## 6. Facts learned about Quotex / pyquotex (from the old bot and research)

- **Unofficial.** No public developer API was found. The library reverse-engineers the web client; it
  breaks when Quotex changes, and Cloudflare may block automated access. Automation may breach
  Quotex's rules and can get accounts restricted → keep real balances small, default to demo.
- **Domain.** The old hard-coded `qxbroker.com` stopped resolving (`getaddrinfo failed` = DNS failure).
  `quotex.com` worked. The library (1.1.0) takes `host`; alternatives mentioned upstream: `qxbroker.io`,
  `quotex.io`. Make the host a setting; document the change procedure.
- **Python ≥ 3.12 required** by pyquotex (it uses `str | Path` and newer syntax).
- **Latency pitfalls in 1.0.3:** `buy()` called a blocking HTTP profile request each time; the bot waited
  `duration + 5` s before reading results; polling used 0.2 s steps. Do not repeat these (D-13, D-14).
- **Payout data:** `get_payout_by_asset(asset, "1"|"5"|"24H")` and `get_payment()` read fixed positions of
  the pushed instrument list → sanity-check the values.
- **Results:** a trade's outcome arrives via websocket data (`listinfodata`, `game_state == 1`); `check_win(id)`
  polls it. Prefer an awaitable with timeout `duration + 60 s`.
- **Login:** may need an email PIN; session data is stored in `session.json` — keep it in `data/`, git-ignored,
  and (when frozen into an exe) next to the executable, not the temp dir.
- **Telegram login:** phone number must be international (`+<country code><number>`, no leading 0).
  Telethon `get_dialogs()` lists groups/channels; messages arrive through `events.NewMessage(chats=…)`.
  A blocking `input()` inside the event loop freezes Telethon — never do console input on the loop.
