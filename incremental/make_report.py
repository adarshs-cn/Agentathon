"""Runs 12 real scenarios through final_graph.py, captures every node's update and the
state after it, and writes ../supervisor_graph_explained.html."""
import copy, html, inspect, json, os, sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
import final_graph as fg

OUT = os.path.join(os.path.dirname(__file__), "..", "supervisor_graph_explained.html")

# ------------------------------------------------------------------ 1. run the scenarios
FAULTS = {("B2", 1): "CRASH_AFTER_SEND", ("B3", 1): "CRASH_BEFORE_SEND",
          ("B4", 1): "LOOP", ("B4", 2): "LOOP", ("B4", 3): "LOOP",
          ("B5", 1): "MALFORMED", ("B7", 1): "TIMEOUT"}

D = "2026-11-20T"
SCENARIOS = [
    ("B1", "e1", "DUE_SOON", "09:00", "Happy path",
     "Nothing goes wrong. DPD is 5, so Reminder is chosen, contacts the borrower once, and the lock is released."),
    ("B1", "e2", "CONTACT_REQUESTED", "11:00", "Same borrower, second event",
     "A collector clicks 'contact now' two hours later. The graph state still holds the previous run, so validate_event resets it. Guardrails then block the contact: B1 was already contacted today."),
    ("B2", "e3", "DUE_SOON", "09:05", "Crash AFTER send",
     "The Reminder agent sends the message, then dies. The monitor asks the contact_log, sees the send, and does NOT call the agent again. This is the case that causes double contacts if handled wrongly."),
    ("B3", "e4", "DUE_SOON", "09:10", "Crash BEFORE send",
     "The agent dies before sending anything. The contact_log is empty for B3, so retrying is safe. The graph jumps back to the agent node (not to the start) and the second call succeeds."),
    ("B4", "e5", "DUE_SOON", "09:15", "Loop (never finishes)",
     "Negotiation answers 'IN_PROGRESS' on every call. After 3 attempts the monitor decides this is a loop, stops it, and flags the borrower for human review. Nothing is sent."),
    ("B4", "e6", "CONTACT_REQUESTED", "10:00", "After a loop: borrower is paused",
     "A later event for B4. Because the previous run set status = NEEDS_REVIEW in the borrower's file, guardrails stop automation. This shows the BorrowerState surviving between runs."),
    ("B5", "e7", "DUE_SOON", "09:20", "Malformed output, then retry",
     "Negotiation returns garbage instead of the expected shape. validate_output catches it, the monitor retries once, and the second answer is fine."),
    ("B6", "e8", "PAYMENT_RECEIVED", "14:00", "Servicing agent",
     "A payment event routes to Servicing, the third stub agent node in the graph."),
    ("B7", "e9", "DUE_SOON", "09:25", "Timeout (no rule for it)",
     "B7 has a legal flag, so Legal is chosen. The agent never answers. There is no scripted rule for TIMEOUT, so the monitor's catch-all quarantines the borrower. This is where the LLM would be consulted."),
    ("B8", "e10", "DUE_SOON", "09:30", "Owner lock",
     "B8's file already says negotiation is the active owner (mid-conversation). Guardrails refuse a second agent."),
    ("B9", "e11", "DUE_SOON", "09:35", "Open promise to pay",
     "B9 has an open promise to pay. Guardrails pass, but routing decides nobody should contact them."),
    ("B99", "e12", "DUE_SOON", "09:40", "Bad event",
     "An event for an account that does not exist. validate_event rejects it and the run ends cleanly."),
]


def snapshot(acc):
    if acc not in fg.STORE.borrower_state:
        return None, []
    return (copy.deepcopy(fg.STORE.borrower_state[acc]),
            [r["key"] for r in fg.STORE.contact_log if r["account_id"] == acc])


def run_all():
    fg.reset_store()
    fg.STORE.borrower_state["B8"]["owner"] = "negotiation"
    fg.STORE.borrower_state["B9"]["commitments"] = [{"type": "PTP", "due": "2026-11-22", "amount": 5000}]
    start_state = copy.deepcopy(fg.STORE.borrower_state)
    fg.setup_agents(fg.FaultInjector(FAULTS))
    graph = fg.build(SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False)))
    out = []
    for i, (acc, eid, typ, hhmm, short, why) in enumerate(SCENARIOS, 1):
        ev = {"id": eid, "type": typ, "account_id": acc, "time": D + hhmm}
        cfg = {"configurable": {"thread_id": acc}}
        steps, last_state, log_len = [], {"event": ev}, len(fg.STORE.decision_log)
        for mode, chunk in graph.stream({"event": ev}, cfg, stream_mode=["updates", "values"]):
            if mode == "updates":
                node, upd = next(iter(chunk.items()))
                b, c = snapshot(acc)
                new_log = [f"{r['node']}: {r['text']}" for r in fg.STORE.decision_log[log_len:]]
                log_len = len(fg.STORE.decision_log)
                steps.append({"n": len(steps) + 1, "node": node, "update": upd,
                              "state": copy.deepcopy(last_state), "store": b,
                              "contacts": c, "log": new_log})
            else:
                last_state = copy.deepcopy(chunk)
                if steps:
                    steps[-1]["state"] = last_state
        hist = len(list(graph.get_state_history(cfg)))
        out.append({"i": i, "short": short, "why": why, "event": ev, "steps": steps,
                    "outcome": last_state.get("outcome"), "checkpoints": hist})
    return out, start_state


SCN, START_STATE = run_all()

# ------------------------------------------------------------------ 2. the SVG graph
SPINE = 344
NODES = {  # name: (cx, cy, w, class)
    "validate_event": (SPINE, 80, 190, "sup"), "load_borrower": (SPINE, 150, 190, "sup"),
    "guardrails": (SPINE, 220, 190, "sup"), "route": (SPINE, 290, 190, "sup"),
    "assign": (SPINE, 360, 190, "sup"),
    "reminder": (125, 450, 132, "agt"), "negotiation": (271, 450, 132, "agt"),
    "servicing": (417, 450, 132, "agt"), "legal": (563, 450, 132, "agt"),
    "validate_output": (SPINE, 540, 190, "sup"),
    "monitor": (745, 600, 150, "flt"), "recover": (745, 670, 150, "flt"),
    "commit": (SPINE, 720, 190, "sup"), "release": (SPINE, 790, 190, "sup"),
    "close_event": (SPINE, 860, 190, "sup"),
}


def svg(prefix):
    p = []
    a = p.append
    a('<svg viewBox="0 0 880 950" role="img" aria-label="The supervisor LangGraph">')
    a('<defs><marker id="%s-ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
      'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8a8a82"/></marker></defs>' % prefix)

    def edge(d, dashed=False):
        a('<path class="edge%s" d="%s" marker-end="url(#%s-ah)"/>' % (" dash" if dashed else "", d, prefix))

    def label(x, y, t, anchor="start", rot=None):
        tr = ' transform="rotate(%d %d %d)"' % (rot, x, y) if rot else ""
        a('<text class="elabel" x="%d" y="%d" text-anchor="%s"%s>%s</text>' % (x, y, anchor, tr, t))

    # edges first so boxes sit on top
    a('<circle class="se" cx="%d" cy="24" r="14"/><text class="elabel" x="%d" y="28" text-anchor="middle">start</text>' % (SPINE, SPINE))
    edge("M%d,38 L%d,60" % (SPINE, SPINE))
    edge("M%d,100 L%d,130" % (SPINE, SPINE)); label(SPINE + 8, 120, "valid")
    edge("M%d,170 L%d,200" % (SPINE, SPINE))
    edge("M%d,240 L%d,270" % (SPINE, SPINE)); label(SPINE + 8, 260, "allowed")
    edge("M%d,310 L%d,340" % (SPINE, SPINE)); label(SPINE + 8, 330, "agent chosen")
    for n in fg.AGENTS:
        cx = NODES[n][0]
        edge("M%d,380 L%d,430" % (SPINE, cx))
        edge("M%d,470 L%d,520" % (cx, SPINE))
    label(SPINE + 105, 398, "which agent?")
    edge("M%d,540 H745 V580" % (SPINE + 95)); label(560, 532, "fault found", "middle")
    edge("M745,620 V650")
    edge("M%d,560 V700" % SPINE); label(SPINE + 8, 640, "ok")
    edge("M820,670 H852 V450 H629", dashed=True); label(866, 560, "RESUME: same agent again", "middle", -90)
    edge("M745,690 V720 H%d" % (SPINE + 95), dashed=True); label(600, 712, "skip / escalate", "middle")
    edge("M%d,740 L%d,770" % (SPINE, SPINE))
    edge("M%d,810 L%d,840" % (SPINE, SPINE))
    edge("M%d,880 L%d,911" % (SPINE, SPINE))
    a('<circle class="se" cx="%d" cy="925" r="14"/><text class="elabel" x="%d" y="929" text-anchor="middle">end</text>' % (SPINE, SPINE))
    # early-exit rail on the left
    edge("M%d,80 H22 V860 H%d" % (SPINE - 95, SPINE - 95), dashed=True)
    a('<path class="edge dash" d="M%d,220 H22"/><path class="edge dash" d="M%d,290 H22"/>' % (SPINE - 95, SPINE - 95))
    label(30, 72, "invalid event"); label(30, 212, "blocked"); label(30, 282, "suppressed (no agent)")
    for name, (cx, cy, w, cls) in NODES.items():
        a('<g class="node %s" id="%s-n-%s"><rect x="%d" y="%d" width="%d" height="40" rx="8"/>'
          '<text x="%d" y="%d" text-anchor="middle">%s</text></g>'
          % (cls, prefix, name, cx - w // 2, cy - 20, w, cx, cy + 5, name))
    a("</svg>")
    return "".join(a_ for a_ in p)


# ------------------------------------------------------------------ 3. documentation tables
GRAPH_FIELDS = [
    ("event", "Event", "the driver (input)", "The event being handled right now.", '{"id":"e1","type":"DUE_SOON","account_id":"B1","time":"2026-11-20T09:00"}'),
    ("borrower", "BorrowerState", "load_borrower; then assign, commit, release update the copy", "A working COPY of the borrower's file, loaded at the start of the run.", "{account_id, dpd, legal_flag, owner, last_contact, commitments, status}"),
    ("guard", "dict | None", "guardrails", "The guardrail verdict: allowed or blocked, and which rule decided.", '{"ok": true, "rule": "NONE", "reason": "..."}'),
    ("decision", "dict | None", "route", "Which agent was chosen, the rule number, and the reason.", '{"agent":"reminder","reason":"DPD 5 is below 30","rule":7}'),
    ("attempt", "int", "assign sets 0; each agent node adds 1", "How many times the agent has been called in this run. Used to stop loops.", "2"),
    ("result", "dict | None", "agent nodes; recover may replace it", "What the agent returned (or what recovery substituted).", '{"account_id":"B1","status":"DONE","outcome":"CONTACTED"}'),
    ("fault", "dict | None", "agent nodes (exceptions), validate_output; recover clears it", "What went wrong: CRASH, TIMEOUT, MALFORMED or NO_PROGRESS.", '{"type":"CRASH","detail":"agent died after sending"}'),
    ("sent", "bool", "monitor", "Does the contact_log show a send today for this borrower? Decides retry vs skip.", "true"),
    ("recovery", "dict | None", "monitor", "The recovery action chosen and why.", '{"action":"RESTART_SKIP_CURRENT","reason":"..."}'),
    ("outcome", "dict | None", "validate_event, guardrails, route (early exits); close_event", "The final answer for this event: CONTACTED, BLOCKED, SUPPRESSED, REJECTED or ESCALATED.", '{"status":"BLOCKED","reason":"already contacted today (1/1)"}'),
]
BORROWER_FIELDS = [
    ("account_id", "str", "key from D1/D2/D4/D6", "read-only", "Which borrower.", "B1"),
    ("dpd", "int", "D tables", "read-only", "Days past due. Drives routing.", "45"),
    ("legal_flag", "bool", "D tables", "read-only", "If true, only Legal may act.", "false"),
    ("owner", "str | None", "our borrower_state table", "assign sets it, release clears it", "The one agent allowed to act right now. This is the lock.", '"reminder" or null'),
    ("last_contact", "str | None", "our borrower_state table", "commit", "When the borrower was last contacted. Shown on the listing page.", '"2026-11-20T09:00"'),
    ("commitments", "list", "our borrower_state table", "supervisor (seeded by hand in this prototype)", "Open promises to pay. While one is open, nobody contacts the borrower.", '[{"type":"PTP","due":"2026-11-22","amount":5000}]'),
    ("status", "str", "our borrower_state table", "commit", "ACTIVE, NEEDS_REVIEW or QUARANTINED. Anything but ACTIVE pauses automation.", '"ACTIVE"'),
]
COMPARE = [
    ("What it is", "Scratchpad for handling ONE event", "The borrower's permanent file"),
    ("Scope", "One event, one run of the graph", "One borrower, forever"),
    ("Where it lives", "LangGraph checkpoint (SQLite here, Postgres later), thread_id = account_id", "Our own table, <code>borrower_state</code>"),
    ("Who writes it", "Every node returns a partial update; LangGraph merges it", "Only three nodes: assign, commit, release"),
    ("Do agents touch it?", "They return a result into it", "Never. Agents only call send()"),
    ("Used for", "Passing the decision from node to node, retries, resuming after a crash", "Locks, last contact, promises, the account listing page, audits"),
    ("If the process dies", "Reloaded from the last checkpoint: resume at the next node", "Still there: it is a normal table"),
    ("Contains a BorrowerState?", "Yes: <code>borrower</code> is a copy of it", "No"),
]
EDGES = [
    ("start", "always", "validate_event"),
    ("validate_event", "outcome already set (bad event)", "close_event"),
    ("validate_event", "otherwise", "load_borrower"),
    ("load_borrower", "always", "guardrails"),
    ("guardrails", "guard.ok is false", "close_event"),
    ("guardrails", "guard.ok is true", "route"),
    ("route", "decision.agent is None", "close_event"),
    ("route", "an agent was chosen", "assign"),
    ("assign", "decision.agent", "reminder | negotiation | servicing | legal"),
    ("each agent node", "always", "validate_output"),
    ("validate_output", "fault is set", "monitor"),
    ("validate_output", "no fault", "commit"),
    ("monitor", "always", "recover"),
    ("recover", "recovery.action is RESUME", "the same agent node again"),
    ("recover", "anything else", "commit"),
    ("commit", "always", "release"),
    ("release", "always", "close_event"),
    ("close_event", "always", "end"),
]

NODE_DOC = [
    dict(name="validate_event", kind="sup", fn=fg.validate_event,
         title="Gatekeeper and reset",
         plain="Two jobs. First, clear the scratch fields left over from this account's previous event, because LangGraph keeps one saved state per account and we do not want yesterday's fault leaking into today's run. Second, check the event is well-formed and the account exists. A bad event is rejected here and the run ends cleanly.",
         reads="event; the account list", gw="guard, decision, attempt, result, fault, sent, recovery, outcome (all reset); outcome if rejected", sw="decision_log", nxt="load_borrower, or close_event if rejected"),
    dict(name="load_borrower", kind="sup", fn=fg.load_borrower,
         title="Fetch the borrower's file",
         plain="Reads the borrower's facts from the data tables (DPD, legal flag) and the supervisor's own record (owner, last contact, promises, status), and puts a copy into the graph state as <code>borrower</code>. Nothing is changed.",
         reads="event.account_id; borrower_state; the D tables", gw="borrower", sw="decision_log", nxt="guardrails"),
    dict(name="guardrails", kind="sup", fn=fg.guardrails,
         title="Hard yes/no safety checks",
         plain="No AI, only rules, checked in this order: (1) is the borrower paused (status not ACTIVE)? (2) is another agent already the owner? (3) was the borrower already contacted today? If any fails, the run is blocked and a reason is recorded. This is where 'zero conflicting contacts' is enforced.",
         reads="borrower, event.time, contact_log", gw="guard; outcome if blocked", sw="decision_log", nxt="route, or close_event if blocked"),
    dict(name="route", kind="sup", fn=fg.route,
         title="Pick exactly one agent",
         plain="Fixed rules, first match wins: legal flag, payment received, promise broken, open promise (nobody), DPD 90+, DPD 30 to 89, otherwise Reminder. It also checks the chosen agent's daily budget. The agent and the reason are stored. It is pure rules so it takes microseconds, well inside the 100 ms limit.",
         reads="borrower, event.type, contact_log (for the agent budget)", gw="decision; outcome if no agent", sw="decision_log", nxt="assign, or close_event if no agent"),
    dict(name="assign", kind="sup", fn=fg.assign,
         title="Take the owner lock",
         plain="Writes the chosen agent as the borrower's owner in the durable table before the agent is called. From now until release, nobody else can act on this borrower. Also resets the attempt counter to 0.",
         reads="decision.agent", gw="borrower.owner, attempt = 0", sw="borrower_state.owner (WRITE), decision_log", nxt="the chosen agent node"),
    dict(name="agents", kind="agt", fn=fg.make_agent_node, extra=[fg.StubAgent.run],
         title="The four stub agents: reminder, negotiation, servicing, legal",
         plain="Four nodes built from one factory, one per stub agent. Each calls its stub, handing it a <code>send()</code> function that writes the contact_log row and then delivers. The stub may raise an exception (crash, timeout) or return something odd (garbage, 'in progress'). A LangGraph node that raises would abort the whole run, so the node catches the exception and stores it in the state as <code>fault</code>. Which fault happens is decided by the fault injector, which the supervisor knows nothing about.",
         reads="borrower, attempt", gw="attempt (+1), result, fault", sw="contact_log (via send), decision_log", nxt="validate_output"),
    dict(name="validate_output", kind="sup", fn=fg.validate_output,
         title="Check what the agent returned",
         plain="If the agent node already reported an exception, it keeps that fault. Otherwise it checks the shape: 'IN_PROGRESS' means NO_PROGRESS (possible loop), missing fields or a status other than DONE means MALFORMED. A good result clears the fault. When the agent already reported an exception it returns nothing, which is why such steps show 'no change'.",
         reads="result, fault, attempt", gw="fault", sw="decision_log", nxt="monitor if there is a fault, else commit"),
    dict(name="monitor", kind="flt", fn=fg.monitor,
         title="Diagnose the fault",
         plain="The key move is that it asks the contact_log, not the agent, whether a message went out. Sent already: skip (never resend). Not sent: retry while the attempt limit allows, then reroute. A fault with no rule (such as TIMEOUT) falls to the catch-all, which quarantines. In the full design that last branch consults the LLM, which may only choose from a safe menu. It is not wired in here.",
         reads="fault, attempt, contact_log", gw="sent, recovery", sw="decision_log", nxt="recover"),
    dict(name="recover", kind="flt", fn=fg.recover,
         title="Apply the recovery",
         plain="Carries out what the monitor decided. RESUME clears the fault and the graph jumps back to the same agent node, not to the start, so guardrails and routing are not repeated. SKIP builds a DONE result from the already-logged send. REROUTE or QUARANTINE builds an ESCALATED result. It never writes to the event bus.",
         reads="recovery", gw="fault (cleared), result (for skip and escalate)", sw="decision_log", nxt="the agent node (RESUME), else commit"),
    dict(name="commit", kind="sup", fn=fg.commit,
         title="Write the result to the borrower's file",
         plain="For a successful contact it records last_contact. For an escalation it sets the status to NEEDS_REVIEW or QUARANTINED and records no contact. This is one of only three nodes that write to the borrower's file.",
         reads="result, event.time", gw="borrower", sw="borrower_state.last_contact / status (WRITE), decision_log", nxt="release"),
    dict(name="release", kind="sup", fn=fg.release,
         title="Release the owner lock",
         plain="Clears the owner so the next event for this borrower can proceed.",
         reads="borrower", gw="borrower.owner = None", sw="borrower_state.owner (WRITE), decision_log", nxt="close_event"),
    dict(name="close_event", kind="sup", fn=fg.close_event,
         title="Close the event and state the outcome",
         plain="Every path ends here, including blocked, suppressed and rejected ones. It writes the final outcome and marks the event done, so the event is never processed twice and every event has a recorded ending.",
         reads="outcome or result", gw="outcome", sw="events_done, decision_log", nxt="end"),
]
NODE_ONE = {d["name"]: d["title"] for d in NODE_DOC}
for a_ in fg.AGENTS:
    NODE_ONE[a_] = "Stub agent node: " + a_

# ------------------------------------------------------------------ 4. end of day
def end_of_day():
    rows = []
    for acc, rec in fg.STORE.borrower_state.items():
        n = len([r for r in fg.STORE.contact_log if r["account_id"] == acc])
        rows.append((acc, rec["owner"], rec["last_contact"], rec["status"], n))
    worst = max([r[4] for r in rows] or [0])
    return rows, worst


EOD, WORST = end_of_day()


# ------------------------------------------------------------------ 5. HTML helpers
def e(x): return html.escape(str(x))


def table(head, rows, raw_cols=()):
    h = "<tr>" + "".join("<th>%s</th>" % e(c) for c in head) + "</tr>"
    b = ""
    for r in rows:
        b += "<tr>" + "".join("<td>%s</td>" % (c if i in raw_cols else ("<code>%s</code>" % e(c) if i == 0 else e(c)))
                              for i, c in enumerate(r)) + "</tr>"
    return '<div class="tablewrap"><table>%s%s</table></div>' % (h, b)


def node_cards():
    out = []
    for d in NODE_DOC:
        src = inspect.getsource(d["fn"])
        for x in d.get("extra", []):
            src += "\n" + inspect.getsource(x)
        out.append(
            '<div class="ncard %s"><h3><code>%s</code> <span class="tag %s">%s</span></h3><p class="ttl">%s</p><p>%s</p>'
            '<table class="mini"><tr><th>Reads</th><td>%s</td></tr><tr><th>Writes to GraphState</th><td>%s</td></tr>'
            '<tr><th>Writes to stores</th><td>%s</td></tr><tr><th>Goes next to</th><td>%s</td></tr></table>'
            '<details><summary>Show the real code</summary><pre>%s</pre></details></div>'
            % (d["kind"], d["name"], d["kind"], {"sup": "supervisor node", "agt": "stub agent node", "flt": "fault handling"}[d["kind"]],
               e(d["title"]), d["plain"], e(d["reads"]), e(d["gw"]), e(d["sw"]), e(d["nxt"]), e(src)))
    return "".join(out)


data = {"scenarios": SCN, "one": NODE_ONE}
data_json = json.dumps(data, default=str).replace("</", "<\\/")

eod_rows = table(["account", "owner", "last_contact", "status", "contacts today"],
                 [(a, o if o else "None", lc if lc else "None", s, n) for a, o, lc, s, n in EOD])
log_rows = table(["contact_log key", "agent", "time"],
                 [(r["key"], r["agent"], r["time"]) for r in fg.STORE.contact_log])

TEMPLATE = open(os.path.join(os.path.dirname(__file__), "report_template.html")).read()
page = (TEMPLATE
        .replace("@@SVG_OVERVIEW@@", svg("o"))
        .replace("@@SVG_WALK@@", svg("w"))
        .replace("@@GRAPH_FIELDS@@", table(["field", "type", "written by", "meaning", "example"], GRAPH_FIELDS))
        .replace("@@BORROWER_FIELDS@@", table(["field", "type", "comes from", "written by", "meaning", "example"], BORROWER_FIELDS))
        .replace("@@COMPARE@@", table(["", "GraphState", "BorrowerState"], COMPARE, raw_cols=(0, 1, 2)))
        .replace("@@EDGES@@", table(["from", "when", "goes to"], EDGES))
        .replace("@@NODES@@", node_cards())
        .replace("@@EOD@@", eod_rows)
        .replace("@@LOG@@", log_rows)
        .replace("@@WORST@@", str(WORST))
        .replace("@@NSCN@@", str(len(SCN)))
        .replace("@@DATA@@", data_json))
open(OUT, "w").write(page)
print("wrote", os.path.abspath(OUT), len(page) // 1024, "KB; worst contacts per borrower:", WORST)
for s in SCN:
    print(s["i"], s["event"]["account_id"], s["short"], "->", s["outcome"], "| steps", len(s["steps"]))
