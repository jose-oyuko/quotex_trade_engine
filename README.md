# Quotex Trade Engine

A local web app that listens to several Telegram signal groups, turns the signals into Quotex
binary-option trades, runs a martingale / flip strategy per group, stores everything in a database
and shows it on a live dashboard with reports.

> **Status:** all nine phases are built and tested on fakes (a simulated Quotex and Telegram). **Nothing
> has been run against the real Quotex or Telegram by the builder.** Run it on the **demo** account
> first and do the live checks listed in the phase reports ([docs/STATUS.md](docs/STATUS.md)).

## Security note (read this)

- **Quotex has no official API.** This project uses an unofficial library (`pyquotex`) that imitates
  the Quotex website. It can break at any time, and automated trading may break Quotex's rules and
  get an account restricted. Keep real balances small. The app defaults to the **demo** account.
- **The dashboard has an owner login**, created on the first start with a one-time setup code printed in
  the application's log (see [docs/OPERATIONS.md](docs/OPERATIONS.md)). It still listens on `127.0.0.1`
  only and **refuses to start on any other address** unless you set `ALLOW_PUBLIC_BIND=true`: a login
  over plain HTTP on an open network is not safe. For a server, use an SSH tunnel
  ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
- **Credentials stay on your machine.** Telegram keys, Quotex password and session files live in
  `backend/.env` and `backend/data/`, both git-ignored. Logins typed into the dashboard's Settings page
  are stored **encrypted** in the database with the key `SECRET_KEY` in `backend/.env` (made for you by
  `npm start`): keep a copy of that file somewhere safe. The saved session files and `.env` logins are
  still plain text, so protect the folder with normal file permissions. Never paste them into issues, logs or chat. Log files mask
  them, and backups that include the session files are as sensitive as the passwords.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | recent | Installs Python 3.12 and the backend dependencies |
| Node.js | 22 LTS or newer (tested on 26.13) | Vite 8 needs Node 20.19+ or 22.12+ |
| Git | any | `pyquotex` is installed from GitHub |

You do not need Python installed yourself: `uv` downloads Python 3.12 when needed.

## Quick start (a new machine)

1. Install the three tools above.
2. Get the code (`git clone <repository URL>`) and open a terminal in its folder.
3. Install everything (a few minutes the first time, `pyquotex` is fetched from GitHub):

   ```
   npm run setup
   ```

4. Start:

   ```
   npm start            # on Windows you can also double-click start.bat
   ```

That is all: `npm start` builds the dashboard if needed, creates the database, checks the port, prints
how the app is configured (never your passwords) and opens <http://127.0.0.1:8000>. Stop it with
Ctrl+C.

With no settings file it runs safely: demo only, **trading off**. You can look around, create groups and
set limits. To trade, follow the first-time logins in [docs/OPERATIONS.md](docs/OPERATIONS.md).

**To see everything working with no accounts at all:** `npm run build`, then `npm run demo`, and open
<http://127.0.0.1:8000>, logging in as `demo` with the password `demo-password`. The demo runs on a simulated Quotex and simulated Telegram groups, posts a
made-up signal every few seconds, and uses its own database (`backend/data/demo`). It cannot touch your
real accounts or data.

`npm start -- --prepare-only` does the preparation and stops, which is a quick way to check a new
installation; `npm start -- --no-browser` does not open a browser window.

## The guides

| Guide | Read it when |
|---|---|
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Setting up logins, running day to day, backups, a Quotex domain change, upgrades |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | You see an error: phone number format, `getaddrinfo failed`, session reset, port in use ... |
| [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md) | You want to know what happens when Telegram, Quotex or the database fails |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Moving it to a VPS |
| [docs/API.md](docs/API.md) | Using the API or the live feed directly |
| [docs/STATUS.md](docs/STATUS.md) | Where the project is and what is still unverified |

## Configuration

Optional: copy `.env.example` to `backend/.env` and edit. Every setting is listed there with its
meaning. The defaults are safe and need no file. The main ones:

| Setting | Default | Meaning |
|---|---|---|
| `ENGINE_ENABLED` | `false` | Only the starting value: start and stop the engine on the dashboard's Settings page, which remembers it |
| `QUOTEX_EMAIL`, `QUOTEX_PASSWORD` | unset | Quotex login (secrets) |
| `QUOTEX_HOST` | `quotex.com` | The broker's domain; changes now and then |
| `QUOTEX_ALLOW_REAL` | `false` | Only the starting value: allow real money on the Settings page (asks for your password) |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | unset | From <https://my.telegram.org> (secrets) |
| `PORT` | `8000` | Port on `127.0.0.1` |
| `LOG_LEVEL`, `LOG_TO_FILE`, `LOG_MAX_MB`, `LOG_BACKUPS` | `INFO`, `true`, `10`, `5` | Logs, also in `backend/data/logs/engine.log` |

## What it does

- **Telegram and signals.** Reads the groups you add, understands the signal formats of the old bot
  (`npm run signal:try -- "EURUSD PUT 1m"` tests a message). Test a group without trading:
  `npm run telegram:listen -- --chat -1001234567890 --suffix auto --tz UTC-3`.
- **Quotex.** One adapter, demo by default. `npm run quotex:diagnose` connects and shows the balance
  and payout; with `-- --order` it places one demo order.
- **Strategies.** Per group: no martingale, martingale, flip every loss, two-step flip, as chains of steps. Orders
  go out on a short path with no database wait (the result is stored in the background).
- **Safety.** Limits before every order (max stake, exposure, concurrent trades, chain length, minimum
  payout, daily stop-loss and profit target, globally and per group), a kill switch, group pausing, "stop
  after current trade" and "end chain". Kill switch, pauses and limits survive restarts. If the app
  stops with trades open, the next start marks them `unknown`: check them on Quotex.
- **Dashboard.** Live, Signals, Groups, History and Reports pages, fed over a WebSocket. A banner
  appears when something is wrong.
- **Reports.** Profit, win rate, drawdown, streaks, results by group, asset, strategy, hour and weekday,
  how deep chains go, and a plain verdict comparing the win rate with the break-even line (it refuses
  to conclude from too few trades). Demo and real are never mixed. Every table downloads as an
  Excel-friendly CSV.
- **Backups and speed.** `npm run backup` (consistent while running) and `npm run latency` (your own
  signal-to-order timings); see [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Development

Two terminals, both from the repository root:

```
npm run backend      # API on http://127.0.0.1:8000
npm run frontend     # dashboard with hot reload on http://127.0.0.1:5173
```

The dev server forwards `/api` and `/ws` to the backend. Start the backend with `npm run backend`
(or `python -m app`), never a bare `uvicorn`: that is what enforces the loopback-only rule.

After changing the backend API run `npm run api:generate`: it rewrites `docs/openapi.json` and the
frontend's types, and `npm run check` fails if you forget. With the backend running,
<http://127.0.0.1:8000/docs> is an interactive page for every endpoint, and `npm run api:watch` prints
the live feed.

| Command | What it does |
|---|---|
| `npm run lint` | ruff (check + format check), ESLint, Prettier check |
| `npm run typecheck` | mypy (strict) and `tsc --noEmit` |
| `npm run test` | pytest and Vitest |
| `npm run build` | production build of the frontend |
| `npm run api:check` | the committed API description and frontend types match the code |
| `npm run check` | all of the above |
| `npm run db:upgrade` | Create or update the database to the newest schema |
| `npm run db:downgrade` | Remove every table. **Deletes all data.** |

## Layout

```
backend/    FastAPI app (app/), tests (tests/), scripts (scripts/), pyproject.toml, uv.lock
frontend/   React + Vite + TypeScript dashboard
docs/       architecture, decisions, phases, status, guides, phase reports
backups/    created by `npm run backup` (git-ignored)
backend/data/   created at runtime (git-ignored): database, sessions, logs
```

Start with [CLAUDE.md](CLAUDE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) to see how the
parts fit together.
