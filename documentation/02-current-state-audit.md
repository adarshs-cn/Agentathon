# 02. Current state audit

Honest account of what is on screen today, what it is for, and what is wrong with it from a viewer's point of view.

## The Overview screen, element by element

| Element | What it is for | Problem | Decision |
|---|---|---|---|
| **Sim time / play / pause / 1x 60x 300x 900x** | Replays a whole simulated day: the clock advances and each event is released when its time arrives. | Built for a day-long run of ~500 events. For a 10 to 15 event walkthrough it is the wrong control: you cannot choose an event, and "paused at 12:23:10" means nothing to a viewer. | **Remove from Overview and header.** Replace with per-event **Run**. The day clock stays in the backend only as an optional "day mode" (off by default). |
| **Six hero tiles** (Conflicting contacts, Faults recovered, Routing latency, Borrowers handled, Contacts made, Blocked / deferred) | Headline numbers that update live as events are processed. They are the supervisor's report card. | They update but **clicking does nothing**, so they raise a question and refuse to answer it. | **Keep.** Make each one open an in-place drawer listing what is behind the number, in plain English. See 03. |
| **Acceptance scorecard** | Shows the four criteria from the problem statement (zero conflicts, faults recovered, complete traces, routing under 100 ms). | Duplicates the tiles; adds a second place to look. | **Remove.** The tiles already carry the same four facts; the drawers carry the evidence. |
| **Why contacts were stopped** | Ranks the rules that blocked contacts. | Shows codes (D12-matrix, R063, R007) with long policy text. A viewer cannot tell what happened or why it matters. This is the panel you called out. | **Remove.** Its useful content moves into the "Blocked / deferred" drawer as plain sentences. |
| **The day so far** (stacked chart by hour) | Shows outcomes through a simulated day. | Meaningful only for a day-long run. With 15 events it is nearly empty. | **Remove.** |
| **Contacts by channel** | Bars of messages per channel and role. | Informational noise for a 15-event demo. | **Remove** (the "Contacts made" drawer shows channel per contact). |
| **Live decision feed** | Newest-first stream of every step of every event. | A firehose: 5 to 8 lines per event, mixed across borrowers, with codes. It shows *a lot* but explains *little*. | **Replace** with the workflow graph for one chosen event, plus a short plain-English event log under it. |
| **Reset day** | Rebuilds the simulated day. | Fine, but "day" is the wrong word once the scenario is 15 events. | **Keep as "Reset demo"**, moved into the graph card. |
| **Live stream connected** dot | Shows the event stream is alive. | Useful but takes a whole card. | **Shrink** to a small dot beside the title. |

## The other screens

| Screen | What it does today | Verdict |
|---|---|---|
| **Accounts** | Grid of all 20,000 accounts with filters, live owner and last contact. | **Keep.** It is the borrower list. Default to the 15 demo borrowers (see 09); row click opens a drawer (not a new page) with that borrower's story. |
| **Borrower Trace** | One borrower's standing now and every event, step by step. | **Fold in.** The workflow graph *is* the trace. The standing-now facts (limits, holds, consent) move into the borrower drawer. Route stays reachable for deep links until sign-off, then is removed. |
| **Decision Log** | Every decision with its reason and rule ids; filters in the URL. | **Keep** as the audit table, renamed **History**, with plain-language reasons first. It is the one place where the codes may be shown, as a secondary column. |
| **Faults & Recovery** | Incident table and fault script. | **Fold in.** A fault now appears *in the graph* (the amber recovery branch lights up when it happens). The "Faults recovered" tile opens the incident list. Screen removed from navigation. |
| **Agents** | Health of the three channel agents and the role-by-bucket matrix. | **Fold in.** Hovering the agent node shows which agent acted. The matrix is policy documentation, not a live view. Screen removed from navigation. |
| **Ownership** | Leases, handoffs, simultaneous requests. | **Fold in.** Owner appears in every node's hover (fact 2). Handoffs and simultaneous requests are two of the 15 demo events. Screen removed from navigation. |
| **Budgets** | D13 attempt budgets and spend. | **Remove from navigation.** Not part of a 15-event story. The data and API stay; a "Budgets" drawer can be added later if wanted. |

## Net effect on navigation

Eight sidebar entries become **three**: **Overview** (workflow), **Accounts**, **History**. Nothing is deleted from the codebase
in the first pass: pages are removed from the navigation and from the router only after you have approved the new Overview,
so there is no point at which something you relied on has silently disappeared.

## What is working well and must not regress

* The data flow: real database, real supervisor, real fault injection. The refinement reads and drives it; it does not fake it.
* The theme and every shared component (`Section`, `StatTile`, `StatusChip`, `OutcomeChip`, `RuleChip`, `SimpleTable`).
* The privacy rule: names and phones are masked in the database; nothing identifying leaves the API.
* The independent audit and the 285 tests.
