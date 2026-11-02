# Project Status

Updated by the agent at the end of every phase. The owner moves the project forward by telling the
agent to start the next phase.

| Phase | Name | State |
|---|---|---|
| 0 | Foundation and tooling | Approved |
| 1 | Database and domain models | Approved |
| 2 | Quotex adapter | Done — owner moved on; live demo checks still pending |
| 3 | Telegram listener and parser | Done — committed (`607c145`); live checks pending |
| 4 | Strategy and chain engine | Done — committed and pushed; awaiting owner approval (live checks pending) |
| 5 | Safety and control | Not started |
| 6 | API and realtime events | Not started |
| 7 | Dashboard v1 | Not started |
| 8 | Reports | Not started |
| 9 | Hardening and packaging | Not started |

States: `Not started` → `In progress` → `Done — awaiting owner approval` → `Approved`.

**Current phase:** Phase 4 finished and committed. The owner asked for Phase 5 to follow, then to stop.
All offline checks pass (529 backend tests, 3 frontend, lint, strict types, build). Report:
[reports/phase-4.md](reports/phase-4.md). Phases 2-4 are only verified on fakes; their live checks are
listed in each report's last section.

**Commits:** the owner's up to `607c145 telegram listener`; Phase 4 was committed and pushed by the agent
at the owner's explicit instruction for this session (not a standing permission).

## Open questions for the owner

- Phase 3 §10: please send real messages from your groups (signals and non-signals) to add to the parser
  tests; and say whether a message without a stated expiry should be traded (as 60 s, the old behaviour)
  or ignored.
- Phase 3 §12: run the live Telegram steps (create the API id, log in, listen to a group) and send back one
  `[parsed]` line and any `not_parsed` message that should have been a signal.
- Phase 2 §7/§12: run the live demo checks and send back the timing lines and one losing-trade result
  (to confirm a loss shows a negative profit).
- Phase 2 §10: `TIME` (clock-aligned expiry, library default) or `TIMER` (countdown) expiry mode?
