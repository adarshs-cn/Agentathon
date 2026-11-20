# 07. Frontend plan

## Theme rules (unchanged, enforced)

Only tokens from `src/theme/muiTheme.js` and `src/index.css`. Teal navigation, green primary action, yellow accent, Inter on the
12px scale, 10px-radius white cards with the grouped-grey header strip, `cardShadow`, icon plus label for every status,
monospace for IDs, tabular figures for numbers. **No new colours, fonts, or shadows.** New components are composed from the
existing `Section`, `StatTile`, `StatusChip`, `OutcomeChip`, `MonoId`, `SimpleTable`.

## Navigation

Rail entries: **Overview**, **Accounts**, **History** (the Decision Log). The five other entries leave the rail and the router
only after you approve the new Overview (see 08, gate G2). Until then they stay reachable by URL.
The header loses the sim clock and keeps the borrower search (it now opens the borrower drawer).

## New and changed files

```
src/components/workflow/
  WorkflowGraph.jsx     the SVG: stations, edges, arrowheads, states
  Station.jsx           one node: icon, name, state word, motion
  Edge.jsx              one connector: idle / active (flowing) / done / skipped
  layout.js             positions of stations and edges; wraps to two rows below 1280px
  NodeHoverCard.jsx     the three-fact hover card (Popper, anchored to the station)
  PhonePreview.jsx      the message as the borrower receives it
  EventPicker.jsx       the dropdown: "4 · Higher-priority agent takes over · ✓ Message sent"
  RunControls.jsx       Run / Replay / Reset demo / speed toggle
  EventLog.jsx          collapsed "What happened": one sentence per station, technical detail on demand
src/components/TileDrawer.jsx     the in-place right drawer behind each tile
src/components/BorrowerDrawer.jsx borrower's standing now (reuses the trace page's cards), opened from Accounts rows
src/hooks/useScenario.js          the 15 events and their status
src/hooks/useRun.js               run state machine fed by the stream, or by stored steps for Replay
src/pages/Overview.jsx            rebuilt: tiles + workflow card
src/components/StatTile.jsx       gains onClick, keyboard focus, hover affordance
src/pages/Decisions.jsx           becomes History: plain reason first, code as a secondary column
src/pages/Accounts.jsx            demo borrowers first; row click opens the drawer (no navigation)
```

## Drawing the graph: custom SVG, not a graph library

**Choice: hand-drawn SVG with CSS transitions.** The flow is fixed (about 10 stations), the look is the priority, and the
animation must be exact. A library (React Flow, dagre) adds a dependency, auto-layout surprises, and styling fights, for no gain on a
graph this small. If the flow ever becomes dynamic, swapping to a library is contained inside `WorkflowGraph.jsx`.

### Geometry
* Station: 128 x 68, 10px radius, white fill, card shadow, 1px divider-grey border; icon at the top, name below (12px, 600), a one-word
  state under it (10.5px). 8px grid; 40px horizontal gap; the main lane is vertically centred in the card.
* Main lane (left to right): Event, Borrower, Safety, Agent chosen, Ownership, Agent acts, Result, State saved, Done.
  Recover branch sits below between Agent acts and State saved; Stopped sits below Safety/Agent chosen.
* Edges: 1.5px grey lines, rounded corners on bends, 6px arrowheads. Loop-back (Recover to Agent acts) is a gentle curve.
* Width: the SVG scales to the card; below 1280px the lane wraps to two rows; text never shrinks below 11px.

### States and motion (the part you asked to be picky about)

| State | Look |
|---|---|
| Not reached | Grey outline, grey icon, "Waiting" |
| **Active** | Scale 1.12 (250 ms ease-out), 2px teal ring with a soft glow, icon in teal, others dim to 60% |
| Done | Green check badge, back to scale 1.0 (200 ms), one-word result ("Allowed", "Sent") |
| Skipped | Dashed grey outline (a branch not taken) |
| Recovering | Amber ring on Recover, edge to it flowing amber |
| Stopped | Red ring and block icon on Stopped, one-line reason caption beneath |

| Edge | Look |
|---|---|
| Idle | Grey, 1.5px |
| **To the next station (active)** | Teal, 3px, dashes flowing toward the target (0.8 s linear loop), arrowhead teal |
| Done | Solid teal, 2px |
| Branch not taken | Light grey, dashed |

* Per step: station zooms in, runs, then the next edge lights while the current one settles; about 650 ms per step by default.
* **Reduced motion**: no scale, glow or flowing dashes; instant highlight with the same sequence.
* Honours the Slow / Normal toggle.

## Behaviour of the Overview

1. Loads `GET /api/scenario`; the dropdown opens on the first event not yet run.
2. Selecting an event draws the graph in its current state (finished events open fully drawn; unrun events open all grey).
3. **Run** calls `POST …/run`; the stream drives `useRun`: `step start` zooms the station and lights the incoming edge, `step end`
   fills the hover sentence and ticks the station, `run_end` shows the outcome caption and slides the phone view in.
4. **Replay** replays stored steps with the same animation and the same pacing, without executing.
5. Hover or focus a station: the three-fact card (03). No other tooltips on the graph.
6. Tiles keep updating from the existing live counters; a click opens `TileDrawer`; a row there selects that event in the graph.
7. Everything is announced for screen readers (station name, state, the three facts).

## Accounts, History, and the borrower drawer

* **Accounts:** a "Demo borrowers (15)" chip is on by default, with "All 20,000" beside it (09, question 3). Clicking a row opens the
  **BorrowerDrawer** (borrower facts, limits used today, holds, consent, "what would happen now") instead of navigating away.
* **History:** columns reordered to Time, Borrower, Event (in words), Outcome (in words), Why (plain sentence), then a small grey
  Rules column. Row click opens the existing detail drawer.

## Verification (see 08 for gates)

* Unit-level: `layout.js` and the run state machine are pure functions; checked with a small script run under Node.
* Browser: the existing CDP driver is extended into `frontend/e2e/`: it presses Run for several events and asserts, from the DOM
  (`data-state` attributes), that stations become active **in order**, that the edge to the next station is highlighted, that the
  hover card shows exactly three rows, that the phone view shows the message, and that tile clicks open drawers with rows.
* Visual: screenshots at 1280, 1440 and 1920 wide, at idle, mid-run on a fault event, and finished, reviewed with you before the
  rest of the screens are touched (gate G1).
