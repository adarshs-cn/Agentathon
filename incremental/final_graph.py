"""FINAL supervisor graph: 15 nodes, the 4 stub agents are nodes inside the graph.

Two kinds of state, kept deliberately separate:
  GraphState     = scratchpad for ONE event (checkpointed by LangGraph, thread = account_id)
  BorrowerState  = the borrower's permanent file (our own table, STORE.borrower_state)
"""
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, START, END

# ------------------------------------------------------------------ policy knobs
MAX_ATTEMPTS = 3          # NO_PROGRESS retries before we call it a loop
MAX_RETRIES_OTHER = 2     # crash / malformed: one retry, then give up
PER_BORROWER_CAP = 1      # contacts per borrower per day
PER_AGENT_CAP = 10        # contacts per agent per day
AGENTS = ("reminder", "negotiation", "servicing", "legal")
KNOWN_EVENTS = {"DUE_SOON", "PAYMENT_RECEIVED", "PTP_BROKEN", "CONTACT_REQUESTED"}
REQUIRED_OUTPUT = {"account_id", "status", "outcome"}


# ------------------------------------------------------------------ the two state types
class Event(TypedDict):
    id: str
    type: str
    account_id: str
    time: str                      # "2026-11-20T09:00"


class BorrowerState(TypedDict):
    # --- facts, read-only, come from D1/D2/D4/D6
    account_id: str
    dpd: int
    legal_flag: bool
    # --- supervisor-owned record, read/write (our borrower_state table)
    owner: Optional[str]           # active owner agent, None = nobody
    last_contact: Optional[str]    # time of the last contact
    commitments: list              # open promises to pay
    status: str                    # ACTIVE | NEEDS_REVIEW | QUARANTINED


class GraphState(TypedDict, total=False):
    event: Event                   # input: what just happened
    borrower: BorrowerState        # a COPY of the borrower's file, loaded for this run
    guard: dict                    # guardrail verdict
    decision: dict                 # routing decision {agent, reason, rule}
    attempt: int                   # how many times the agent has been called
    result: Optional[dict]         # what the agent returned
    fault: Optional[dict]          # {type, detail} when something went wrong
    sent: bool                     # monitor: does contact_log show a send today?
    recovery: Optional[dict]       # monitor's verdict {action, reason}
    outcome: Optional[dict]        # final answer for this event


# ------------------------------------------------------------------ the durable stores
PROFILE = {   # D1/D2/D4/D6 (read-only)
    "B1": (5, False), "B2": (12, False), "B3": (20, False), "B4": (45, False),
    "B5": (60, False), "B6": (8, False), "B7": (95, True), "B8": (3, False),
    "B9": (33, False), "B10": (15, False),
}


class Stores:
    def __init__(self):
        self.profile = {a: {"dpd": d, "legal_flag": f} for a, (d, f) in PROFILE.items()}
        self.borrower_state = {a: {"owner": None, "last_contact": None,
                                   "commitments": [], "status": "ACTIVE"} for a in PROFILE}
        self.contact_log = []      # {key, account_id, agent, time}
        self.decision_log = []     # {event_id, account_id, node, text}
        self.events_done = {}      # event_id -> outcome


STORE = Stores()


def reset_store():
    STORE.__init__()


def log(state, node, text):
    ev = state["event"]
    STORE.decision_log.append({"event_id": ev.get("id"), "account_id": ev.get("account_id"),
                               "node": node, "text": text})


def contacts_today(acc, date):
    return [r for r in STORE.contact_log if r["account_id"] == acc and r["time"][:10] == date]


def agent_count(agent, date):
    return sum(1 for r in STORE.contact_log if r["agent"] == agent and r["time"][:10] == date)


# ------------------------------------------------------------------ fault injector + stub agents
class AgentCrash(Exception): ...
class AgentTimeout(Exception): ...


class FaultInjector:
    def __init__(self, script):
        self.script = script           # {(account, call_number): "FAULT_NAME"}
        self.calls = {}                # how many times each account has reached an agent

    def next_fault(self, acc):
        self.calls[acc] = self.calls.get(acc, 0) + 1
        return self.script.get((acc, self.calls[acc]))


class StubAgent:
    def __init__(self, name, injector):
        self.name, self.injector = name, injector

    def run(self, acc, send):
        fault = self.injector.next_fault(acc)
        if fault == "CRASH_BEFORE_SEND": raise AgentCrash("agent died before sending")
        if fault == "TIMEOUT":           raise AgentTimeout("agent never answered")
        if fault == "MALFORMED":         return {"oops": "garbage"}
        if fault == "LOOP":              return {"account_id": acc, "status": "IN_PROGRESS"}
        send(acc)
        if fault == "CRASH_AFTER_SEND":  raise AgentCrash("agent died after sending")
        return {"account_id": acc, "status": "DONE", "outcome": "CONTACTED"}


AGENT_OBJS = {}


def setup_agents(injector):
    for n in AGENTS:
        AGENT_OBJS[n] = StubAgent(n, injector)


def make_send(acc, agent, ev):
    """The supervisor hands this to the agent. It writes the contact_log row, then 'delivers'."""
    def send(_acc):
        key = f"{acc}|{ev['time'][:10]}|{agent}"
        if any(r["key"] == key for r in STORE.contact_log):
            return "DUPLICATE_SUPPRESSED"          # idempotency: replay cannot double-send
        STORE.contact_log.append({"key": key, "account_id": acc, "agent": agent, "time": ev["time"]})
        return "SENT"
    return send


# ------------------------------------------------------------------ NODES
def validate_event(state: GraphState) -> dict:
    ev = state["event"]
    reset = {"guard": None, "decision": None, "attempt": 0, "result": None,
             "fault": None, "sent": False, "recovery": None, "outcome": None}
    missing = [k for k in ("id", "type", "account_id", "time") if not ev.get(k)]
    if missing:
        why = f"event is missing {missing}"
    elif ev["type"] not in KNOWN_EVENTS:
        why = f"unknown event type {ev['type']}"
    elif ev["account_id"] not in STORE.profile:
        why = f"unknown account {ev['account_id']}"
    else:
        log(state, "validate_event", "event is well-formed, scratch fields reset")
        return reset
    log(state, "validate_event", f"REJECTED: {why}")
    return {**reset, "outcome": {"status": "REJECTED", "reason": why}}


def load_borrower(state: GraphState) -> dict:
    acc = state["event"]["account_id"]
    rec = STORE.borrower_state[acc]
    b = {"account_id": acc, **STORE.profile[acc],
         "owner": rec["owner"], "last_contact": rec["last_contact"],
         "commitments": list(rec["commitments"]), "status": rec["status"]}
    log(state, "load_borrower", f"loaded {acc}: dpd={b['dpd']} owner={b['owner']} status={b['status']}")
    return {"borrower": b}


def guardrails(state: GraphState) -> dict:
    b, ev = state["borrower"], state["event"]
    date = ev["time"][:10]
    if b["status"] != "ACTIVE":
        g = {"ok": False, "rule": "STATUS", "reason": f"borrower is {b['status']}, automation paused"}
    elif b["owner"]:
        g = {"ok": False, "rule": "OWNER_LOCK", "reason": f"{b['owner']} is already the active owner"}
    elif len(contacts_today(b["account_id"], date)) >= PER_BORROWER_CAP:
        g = {"ok": False, "rule": "DAILY_CAP", "reason": "already contacted today (1/1)"}
    else:
        g = {"ok": True, "rule": "NONE", "reason": "no owner, not contacted today, status ACTIVE"}
    log(state, "guardrails", ("ALLOWED: " if g["ok"] else "BLOCKED: ") + g["reason"])
    out = {"guard": g}
    if not g["ok"]:
        out["outcome"] = {"status": "BLOCKED", "reason": g["reason"]}
    return out


def route(state: GraphState) -> dict:
    b, ev = state["borrower"], state["event"]
    date = ev["time"][:10]
    if b["legal_flag"]:
        agent, why, rule = "legal", "legal flag is set", 1
    elif ev["type"] == "PAYMENT_RECEIVED":
        agent, why, rule = "servicing", "payment received", 2
    elif ev["type"] == "PTP_BROKEN":
        agent, why, rule = "negotiation", "promise to pay was broken", 3
    elif b["commitments"]:
        agent, why, rule = None, f"open promise to pay ({b['commitments'][0]['due']}), do not contact", 4
    elif b["dpd"] >= 90:
        agent, why, rule = "legal", f"DPD {b['dpd']} is 90 or more", 5
    elif b["dpd"] >= 30:
        agent, why, rule = "negotiation", f"DPD {b['dpd']} is between 30 and 89", 6
    else:
        agent, why, rule = "reminder", f"DPD {b['dpd']} is below 30", 7
    if agent and agent_count(agent, date) >= PER_AGENT_CAP:
        agent, why, rule = None, f"{agent} agent daily budget used up", 8
    log(state, "route", f"rule {rule}: {agent or 'NO AGENT'} because {why}")
    out = {"decision": {"agent": agent, "reason": why, "rule": rule}}
    if agent is None:
        out["outcome"] = {"status": "SUPPRESSED", "reason": why}
    return out


def assign(state: GraphState) -> dict:
    acc, agent = state["borrower"]["account_id"], state["decision"]["agent"]
    STORE.borrower_state[acc]["owner"] = agent                  # take the lock (durable)
    log(state, "assign", f"owner lock taken: {agent} owns {acc}")
    return {"borrower": {**state["borrower"], "owner": agent}, "attempt": 0}


def make_agent_node(name):
    def agent_node(state: GraphState) -> dict:
        ev, acc = state["event"], state["borrower"]["account_id"]
        attempt = state.get("attempt", 0) + 1
        try:
            out = AGENT_OBJS[name].run(acc, send=make_send(acc, name, ev))
            log(state, name, f"attempt {attempt}: agent returned {out}")
            return {"attempt": attempt, "result": out, "fault": None}
        except AgentCrash as e:
            log(state, name, f"attempt {attempt}: agent CRASHED ({e})")
            return {"attempt": attempt, "result": None, "fault": {"type": "CRASH", "detail": str(e)}}
        except AgentTimeout as e:
            log(state, name, f"attempt {attempt}: agent TIMED OUT ({e})")
            return {"attempt": attempt, "result": None, "fault": {"type": "TIMEOUT", "detail": str(e)}}
    agent_node.__name__ = name
    return agent_node


def validate_output(state: GraphState) -> dict:
    if state.get("fault"):                       # agent node already reported an exception
        log(state, "validate_output", f"fault already reported: {state['fault']['type']}")
        return {}
    res = state.get("result")
    keys = set(res) if isinstance(res, dict) else set()
    if isinstance(res, dict) and res.get("status") == "IN_PROGRESS":
        f = {"type": "NO_PROGRESS", "detail": f"still IN_PROGRESS after attempt {state['attempt']}"}
    elif not REQUIRED_OUTPUT <= keys or res.get("status") != "DONE":
        f = {"type": "MALFORMED", "detail": f"got keys {sorted(keys)}, expected {sorted(REQUIRED_OUTPUT)}"}
    else:
        log(state, "validate_output", "output has the right shape")
        return {"fault": None}
    log(state, "validate_output", f"FAULT {f['type']}: {f['detail']}")
    return {"fault": f}


def monitor(state: GraphState) -> dict:
    ev, acc = state["event"], state["borrower"]["account_id"]
    fault, n = state["fault"], state["attempt"]
    sent = len(contacts_today(acc, ev["time"][:10])) > 0         # ask the contact_log, not the agent
    t = fault["type"]
    if sent:
        action = "RESTART_SKIP_CURRENT"
        why = f"{t}, but contact_log already has today's send: do not call the agent again"
    elif t == "CRASH":
        action, why = ("RESUME", "crash before anything was sent: safe to retry") if n < MAX_RETRIES_OTHER \
            else ("REROUTE", "crashed again: stop retrying")
    elif t == "MALFORMED":
        action, why = ("RESUME", "bad output, nothing sent: retry once") if n < MAX_RETRIES_OTHER \
            else ("REROUTE", "second bad output: stop retrying")
    elif t == "NO_PROGRESS":
        action, why = ("RESUME", f"no progress yet (attempt {n} of {MAX_ATTEMPTS})") if n < MAX_ATTEMPTS \
            else ("REROUTE", f"no progress after {n} attempts: this is a loop")
    else:                                                          # catch-all: unscripted fault
        action, why = "QUARANTINE", f"unscripted fault {t}: no rule, hold borrower for human review"
    log(state, "monitor", f"{t} -> {action}: {why}")
    return {"sent": sent, "recovery": {"action": action, "reason": why}}


def recover(state: GraphState) -> dict:
    acc, action = state["borrower"]["account_id"], state["recovery"]["action"]
    if action == "RESUME":
        log(state, "recover", "RESUME: go back to the same agent node")
        return {"fault": None}
    if action == "RESTART_SKIP_CURRENT":
        log(state, "recover", "SKIP: treat the already-logged send as the result")
        return {"fault": None, "result": {"account_id": acc, "status": "DONE",
                                          "outcome": "CONTACTED", "via": "recovery"}}
    log(state, "recover", f"{action}: give up on automation for this borrower")
    return {"fault": None, "result": {"account_id": acc, "status": "ESCALATED", "outcome": action}}


def commit(state: GraphState) -> dict:
    acc, ev, res = state["borrower"]["account_id"], state["event"], state["result"]
    b = dict(state["borrower"])
    if res["status"] == "DONE":
        b["last_contact"] = ev["time"]
        log(state, "commit", f"contact recorded, last_contact={ev['time']}")
    else:
        b["status"] = "NEEDS_REVIEW" if res["outcome"] == "REROUTE" else "QUARANTINED"
        log(state, "commit", f"no contact; status set to {b['status']}")
    STORE.borrower_state[acc].update(last_contact=b["last_contact"], status=b["status"])
    return {"borrower": b}


def release(state: GraphState) -> dict:
    acc = state["borrower"]["account_id"]
    STORE.borrower_state[acc]["owner"] = None
    log(state, "release", "owner lock released")
    return {"borrower": {**state["borrower"], "owner": None}}


def close_event(state: GraphState) -> dict:
    ev = state["event"]
    out = state.get("outcome")
    if not out:
        res = state["result"]
        out = {"status": "CONTACTED" if res["status"] == "DONE" else "ESCALATED",
               "agent": state["decision"]["agent"], "attempts": state["attempt"]}
    STORE.events_done[ev["id"]] = out["status"]
    log(state, "close_event", f"event {ev['id']} closed as {out['status']}")
    return {"outcome": out}


# ------------------------------------------------------------------ edge decisions
def after_validate_event(s): return "close_event" if s.get("outcome") else "load_borrower"
def after_guardrails(s):     return "route" if s["guard"]["ok"] else "close_event"
def after_route(s):          return "assign" if s["decision"]["agent"] else "close_event"
def after_assign(s):         return s["decision"]["agent"]
def after_validate_output(s): return "monitor" if s.get("fault") else "commit"
def after_recover(s):
    return s["decision"]["agent"] if s["recovery"]["action"] == "RESUME" else "commit"


def build(checkpointer):
    g = StateGraph(GraphState)
    plain = {"validate_event": validate_event, "load_borrower": load_borrower,
             "guardrails": guardrails, "route": route, "assign": assign,
             "validate_output": validate_output, "monitor": monitor, "recover": recover,
             "commit": commit, "release": release, "close_event": close_event}
    for name, fn in plain.items():
        g.add_node(name, fn)
    for n in AGENTS:
        g.add_node(n, make_agent_node(n))

    g.add_edge(START, "validate_event")
    g.add_conditional_edges("validate_event", after_validate_event, ["load_borrower", "close_event"])
    g.add_edge("load_borrower", "guardrails")
    g.add_conditional_edges("guardrails", after_guardrails, ["route", "close_event"])
    g.add_conditional_edges("route", after_route, ["assign", "close_event"])
    g.add_conditional_edges("assign", after_assign, list(AGENTS))
    for n in AGENTS:
        g.add_edge(n, "validate_output")
    g.add_conditional_edges("validate_output", after_validate_output, ["monitor", "commit"])
    g.add_edge("monitor", "recover")
    g.add_conditional_edges("recover", after_recover, list(AGENTS) + ["commit"])
    g.add_edge("commit", "release")
    g.add_edge("release", "close_event")
    g.add_edge("close_event", END)
    return g.compile(checkpointer=checkpointer)
