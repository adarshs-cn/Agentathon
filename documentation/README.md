# Refinement plan: from "lots of numbers" to "watch one borrower's workflow"

Status: **PLAN ONLY. No code has been changed for this refinement yet.** Read, correct, then approve.

## The one-paragraph version

Today the dashboard shows aggregate numbers and rule codes for a whole simulated day. The refinement turns it into a
**walkthrough of 10 to 15 individual events**. You pick an event from a dropdown, press **Run**, and watch a clean
workflow graph execute that event for real: the current step zooms, the edge to the next step lights up, and hovering a
step tells you three things in plain English (who the borrower is, who owns them, what the supervisor did and why). When
the agent sends a message, you see it as it would appear on a phone. Everything that is not needed for that story is
removed or tucked into an in-place drawer, and the side navigation shrinks.

## Reading order

| # | Document | What it answers |
|---|---|---|
| 01 | [Brief and principles](01-brief-and-principles.md) | What was asked, how it was understood, the rules we follow |
| 02 | [Current state audit](02-current-state-audit.md) | What each screen does today, what is wrong with it, what is kept |
| 03 | [Target Overview screen](03-target-overview-screen.md) | The new screen: layout, workflow graph, hover, Run animation, tiles |
| 04 | [Demo scenario](04-demo-scenario.md) | The 15 events, one per workflow feature, and what each should show |
| 05 | [Plain-language reasons](05-plain-language-reasons.md) | Every rule code translated into words a viewer understands |
| 06 | [Backend plan](06-backend-plan.md) | New endpoints, live node streaming, messages, scenario builder, tests |
| 07 | [Frontend plan](07-frontend-plan.md) | Components, graph drawing, animation spec, navigation, theme rules |
| 08 | [Delivery phases and tests](08-delivery-phases-and-tests.md) | Order of work, acceptance criteria, how each phase is verified |
| 09 | [Open questions](09-open-questions.md) | Decisions only you can make (the first three block the work) |

## Decisions needed before work starts

1. **The phone message.** Show the message *as it would appear* on the borrower's phone (safe, no external send), or *really
   send* it to your number through your teammates' agents (needs their endpoints and credentials)? Recommended: preview first,
   real sending as a clearly separate later phase. See 09.
2. **Which screens go.** The plan keeps three (Overview, Accounts, Decision Log) and folds the rest into the Overview. See 02 and 03.
3. **Accounts page scope.** Show the 15 demo borrowers first with a toggle for all 20,000, or only the 15? See 09.

## What stays exactly as it is

The supervisor itself (graph, policy engine, recovery, audit, tests), the data in SQLite, the theme and all its tokens, the
Accounts grid, and the Decision Log. The refinement changes what the dashboard *shows*, not what the supervisor *does*.


## Implementation status

* **P1 backend foundation: done.** Plain-language layer, the 15-event scenario, run-one-event, live node stream, stored steps, messages,
  tile drilldowns. Tests: `backend/Orchestrator/tests/test_phase14_scenario.py` (all 15 events end as planned in 04).
* **P2 workflow graph: built, awaiting your sign-off (gate G1).** Overview now shows the six clickable tiles, the live graph with the
  event picker and Run / Replay / Reset, the phone preview and the step log. Browser test: `frontend/e2e/overview.mjs`.
* P3 (navigation down to Overview / Accounts / History, borrower drawer, Accounts demo-first, History in plain words) waits for G1.
