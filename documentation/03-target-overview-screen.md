# 03. Target Overview screen

## Layout

```
┌ rail ┬──────────────────────────────────────────────────────────────────────────────────────┐
│      │ Overview                                                  ● live          [Find borrower /] │
│  ◉   ├──────────────────────────────────────────────────────────────────────────────────────┤
│  ▤   │ ┌ Conflicting ┐ ┌ Faults ──┐ ┌ Routing ─┐ ┌ Borrowers ┐ ┌ Contacts ┐ ┌ Blocked / ──┐ │
│  ≡   │ │ contacts  0 │ │ recovered│ │ latency  │ │ handled  7│ │ made    5│ │ deferred  3 │ │  ← kept, now clickable
│      │ └─────────────┘ └──────────┘ └──────────┘ └───────────┘ └──────────┘ └─────────────┘ │
│      │ ┌ Workflow ──────────────────────────────────────────────────────────────────────────┐│
│      │ │ [ 1 · Reminder due · BRW00039 · ✓ Message sent  ▾ ]        [ ▶ Run ]  [↺ Reset]   ││
│      │ │                                                                                    ││
│      │ │  (Event)──▶(Borrower)──▶(Safety)──▶(Agent)──▶(Owner)──▶(WhatsApp)──▶(Check)──▶(Save)──▶(Done)
│      │ │   received   loaded      checks     chosen    locked     acts        result    state     closed
│      │ │                              └────▶ ( Stopped: reason )          └─▶(Recover)─┘          ││
│      │ │                                                                       ┌────────────┐   ││
│      │ │  hover card (3 facts)                                                 │ phone view │   ││
│      │ │                                                                       │ the message│   ││
│      │ │ "Reminder due for BRW00039 → Reminder agent → sent on WhatsApp. Owner: Reminder, 24 h."││
│      │ └────────────────────────────────────────────────────────────────────────────────────┘│
└──────┴──────────────────────────────────────────────────────────────────────────────────────┘
```

Three zones only: the **six tiles**, the **workflow card**, and (collapsed by default) a short **event log** under the graph.

## The workflow graph

The real LangGraph has 15 nodes. Drawing all of them would be noise, so the picture shows **stations** (one station may
cover one or two real nodes). Plain names on the picture; technical node names only in a small secondary line of the hover.

| Station (shown) | Real node(s) | What a viewer should understand |
|---|---|---|
| **Event received** | `validate_event`, `close_event` (entry) | The event arrived and is well-formed. |
| **Borrower loaded** | `load_borrower` | The supervisor looked up the borrower's file. |
| **Safety checks** | `guardrails` | Is any rule stopping contact right now? |
| **Agent chosen** | `route` | Which role acts, and on which channel. |
| **Ownership taken** | `assign` | The borrower is locked to one agent (and a handoff is shown here if it happens). |
| **Agent acts** | `whatsapp` / `email` / `voice` | The channel agent sends the message. The label changes to the channel that was chosen. |
| **Result checked** | `validate_output` | Did the agent really do what it said? |
| **Recover** *(branch, amber)* | `monitor`, `recover` | Only lit when something went wrong: retry, switch channel, skip, or escalate. |
| **State saved** | `commit`, `release` | Last contact and the 24-hour ownership lease are written; the lock is released. |
| **Done / Stopped** | `close_event` | Final outcome in words: Message sent, Not allowed, Waiting for a better time, and so on. |

**Shape.** A single left-to-right main lane of seven or eight stations; the **Recover** branch drops below the lane between
"Agent acts" and "State saved"; a **Stopped** end node sits below the lane and receives the early-exit edges from "Safety
checks" and "Agent chosen". Fits one row at 1280px and above; below that the lane wraps into two rows (snake layout) rather
than shrinking text.

**Look.** Rounded nodes in the card style (white, 10px radius, soft card shadow), a small icon from the existing icon set, the
station name in 12px Inter 600, a one-word state under it. Edges are thin grey lines with a small arrowhead. The palette is
the theme's only: teal for the active path, green for completed, amber for recovery, red for stopped, grey for not yet reached.
Colour is never the only signal: every node carries an icon (check, clock, warning, block).

## Hover: exactly three facts

Hovering (or keyboard-focusing) any station opens one small card, nothing else:

| | Shows | Example |
|---|---|---|
| 1. **Borrower** | Customer number, masked name, days past due | `BRW00039 · R*** J*** · 36 days past due` |
| 2. **Owner** | Who owned the borrower *at this step* ("Nobody (new)" for a fresh borrower) | `Nobody → Reminder` at "Ownership taken"; `Reminder until tomorrow 14:00` afterwards |
| 3. **What the supervisor did** | One or two plain sentences, with the reason | `Allowed: 0 of 3 contacts used today, no holds.` / `Stopped: a promise to pay is open until 2 Nov.` |

A station not reached yet says "Not run yet". The rule code, if any, is a small grey tag at the end of fact 3 and nowhere else.
Sentences are generated from the real decision-log row plus the reason catalogue in 05.

## Run (ad hoc execution)

* The **Run** button sits in the graph card header. It executes the *selected* event through the real supervisor, now, on demand.
  There is no clock and no queue to wait for.
* While running, the button becomes **Running…** (disabled) and the dropdown is locked.
* **Animation, driven by real node events** (the backend announces `step started` and `step finished`; the screen follows):
  1. the **current station zooms**: scales to about 1.12x over 250 ms, gets a soft teal glow ring, every other station dims to ~60%;
  2. the **edge to the next station** lights up (teal, thicker, flowing dashes) as soon as the current step finishes;
  3. a finished station shows a green check and settles back to normal size; its incoming edge stays solid teal;
  4. at about 600 ms per step, a whole event takes four to six seconds; a **speed** toggle (Slow / Normal) is offered;
  5. if the event is stopped, the path turns to the **Stopped** node (red, with the reason as a one-line caption);
  6. if a fault occurs, the **Recover** branch lights in amber and the loop back to the agent is drawn, then the path continues.
* When the agent node finishes, the **phone view** slides in (see below).
* After a run, **Run** becomes **Replay**: it animates the stored steps without executing anything again.
* Events that were already processed (for example, ones the clock ran earlier) open in their finished state and can be replayed.

If a literal camera zoom is wanted (the canvas pans and scales to centre the current node) it is a CSS transform on the graph
group and costs little; the default is emphasis-only because with eight stations on one row everything is always visible.

## The phone view (the message the borrower receives)

A compact phone-style card to the right of the "Agent acts" station, shown after that step:

* header: channel icon and name (WhatsApp / Email / Voice call), `To: XXXXXX1234` (the demo number, masked; see 09), time;
* body: the exact message text the agent produced: for WhatsApp a bubble, for email a subject and a two-line body, for voice
  the script the IVR would read;
* footer: `Sent via WhatsApp agent · ref whatsapp-000001`.

In phase 1 this text is produced by the stub agents from message templates (see 06), so it is **the real output of the
agent in this system**. Delivering it to a real phone is a separate, later phase (see 09, question 1).

## The six tiles: kept, now clickable

Each opens a **drawer on the right** (same screen, no navigation). A row in a drawer **selects that event in the graph**.

| Tile | Drawer lists | Plain-English line per row |
|---|---|---|
| **Conflicting contacts** | The audit result: "Checked N contacts against every policy rule: 0 problems." If any, each problem with the borrower. | "BRW0012 was contacted twice within 30 minutes." |
| **Faults recovered** | Each fault that fired: what broke, what the provider said, what the supervisor did. | "WhatsApp agent crashed after sending. Provider confirmed it was sent, so it was recorded and not sent again." |
| **Routing latency** | Per-step timings of the last runs (a tiny bar list), the 100 ms target. | "Choose agent: 0.8 ms median." |
| **Borrowers handled** | Each borrower with the outcome of their event. | "BRW0039: Reminder sent on WhatsApp." |
| **Contacts made** | Each message sent: channel, time, first line of the text. | "WhatsApp 09:14: Hi R***, your EMI of ₹6,424 is due on 2 Nov." |
| **Blocked / deferred** | Each stopped event with the reason in words. | "BRW0107: not contacted, a promise to pay is open until 2 Nov." |

Tiles keep updating live while a run is in progress (they already do).

## Under the graph: the event log (collapsed)

A single collapsible "What happened" list for the selected event: one plain sentence per station, in order. It is the text
version of the graph for anyone who prefers to read, and the place where the technical detail (request, response, rule
codes) can be expanded for anyone who wants it.

## Accessibility and motion

Every station is reachable by keyboard and shows the hover card on focus. All state is conveyed by icon and word as well as
colour. Under "reduce motion" the zoom, glow and flowing dashes are replaced by an instant highlight; the run still steps.
