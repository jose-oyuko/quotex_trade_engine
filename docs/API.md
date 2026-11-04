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
| `GET /health` | Is the backend alive: database, writer queue, engine, Telegram/Quotex connection, number of dashboards connected. No secrets. |
| `GET /auth/state` | *No login needed.* Is an owner account still to be created, and is this browser logged in (and as whom). |
| `POST /auth/setup` | *No login needed.* Create the owner account, once: needs the setup code from the application's log. Logs the browser in. 403 `wrong_setup_code`, 409 `setup_closed`, 422 `invalid_account`. |
| `POST /auth/login`, `POST /auth/logout` | *No login needed.* Log in with username and password (sets the session cookie); end this browser's session. Wrong login: 401 `invalid_login` (never says which part was wrong); too many failures: 429 `too_many_attempts`. |
| `POST /auth/password` | Change the password (needs the current one). Every other logged-in browser is logged out. |
| `GET /status` | The whole picture now: account (demo/real), connections, balance, controls, today's result, open chains and open trades. Same data as the WebSocket's first message. |
| `GET /settings`, `PUT /settings` | The settings that can be changed in the dashboard (log detail, Quotex address, trade expiry mode), each with its value, the default and where the value comes from (`database`, `environment`, `default`). `PUT` takes `{"values": {key: text or null}}` (`null` removes the stored value); all or none are saved; an unknown key or a bad value is 422 `invalid_setting`. A saved value is used from the next start. |
| `GET /secrets` | Which stored logins exist (`quotex_email`, `quotex_password`, `telegram_api_hash`), whether each can be read with `SECRET_KEY`, and what the key is like (`ok`, `missing`, `invalid`). **Never a value.** |
| `PUT /secrets/{name}`, `DELETE /secrets/{name}` | Store (encrypted, replacing any earlier value) or remove one. There is no way to read a value back. 503 `secret_key_missing` / `secret_key_invalid` without a usable key, 404 `unknown_secret`, 422 `invalid_secret`. |
| `GET /groups`, `POST /groups` | List the groups; add one (chat id, title, strategy settings). |
| `GET /groups/{id}`, `PUT /groups/{id}`, `DELETE /groups/{id}` | Read one; replace its title, enabled flag and settings; delete one (only if it has no history — otherwise disable it). |
| `POST /groups/{id}/pause`, `POST /groups/{id}/resume` | New signals of the group are ignored (and say so) while it is paused; its running chains finish. *Needs the engine.* |
| `GET /groups/{id}/risk`, `PUT /groups/{id}/risk` | The group's own limits (max stake, daily stop-loss, daily profit target). |
| `GET /telegram/chats` | The groups and channels the logged-in Telegram account is in (name, chat id, and whether a group for it already exists), for the "Choose from my Telegram chats" picker. Private chats are left out. Read-only. *Needs the engine* and a connected Telegram: otherwise 503 `engine_not_running`, `telegram_not_connected` or `telegram_unavailable`. |
| `GET /chains`, `GET /chains/{id}` | Chain history (filters `group_id`, `status`, `account_type`); one chain with its trades and the message that started it. |
| `POST /chains/{id}/stop-after-current` | Let the open trade settle, then end the chain without a further step. *Needs the engine.* |
| `POST /chains/{id}/end` | End the chain now so the group is free for new signals (the dashboard's "skip to base"). An open trade still settles and is recorded. *Needs the engine.* |
| `GET /trades`, `GET /trades/{id}` | Trade history (filters `group_id`, `status`, `account_type`), with the signal→order latency of each. |
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
| `GET /reports/breakdown?by=group\|asset\|strategy\|hour\|weekday` | The same figures split five ways (hour and weekday always list every hour / day). |
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
    "min_payout_pct": 80
  }
}
```

`multipliers` must have exactly `max_steps` entries (one per step) and each must be above 0;
`base_stake` has at most 2 decimals; `max_steps` is at most 20. Editing a group applies to chains
started from then on; a chain already running keeps the settings it started with.

## Reports

Every report takes the same filters as query parameters: `account_type` (`demo` by default; demo
and real are never mixed), `from` (inclusive) and `to` (exclusive) as ISO times **with a zone**
(`2026-11-02T00:00:00Z`), `group_id`, `strategy`, `asset`, and `utc_offset_minutes` (your clock for
hour of day, weekday and days: UTC-3 is `-180`; fixed, daylight saving is not followed). The answer
echoes the filters used. Rates are numbers from 0 to 1; money is text.

Only **finished** trades (won, lost, draw) count; failed, unknown and open ones are listed as "not
counted". Every figure comes with its sample size: `tiny` is under 10 trades, `small` under 30,
`ok` beyond. The definitions are in decision D-47 (`docs/DECISIONS.md`).

**CSV downloads** (`/reports/export/trades.csv`, `/reports/export/breakdown.csv?by=…`) open in Excel:
UTF-8 with a byte-order mark, CRLF line ends, a dot for decimals, text that could be read as a
formula defused. Add `delimiter=semicolon` if Excel shows everything in one column (many European
locales). The trades file has one row per trade in the period, whatever its status (the period there
is when the trade was created).

## The live feed: `/ws`

Connect a WebSocket to `/ws` (the dashboard uses the page's own host; in development Vite proxies
it). Every message is a JSON text frame with `type`, `seq` and `at`.

1. **`snapshot`** is always the first message: the whole picture (the same as `GET /status`). It
   replaces whatever the client believed.
2. After it come **events**, named by `type`: `signal.received`, `chain.started`, `chain.advanced`,
   `chain.ended`, `trade.opened`, `trade.settled`, `risk.tripped`, `balance.updated`,
   `connection.changed`, `account.changed`, `controls.changed`. Each carries the full record in
   `data`. Their `seq` goes up by **exactly 1** each time.
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
