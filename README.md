# Quotex Trade Engine

A local web app that listens to several Telegram signal groups, turns the signals into Quotex
binary-option trades, runs a martingale / flip strategy per group, stores everything in a database
and shows it on a live dashboard with reports.

> **Status:** under construction, built phase by phase. See [docs/STATUS.md](docs/STATUS.md).
> Right now only the empty, wired-up foundation exists (Phase 0): a backend with a health check and a
> frontend page that shows it.

## Security note (read this)

- **Quotex has no official API.** This project uses an unofficial library (`pyquotex`) that imitates
  the Quotex website. It can break at any time, and automated trading may break Quotex's rules and
  get an account restricted. Keep real balances small. The app defaults to the **demo** account.
- **There is no login.** Whoever can reach the server can control trading. The server therefore listens
  on `127.0.0.1` only and **refuses to start on any other address** unless you set
  `ALLOW_PUBLIC_BIND=true`. Do not do that on an open network.
- **Credentials stay on your machine.** Telegram keys, Quotex password and session files live in
  `.env` and `data/`, both git-ignored. They are stored unencrypted for now, so protect the folder
  with normal file permissions. Never paste them into issues, logs or chat.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | recent | Installs Python 3.12 and the backend dependencies |
| Node.js | 22 LTS or newer (tested on 26.13) | Vite 8 needs Node 20.19+ or 22.12+ |
| Git | any | `pyquotex` is installed from GitHub |

You do not need Python installed yourself: `uv` downloads Python 3.12 when needed.

## Setup

From the repository root:

```
npm run setup
```

This runs `uv sync` for the backend (creates `backend/.venv`, installs everything including the pinned
`pyquotex`), `npm install` for the frontend, and `npm run db:upgrade`, which creates the database
(`backend/data/quotex.db`, git-ignored). The first run takes a few minutes because `pyquotex` is
fetched from GitHub.

The backend refuses to start if the database has not been created or is behind the code. After
pulling new code, run `npm run db:upgrade` again; it only applies what is missing.

| Command | What it does |
|---|---|
| `npm run db:upgrade` | Create or update the database to the newest schema |
| `npm run db:downgrade` | Remove every table (back to an empty database). **Deletes all data.** |

Optional: copy `.env.example` to `backend/.env` to change settings (port, log level, ...). The
defaults are safe and need no file.

## Run (development)

Two terminals, both from the repository root:

```
npm run backend      # API on http://127.0.0.1:8000
npm run frontend     # dashboard on http://127.0.0.1:5173
```

Open <http://127.0.0.1:5173>. The page should say **Health OK**. The dev server forwards `/api` and
`/ws` to the backend, so the browser only ever talks to one address.

Always start the backend with `npm run backend` (or `python -m app`), not with a bare `uvicorn`
command: that is what enforces the loopback-only rule.

## Quotex connection (Phase 2)

Put your Quotex login in `backend/.env` (see `.env.example`): `QUOTEX_EMAIL`, `QUOTEX_PASSWORD`, and
`QUOTEX_HOST` if the domain changes. These are secrets; the file is git-ignored.

Check the connection **on the demo account** with the diagnostic:

```
npm run quotex:diagnose                  # connect, show balance and payout
npm run quotex:diagnose -- --order       # also place ONE demo order and wait for its result
```

It can only use the demo account. If Quotex emails you a PIN, type it into that terminal once; the
session is then stored in `backend/data/session.json` (a secret: it can act as you, keep that folder
private) and the application never has to ask again.

**When the domain stops working** (`getaddrinfo failed` = the name no longer resolves): set
`QUOTEX_HOST` in `backend/.env` to the new bare domain (for example `quotex.io`), delete
`backend/data/session.json`, and run the diagnostic again.

Real-money trading is impossible unless `QUOTEX_ALLOW_REAL=true` *and* the account is switched to
real explicitly. Keep it off while testing.

## Telegram and signals (Phase 3)

1. Go to https://my.telegram.org, log in, open **API development tools** and create an app. Put the
   `api_id` and `api_hash` in `backend/.env` (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`). They are
   secrets; the file is git-ignored.
2. Log in once: `npm run telegram:login`. Type your phone number in international format
   (`+254712345678`, no leading 0), then the code Telegram sends to your Telegram app, and your
   two-step password if you have one. The session is stored in `backend/data/telegram.session`
   (a secret: it can read your chats, keep that folder private).
3. List your chats and their ids: `npm run telegram:dialogs`.
4. Watch what the system makes of a group's messages, trading nothing:
   `npm run telegram:listen -- --chat -1001234567890 --suffix auto --tz UTC-3`
   (`--suffix` is `otc`, `none` or `auto`; `--tz` is the zone entry times are written in).

To try the parser on any message without Telegram:
`npm run signal:try -- "EURUSD PUT 1m"` or `npm run signal:try -- --file message.txt`.

## Running the trading engine (Phase 4)

By default `npm run backend` does **not** touch Quotex or Telegram. To let the application act on
signals, set `ENGINE_ENABLED=true` in `backend/.env` (after the Quotex and Telegram logins work, see
above). It trades on the **demo** account. A group's strategy and stakes come from its stored
settings; groups cannot be created from the dashboard until Phase 6, so until then the engine has no
groups to listen to. What it does is tested end to end with fakes (`npm run test:backend`).

**Safety.** The engine enforces limits before every order (max stake, max exposure, max concurrent
trades, max chain length, minimum payout, daily stop-loss and profit target, globally and per group)
and has a kill switch, group pausing, "stop after current trade" and "end chain". They are controlled
from code today (`engine.guard`, `engine.manager`); the dashboard buttons arrive with Phase 6/7. The kill
switch, pauses and limits are remembered across restarts. The day for the daily limits starts at
00:00 UTC unless configured otherwise. See `docs/DECISIONS.md` D-37 and D-38.

If the application stops while trades are open, the next start marks those trades and their chains
`unknown` (it cannot see Quotex's history) and logs a `risk.tripped` event: check them on Quotex.

## Checks

| Command | What it does |
|---|---|
| `npm run lint` | ruff (check + format check), ESLint, Prettier check |
| `npm run typecheck` | mypy (strict) and `tsc --noEmit` |
| `npm run test` | pytest and Vitest |
| `npm run build` | production build of the frontend |
| `npm run check` | all of the above |

## Layout

```
backend/    FastAPI app (app/), tests (tests/), pyproject.toml, uv.lock
frontend/   React + Vite + TypeScript dashboard
docs/       architecture, decisions, phases, status, phase reports
data/       created at runtime (git-ignored): database, sessions, logs
```

Start with [CLAUDE.md](CLAUDE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) to see how the
parts fit together.
