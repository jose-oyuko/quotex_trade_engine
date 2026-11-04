# Operations guide

How to run the application day to day: starting it, logging in, watching it, backing it up, and what
to do when Quotex changes something. When something goes wrong, go to
[TROUBLESHOOTING.md](TROUBLESHOOTING.md); for what the application does by itself when a part
fails, see [FAILURE_MODES.md](FAILURE_MODES.md).

All commands are run from the repository root.

## Starting and stopping

| You want to | Do this |
|---|---|
| Start everything | `npm start` (or double-click `start.bat` on Windows) |
| Start without opening a browser | `npm start -- --no-browser` |
| Check a new installation without starting | `npm start -- --prepare-only` |
| Stop | Ctrl+C in the window. Closing the window works too but is less tidy. |
| See it with no accounts | `npm run build`, then `npm run demo` |

`npm start` does the housekeeping for you, skipping what is already done: it checks Node.js is
installed, installs the dashboard's packages, builds the dashboard if it is missing or older than its
source, creates or updates the database, and checks the port is free. It then prints how the app is
configured (never the passwords), starts the server and opens <http://127.0.0.1:8000>.

Stopping is safe at any time. Open trades stay open on Quotex and run to their expiry; the next start
marks them `unknown` in the application (it cannot see Quotex's history), so look at them on Quotex.

## The owner account (first start)

The dashboard is behind a login. The first time the application starts with an empty database it has no
account, so it prints a **setup code** in its log (in the `npm start` window; on a server, in
`journalctl -u quotex-engine`), on the line `owner_setup_required`:

```
[warning ] owner_setup_required  setup_code=4GPA-P5Q4-EACW ...
```

Open the dashboard: it shows "Create the owner account". Type the code, choose a username and a password
(at least 10 characters) and you are in. The code works once, changes every time the application starts
and stops working as soon as the account exists. After that the login page is what you see; the
**Account** link at the top changes the password (which logs every other browser out) and logs out.

- **Forgot the password?** On the computer that runs the application: `npm run owner:reset` (on a
  server: `uv run --directory backend python -m scripts.owner`). It asks for a new password, ends every
  session, and works whether or not the application is running. It also creates the account if there is
  none, without the setup code.
- **Locked out after typing it wrong?** Five failures lock that name for 15 minutes. Wait, or restart
  the application (the lock is in memory).
- The demo (`npm run demo`) has its own account: `demo` / `demo-password`.
- `npm run api:watch -- --username <name>` asks for the password too.

## Settings and stored logins (the Settings page)

The **Settings** page in the dashboard replaces editing `backend/.env` for these:

| Setting | Meaning |
|---|---|
| Log detail | How much is written to the log (`INFO` normally, `DEBUG` to find a problem) |
| Quotex address | The domain Quotex is reached at (change it when Quotex moves) |
| Trade expiry mode | `TIME` (clock-aligned) or `TIMER` (countdown) |

A value saved there wins over `backend/.env`, which wins over the built-in default; each shows where it
comes from. **A saved setting is used from the next start of the application.** "Go back to ..." removes
the saved value.

The page also has **Stored logins** (Quotex email, Quotex password, Telegram API hash): type a value,
**Save**, and it is stored encrypted in the database. It is never shown again; the page only says
*Stored*, *Not set* or *Stored, cannot be read*. **In this version the trading engine does not use them
yet** (it still reads `backend/.env`); they become the source of the logins in the next phases.

**The key.** Stored logins are encrypted with `SECRET_KEY` in `backend/.env`. `npm start` adds one the
first time (and says so); `npm run key:create` does the same by hand (on a server:
`uv run --directory backend python -m scripts.secret_key`). It never replaces a key that is there.
- **Keep a copy of `backend/.env` somewhere safe.** Without the key the stored logins cannot be read; you
  type them again, nothing else is lost.
- **"Stored, cannot be read"** means the key is not the one the value was stored with (for example a
  restored database on another machine). Press **Replace** and type it again.
- **The page says SECRET_KEY is missing or not valid:** run `npm run key:create` (only if the line is
  missing or you have nothing stored that you need), then restart.
- A key is also found in the environment variable `SECRET_KEY` (for a server's service file).

## First-time logins

Telegram and Quotex need no login until you set `ENGINE_ENABLED=true`. Do these once, on the demo account.
(These logins are still typed into a terminal and `backend/.env`; moving them into the dashboard is the
next phases, see PHASES.md.)

**1. Settings file.** Copy `.env.example` to `backend/.env`. It is git-ignored. Fill in:

```
QUOTEX_EMAIL=you@example.com
QUOTEX_PASSWORD=your-password
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
```

**2. Telegram.** Create the id and hash at <https://my.telegram.org> under "API development tools", then
run `npm run telegram:login`. Type your phone number in international format (`+254712345678`: plus,
country code, no leading 0), the code Telegram sends to your Telegram app (not an SMS, usually), and
your two-step password if you have one. The login is saved in `backend/data/telegram.session`.
`npm run telegram:dialogs` lists your chats with their ids, to find a group's number.

**3. Quotex.** Run `npm run quotex:diagnose`. If Quotex emails you a PIN, type it into that window once.
The session is saved in `backend/data/session.json` and the application does not ask again until it
expires. The diagnostic only ever uses the demo account.

**4. Groups and limits.** Start the app (`npm start`), open the **Groups** page and add each Telegram group
with its strategy and stakes. Set the risk limits **before** enabling the engine (max stake, daily
stop-loss and so on). These can be set while `ENGINE_ENABLED=false`.

In the add-group form, **Choose from my Telegram chats** lists the groups and channels your Telegram
account is in, by name; pick one and its chat id (and name, if you have not typed one) are filled in.
The list comes through the running engine, so it only works once step 5 is done and Telegram has
connected. Before that, type the chat id yourself (`npm run telegram:dialogs` prints them). Chats that
already have a group are shown greyed out.

**5. Turn it on.** Set `ENGINE_ENABLED=true` in `backend/.env` and restart. The summary printed at
start-up should say "Logins: all present in .env" and "Account: demo only".

The two session files are as good as your passwords. Keep `backend/data/` private.

## The daily routine

1. Start the app. Look at the header: the account badge must say **DEMO** unless you chose otherwise
   on purpose, and no red banner should be showing.
2. Watch **Live** while signals arrive. A banner means something is wrong; it names the problem and
   what to check.
3. At the end of the day, **Reports** shows the day. Use the CSV buttons if you keep your own records.
4. Run a backup (below), at least weekly, and always before an upgrade.

## Controls

- **Kill switch** (Live page): stops all new orders at once and ends the running chains. Remembered
  across restarts: after a crash it is still on until you release it.
- **Pause a group**, **stop after the current trade**, **end a chain**: on the Groups and Live pages.
- **Risk limits:** global and per group. The day for the daily limits starts at 00:00 UTC unless
  configured otherwise (D-38).
- **Account type:** demo unless `QUOTEX_ALLOW_REAL=true` *and* you switch to real on the dashboard.
  Real money is never one click or one setting away.

## Logs

- Console: readable lines. File: `backend/data/logs/engine.log`, JSON lines, rotated at 10 MB with 5
  old files kept (`LOG_MAX_MB`, `LOG_BACKUPS`, `LOG_TO_FILE=false` to turn the file off).
- Passwords and the Telegram hash are masked as `***` wherever they would appear.
- Look for `"level": "error"` or `"warning"`. Useful events: `quotex_connection_lost`,
  `telegram_connection_failed`, `risk.tripped`, `db_unavailable_retrying`, `db_event_failed`,
  `event_queue_overflow`, `db_outage_batch_dropped`.
- When asking someone for help, send the relevant lines, not the whole file.

## Health

<http://127.0.0.1:8000/api/v1/health> returns `status` (`ok` or `degraded`), a `problems` list in plain
sentences, and the state of the database, the writer and the two connections. The dashboard polls it
every 15 seconds and shows the problems in a banner.

## Backups

```
npm run backup                          copy to backups/quotex-<date>-<time>/
npm run backup -- --no-secrets          leave out the saved logins, the stored secrets and the sessions
npm run backup -- --keep 30             keep the newest 30 (default 14)
npm run backup -- --restore backups/quotex-20261102-093000 --yes
```

- **What it saves:** the database (every trade, chain, signal and setting) using SQLite's own
  online-backup call, so it is consistent even while the app is running, plus the two session files.
  It checks the copy's integrity and refuses to make a backup of a damaged database.
- **What it does not save:** `backend/.env` (keep your own copy somewhere safe: it holds `SECRET_KEY`, the
  key to the secrets stored in the dashboard) and the logs.
- **`--no-secrets`** also empties the stored secrets and login sessions out of the backup's copy of the
  database and compacts it, so none of it stays in the file. The history is complete.
- **A backup with the session files in it is as sensitive as your passwords.** `backups/` is
  git-ignored. Do not put it in a shared or public cloud folder; use `--no-secrets` if you only want the
  history.
- **Restoring:** stop the app first. The current database is kept beside the restored one as
  `quotex.db.before-restore-<time>`, so a mistake can be undone by renaming it back.
- **Better:** copy the `backups/` folder to another disk or machine now and then. A backup on the same
  disk does not survive the disk.

## When Quotex changes its domain

Quotex has changed its web address before (`qxbroker.com` stopped resolving; `quotex.com` worked). The
sign is a connection error that mentions `getaddrinfo failed`, or Quotex never connecting.

1. Stop the app.
2. Find the new address by opening Quotex in your browser (the bare domain, for example `quotex.io`).
3. In `backend/.env` set `QUOTEX_HOST=quotex.io` (no `https://`, no path).
4. Delete `backend/data/session.json` (it belongs to the old domain).
5. Run `npm run quotex:diagnose` (demo only), type the PIN if asked.
6. Start the app again.

## Upgrading

1. Stop the app and run `npm run backup`.
2. Get the new code (`git pull`).
3. `npm run setup` (installs anything new) and `npm start`. The database is updated automatically
   (`alembic upgrade head`); the application refuses to start on a database that is behind the code.

## Measuring speed

After some demo trades, `npm run latency` (or `npm run latency -- --account demo --days 7`) prints the
median, 95th and 99th percentile and the worst time from "message received" to "order sent", for the
first trade of each chain, plus "decision to order" and "order to Quotex's confirmation". It reads the
numbers each trade stored about itself, so it describes your real runs. It does not include the time
the message took to reach you from Telegram's servers.

## Real money

Do not, until the demo account has run for a good while with the live checks in the phase reports
done and the results read. When you do: small stakes and a daily stop-loss first. Quotex has no
official API; this application can break at any time and automated trading may break Quotex's rules.
