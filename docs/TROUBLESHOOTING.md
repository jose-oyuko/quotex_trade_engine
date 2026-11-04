# Troubleshooting

Find the message or symptom you see, read the cause, do the fix. Commands run from the repository
root. For what the application does by itself when parts fail, see
[FAILURE_MODES.md](FAILURE_MODES.md); for routine tasks, [OPERATIONS.md](OPERATIONS.md).

First, two places that answer most questions:

- the banner on the dashboard (or <http://127.0.0.1:8000/api/v1/health>), which names each problem;
- the log file `backend/data/logs/engine.log` (the last lines, newest at the bottom).

## Starting

**"Cannot start: Node.js is not installed"** — install Node.js 22 or newer from <https://nodejs.org>,
close the window, open a new one, run again. (`npm` must be found: `npm --version`.)

**"uv is not installed"** (from `start.bat`) — install uv from <https://docs.astral.sh/uv/>, open a new
window, run again.

**The Settings page says "SECRET_KEY is not set" or "is not a valid key"** — run `npm run key:create` (it
only adds a key when there is none, and never replaces one), then restart. If a key was there and stored
logins show "cannot be read", it is not the key they were stored with: see "Settings and stored logins"
in [OPERATIONS.md](OPERATIONS.md).

**Telegram login on the dashboard: "That code is not right" / "has expired"** — type the code again; if it
says it expired, press *Use another number* (or just start again): Telegram sends a new one. If the code
never arrives, look for a message from the chat named "Telegram" inside the Telegram app, then try *Send it
another way*.

**Telegram login: "Telegram asks you to wait"** — Telegram limits login attempts. Wait as long as it says,
then try once; repeating makes the wait longer.

**Telegram login: "Telegram rejected the API id / API hash"** — copy them again from my.telegram.org (the id is
a number; the hash is 32 letters and digits) with *Change them*.

**Telegram login: "Stop the trading engine first"** — logging in or out is refused while the engine is
using the login. Stop it on the Settings page, do the login, start it again.

**"Port 8000 is already in use"** — the app is probably already running (look for another window, or open
<http://127.0.0.1:8000>). If not, another program has the port: stop it, or set `PORT=8001` in
`backend/.env`. On Windows, `netstat -ano | findstr :8000` shows the process id; Task Manager can end it.

**"Building the dashboard failed" / "`npm install` failed"** — read the messages above the error. Usual
causes: no internet on the first run, or a Node.js older than 22. Delete `frontend/node_modules` and run
again.

**"DLL load failed ... The filename or extension is too long"** (on Windows, when starting) — the project folder
is inside a very deep path and one of the libraries cannot load. Move the whole project to a short
folder such as `C:\quotex_trade_engine`, run `npm run setup` there, and start again. (Seen once, with a
folder path of about 190 characters.)

**"The database is missing or out of date"** — run `npm run db:upgrade` (or just `npm start`, which does
it).

**"Refusing to listen on ... the API can place trades and is meant for loopback"** — `HOST` in `backend/.env` is
not a loopback address. Use `HOST=127.0.0.1`. Read [DEPLOYMENT.md](DEPLOYMENT.md) before changing it.

**"Invalid configuration in backend/.env"** — a value has the wrong form (for example text where a number
is expected). The message names the setting. A line like `TELEGRAM_API_ID=` with nothing after it is fine.

**The address shows an error page instead of the dashboard** — the dashboard has not been built (the log says
`frontend_not_built`). Run `npm run build` (`npm start` does it for you), then reload.

**The page shows an error such as `host_not_allowed`** ("This host name is not served") — open it as
`http://127.0.0.1:8000` or `http://localhost:8000`. Other host names are refused on purpose.

**It starts, but nothing happens when signals arrive** — trading is off by default. The start-up summary
says the engine is stopped. Start it on the dashboard's Settings page. Also check the group is
added on the **Groups** page, enabled and not paused, and the kill switch is not on.

**"ENGINE_ENABLED is true but ... is missing"** — the summary names the missing settings
(`QUOTEX_EMAIL`, `QUOTEX_PASSWORD`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`). Add them to `backend/.env`.

## Telegram

**The phone number is rejected** — use the international format: `+`, country code, the number without the
leading 0. Kenya: `+254712345678`, not `0712345678` or `254712345678`. No spaces or dashes.

**The code never arrives** — it is sent to the Telegram app on another device where you are logged in,
not by SMS. Check the "Telegram" chat in that app. Asking too often gets you blocked for a while; wait
and ask once.

**"Two-step verification password"** — type the password you set in Telegram (Settings, Privacy, Two-step
verification). It is not stored.

**"Telegram is not logged in" / "not logged in: run `npm run telegram:login`"** — the saved login expired or was ended from Telegram's
"Devices" list. Log in again.

**Reset the Telegram login** — stop the engine, then on the dashboard's Settings page press *Log out of
Telegram* and log in again. (Command line: stop the app, delete `backend/data/telegram.session`, run
`npm run telegram:login`.) (Telegram may list the old session under Devices; you can end it there.)

**`api_id` / `api_hash` invalid** — copy them again from <https://my.telegram.org>, "API development
tools". The hash is 32 characters of 0-9 and a-f.

**"Telegram is not connected" banner** — it is reconnecting by itself (1 to 30 seconds between tries). If
it stays, check the internet and that Telegram is reachable (some networks block it).

**"Choose from my Telegram chats" says the engine is not running** — the list is fetched through the running
engine. Start the engine on the Settings page, or type the chat id by hand
(`npm run telegram:dialogs` prints them).

**"Telegram is not connected yet" in that list** — wait a few seconds and press "Try again"; if it never
connects, see "Telegram is not connected" above.

**A group is not read** — run `npm run telegram:dialogs` to confirm the chat id (supergroups are negative
numbers like `-1001234567890`) and that your account is a member. Try the parser on a message:
`npm run signal:try -- "EURUSD PUT 1m"`.

## Quotex

**`getaddrinfo failed`** — the name does not resolve. Either your internet or DNS is down (open a website to
check) or Quotex changed its domain: follow "When Quotex changes its domain" in
[OPERATIONS.md](OPERATIONS.md). Try `nslookup quotex.com` to tell the cases apart.

**An email with a PIN arrives** — Quotex asks for a PIN when it sees a new login. Type it where the
diagnostic (`npm run quotex:diagnose`) asks. If the *application* starts a login you cannot answer, stop
it and run the diagnostic first. Many logins in a row may get the account flagged: do not loop.

**Reset the Quotex login** — stop the app, delete `backend/data/session.json`, run
`npm run quotex:diagnose`.

**"Quotex is not connected" banner** — it is reconnecting by itself. While it is down, orders fail and are
recorded as `failed` (they are not queued); see [FAILURE_MODES.md](FAILURE_MODES.md). If it stays, run
`npm run quotex:diagnose` with the app stopped, to see the reason.

**A trade shows `unknown`** — the application could not learn how it ended (it restarted, or the result
never arrived). Look at it in Quotex's own trade history and treat that as the truth. The chain ended
there for safety.

**Orders are `failed` because the asset is closed or unknown, or the payout is below the minimum** — the
asset is not open now (an OTC suffix may be needed), or its payout is under the group's minimum. The
trade's error text says which. Not a fault.

## The dashboard

**The header says "reconnecting…" or "stopped" instead of "live"** — the dashboard lost its connection to the
backend. It retries by itself; reload the page if it does not come back. If it persists, the backend may
have stopped: look at its window.

**A red banner at the top** — read it: it is the sentence from `/health`. The common ones are in
[FAILURE_MODES.md](FAILURE_MODES.md).

**The numbers on Reports do not match Quotex** — Reports counts only resolved trades, never mixes demo and
real, and shows profit after the payout, not turnover. A trade that is `unknown` is not counted until it
is resolved. Excel shows one column: use the semicolon CSV.

## Data

**"database is locked" in the log** — another program has `backend/data/quotex.db` open (a database viewer,
a sync or backup tool, antivirus scanning). Close it. The application keeps trading and writes the
history when the database is free; the banner clears by itself.

**The disk is full** — free space; same behaviour as above. Old logs are capped (5 files of 10 MB).

**Start again with an empty database** — stop the app, run `npm run backup` first if you may want the old
data, then delete `backend/data/quotex.db*` (the `-wal` and `-shm` files too), then `npm start`. The two
login files stay.

**A backup says "failed its integrity check"** — the database file is damaged (a failing disk or a copy
made while the app was writing). Restore the newest good backup (`npm run backup -- --restore ...`).

## Still stuck

Collect: what you did, the exact message, the last 30 lines of `backend/data/logs/engine.log`, and the
output of `npm start -- --prepare-only`. These contain no passwords (they are masked), but read before
sending. Never send `backend/.env`, `session.json`, `telegram.session` or a backup folder.
