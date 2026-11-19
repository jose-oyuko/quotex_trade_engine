# Project Status

Updated by the agent at the end of every phase. The owner moves the project forward by telling the
agent to start the next phase.

| Phase | Name | State |
|---|---|---|
| 0 | Foundation and tooling | Approved |
| 1 | Database and domain models | Approved |
| 2 | Quotex adapter | Done — owner moved on; live demo checks still pending |
| 3 | Telegram listener and parser | Done — committed (`607c145`); live checks pending |
| 4 | Strategy and chain engine | Done — committed and pushed (`b3d9631`); live checks pending |
| 5 | Safety and control | Done — committed; live checks pending |
| 6 | API and realtime events | Done — committed; live checks pending |
| 7 | Dashboard v1 | Done — committed; live checks pending |
| 8 | Reports | Done — committed; live checks pending |
| 9 | Hardening and packaging | Done — committed; live checks pending |
| 10 | Owner account and login | Done — awaiting owner approval (not committed) |
| 11 | Encrypted store and settings in the database | Done — awaiting owner approval (not committed) |
| 12 | Engine control from the dashboard | Done — committed; live checks pending |
| 13 | Telegram login in the dashboard | Done — committed; live checks pending |
| 14 | Quotex login in the dashboard | Done — committed; live checks pending |
| 15 | Clean-up and documentation | Done — committed; live checks pending |
| 16 | Trading sessions: one pair at a time (backend) | Done — committed; live checks pending |
| 17 | Trading sessions: a pair at every candle (backend) | Done — committed; live checks pending |
| 18 | Trading sessions on the dashboard and in the reports | Done — committed; live checks pending |
| 19 | Deriv adapter (backend, not yet in the engine) | Done — committed (`fbdbeb1`); checked live on the Deriv demo |
| 20 | Two brokers in the engine (backend) | Done — committed (`69d0ded`); live check pending |
| 21 | Deriv on the dashboard, in the reports and in the guides | Done — committed; live check pending |
| 22 | Never freeze on a dropped connection; continue chains when nothing was missed | Done — committed (`2a75d06`); live check pending |
| 23 | Turn a broker on or off without stopping the engine | Done — committed (`5febc99`); live check pending |
| 24 | Settle faster, so martingale steps stop drifting | Done — committed; live timeline 3/3 agreed (2.0 s saved); early result OFF until the owner switches it on |
| 25 | The growing flip strategy | Done — committed; live check pending |

States: `Not started` → `In progress` → `Done — awaiting owner approval` → `Approved`.

**Current phase:** Phase 25 (the growing flip strategy, D-83, [report](reports/phase-25.md)) is done and committed; nothing is in progress. Phases 22-24 are done and committed. Phase 24 ([report](reports/phase-24.md)) added the Deriv early result (D-82), switched OFF until the owner runs `npm run deriv:check -- --asset 1HZ75V --order --timeline` on the demo and the early and Deriv results agree; `npm run latency` now shows expiry -> result and expiry -> next. Phase 23 ([report](reports/phase-23.md)) is done and committed: a switch per broker on the Settings page (an off broker is not connected and stops logging in; remembered), and a login only the owner can fix (Quotex's e-mailed PIN) stops the retries and shows "needs you". Phase 22 ([report](reports/phase-22.md)) is done and committed: the Deriv freeze on a dropped connection is fixed, chains carry on unless a trade time was missed (D-79), Deriv trades left open or `unknown` get their real result after a restart, session runs carry on after a crash or Ctrl+C, Start now reads the payout first, and a stall watchdog reports a frozen engine and makes Ctrl+C always work; its live check on the owner's Deriv demo is in section 7 of its report. The owner asked for Phases 22-24 to be built in order, testing and committing each. Before that: Phase 21 (Deriv on the dashboard, in the reports and in the guides) is done and committed ([report](reports/phase-21.md)); its live check on the owner's Deriv demo is pending. Phase 20 (two brokers in the engine, [report](reports/phase-20.md)) is committed (`69d0ded`), Phase 19 (the Deriv adapter, [report](reports/phase-19.md)) is committed (`fbdbeb1`). Phases 19-21 make Deriv a second broker next to Quotex (decisions D-74 to D-77). The owner ran `npm run deriv:check -- --order` on the Deriv demo on 2026-11-17: a 1-minute R_75 trade was confirmed in 510 ms and won 0.88. The live check of Phases 20-21 is in section 7B of the Phase 21 report. Before that: Phases 16-18 (trading sessions: automatic pairs from a schedule set on the dashboard; decisions
D-71 to D-73; planned in `PHASES.md`). The owner asked for all three to be built in order, testing and committing after
each. Phases 16, 17 and 18 are done ([16](reports/phase-16.md), [17](reports/phase-17.md), [18](reports/phase-18.md)); the live checks of each are still to be run on the demo account. The opposite pair for the flip strategies ([report](reports/opposite-pair.md), D-70) is built and
committed (`d6ddc24`). All fifteen numbered phases before them are built and committed. Phases 10-15 (everything the owner types moves into the dashboard: reports [phase-10](reports/phase-10.md), [phase-11](reports/phase-11.md), [phase-12](reports/phase-12.md), [phase-13](reports/phase-13.md), [phase-14](reports/phase-14.md), [phase-15](reports/phase-15.md)) were done on the owner's instruction to carry on to the end, testing and committing after each. The owner asked the agent to carry on through Phase 15, testing and committing after each phase. Phases 10-15 (everything the owner types moves into the dashboard, D-58) are planned in `PHASES.md`; The final report ([phase-15](reports/phase-15.md)) lists the known limitations and every live check still to be run. Before that: all nine original phases were built. Phase 9 is committed. The owner asked the agent to
carry on through the remaining phases in order, committing after each finished and tested phase; that is
complete. Phases 2-9 are only verified on fakes; their live checks are in each report's "could not be
verified" section (for Phase 9: the real signal-to-order latency with `npm run latency`, real reconnects,
a real VPS). Report: [reports/phase-9.md](reports/phase-9.md), which also lists the known limitations and
the "Later" backlog. To run it: `npm run setup`, then `npm start` (guides: README, `OPERATIONS.md`,
`TROUBLESHOOTING.md`, `FAILURE_MODES.md`, `DEPLOYMENT.md`).

**Commits:** the owner's up to `607c145`; Phases 4-9 committed by the agent. The owner gave explicit
permission (this session) to commit after every finished phase; it is not a standing permission for later
sessions. Nothing has been pushed by the agent in this session.

## Open questions for the owner

- Phase 11: the key in `backend/.env` is created by `npm start`: please keep a copy of that file somewhere safe.

- Phase 10: `test_reports_performance` fails on this PC for speed only (section 5 of the report).

- Phase 3 §10: please send real messages from your groups (signals and non-signals) to add to the parser
  tests; and say whether a message without a stated expiry should be traded (as 60 s, the old behaviour)
  or ignored.
- Phase 3 §12: run the live Telegram steps (create the API id, log in, listen to a group) and send back one
  `[parsed]` line and any `not_parsed` message that should have been a signal.
- Phase 2 §7/§12: run the live demo checks and send back the timing lines and one losing-trade result
  (to confirm a loss shows a negative profit).
- Phase 2 §10: `TIME` (clock-aligned expiry, library default) or `TIMER` (countdown) expiry mode?
- Phase 9: Docker or systemd-and-SSH-tunnel only for a server (D-53)? And should a signal missed during a
  Telegram outage ever be fetched and traded (D-55)?
- Phase 9 §7: do the live checks on demo (latency, reconnect, crash, Ctrl+C) and send back the
  `npm run latency` table.
