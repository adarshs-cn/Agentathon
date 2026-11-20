# 08. Delivery phases, gates and tests

Work is split so that **you see the graph early** (it is the part you are most particular about) and nothing you rely on
disappears before the replacement is approved. Each phase ends with something you can run and judge.

Sizes are relative effort: S small, M medium, L large.

## Phases

### P0: Sign-off (you)  *size S*
* Read this folder; answer the questions in 09 (the first three block P1 and P2).
* **Gate G0:** the plan is approved or corrected. No code changes before this.

### P1: Backend foundation  *size L*
Deliver, in this order, each with its tests:
1. **Plain-language layer** (`reasons.py`): catalogue and sentence builders (05), `reason_plain` added to existing responses.
2. **Scenario builder**: the 15 events, setup rows, fault scripts, `demo_event` table, reset.
3. **Run by id**: `EventQueue.claim`, `Supervisor.process_event`, dependency and run lock, stored `run_step` rows.
4. **Node streaming**: listeners in `instrument`, pacing, the `run_start / step / run_end` stream events, `GET …/steps`.
5. **Messages**: templates, `ContactRequest.context`, stub agents return the message, `contact_log` columns, masked demo contact.
6. **Drilldown endpoints** for the six tiles.

**Acceptance (P1):** with a script (no UI), all 15 events run through the API and each ends exactly as 04 says; the stream emits
start-then-end for every node in order; every step has a plain sentence and owners; every contacted event carries a message; the
existing 285 tests pass; the new tests in 06 pass.

### P2: The workflow graph  *size L*
1. `layout.js`, `Station`, `Edge`, `WorkflowGraph` drawn **statically** from stored steps (idle, finished, stopped, fault).
2. The three-fact hover card.
3. `EventPicker` and `RunControls`; live **Run** animation from the stream; **Replay**.
4. `PhonePreview`.

**Gate G1 (visual review with you):** screenshots at 1280 / 1440 / 1920 for events 1 (happy path), 8 (stopped), 13 (fault and
recovery), and mid-animation frames. **Nothing else on the Overview is changed until you approve the graph's look.**

**Acceptance (P2):** pressing Run on any of the 15 events animates the real run: stations activate in graph order, the edge to the
next one highlights, hover shows exactly three facts, the phone view shows the message, Replay matches the live run, and
reduced-motion behaves.

### P3: Overview cleanup, tiles, navigation  *size M*
1. Rebuild `Overview.jsx`: tiles above, workflow card below; remove the clock, scorecard, "why stopped", chart, channel mix, feed.
2. `TileDrawer` for all six tiles; rows select the event in the graph; tiles stay live.
3. `BorrowerDrawer`; Accounts shows demo borrowers first, rows open the drawer.
4. History: plain reasons first, codes secondary.
5. Rail reduced to Overview, Accounts, History; header without the clock.

**Gate G2 (sign-off to retire screens):** after you confirm, Faults, Agents, Ownership, Budgets and Borrower Trace are removed from
the router and the code is deleted (or archived, your choice, see 09).

**Acceptance (P3):** every tile click opens a drawer whose rows add up to the tile's number; no code appears as a headline anywhere;
three sidebar items; no click leads nowhere.

### P4: Polish and proof  *size M*
Copy review against the plain-language checklist below; spacing and alignment pass; performance (first paint, animation smoothness);
e2e click tests in `frontend/e2e/`; screenshot set; docs refreshed (README, this folder marked as implemented).

### P5 (optional, needs your input): real delivery to a real phone  *size M, depends on teammates*
A `ChannelAgent` adapter per channel that calls your teammates' services with the demo number; `lookup` mapped to their status
API; a clear on-screen marker "Delivered by the real WhatsApp agent". Separate because it needs endpoints, credentials, template
approvals, and consent for the demo number. See 09, question 1.

## Plain-language checklist (applied in P4, and by a test where it can be)

* No rule code is the first thing on any line. (Test: scan API reasons and rendered text.)
* Every outcome, event and agent name is the friendly word from 05.
* A reason answers "why" in one sentence with no jargon (no "matrix", "lease", "guard", "idempotent").
* Numbers have units and a denominator where one exists ("2 of 3 contacts used today").
* If something is empty because the data does not contain it, the screen says so instead of showing a blank.

## Test strategy

| Layer | What | Where |
|---|---|---|
| Backend unit and integration | Everything in 06 section 7 | `backend/Orchestrator/tests/` |
| API contract | The shapes the new components read (scenario list, steps, stream events, drilldowns) | same, using the real portfolio |
| Frontend logic | `layout.js` positions and the run state machine (pure functions) | `frontend/e2e/logic.mjs` run with Node |
| Browser end to end | Real clicks: Run animates in order, hover has three rows, tile drawers, Replay, reduced motion | `frontend/e2e/` using headless Chrome (the CDP driver already proven in this project) |
| Visual | Screenshots at three widths and key frames, reviewed with you at G1 and G2 | `documentation/screens/` (added in P2) |
| Lint and build | `npm run lint` clean, `npm run build` passes | CI-style check each phase |
| Regression | The existing 285 backend tests every phase | always |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The graph looks off, or is not what you picture | G1 happens **before** the rest of the Overview is rebuilt; the graph is isolated in one folder so it is cheap to redo. |
| "Zoom" means a camera move, not emphasis | Called out in 01 and 03; a camera pan and scale is a small addition if wanted. |
| Pacing makes a run feel slow | Slow / Normal toggle; default 650 ms per step; pacing is a parameter, not a constant. |
| The 15 scenarios depend on rare data | The builder fails loudly if a criterion has no match; a test covers every row. |
| Removing screens loses something you use | Screens are removed only at G2, after your confirmation; archive option in 09. |
| Real delivery expectations | Kept as an explicit, optional phase (P5); the preview in P2 is labelled as the agent's output in this system, not a delivered message. |

## Definition of done for the whole refinement

You open the Overview, pick any of the 15 events, press Run, and watch a clean graph walk the real workflow with plain-English
hovers and the message on a phone view. Every tile opens a list that explains its number. Three sidebar items remain. No rule
code is the headline anywhere. Lint, build and all tests are green.
