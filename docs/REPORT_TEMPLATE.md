# Phase Report Template

Copy this to `docs/reports/phase-<N>.md` at the end of each phase and fill in every section.
Be honest and specific: commands run, results seen, things you could not verify. Keep it readable
for the owner (who is learning the system) — explain jargon briefly.

---

# Phase <N> — <name> — Report

**Date:** <YYYY-MM-DD>
**Status:** Done / Done with open items / Blocked

## 1. Summary
Three to six sentences: what this phase delivered and what the owner can now do or see.

## 2. What was done
Bullet list, grouped by area. Reference files as `path:line` where useful.
- …

## 3. Acceptance criteria
Copy the criteria from `docs/PHASES.md` and mark each one.

| Criterion | Result | Evidence (command / test name / output) |
|---|---|---|
| … | ✅ / ⚠️ / ❌ / ⏸ not verifiable | … |

## 4. Checks run
Exact commands and outcomes (lint, type check, tests, build). Include test counts.

```
$ <command>
<short result>
```

## 5. Challenges and how they were resolved
For each real problem: what happened, what was tried, what fixed it, and whether anything remains.

1. **<problem>** — cause: … — resolution: … — remaining risk: …

## 6. Deviations from the plan
Anything done differently from `docs/PHASES.md`, `docs/ARCHITECTURE.md` or `docs/DECISIONS.md`, and why.
New decisions made (add them to `docs/DECISIONS.md` and list the IDs here).

## 7. Could not be verified
Items needing live Telegram/Quotex, real money or the owner's input. For each: the exact manual steps
the owner can follow and the result that means success.

## 8. Measurements
Latency, throughput or timing numbers collected this phase (with how they were measured).

## 9. New dependencies / files of note
Dependency (version) — why it was needed. Important new files and what they are for.

## 10. Suggestions and open questions
Ideas that were out of scope, risks noticed, and decisions the owner needs to make.

## 11. Git state
Confirm: **no commits were made.** List of changed/new files (`git status --short`).

---

_After writing this report: update `docs/STATUS.md`, give the owner a short summary, and stop._
