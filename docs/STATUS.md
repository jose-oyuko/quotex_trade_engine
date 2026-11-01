# Project Status

Updated by the agent at the end of every phase. The owner moves the project forward by telling the
agent to start the next phase.

| Phase | Name | State |
|---|---|---|
| 0 | Foundation and tooling | Done — awaiting owner approval |
| 1 | Database and domain models | Not started |
| 2 | Quotex adapter | Not started |
| 3 | Telegram listener and parser | Not started |
| 4 | Strategy and chain engine | Not started |
| 5 | Safety and control | Not started |
| 6 | API and realtime events | Not started |
| 7 | Dashboard v1 | Not started |
| 8 | Reports | Not started |
| 9 | Hardening and packaging | Not started |

States: `Not started` → `In progress` → `Done — awaiting owner approval` → `Approved`.

**Current phase:** Phase 0 finished — waiting for the owner's review and "go on" for Phase 1.
Report: [reports/phase-0.md](reports/phase-0.md).

**Commits:** only the owner's `77a5ded agent guide files`. The agent has made none and does not
commit unless the owner says so. Phase 0 work is uncommitted in the working tree.

## Open questions for the owner

- Phase 0 report §7: two checks only the owner can do (clean-clone setup, page in a browser).
- Decided: `data/` stays in `backend/` (`backend/data`, git-ignored).
- Node upgrade (see D-21): owner is considering it; not required for any phase.
