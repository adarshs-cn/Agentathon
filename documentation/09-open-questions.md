# 09. Open questions

Questions 1 to 3 **block** the work; the rest have a stated default and only need an answer if you disagree.

## Blocking

### 1. The phone message: preview, or really send?

You said: *"I want to show the message that I received from the agent to my phone number."* Two readings:

* **A. Preview (recommended first).** The stub agents generate the exact message text, and the Overview shows it in a phone view
  addressed to your number (masked). Nothing leaves the machine. It is the agent's genuine output in this system, but it is not
  delivered to a phone.
* **B. Real delivery.** The message is actually sent to your phone by your teammates' WhatsApp, email and voice agents. That needs, from you:
  * how each agent is called (URL or SDK, request shape, how to ask "was this message sent?");
  * credentials, kept in the git-ignored `.env`;
  * whether WhatsApp needs a pre-approved template for the text, and whether your number has opted in;
  * confirmation that sending to your number from this demo is fine (cost, rate limits, no other recipients).
  The supervisor is already built for it (`execute` and `lookup`), so it is an adapter, not a redesign.

**Recommendation:** build A in P1 and P2, and treat B as P5 once you have the agent details. Which do you want, and if B, can you share the agent details?

### 2. Which screens leave the navigation?

Proposed: keep **Overview, Accounts, History**; fold **Borrower Trace, Faults & Recovery, Agents, Ownership** into the Overview and
borrower drawer; drop **Budgets** from the navigation (data and API stay). Files are removed only at gate G2.
Confirm, or name any screen you want to keep. Also: when removed, **delete the code** or **archive it** (kept out of the router in an `_archive` folder)?

### 3. What should the Accounts page show?

You said the Accounts page holds a lot of data. Options:

* **Demo borrowers first, with a toggle to all 20,000** (recommended: the 15 are one click away, nothing is lost);
* **Only the 15 demo borrowers**;
* **All 20,000 as now** (plus the drawer change).

## With defaults (answer only if you disagree)

| # | Question | Default |
|---|---|---|
| 4 | The demo phone number and where it lives | Set `MT02_DEMO_PHONE` (and optionally `MT02_DEMO_EMAIL`) in the git-ignored `.env`; shown masked (`XXXXXX1234`); unmasked only if you set `MT02_SHOW_FULL_PHONE=1` on the demo machine. |
| 5 | Event naming | "Remainder" is read as Reminder; `DUE_SOON` shows as "Reminder due" (05). |
| 6 | "Zooms out the current node" | Emphasise: scale up and glow, dim the rest. A camera pan and zoom of the whole canvas is available if you want that literally. |
| 7 | Animation speed | 650 ms per step, with a Slow (1000 ms) and Normal toggle. |
| 8 | The list of 15 events | As in 04. Swap candidates are listed there (Do-Not-Disturb, deceased borrower, timeout quarantined for a person). |
| 9 | A "Run all in order" button | Yes, as a secondary action next to Run (for presenting); Run stays per-event. |
| 10 | The day clock | Kept in the backend behind `MT02_MODE=day`, removed from the UI. Say if you want it deleted outright. |
| 11 | Message wording and sender name | Short, neutral, a clearly fake pay link, lender name "CreditNirvana", standard opt-out line. Give me the exact wording if you have approved copy. |
| 12 | Hero tile set | The same six. If any should go (for example Routing latency) say so. |
| 13 | Deferred events (event 10) | The retry event is created and visible in History, not in the dropdown; "Waiting for a better time, earliest 08:00" is the outcome shown. |

## Assumptions I am making (flagging, not asking)

* The 15 borrowers come from the **real loaded portfolio**, chosen by rule, with small flagged setup rows where a situation must be staged.
* The messages shown are generated from templates by the **stub agents**; they are realistic text, not captured from a real provider.
* Names and phones stay **masked** in the database and the API, as before; only the demo number is configurable.
* The existing 285 tests are a hard floor: nothing in this refinement is allowed to break them.
