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
| 8 | Reports | Not started |
| 9 | Hardening and packaging | Not started |

States: `Not started` → `In progress` → `Done — awaiting owner approval` → `Approved`.

**Current phase:** Phase 7 committed. The owner has asked the agent to carry on through the remaining
phases (8-9) in order, committing after each finished and tested phase and documenting each in
`docs/reports/`. Phases 2-7 are only verified on fakes; their live checks are in each report's last
section. Report: [reports/phase-7.md](reports/phase-7.md); API guide: [API.md](API.md). To see the
dashboard without accounts: `npm run build` then `npm run demo`.

**Commits:** the owner's up to `607c145`; Phases 4, 5, 6 and 7 committed by the agent. The owner gave
explicit permission (this session) to commit after every finished phase; it is not a standing permission
for later sessions.

## Open questions for the owner

- Phase 3 §10: please send real messages from your groups (signals and non-signals) to add to the parser
  tests; and say whether a message without a stated expiry should be traded (as 60 s, the old behaviour)
  or ignored.
- Phase 3 §12: run the live Telegram steps (create the API id, log in, listen to a group) and send back one
  `[parsed]` line and any `not_parsed` message that should have been a signal.
- Phase 2 §7/§12: run the live demo checks and send back the timing lines and one losing-trade result
  (to confirm a loss shows a negative profit).
- Phase 2 §10: `TIME` (clock-aligned expiry, library default) or `TIMER` (countdown) expiry mode?
