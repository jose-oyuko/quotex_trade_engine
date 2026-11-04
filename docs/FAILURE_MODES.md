# Failure modes

What the application does when something goes wrong, what you will see, what is lost (if anything)
and what you should do. Every row marked **tested** has an automated test that makes the failure
happen on fakes and checks the result; test names are in the right-hand column. Nothing here has been
exercised against the real Quotex or Telegram (see "What is not verified" at the end).

The rule behind all of it: **a failure may stop trading, but it never leaves a trade half-done, never
places a trade twice, and never hides itself.** When something is wrong, `/health` says `degraded` with
a sentence for each problem, and the dashboard shows the same sentence in a banner above the header.

## At a glance

| Failure | Trading | History | You see | Tested |
|---|---|---|---|---|
| Telegram connection drops | Pauses (nothing to read); open trades carry on | Messages sent while away are **not** seen | Banner "Telegram is not connected" | `test_connection_loss` |
| Quotex connection drops | New orders fail cleanly; open trades carry on | Nothing lost | Banner "Quotex is not connected" | `test_connection_loss`, `test_health_degraded` |
| Database locked / down | Trading continues (never waits for the database) | Held in memory, written when it returns | Banner "database is not accepting writes" | `test_writer_outage` |
| Database down longer than 10 minutes | Continues | That batch is **dropped**, loudly | Banner "events were dropped" | `test_writer_outage` |
| Event queue full | Continues | Newest events dropped, counted | Banner "events were dropped" | `test_writer_outage` |
| A record the database refuses | Continues | Only that record is lost | Banner "records could not be stored" | `test_writer_outage` |
| Dashboard too slow | Unaffected | Unaffected | The dashboard reloads itself | `test_ws_hub`, `test_ws_socket` |
| Application crashes / power cut | Stops | Last moments may be missing | On next start: trades and chains `unknown` | `test_restart` |
| Shutdown (Ctrl+C) | Stops | Everything queued is written first | Log line `shutdown` | `test_restart` |
| Random mix of all of the above | Rules hold | Books balance | — | `test_chaos` (14 seeds) |

## Telegram drops

- **What happens.** The listener notices, publishes "Telegram not connected", and reconnects by
  itself: it waits 1 s, then 2, 4, 8 ... up to 30 s between attempts (plus or minus 10 %), and keeps
  trying until it works. Once back it re-subscribes to every group; nothing needs restarting.
- **What is lost.** A message posted while the connection was down is not delivered to us, and we do
  not go back and fetch it. If a signal was posted during the gap, trade it by hand or skip it. This
  is deliberate: acting on a signal minutes late is usually worse than not acting.
- **Open trades** are not affected: results come from Quotex, not Telegram.
- **If it says "not logged in"** the saved session is no longer valid. It will not retry: run
  `npm run telegram:login` (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)).
- Tested: `test_a_telegram_drop_loses_only_what_was_said_meanwhile_and_heals_by_itself`,
  `test_a_trade_open_when_telegram_drops_is_not_disturbed`.

## Quotex drops

- **What happens.** The adapter checks the connection regularly. When it is gone it publishes "Quotex
  not connected", logs in again and keeps trying with the same 1 s to 30 s backoff, for as long as the
  application runs. A stale session is replaced by a fresh login.
- **An order wanted while it is down** is not queued and not retried: the trade is recorded as `failed`
  with the reason, the chain ends as `failed`, and the group is released so the next signal works as
  soon as the connection is back. (Retrying later would enter at a worse price than the signal.)
- **A trade already open** keeps waiting for its result. If the result never arrives within the
  expiry plus a margin, the trade becomes `unknown`, never a guess: check it on Quotex.
- Tested: `test_an_order_while_quotex_is_down_fails_cleanly_and_the_group_works_again_after`,
  `test_a_quotex_drop_while_a_trade_is_open_does_not_disturb_the_waiting_chain`.

## The database is locked, full or unreachable

The execution path never waits for the database (CLAUDE.md rule 5): events go onto a queue and a
background writer stores them. So a database problem never slows or stops a trade.

- **Short outage.** A failed write is retried with backoff (0.2 s growing to 5 s). Meanwhile new events
  pile up in memory (room for 100,000). When the database returns, everything is written in order.
- **Long outage.** After 10 minutes of failing, that batch is given up and counted as dropped. This is
  the only way history is lost to a database problem, and it is reported (banner, log, `/health`).
- **Queue full** (a very long outage during very heavy trading): the *newest* events are dropped, so
  what is stored stays in order (a trade is never stored without its chain). Counted and reported.
- **A record the database refuses** (a bug or damaged data): the batch is retried one record at a
  time so one bad record cannot take the others with it. Counted and logged.
- **A problem that is not an outage** (for example a constraint violation) is *not* retried for ten
  minutes: only transient errors are waited out.
- **At shutdown** with the database down, the writer gives up after three attempts rather than hold
  the process hostage.
- **What to do.** Free disk space, make sure no other program (a database viewer, a sync tool, an
  antivirus scan of `data/`) holds `quotex.db` open, then watch the banner clear. If events were
  dropped, trades that happened are on Quotex's own history; reconcile from there.
- Tested: `test_writer_outage.py` (seven tests), `test_health_degraded.py`.

## The dashboard cannot keep up

Each browser gets its own bounded queue. A slow one is sent a fresh snapshot ("slow consumer") instead
of the events it missed, and a browser that notices a gap in the message numbers asks for the same.
Nothing here can slow the engine. Closing and reopening the page is always safe.

## Crash, power cut or killed process

Nothing can be flushed, so the last fraction of a second of events may not be in the database. On the
next start the application reads the database and:

- marks every trade that was open, and its chain, `unknown` (it cannot see Quotex's history to find
  out how they ended) and records a `risk.tripped` event. **Check those trades on Quotex.**
- restores the kill switch, group pauses, risk limits and the day's profit and loss, so a crash never
  lifts a stop-loss or re-enables a stopped group.
- does not trade on anything it was in the middle of: it does not resend orders.

Tested: `test_a_hard_crash_leaves_work_in_flight_and_the_restart_flags_it_unknown`,
`test_the_kill_switch_and_the_days_loss_survive_a_crash`.

## Orderly shutdown

Ctrl+C (or a service stop) runs shutdown in reverse order of startup: the engine stops (it publishes
its last events), the dashboard feed stops, the writer drains its queue to the database, background
tasks are cancelled (5 s grace), the database closes. Trades that are open stay open in the database
and are flagged `unknown` on the next start, like after a crash. Tested:
`test_a_graceful_shutdown_is_quick_and_flushes_everything_it_knew`.

## Missing logins

`ENGINE_ENABLED=true` without the Quotex or Telegram credentials makes the application refuse to
start, naming what is missing, with nothing half-started. `npm start` also prints this before it
starts. With `ENGINE_ENABLED=false` (the default) the application never touches either service.

## Missing or wrong SECRET_KEY

The key that decrypts the logins stored in the dashboard is only needed when one is stored or read.
Without it (or with a malformed one) the application still starts and trades as before; the Settings
page says what is wrong and storing a login is refused (503). With a *different* key, each stored value
reads as "cannot be read" instead of giving a wrong answer (the encryption is authenticated), and typing
it again replaces it. Nothing else is touched. Tested in `test_api_secrets.py`.

## What the chaos test checks

`test_chaos.py` plays 14 seeded random storms: good, duplicate, unreadable and unknown-asset signals,
refused orders, lost confirmations, Quotex drops, closed assets, delayed results, kill switch and
pause toggles, group edits in the middle of a chain, and a database that goes away and comes back.
After each storm everything is restored and settled, and these must hold:

1. nothing is left half-done: every chain and trade reached an end, and the live picture agrees;
2. the orders the broker saw and the orders stored are the same, none twice;
3. the risk guard has nothing reserved, and today's result equals the sum of the stored profits;
4. every chain is a clean sequence of steps (0, 1, 2 ... no gaps) with the stakes its settings dictate,
   never past its limit;
5. every chain came from exactly one parsed message, and no message started two chains;
6. the safety switches were obeyed (no order while the kill switch or a pause was on) and nothing
   crashed inside the engine;
7. the database outages cost nothing: no record failed or was dropped.

It found one real bug, now fixed: ending a chain in the very moment it started could publish the "ended"
event before the "started" one. The regression test fails without the fix.

## What is not verified

All of the above runs on fakes: a fake Quotex, a fake Telegram and a real SQLite file. The real services
fail in more ways than a fake can imitate (half-open sockets, rate limits, changed website, account
bans). Run on the demo account for a while and read the log (`backend/data/logs/engine.log`) before
trusting it with real money. Specific unknowns:

- how long the real pyquotex takes to notice a dead connection (the check interval is ours; the
  library's own timeouts are not);
- whether Quotex delivers a result for an order that was open across a reconnect (the fake does);
- Telegram's behaviour after a long outage (Telethon may or may not replay what it missed; the
  application does not ask for it, and this has not been observed).
