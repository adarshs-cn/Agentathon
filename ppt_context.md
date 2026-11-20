# ppt_context.md — brief for generating the pitch deck

You are generating a pitch deck for **MT-02 Journey Supervisor** (team project for the Agentathon, CreditNirvana).
Read this whole file first. Then **ask the owner the questions in section 1 before generating anything.**

---

## 0. The rules for this deck (non-negotiable)

* **Short and straight to the point.** Max **12 words per bullet**, max **3 bullets per slide**, max **1 idea per slide**.
  No paragraphs. If a slide needs more, it is two slides.
* **Show, don't tell.** Every slide has one visual: a graph, a diagram, a number, or a screenshot. Text supports the visual.
* **Great animations are the point of this deck.** Use motion to explain, never to decorate (spec in section 4).
  Use PowerPoint **Morph** transitions between consecutive slides wherever a picture evolves.
* **Big numbers.** Use a number as the hero of a slide when there is one (e.g. "**0** conflicting contacts").
* **Only claim what is true** (section 6). No invented metrics, customers or results.
* Target: **6 to 7 slides maximum**, a **5-minute** pitch. Fewer is better; never exceed 7.

---

## 1. ASK THE OWNER FIRST (do not skip)

Ask these, in one message, and wait for the answers:

1. **Audience & length:** hackathon judges, internal leadership, or a client? 5 minutes or 10?
2. **Format:** PowerPoint (.pptx with Morph) or Google Slides? 16:9? Exactly 6 or 7 slides?
3. **Look:** dark "studio" theme (matches the Workflow Studio screen) or the light CreditNirvana dashboard theme?
4. **Names:** what to call the product and the Overview screen ("Live Journey" is a placeholder), and the presenter / team names.
5. **The graph visualizer slides (section 5):** recreate the graph natively in slides with Morph (recommended),
   or embed screen recordings / screenshots of the Workflow Studio?
6. **Live demo:** will there be a live demo after slide 4 or at the end? If yes, mark the hand-off slide.
7. **Logo / brand assets** to use, and anything that must NOT be shown (data, partner names).
8. **The ask / closing slide:** what do they want from the audience (funding, pilot, approval, prize)?

---

## 2. The business story (tell this, not the tech)

**The hero is the Collection Manager.** Today they babysit AI agents: checking who called whom, catching double
outreaches, fixing failed channels, answering "why did we contact this person?". It is stressful and it eats their day.

**With the supervisor:**
1. **Less stress.** The supervisor watches every outreach, all day, inside the legal contact window. The manager is only
   pinged when something went wrong *and was already fixed*.
2. **Time back for strategy.** The manager spends the day on what matters: building new collection strategies.
3. **One customer, one outreach.** A customer never appears in two communication outreaches at once, even across
   several loans and several agents.
4. **Re-routing handled.** If a channel fails (WhatsApp crash, voice stall), the supervisor switches channel or holds,
   without ever sending twice.

**One-line pitch:** *"Your AI agents, supervised. Your collection manager, free."*

---

## 3. Slide-by-slide outline (7 slides max; the visual does the work)

| # | Title (on slide) | On-slide text (max) | Visual |
|---|---|---|---|
| 1 | **Your AI agents, supervised.** | "Your collection manager, free." · product · team | Calm manager silhouette; the supervisor graph glowing behind |
| 2 | **A collection manager's day today** | "Who called whom? Why twice? Which channel failed?" | Manager surrounded by alerts; one customer hit by WhatsApp, Email and a Call at once (red) |
| 3 | **One customer. One outreach.** | "Every loan, every agent — one voice at a time." | Two loans (0 DPD, 60 DPD) → one customer → one owner badge; the second outreach is blocked |
| 4 | **Watch it decide** (signature slide) | "Each step zooms in and explains itself." | The graph run with zoom + trace pad (section 5) |
| 5 | **When a channel fails, it re-routes** | "Channel stalls → checked → next channel. Never sent twice." | Fault path: WhatsApp red → Monitor → Recover → Email lights green |
| 6 | **Stress off, strategy on** | "Alerted only after it is fixed." | Alert drops in ("…happened and recovering") → bell clears; manager's calendar fills with "New strategy" |
| 7 | **Proof & next** | 4 big numbers · "Next: delivery webhooks, real channels, pilot" | Count-up number tiles, then a short roadmap arrow |

Speaker notes: 2–3 short spoken sentences per slide, always from the manager's point of view.

Optional merge if 6 slides are wanted: fold slide 7's roadmap into slide 6 and keep the numbers.

---

## 4. Animation spec (make it feel alive)

General
* **Transitions:** Morph between slides that share a visual (2→3, 4→5, 5→6, 6→7). Fade elsewhere. Duration 0.8–1.2 s.
* **Entrances:** Fade + Zoom (subtle) or Wipe along the reading direction. Stagger list items 0.15–0.25 s.
* **Never:** bounce, spin, fly-in from off-screen, sound effects, more than 3 animated things at once.
* **Numbers:** count-up effect (or 3 quick Morph steps) on slide 11.

Per slide
* **1:** the graph's edges draw in (Wipe left→right), nodes fade in; the manager silhouette fades up in front;
  title types in, then the subline "Your collection manager, free."
* **2:** alert cards pile up around the manager one by one (stagger 0.2 s); three channel icons slide toward one
  customer; on arrival the customer pulses red three times.
* **2 → 3 (Morph):** the red pile collapses; the three icons merge into a single outreach; two loan cards appear and
  join into one customer with one owner badge; a second outreach arrow tries, hits the badge, turns grey ("blocked").
* **3 → 4 (Morph):** the customer card shrinks into the "Load customer" node of the full graph.
* **4:** the signature run, see section 5.
* **4 → 5 (Morph):** stay on the graph; zoom onto the channel fan-out.
* **5:** WhatsApp node flashes red (stalls) → edge to Monitor lights ("provider: nothing was sent") → Recover glows →
  a new edge lights toward Email → Email turns green → stamp "Sent once. Re-routed."
* **6:** an alert drops from the top ("Alert Supervisor Agent – WhatsApp agent/Crash happened and recovering"),
  the bell badge counts 1, then "Mark as read" clears it; the manager's calendar blocks fill with "New strategy".
* **7:** four number tiles count up together; a roadmap arrow wipes in with three short stops.

---

## 5. THE GRAPH VISUALIZER (the owner's signature expectation — get this right)

This mirrors the product's **Workflow Studio** screen. The owner expects this behaviour exactly:

**The graph** (real nodes and edges of the compiled LangGraph):
* Main line: **Start → Validate event → Load customer → Guardrails → Route → Assign**
* Fan-out: **Assign → WhatsApp agent / Email agent / Voice agent** → **Validate output** → **Commit → Release → Close event → End**
* Fault loop: **Validate output → Monitor → Recover**, and **Recover → back to any channel agent, or → Commit**
* Refusals: **Validate event / Guardrails / Route / Assign → Close event** (arcs over the top)
* Mark **5 steps with an "AI" badge**: Validate event, Route, Assign, Monitor, Recover (LLM explains these).
* Conditional edges dashed; plain edges solid.

**The run animation (slide 4, build with click-builds or Morph steps; keep it inside slide 4–5 so the deck stays at 7):**
1. **Zoom in big** on the working step (~2× — a real camera zoom, not a 5% bulge). The step itself grows a bit more and
   gets a glowing cyan ring.
2. Steps **not reached yet fade to ~10% opacity**; finished steps stay visible but dimmer, with a check mark.
3. The **edge being travelled lights up** (cyan, glowing) with a pulse moving along it; travelled edges stay lit.
4. A **trace pad** on the right **types out** what the step is doing, word by word:
   * AI steps: a violet "Reasoning over the facts…" meter, then a **two-sentence** explanation, e.g.
     *Route:* "The reminder agent will act on WhatsApp, with Email and Voice as backups. The payment is 7 days overdue and
     WhatsApp is reachable."
   * Rule steps: their check, line by line, e.g. *Guardrails:* "Deceased, stop requests, complaints… All clear."
5. **Only after the text finishes**, move to the next step (camera pans to it).
6. At the end, **zoom back out** to the whole path; unreached branches stay faded.
7. Optional last build: "hover" a step → it enlarges ~2×, others dim, the pad shows its saved trace.

**Palette for these slides (studio):** background `#070D1A`, nodes `#0F1A2E` with `#3A4D75` outline, active **cyan
`#22D3EE`**, done **green `#34D399`**, fault **red `#F87171`**, AI badge **violet `#A78BFA`**, text `#E2E8F0`,
muted `#8EA3C7`. Monospace for the trace pad.

**Reference screenshots** (real product, in `documentation/ppt_assets/`):
`40-studio-idle.png` (whole graph), `41-running-a.png` (first step zoomed), `42-running-route.png` (Route zoomed, AI
reasoning), `43-done.png` (finished path), `44-hover-route.png` (hover after run), `45-pinned.png` (pinned trace).

---

## 6. Facts you may use (all verified in the codebase)

* **20,000** accounts · **17,000** customers (synthetic, masked data)
* **93** policy rules (D12), e.g. R007 contact hours 08:00–19:00, R033 limits per customer, R035–R038 one owner per customer
* **14** workflow steps · **25** connections (16 conditional) — read from the compiled LangGraph
* **5** steps explained by an LLM (DeepSeek via Sarvam); **rules always decide**; the LLM never sees names, phones or ids
* **Faults recovered:** crash, timeout, garbled reply, stall → retry / switch channel / don't resend / hand to a person.
  Re-routing to the next channel happens only when the provider confirms **nothing was sent**; if the message already
  went out, it is never sent again (one message, exactly). Say it precisely like that.
* **0** conflicting contacts in the independent audit of every contact
* Routing decision **well under 100 ms** (typically ~25–30 ms on the demo); live runs never call the LLM
* **345** automated tests + 3 real-browser end-to-end tests
* Live monitor: watches a pool of **15** customers, only inside **08:00–19:00**; alerts the manager on every recovered fault
* Data model: **events per account (loan), safety per customer (person)**; one journey at a time per customer

**Do NOT claim:**
* Real messages sent to customers (channel agents are stubs; real email/voice exist behind switches for testing only)
* A live connection to the bank's systems or delivery webhooks (not built yet — say "next")
* Agents creating events (they don't; events come from lender data and the monitor's schedule)
* Production users, revenue, or accuracy percentages

---

## 7. Design system (pick per the owner's answer to Q3)

* **Studio (dark):** palette in section 5. Font: Inter / Segoe UI; trace pad in a monospace font.
* **Dashboard (light):** navy `#034E63`, green `#61CE70`, yellow `#FFDD64`, red `#D32F2F`, blue `#4BAEEA`,
  background `#F8F9FC`. Same fonts.
* One accent colour per slide. Generous white (or dark) space. Icons: outline style, one family.

---

## 8. Deliverables

1. The deck (format per Q2), **6–7 slides**, speaker notes on every slide.
2. A one-line description of each animation on each slide (so the owner can tweak timings).
3. List of any assumption you made, flagged clearly.
