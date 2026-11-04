# Operations guide

How to run the application day to day: starting it, logging in, watching it, backing it up, and what
to do when Quotex changes something. When something goes wrong, go to
[TROUBLESHOOTING.md](TROUBLESHOOTING.md); for what the application does by itself when a part
fails, see [FAILURE_MODES.md](FAILURE_MODES.md).

All commands are run from the repository root.

## Starting and stopping

(Running in Docker instead? Everything on this page applies except the `npm` commands; see
[DOCKER.md](DOCKER.md) for the equivalents.)

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

## The trading engine (the Settings page)

The **Settings** page starts, stops and restarts the engine (Quotex and Telegram together) while the
application keeps running: no `.env` edit, no restart.

- **Start the engine:** needs the logins (the page lists each one and where it comes from: *stored here*,
  *from backend/.env*, *missing*). It always starts on the **demo** account. If it cannot start, the page
  says why in words (and `/health` shows it), and you can fix it and try again.
- **Stop the engine:** asks first. No new signal is traded. Trades that are open stay open on Quotex and run
  to their expiry; here they are marked *unknown* at once (the application can no longer follow them), so look
  at them on Quotex.
- **Restart:** stop and start again, for example after storing a different login.
- **It remembers:** an engine you left running starts again by itself when the application starts (also after
  a crash, with the service restarting it); one you stopped stays stopped. A new installation never starts it
  by itself. (The old `ENGINE_ENABLED` line in `.env` is not read any more.)
- **A login that is stored but cannot be read** (wrong `SECRET_KEY`) stops the start with a message; the engine
  never quietly uses an older `.env` password instead.
- **Real money:** *Allow real-money trading* (needs your password) only makes the switch possible; the account
  stays DEMO until you press *Switch to the REAL account* (password again, refused while a chain or trade is
  running). Both are written to the risk log. You cannot stop allowing it while REAL is in use. After a
  restart the engine is on demo again.

## Moving old logins out of `.env`

Versions before the dashboard kept the Quotex and Telegram logins in `backend/.env`, in plain text. They still
work, and a login stored on the dashboard always wins over them. To move them:

- **On the dashboard:** the Settings page shows a notice naming them; press *Move them into the encrypted
  store*. It never overwrites a login that is already stored and never shows a value. Then delete those
  lines from `backend/.env` yourself (the notice says so).
- **Or from a terminal:** `npm run env:import` (on a server: `uv run --directory backend python -m
  scripts.env_import`). It lists what will move, asks, stores them encrypted, replaces each line in `.env` by
  a comment (so the value is gone from the file) and retires the lines it no longer reads. If `.env` said
  `ENGINE_ENABLED=true` and you never decided on the dashboard, the engine is left running so it starts with
  the application as before. `QUOTEX_ALLOW_REAL=true` is **never** carried over: allow real money on the
  Settings page, with your password. `--yes` does not ask.

Both need `SECRET_KEY` (made by `npm start`) and a migrated database, and both say so if not.

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
*Stored*, *Not set* or *Stored, cannot be read*. **The engine uses them** when it starts (a stored value
wins over `backend/.env`); after changing one, restart the engine.

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

Telegram and Quotex need no login until you start the engine (Settings page). Do these once, on the demo
account. The Telegram login is made on the dashboard (below); the Quotex login is stored on the dashboard
too, and the command-line logins (`npm run telegram:login`, `npm run quotex:diagnose`) remain as a fallback.

**1. Quotex.** On **Settings > Quotex email and password** store what you use to log in to Quotex (encrypted;
see "Settings and stored logins"), then press **Log in to Quotex** in the box below. If Quotex e-mails you a
PIN (it does the first time, and when it sees a new place), the box asks for it: type the digits and press
*Send the PIN*. The login is then stored encrypted and the engine uses it. A refused login says why in words
(a wrong password, or Quotex's website refusing this computer's address: see TROUBLESHOOTING). The login
uses the **demo** account. Logging in or out needs the engine stopped. `QUOTEX_EMAIL` and `QUOTEX_PASSWORD`
in `backend/.env` still work (a stored value wins).

**2. Telegram** (Settings > **Telegram**), in this order:
1. **The API id and hash.** Create them at <https://my.telegram.org> (log in with your phone number, open
   "API development tools", create an application with any name). Type them in the box and press Save.
2. **The phone number** of the Telegram account that is in the signal groups, written with the country
   code and no leading 0 (`+254712345678`), and press *Send me the code*.
3. **The code.** Telegram says where it sent it (usually the Telegram app, as a message from "Telegram", not
   an SMS). Type it. *Send it another way* asks for an SMS or a call (twice at most); a wrong code can simply
   be typed again; an old one starts the login again.
4. **The two-step password**, only if the account has two-step verification.
Then it says *Logged in*. A half-made login survives a page reload (it is forgotten after ten minutes and
when the application restarts). The login is stored encrypted in the database, not in a file. **Log out of
Telegram** removes it (and ends it on Telegram's side). Logging in or out needs the engine **stopped**.
Telegram lists this program among your devices (Settings > Devices), where you can also end it.
If Telegram says to wait, the box says for how long: wait, do not retry.

(An older `backend/data/telegram.session` file made by `npm run telegram:login` still works when nothing is
stored on the dashboard; *Log out of Telegram* removes it too.)

**3. Checking the Quotex connection (optional).** `npm run quotex:diagnose` is still there: it logs in and
shows the balance from a terminal (demo only; it keeps its own `backend/data/session.json`). The dashboard
login needs none of it, and writes nothing to disk: the library's session file lives only in a private
temporary folder while a login or a connection is being made.

**4. Groups and limits.** Start the app (`npm start`), open the **Groups** page and add each Telegram group
with its strategy and stakes. Set the risk limits **before** enabling the engine (max stake, daily
stop-loss and so on). These can be set while the engine is stopped.

In the add-group form, **Choose from my Telegram chats** lists the groups and channels your Telegram
account is in, by name; pick one and its chat id (and name, if you have not typed one) are filled in.
The list comes through the running engine, so it only works once step 5 is done and Telegram has
connected. Before that, type the chat id yourself (`npm run telegram:dialogs` prints them). Chats that
already have a group are shown greyed out.

**5. Turn it on.** Open **Settings** and press **Start the engine** (see "The trading engine" above). The box
lists each login and where it comes from; the button stays grey while one is missing.

The saved Quotex session file (and a Telegram `.session` file if you used the command line) are as good as
your passwords. Keep `backend/data/` private.

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
- **Account type:** demo unless you allowed real money on the Settings page *and* switched to real there; both ask for your password again and are written to the risk log.
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
4. On Settings, press *Remove the stored login* (and delete `backend/data/session.json` if you used the
   command line): they belong to the old domain. (Or save the new address as *Quotex address* on the Settings
   page instead of editing `.env`.)
5. Press *Log in to Quotex* (demo only), type the PIN if asked.
6. Start the engine again.

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
