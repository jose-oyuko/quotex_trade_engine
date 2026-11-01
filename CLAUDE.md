# Quotex Trade Engine — Agent Guide

Read this file first, every session. Then read the documents listed under "Read order".

## What this project is

A local-first web application that listens to **several Telegram signal groups at once**, turns the
signals into **Quotex binary-option trades** with near-real-time execution, runs per-group
**martingale / flip strategies**, stores everything in a database, and shows it all on a **live
dashboard** with **reports**.

- Backend: **Python 3.12 + FastAPI** (one async process: web server + trading engine)
- Frontend: **React + Vite + TypeScript**
- Database: **SQLite (WAL)**, designed so it can move to PostgreSQL later
- Telegram: **Telethon**. Quotex: **pyquotex** (unofficial, pinned git dependency), always behind one adapter
- Runs on the owner's Windows PC first, a VPS later. Single user, **no user accounts** for now.

The owner is learning the system as it is built. Explain what you did and why, in plain language.

## Hard rules (never break these)

1. **One phase at a time.** Work only on the phase the owner has told you to do (see `docs/STATUS.md`).
   When it is finished, **stop**, write the phase report, and **wait** for the owner to say "go on".
   Never start the next phase on your own, not even "small preparations".
2. **Never commit, push, tag or change git history** unless the owner explicitly tells you to.
   Leave changes in the working tree. You may run read-only git commands (`status`, `diff`, `log`).
3. **Never put secrets in the repo**: no passwords, Telegram API hashes, session strings, `.session`
   files, `session.json`, tokens. They live in `.env` / a local data directory that is git-ignored.
   Never copy credentials out of the old project (see below), never print them in logs or reports.
4. **Default to demo.** Nothing may place a real-money trade unless the owner has set the account
   type to REAL explicitly. Tests and development use the fake Quotex adapter or the demo account.
5. **The execution path is sacred.** Between "signal received" and "order sent" there must be no
   database wait, no blocking I/O and no dashboard work (see `docs/ARCHITECTURE.md`, section 4).
6. **All Quotex access goes through the adapter** (`app/quotex/`). No other module imports `pyquotex`.
7. **Do not invent scope.** If something is not in the current phase, put it in the report under
   "Suggestions" instead of building it. If a decision is genuinely the owner's, ask.
8. **No fake success.** If a test fails or something could not be verified (for example anything that
   needs the live Quotex or Telegram), say so plainly in the report. Never claim it works if you did not run it.

## Read order

1. `docs/STATUS.md` — which phase is current, what is done
2. `docs/PHASES.md` — scope and acceptance criteria of the current phase
3. `docs/ARCHITECTURE.md` — components, data flow, concurrency, execution path
4. `docs/DECISIONS.md` — decisions already made and why (do not re-litigate them)
5. `docs/DOMAIN.md` — strategies, chains, signal formats, config shape, Quotex facts
6. `docs/CONVENTIONS.md` — coding standards for backend and frontend, testing, git hygiene
7. `docs/REPORT_TEMPLATE.md` — how to write the end-of-phase report

## How a phase works

1. Read the documents above and the phase section in `docs/PHASES.md`.
2. Write a short plan (a few bullets) and show it before large changes. Ask only about real blockers.
3. Implement **only** that phase, following `docs/CONVENTIONS.md`. Write tests as you go.
4. Run the checks (lint, type check, tests, build). Fix failures; do not skip or weaken checks.
5. Verify the phase's **acceptance criteria** one by one.
6. Write the report to `docs/reports/phase-<N>.md` using `docs/REPORT_TEMPLATE.md`:
   what was done, challenges faced and how they were resolved, what could not be verified,
   deviations from the plan, suggestions.
7. Update `docs/STATUS.md`.
8. **Stop.** Summarise the report for the owner and wait. Do not commit.

## Definition of done (every phase)

- All acceptance criteria of the phase are met and demonstrated (command output or test names).
- `ruff check`, `ruff format --check`, `mypy` (backend) and `eslint`, `tsc --noEmit` (frontend, once it exists) pass.
- New behaviour has tests; the whole test suite passes.
- No secrets, no stray files, no leftover debug prints, no TODOs without an entry in the report.
- The phase report and `docs/STATUS.md` are updated.

## Old project (read-only reference)

The previous console bot lives at `C:\Users\Administrator\Desktop\paul\jose_trial\pyquotex\`
(main file `trading_bot_V2.py`). Use it **only to read** the signal parser (`parse_signal`) and the
strategy logic when a phase tells you to port them. It contains plaintext credentials and session
files: never copy, open or print `trade_copier_config.json`, `session.json`, `*.session` or any
`.env`-like file from there. Do not modify anything in that folder.

## Communication style

Be concise and concrete. Report facts: what you ran, what the output was. When you hit a problem,
say what you tried and what resolved it. Prefer the owner's terms (group, signal, chain, step).
