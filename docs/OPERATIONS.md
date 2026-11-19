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

Stopping is safe at any time. Open trades stay open at the broker and run to their expiry. At the next
start, Deriv trades get their real result and Deriv chains carry on if none of their steps was missed; Quotex
trades are marked `unknown` (the app cannot see Quotex's history), so look at those on Quotex. If Ctrl+C has
not ended the program within 15 seconds, it is ended anyway (the stall watchdog, decision D-80).

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

- **Start the engine:** needs the **Quotex** logins (the page lists each one and where it comes from: *stored
  here*, *from backend/.env*, *missing*). The **Telegram** login is optional: without it the engine starts with
  signals off (the page says so) and the trading sessions below still run. It always starts on the **demo**
  account. If it cannot start, the page says why in words (and `/health` shows it), and you can fix it and try
  again.
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

## Trading sessions (automatic trading from a schedule)

A trading session trades by the clock, with no Telegram signal: you set it up once, and while its window is
open it opens **pairs** (a CALL and a PUT on one asset, together) by itself. The one that loses recovers by the
strategy you chose; the one that wins ends. With **Growing flip** (decision D-83) each leg's steps change direction in
blocks of 1, 1, 2, 2, 3: the CALL leg goes Buy, Sell, Buy, Buy, Sell, Sell, Buy, Buy, Buy and the PUT leg the
mirror, at most 9 trades (8 steps). You set it up on the **Sessions** page (the API is in `docs/API.md`).

1. **Save a session:** open **Sessions**, press *Add a session* and fill in asset (for example `EURUSD`, or `EURUSD_otc` at the weekend), trade length (M5 = 300 s),
   start and end time with their time zone, how often it repeats (*once*: the next window only, or chosen
   weekdays), the minimum payout, the strategy and its stakes, and optional profit and loss targets.
2. **Leave the engine running.** At the start time the first pair goes out (a minute earlier the asset is made
   ready). Pick a start on a candle boundary (an M5 session at `11:00`, `11:05`...): the form warns when you do
   not, because Quotex may then give the trades a different expiry.
3. **How pairs are spaced.** *Sequential* (the default): one pair at a time. When both chains of a pair have ended, it
   waits the pause you set, then opens the next pair on the next candle. *Every candle*: a pair at every candle, whatever is
   still running, up to the number of open pairs you set (a pair is open while one of its chains runs); a candle that finds
   the limit reached is skipped. Every chain stays independent. More open pairs means more stakes at risk at once.
   A round where the asset is closed, the payout is too low or Quotex is not connected is **skipped** (nothing is
   sent) and tried again on the next candle; the run says why.
4. **It stops by itself** at the end of the window, at the profit target or the loss limit, or after the maximum
   number of pairs. **Stopping never cuts a chain off:** no new pair opens, but a chain that is recovering keeps
   going until it wins or runs out of steps. So the loss limit is **not** a cap on the loss: the worst case is the
   limit plus the rest of every running chain's steps.
5. **Start now / Stop:** *Start now* begins a run at once (the first pair immediately, for a window of the usual
   length). *Stop* has the same soft effect as a target. The **kill switch** also ends the run.
6. **Only one session runs at a time**, so two enabled sessions may not have overlapping windows. A session
   cannot be edited or deleted while it runs.
7. **Restarts and missed windows:** a run that was going when the application stopped (a crash, a power cut,
   Ctrl+C) **carries on by itself** at the next start if its window is still open: the rounds missed meanwhile
   count as skipped, its profit and counters carry on, and its chains follow the "missed" rule (decision D-79:
   a chain whose next step was due while the program was down ends; the others continue). If the window ended
   meanwhile, the kill switch is on, or the session was switched off, it is marked *interrupted*. *Stop* on
   the Settings page ends the run instead (you chose to stop trading). A window that is already open when the
   engine starts is not started by itself (press *Start now*), and a window that passed while the engine was
   off is skipped. The next window starts normally.

Sessions use whichever account the engine is on (demo unless you switched on purpose); the account cannot be
switched while a session runs.

**What the Sessions page shows.** The table lists each session with its window and zone, how often it repeats, how
pairs are spaced, when it stops, its **next start** and its state, with *Edit*, *Start now*, *Disable* and *Delete*.
While a run is going, a panel at the top shows its state, the time left in the window, the **profit so far against
the targets**, the pairs opened and the rounds skipped (with the last reason), and the run's own chains with the usual
chain controls. *Stop* asks first and says the chains are not cut off. Under the table, **Past runs** lists every run
with how it ended and what it made. The form shows **in figures the most that can be at stake** (both first trades
and every step of the leg that keeps losing, times the open pairs) and warns when the start is not on a candle
boundary; an overlap with another session is refused with the name of the other. **Reports** can be narrowed to one
session and split *By session*, and the signal and trade lists name a session's trades *Session: <name>*.

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

The page also has **Stored logins** (Quotex email and password, the Telegram API id and hash, and Deriv's
app id and tokens): type a value,
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

**2b. Deriv (optional; instead of Quotex or next to it).** On **Settings > Deriv**:
1. **The app id.** Register an application on Deriv's developer site, <https://developers.deriv.com>
   ("Register an application"), and store the app id it gives you.
2. **The demo token.** In your Deriv account, create a token (a Personal Access Token) for the **demo**
   account with **only the Read and Trade permissions**: never Payments or Admin. Store it as *Deriv
   demo token*. (If Deriv's dashboard only shows the real account, switch to the demo account first: the
   token belongs to the account that is selected when it is made.)
3. **Check the demo token.** The button asks Deriv which account the token opens and shows its number
   (`VRTC…` or `DOT…` for a demo account), currency and balance. Nothing is traded and the engine does not
   need to be stopped.
4. **The real token** (only if you will trade real money on Deriv): a token of the real account, Read and
   Trade only. It is used only when real money is allowed (with your password) and REAL is chosen; the
   switch then moves Quotex and Deriv together, or refuses and moves neither.
Restart the engine after storing or changing a Deriv login. `DERIV_APP_ID`, `DERIV_TOKEN_DEMO` and
`DERIV_TOKEN_REAL` in `backend/.env` still work (a stored value wins), and **Move them** on the Settings
page (or `npm run env:import`) moves them into the store like the other logins.

**Picking the broker.** Each group and each trading session has a **Broker** (Quotex or Deriv) on its
form. On Deriv, forex Rise/Fall starts at 15 minutes and there are no OTC pairs: give a Deriv group
"Never OTC", and for 1- or 5-minute trades use a synthetic index (Volatility 75 is `R_75`). The session
form shows Deriv's own list of assets, grouped as forex pairs and synthetic indices, and greys out the
trade lengths the chosen asset does not offer; the list is there while the engine is connected to
Deriv (before that, type the name). A signal its broker cannot take is skipped, and the Signals page
says why. Each broker's balance and today's result are shown separately on the Live page, and its
daily limits count its own trades only.

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
- **Switch a broker off or on** (Settings page, *Brokers*; decision D-81): an off broker is not connected and
  stops trying to log in (use it when you trade on Deriv only, so Quotex stops retrying), and the other broker,
  Telegram and the dashboard carry on. Signals and sessions on an off broker are skipped, saying so. It is
  remembered across restarts, and refused while that broker has open trades, running chains or a running
  session. The top bar then shows "Quotex: off".
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

## A steadier connection on a home PC

Every lost connection costs the trades whose next step falls inside it (decision D-79). On 2026-11-18 the
PC's Wi-Fi lost the router in bursts while the laptop ran on battery, and the router's DNS took up to 30 s
to answer. In order of effect:

1. **Use a network cable** to the router instead of Wi-Fi. This alone removes the Wi-Fi drops.
2. **If you stay on Wi-Fi, turn off its power saving on battery:** Control Panel → Power Options → *Change plan
   settings* → *Change advanced power settings* → *Wireless Adapter Settings* → *Power Saving Mode* → **On
   battery: Maximum Performance**.
3. **Use a public DNS** instead of the router's: Settings → Network → your connection → *DNS server
   assignment* → Manual → IPv4 `1.1.1.1` and `8.8.8.8`.
4. **Keep the laptop plugged in**, and put the router on a small UPS if the power cuts out.
5. Later, a **VPS** (a server in a data centre) removes all of the above.

Windows records the Wi-Fi drops: Event Viewer → *Windows Logs* → *System*, source `Netwtw06` (Intel Wi-Fi),
event 6000 "BSS missed beacons".

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

Two more lines (Phase 24) answer "why does each martingale step start later?": **expiry -> result** (how
long after a trade ended its result was known) and **expiry -> next** (how long after a trade ended the
chain's next step was sent; this adds up along a chain).

**Deriv early result** (Settings; decision D-82): ON uses a Deriv result as soon as its closing price is
certain instead of when Deriv marks the contract sold. Before switching it on, run
`npm run deriv:check -- --asset 1HZ75V --order --timeline` (three 1.00 trades on the **demo** account): it
prints, for each trade, when every update and price tick arrived after the end time, when the result was
known, when Deriv marked it sold, and whether the two agree. Switch it on only if they agreed; restart the
engine after changing it. Keep the PC's clock synchronised (Settings > Time > Sync now): the timeline is
read against Deriv's end time.

## Backtests (the Backtest page)

How would a strategy have done on Deriv's real past prices? The **Backtest** page (decision D-84) answers
it without trading anything.

1. **Download prices** (*Price history*): choose an asset and the days, then *Download*. Assets are
   listed by the names Deriv gives them, with Deriv's code in brackets: *Volatility 75 (1s) Index
   (1HZ75V)* is the one-tick-a-second index, *Volatility 75 Index (R_75)* the one ticking every 2 s. The prices come from Deriv's public price service: no login, no token, nothing is traded.
   - A day of a 1-second index takes about a minute (Deriv answers 1,000 prices per request).
   - Days already stored are skipped, so downloading again is quick.
   - *Cancel* keeps what was stored. A dropped connection is retried up to 5 times.
   - Deriv keeps about a year of history.
   - The same from the terminal: `npm run history:download -- --asset 1HZ75V --days 7`.
   - The prices live in `backend/data/history.db` (about 2.5 MB per day of a 1-second index), apart from
     the trading database. *Delete* forgets an asset's prices.
2. **Describe the backtest** (*New backtest*): the same fields as a session (window, days of the week,
   trade length, one pair at a time or a pair at every candle, base stake, limits per window), or *Copy
   the setup of a session*. Then up to six strategies to compare, each with its multipliers (one per
   step: `2, 4, 8` is three steps).
3. **Check the assumptions:** the payout % of a win (Deriv keeps no past payouts; 88% is what `1HZ75V`
   paid on the demo), the order delay (0.5 s) and the step delay (1 s, with the early result ON).
4. ***Run the backtest.*** It runs in the background; the list shows its progress. A month of a
   1-second index with five strategies takes about a minute.

**Reading the result.** The comparison table puts the strategies side by side:
- **profit**, and the **worst drawdown** (the deepest fall from a high point of the running profit: the
  money you must be able to lose on the way);
- the **largest stake** a step reached, and the **most money in play at once**;
- the **chains won** (and at which step, in the chart below the table), the **chains lost** (every step
  lost) and the **most chains lost in a row**.

The chain list shows every chain, with each trade's entry and exit price.

**What a backtest cannot tell you.** Network drops, missed steps, order refusals and payout changes are
not simulated. A strategy changes how wins and losses bunch together, not the odds: on a random index
with a payout under 100% the expected result is slightly negative. A backtest shows the risk you take,
not a profit to expect.

## Real money

Do not, until the demo account has run for a good while with the live checks in the phase reports
done and the results read. When you do: small stakes and a daily stop-loss first. Quotex has no
official API; this application can break at any time and automated trading may break Quotex's rules.
