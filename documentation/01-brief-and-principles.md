# 01. Brief and principles

## What was asked (restated, so it can be corrected)

1. **Simulate only 10 to 15 user events**, and show the workflow while each one is processed. Example: the first event is a
   "reminder due"; the supervisor hands it to the Reminder agent; show the message that came out of that agent as if it
   arrived on a phone.
2. **Keep the six hero tiles** on the Overview, but they must be **clickable** and say something useful. Today clicking does nothing.
3. **Remove the confusing panels.** "Why contacts were stopped" shows codes such as D12-matrix, R063, R007 that mean nothing
   to a viewer. More generally: too much information is shown without explaining what is happening under the hood.
4. **Below the tiles, a live graphical workflow visualiser**, very cleanly drawn:
   * a **dropdown** to choose one specific event;
   * the workflow drawn as a neat graph;
   * **hovering a node shows exactly three things**: (a) who the borrower is, (b) who owns them (none for a fresh account,
     otherwise e.g. Reminder), (c) what the supervisor did at this step, with a proper reason;
   * a **Run / Execute graph** button inside the graph area that executes that event **ad hoc** (on demand, not on a clock);
   * during the run, the **current node zooms**, the **edge to the next node is highlighted**, and so on to the end.
5. **Fewer side-navigation screens and the least information that is still accurate** on each screen. This is stated as the
   real agenda.
6. **Strictly follow the existing UI theme.**
7. Be very picky about the **look and feel of the graph**.

## Vocabulary notes

* "Remainder" is read as **Reminder**. The UI will say Reminder everywhere.
* The event the code calls `DUE_SOON` will be shown as **Reminder due**.
* "Zooms out the current node" is read as **emphasises the current node** (scale it up, add a soft glow, dim the rest). If a
  literal camera zoom (pan and scale of the whole canvas) is wanted, say so; it is easy to add on top. See 03.

## Principles for every change

| Principle | In practice |
|---|---|
| **One story per screen** | The Overview answers "what did the supervisor do to this borrower, and why?" Nothing else competes with it. |
| **Plain language first, codes second** | Every reason is a short sentence. The rule code (R062) appears only as small grey secondary text or in a tooltip. See 05. |
| **Everything clickable explains itself** | A number opens the list behind it, in place. No click leads nowhere. |
| **No new screens to explain old ones** | Detail opens in a drawer or popover on the same screen, not on a new page. |
| **Accurate or absent** | If a value is not in the data, it is not shown (as already done for Total O/S). No decorative numbers. |
| **Real, not mocked** | Run executes the real supervisor on the real database. The animation follows real node events, not a fake timeline. |
| **Strict theme** | Only the tokens in `muiTheme.js` and `index.css`: teal navigation, green primary action, yellow accent, Inter at the 12px scale, 10px-radius white cards with the grouped-grey header strip, icon plus label for every status (never colour alone), monospace for IDs. No new fonts or colours. |
| **Respect motion preferences** | Animations are disabled or reduced when the user's system asks for reduced motion. |

## What "done" looks like

A person who has never seen the system can: open the Overview, choose "Reminder due" for a borrower, press Run, watch the
graph walk through seven or eight steps, hover any step and read three plain sentences, and see the exact message the
borrower would receive. They never have to know what "R062" or "D12-matrix" means to understand why something was stopped.
