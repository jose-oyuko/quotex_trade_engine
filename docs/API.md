# API guide

The backend has two ways to talk to the dashboard (or to you): a **REST API** under `/api/v1` for
asking questions and giving commands, and a **WebSocket** at `/ws` that pushes everything that
happens, live. Both are described by machine-readable files, so nothing here has to be believed on
trust:

- `docs/openapi.json` — the complete description (routes, request and response shapes, the
  WebSocket messages). It is **generated from the code**; `npm run api:generate` rewrites it and the
  frontend's types (`frontend/src/api/schema.d.ts`), and `npm run check` fails if either is stale.
- While the backend runs in development, **http://127.0.0.1:8000/docs** is an interactive page
  where you can try every endpoint from the browser.

## Conventions

- **Money is text**: `"1.00"`, never `1.0`. The dashboard must not do arithmetic on money with
  floating point. Requests may send a number or a string; responses always send a string.
- **Times** are UTC, ISO 8601 (`2026-11-02T10:00:00Z`).
- **Ids**: chains, trades and signals have UUIDs; groups have small integers.
- **Lists are paged**: `?limit=50&offset=0` (limit 1–200). The answer is
  `{"items": [...], "total": N, "limit": 50, "offset": 0}`, newest first, and filters are query
  parameters (`?status=won&group_id=2`). `total` counts every row matching the filters.
- **Errors** always look the same, whatever went wrong:
  `{"error": {"code": "group_exists", "message": "…", "details": null}}`. `code` is stable (for
  programs), `message` is for you. A rejected request (HTTP 422, `validation_error`) lists the
  problems in `details` as `[{"field": "settings.base_stake", "message": "…"}]`, and never repeats
  the values you sent. Unexpected failures are HTTP 500 `internal_error` with no details; the cause
  is in the server log.
- **Commands are idempotent where that makes sense** (engaging the kill switch twice, pausing a
  paused group) and **answer with the new state**.
- The database trails the engine by a moment. Lists (`/chains`, `/trades`, `/signals`) come from the
  database; `/status` and the WebSocket snapshot are the live picture of what is running right now.

## Endpoints

| Method and path | What it does |
|---|---|
| `GET /health` | Is the backend alive: database, writer queue, engine, Telegram/Quotex/Deriv connection, number of dashboards connected. No secrets. |
| `GET /auth/state` | *No login needed.* Is an owner account still to be created, and is this browser logged in (and as whom). |
| `POST /auth/setup` | *No login needed.* Create the owner account, once: needs the setup code from the application's log. Logs the browser in. 403 `wrong_setup_code`, 409 `setup_closed`, 422 `invalid_account`. |
| `POST /auth/login`, `POST /auth/logout` | *No login needed.* Log in with username and password (sets the session cookie); end this browser's session. Wrong login: 401 `invalid_login` (never says which part was wrong); too many failures: 429 `too_many_attempts`. |
| `POST /auth/password` | Change the password (needs the current one). Every other logged-in browser is logged out. |
| `GET /status` | The whole picture now: account (demo/real), the brokers the engine has (`brokers`), the ones the owner switched off (`brokers_off`) and the ones waiting for the owner, with the reason (`broker_problems`), connections, the balance of each broker (`balances`, never added up), controls, today's result (per broker in `day.by_broker`), open chains and open trades. Same data as the WebSocket's first message. |
| `GET /settings`, `PUT /settings` | The settings that can be changed in the dashboard (log detail, Quotex address, trade expiry mode), each with its value, the default and where the value comes from (`database`, `environment`, `default`). `PUT` takes `{"values": {key: text or null}}` (`null` removes the stored value); all or none are saved; an unknown key or a bad value is 422 `invalid_setting`. A saved value is used from the next start. |
| `GET /secrets` | Which stored logins exist (`quotex_email`, `quotex_password`, `telegram_api_id`, `telegram_api_hash`, `deriv_app_id`, `deriv_token_demo`, `deriv_token_real`, each with its `group`: `logins`, `telegram` or `deriv`), whether each can be read with `SECRET_KEY`, and what the key is like (`ok`, `missing`, `invalid`). **Never a value.** |
| `PUT /secrets/{name}`, `DELETE /secrets/{name}` | Store (encrypted, replacing any earlier value) or remove one. There is no way to read a value back. 503 `secret_key_missing` / `secret_key_invalid` without a usable key, 404 `unknown_secret`, 422 `invalid_secret`. |
| `GET /groups`, `POST /groups` | List the groups; add one (chat id, title, `broker`: `quotex` by default or `deriv`, strategy settings). |
| `GET /groups/{id}`, `PUT /groups/{id}`, `DELETE /groups/{id}` | Read one; replace its title, enabled flag and settings; delete one (only if it has no history — otherwise disable it). |
| `POST /groups/{id}/pause`, `POST /groups/{id}/resume` | New signals of the group are ignored (and say so) while it is paused; its running chains finish. *Needs the engine.* |
| `GET /groups/{id}/risk`, `PUT /groups/{id}/risk` | The group's own limits (max stake, daily stop-loss, daily profit target). |
| `GET /sessions`, `POST /sessions` | List the trading sessions; save one (decision D-71): `broker` (`quotex` or `deriv`), asset, trade length, window and time zone, repeat rule, strategy, targets. 409 `session_overlap` if its window overlaps another enabled session's, 422 `invalid_session`. Each session shows when it will start next, its warnings and its run in progress. |
| `GET /sessions/{id}`, `PUT /sessions/{id}`, `DELETE /sessions/{id}` | Read one; replace it (saving a *once* session arms it again); delete it (only with no runs on record, otherwise disable it). Edits and deletes are refused while it runs: 409 `session_in_use`. |
| `POST /sessions/{id}/start`, `POST /sessions/{id}/stop` | Begin a run now (the first pair at once, for a window of the session's usual length; 409 `session_run_active` if another run is going, 422 if the session is switched off); stop the run: no new pairs, the chains already running finish (409 `no_active_run`). *Needs the engine.* |
| `GET /sessions/runs` | The runs of every session (filter `session_id`), newest first: state, pairs opened, rounds skipped, profit, why it ended. |
| `GET /telegram/chats` | The groups and channels the logged-in Telegram account is in (name, chat id, and whether a group for it already exists), for the "Choose from my Telegram chats" picker. Private chats are left out. Read-only. *Needs the engine* and a connected Telegram: otherwise 503 `engine_not_running`, `telegram_not_connected` or `telegram_unavailable`. |
| `GET /quotex/login` | Where the Quotex login is: `logged_out`, `working` (talking to Quotex), `pin_needed` (with Quotex's own wording of what it wants) or `logged_in`; whether an email and password are stored; the reason the last login did not work; whether the engine is running. Safe after a page reload. |
| `POST /quotex/login/start` | Log in with the stored email and password (demo). Returns when the login needs the PIN, has finished, or is still going (ask again). A refused login is `logged_out` with the reason in `message`, not an HTTP error. 409 `quotex_not_configured`, 409 `engine_running`. |
| `POST /quotex/login/pin`, `POST /quotex/login/cancel` | `{"pin"}`: the digits Quotex e-mailed (422 `quotex_pin_invalid` if not digits; 409 `quotex_login_step` if Quotex is not asking); drop a login in progress. |
| `POST /quotex/logout` | Forget the stored Quotex login (email and password stay). Needs the engine stopped. |
| `POST /deriv/check` | `{"account_type": "demo"\|"real"}`: which Deriv account the stored token opens (number, kind, currency, balance), read from Deriv's account list. **Nothing is traded**; works with the engine running or stopped. 409 `deriv_not_configured` (app id or token not stored), 422 `deriv_login_refused` (Deriv refused the token, or it has no account of that kind), 502 `deriv_unreachable`. |
| `GET /deriv/assets` | Deriv's assets as the running engine knows them: name, Deriv's display name, market (`forex`, `synthetic_index`, …), open or not, and the Rise/Fall trade lengths it allows (`null` while not learnt yet). Without a connected Deriv: `available: false` with the reason, never an error. |
| `GET /brokers` | Each broker: switched on or off (`enabled`, remembered) and its `state`: `off`, `needs_you` (it stopped trying: a login only the owner can fix, such as an e-mailed PIN; `detail` says why), `connected`, `connecting`, `reconnecting`, `disconnected`, `no_login` (the engine runs without it) or `engine_stopped`. |
| `PUT /brokers/{broker}` | `{"enabled": true\|false}`: switch a broker off (its connection closes and its login attempts stop; signals and sessions on it are skipped, saying so) or on (it connects at once). Works with the engine stopped too; remembered. 409 `broker_switch_refused` while it has open trades, running chains or a running session, or when switching on a broker whose login is not stored. *Start now* on a session whose broker is off: 409 `broker_off`. |
| `GET /prices` | Past prices stored for backtests (decision D-84): each asset with the number of prices, the oldest and newest, and the periods downloaded (`ranges`); plus the download running now (`running`, or `null`). |
| `GET /prices/assets` | Every asset Deriv lists with Deriv's own name and a family: `{"asset": "1HZ75V", "name": "Volatility 75 (1s) Index", "group": "Volatility indices"}`. From Deriv's public service (no login), asked again every 6 hours; the last list is kept if Deriv cannot be reached. Without any list: `available: false` with the reason, never an error. |
| `GET /prices/downloads` | The latest downloads, newest first: asset, period, `state` (`running`, `done`, `failed`, `cancelled`), new prices stored, `progress` (0 to 1), a `note` (e.g. "Deriv has no R_75 prices from … (its history starts later)") and the `error` in words. |
| `POST /prices/downloads` | `{"asset", "start", "end"}`: download that asset's prices from Deriv's public price service (no login; nothing is traded), in the background, one at a time; parts already stored are skipped. 202 with the download. 422 `invalid_download` (no asset, start not before end, more than 31 days), 409 `download_running`. Progress arrives as `job.changed` events. A dropped connection is opened again up to 5 times; what was stored is always kept. |
| `POST /prices/downloads/{id}/cancel` | Stop a running download; the prices it stored are kept. 404 `download_not_found`. |
| `DELETE /prices/{asset}` | Delete an asset's stored prices. 404 `download_not_found` if none; 409 `asset_downloading` while it is being downloaded. |
| `POST /backtests` | A session-shaped setup (`asset`, `first_day`/`last_day` (at most 92 days), window `start_time`/`end_time` with `timezone` and `weekdays`, `duration_s`, `mode`, `pause_s`, `max_open_pairs`, and per window `max_pairs`, `profit_target`, `loss_limit`; `base_stake`) plus 1 to 6 `strategies` (each `strategy`, `max_steps`, `multipliers`; growing flip at most 8) and the assumptions `payout_pct` (88), `order_delay_s` (0.5), `step_delay_s` (1.0). Phase 31: `opens` (`["window"]` by default; `"breakout"` opens pairs only from a known breakout until the next consolidation is known or `trend_max_candles` (20; null: no limit) have passed; both: compared side by side), `market` (the consolidation and breakout rules, as for `/market/scan`), and an optional second period `check_first_day`/`check_last_day` that judges settings chosen on the first. At most 12 runs (strategies × ways of opening × periods). Replays every strategy on the stored prices in the background, one backtest at a time (decision D-84); nothing is traded. 202 with the backtest. 422 `invalid_backtest` (no window on those days, no prices stored for them), 409 `backtest_running`. Progress arrives as `job.changed` events. |
| `GET /backtests`, `GET /backtests/{id}` | The latest backtests (state, progress, asset, days, strategies); one backtest with its `setup` and, once done, its `summary`: per run (`strategies`: each with its strategy, `index` into the setup's strategies, `opens`, `period`, and `spans`/`active_s`: the stretches in which pairs could open and their seconds) the pairs, chains, chains won at each step (`won_at_step`), chains that lost every step (`exhausted`), trades, profit, money staked, largest stake, most money in play at once, worst drawdown (and when), most chains lost in a row, how the windows ended, profit per day and the running profit (`equity`, about 400 points). |
| `GET /backtests/{id}/chains` | The chains in time order, each with its trades (start, end, direction, stake, entry and exit price, profit). Filters `strategy` (index into the summary's runs), `status` (`completed`, `exhausted`, `failed` = no price data), `limit`, `offset`. |
| `GET /backtests/{id}/pairs?run=0` | Where a run opened its pairs, oldest first: `at`, `profit` (both legs), `lost` (a leg lost every step); at most 20,000, with the `total`. For the Market page's chart. |
| `POST /backtests/{id}/cancel`, `DELETE /backtests/{id}` | Stop a running backtest; delete one (409 `backtest_running` while it runs; 404 `backtest_not_found`). |
| `GET /market/candles?asset&start&end&length=60` | Candles of the stored prices (decision D-85): `start`, `open`, `high`, `low`, `close`, `ticks`, oldest first; `length` in seconds (1 to 86,400). The period is widened to whole candles; at most 5,000 candles per request (422 `invalid_market`). A period without stored prices has no candles. |
| `GET /market/patterns` | The consolidation patterns (`alternating`, `mixed`, `tight`, `overlap`, `choppy`), each with its default settings. |
| `POST /market/scan` | `{"asset", "start", "end", "length", "rules": {"pattern", "candles", "misses", "width", "net_share", "breakout_candles", "breakout_by"}, "deep"}`: every consolidation (first candle, when it was found, end, range, breakout), every trend (start, end, when its end was known, direction, move) and the statistics (DOMAIN section 9), at most 31 days and 200,000 candles. 422 `invalid_market` without stored prices or with settings that do not fit (e.g. more misses than `candles - 2`). Runs in a worker thread; nothing is traded. |
| `GET /telegram/login` | Where the Telegram login is: `logged_out`, `code_sent`, `password_needed` or `logged_in`, with the hidden phone number, where the code went, how many resends are left, whether the API id and hash are stored, and whether the engine is running. Safe after a page reload. |
| `POST /telegram/login/start` | `{"phone"}`: Telegram sends a code. 409 `telegram_not_configured` (store the API id and hash first), 409 `engine_running`, 422 `telegram_login_refused` (bad number, bad API id/hash), 429 `telegram_wait` (flood wait, says how long). |
| `POST /telegram/login/code`, `POST /telegram/login/password`, `POST /telegram/login/resend`, `POST /telegram/login/cancel` | The next steps. Wrong code: 422 `telegram_code_invalid` (the same step continues); old code: 409 `telegram_code_expired` (starts over); wrong two-step password: 422 `telegram_password_invalid`; a step out of order or a timed-out login: 409 `telegram_login_step`. The session is stored encrypted when the last step succeeds. |
| `POST /telegram/logout` | Remove the Telegram login (and end it on Telegram's side if reachable). Needs the engine stopped. |
| `GET /chains`, `GET /chains/{id}` | Chain history (filters `group_id`, `status`, `account_type`, `broker`); one chain with its trades and the message that started it. |
| `POST /chains/{id}/stop-after-current` | Let the open trade settle, then end the chain without a further step. *Needs the engine.* |
| `POST /chains/{id}/end` | End the chain now so the group is free for new signals (the dashboard's "skip to base"). An open trade still settles and is recorded. *Needs the engine.* |
| `GET /trades`, `GET /trades/{id}` | Trade history (filters `group_id`, `status`, `account_type`, `broker`), with the signal→order latency of each. |
| `GET /signals`, `GET /signals/{id}` | The signal inbox: every message, what became of it and why (filters `group_id`, `status`). |
| `GET /risk` | The global limits, the kill switch, paused groups, today's result and what is open. |
| `PUT /risk/limits` | Set the global limits. **Works without the engine**, so you can set them before ever enabling it. Today's result is kept. |
| `GET /risk/events` | Every order a limit blocked, and other safety events. |
| `POST /kill-switch`, `DELETE /kill-switch` | Engage (optionally `{"stop_chains": true}`) or release the kill switch. *Needs the engine.* |
| `GET /account`, `PUT /account` | Which account is in use; switch between demo and real (refused while anything runs). Switching to REAL needs the real-money permission *and* `"password"` (the owner's, again) in the body: 422 `password_required`, 401 `invalid_login`, 403 `real_trading_not_allowed`. *Switching needs the engine.* |
| `PUT /account/real-trading` | `{"allowed": bool, "password": text}`: give or take back the permission to switch to REAL (decision D-15). Written to the risk log. Taking it back while REAL is in use: 409 `real_trading_in_use`. Works with the engine stopped. |
| `GET /engine` | The engine's state (`stopped`, `starting`, `running`, `stopping`, `failed`), why the last start failed, whether it starts with the application, and which logins it has (`dashboard`, `.env`, `missing`, `unreadable`: never their values). |
| `POST /engine/start`, `POST /engine/stop`, `POST /engine/restart` | Start (always on the demo account), stop, or restart the engine without restarting the application. One at a time: while one runs, another is 409 `engine_busy`; a start that cannot work is 409 `engine_start_failed` with the reason. Stopping marks what was in flight `unknown` at once. |
| `GET /reports/summary` | Profit, win rate, return on stakes, drawdown, streaks, what is not counted, and how the win rate compares with break-even. |
| `GET /reports/breakdown?by=group\|broker\|session\|asset\|strategy\|hour\|weekday` | The same figures split seven ways (hour and weekday always list every hour / day; `session` lists the trading sessions only). |
| `GET /reports/equity` | The result of each day and the running total (the profit curve). |
| `GET /reports/depth` | How far chains go: per step, how many chains got there, what it staked and earned, and how chains that ended there did overall. |
| `GET /reports/export/trades.csv`, `GET /reports/export/breakdown.csv?by=…` | Spreadsheet downloads (see below). |

"*Needs the engine*" means the engine is running (start it on the Settings page, or `POST /engine/start`).
Without it these answer HTTP 503 `engine_not_running`; everything else works, including creating
groups and setting limits.

### Group settings

```json
{
  "telegram_chat_id": -1001234567890,
  "title": "Signals A",
  "enabled": true,
  "settings": {
    "parser": "legacy_v1",
    "asset_suffix_mode": "otc",
    "timezone": "UTC-3",
    "strategy": "martingale",
    "base_stake": "1.00",
    "max_steps": 3,
    "multipliers": ["2.0", "2.5", "3.0"],
    "min_payout_pct": 80,
    "allow_opposite_pair": false
  }
}
```

`multipliers` must have exactly `max_steps` entries (one per step) and each must be above 0;
`base_stake` has at most 2 decimals; `max_steps` is at most 20. Editing a group applies to chains
started from then on; a chain already running keeps the settings it started with.
`allow_opposite_pair` (default `false`) is for the flip strategies only (422 otherwise): it lets a second chain
start for the opposite direction on the same asset while one runs, two chains at most (decision D-70).

### Trading session

```json
{
  "name": "London open",
  "enabled": true,
  "asset": "EURUSD",
  "duration_s": 300,
  "start_time": "11:00",
  "end_time": "12:00",
  "timezone": "UTC",
  "repeat": "weekdays",
  "weekdays": [0, 1, 2, 3, 4],
  "mode": "sequential",
  "max_open_pairs": 1,
  "pause_s": 0,
  "profit_target": "10.00",
  "loss_limit": "20.00",
  "max_pairs": null,
  "strategy": {
    "strategy": "flip_every_loss",
    "base_stake": "1.00",
    "max_steps": 2,
    "multipliers": ["2.0", "3.0"],
    "min_payout_pct": 80
  }
}
```

`repeat: "once"` needs no `weekdays`. `mode` is `sequential` (one pair at a time; the next after both chains ended and `pause_s`) or `every_candle` (a pair at every candle, up to `max_open_pairs` open at once; `pause_s` unused; a candle that finds the limit reached is skipped). The strategy part follows the group rules (one multiplier per step).
The `loss_limit` stops new pairs; chains already running finish, so it does not cap the loss (decision D-72).
Chains and trades opened by a session carry `session_run_id` and `pair_no` (`GET /chains`).

## Reports

Every report takes the same filters as query parameters: `account_type` (`demo` by default; demo
and real are never mixed), `from` (inclusive) and `to` (exclusive) as ISO times **with a zone**
(`2026-11-02T00:00:00Z`), `group_id`, `session_id` (only the trades of one trading session), `broker`
(`quotex` by default, `deriv`, or `all` to add every broker's trades together: they are different
accounts, so the dashboard does it only when asked, and says so), `strategy`, `asset`, and `utc_offset_minutes` (your clock for
hour of day, weekday and days: UTC-3 is `-180`; fixed, daylight saving is not followed). The answer
echoes the filters used. Rates are numbers from 0 to 1; money is text.

Only **finished** trades (won, lost, draw) count; failed, unknown and open ones are listed as "not
counted". Every figure comes with its sample size: `tiny` is under 10 trades, `small` under 30,
`ok` beyond. The definitions are in decision D-47 (`docs/DECISIONS.md`).

**CSV downloads** (`/reports/export/trades.csv`, `/reports/export/breakdown.csv?by=…`) open in Excel:
UTF-8 with a byte-order mark, CRLF line ends, a dot for decimals, text that could be read as a
formula defused. Add `delimiter=semicolon` if Excel shows everything in one column (many European
locales). The trades file has one row per trade in the period (with its `broker`), whatever its status (the period there
is when the trade was created).

## The live feed: `/ws`

Connect a WebSocket to `/ws` (the dashboard uses the page's own host; in development Vite proxies
it). Every message is a JSON text frame with `type`, `seq` and `at`.

1. **`snapshot`** is always the first message: the whole picture (the same as `GET /status`). It
   replaces whatever the client believed.
2. After it come **events**, named by `type`: `signal.received`, `chain.started`, `chain.advanced`,
   `chain.ended`, `trade.opened`, `trade.settled`, `risk.tripped`, `balance.updated`,
   `connection.changed`, `account.changed`, `controls.changed`, `session.run`, `job.changed` (a
   price download or a backtest moved on: `kind`, `job_id`, `state`, `detail`; refetch it). Each
   carries the full record in `data`. Their `seq` goes up by **exactly 1** each time.
3. **`heartbeat`** is sent when nothing else was sent for 15 seconds. Its `seq` is the latest event
   number.

**Gaps and catching up.** If a client sees a `seq` that is not the previous one plus 1, or a
heartbeat whose `seq` is ahead of what it has, it missed something: it sends
`{"type": "resync"}` and the server answers with a new `snapshot`. The server does the same by itself
for a client that cannot keep up: each connection has its own bounded queue (1,000 messages), and
when it overflows that client's queue is thrown away and it is sent a fresh `snapshot`
(`"reason": "slow_consumer"`) instead. **A slow dashboard loses its own events; it never slows the
engine or the other dashboards.**

The frontend's `LiveSocket` (`frontend/src/api/live.ts`) implements all of this, including
reconnecting with a growing delay and treating 40 seconds of silence as a dead connection.

To watch the feed from a terminal: `npm run api:watch -- --username <owner>` (it asks for the password).
The socket needs the login cookie like any other request.

## Safety of the API itself

The API can place trades, so on top of binding to `127.0.0.1` (decisions D-16, D-59, D-60):

- **Everything needs a login except `/health` and `/auth/*`** (and the dashboard's own files). The
  session is a random token in an HttpOnly, SameSite=Strict cookie named `qte_session`; the database
  keeps only its hash. Without a valid session every route answers 401 `not_authenticated` and `/ws` is
  refused (HTTP 403 on the handshake). A session ends after 30 days, or after 7 days without use, or
  when the password is changed elsewhere. A test walks the whole API and fails if a route is added
  without this protection.
- **Passwords** are hashed with scrypt and checked in a worker thread. After 5 failed attempts for a
  name (or from an address) it is locked for 15 minutes (429); a restart clears the lock.

- **Only localhost host names are served** (`localhost`, `127.0.0.1`, `::1`), which defeats
  "DNS rebinding" tricks. This check is off only if you set `ALLOW_PUBLIC_BIND=true`.
- **A request that changes something, or a WebSocket, is refused if the browser says it comes from
  another web page** (HTTP 403 `origin_not_allowed`). Without this, any site you happen to open could
  press your kill switch or edit your limits through your own browser. Programs such as `curl` send
  no `Origin` and are not affected.
- **Request bodies are limited to 64 KiB** (HTTP 413) and **commands are rate limited** (burst of
  40, then 10 per second; HTTP 429). Reading is not limited.

## Regenerating the description

After changing a route or a model in the backend:

```
npm run api:generate     # rewrites docs/openapi.json and frontend/src/api/schema.d.ts
npm run check            # also fails if you forgot
```
