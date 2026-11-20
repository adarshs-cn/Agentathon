"""Supervisor as a LangGraph StateGraph.
The supervisor is the only writer of shared state (Store). Graph state carries
only the per-event working data."""
from collections import deque
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from fault_injector import FaultInjector
import llm
from stub_agents import AgentCrash, AgentTimeout, build_agents

LOOP_THRESHOLD = 3
PER_BORROWER_CAP = 1
PER_AGENT_CAP = 10

EVENTS = [
    {"id": "E1", "type": "CONTACT_REQUESTED", "account_id": "B1", "dpd": "0-30"},
    {"id": "E2", "type": "CONTACT_REQUESTED", "account_id": "B2", "dpd": "0-30"},
    {"id": "E3", "type": "CONTACT_REQUESTED", "account_id": "B3", "dpd": "SMA"},
    {"id": "E4", "type": "CONTACT_REQUESTED", "account_id": "B4", "dpd": "30-60"},
    {"id": "E5", "type": "CONTACT_REQUESTED", "account_id": "B5", "dpd": "0-30"},
    {"id": "E6", "type": "CONTACT_REQUESTED", "account_id": "B6", "dpd": "60-90"},
    {"id": "E7", "type": "CONTACT_REQUESTED", "account_id": "B7", "dpd": "30-60"},
]


class Store:
    """Shared state + append-only logs (stand-in for SQLite)."""

    def __init__(self, events):
        self.events = deque(events)
        self.held = []
        self.borrowers = {
            e["account_id"]: {"status": "ACTIVE", "owner": None, "contacts_today": 0,
                              "dpd": e["dpd"]} for e in events}
        self.agents = {a: {"status": "IDLE", "current": None, "last_committed": None,
                           "contacts_today": 0}
                       for a in ("stub_reminder", "stub_negotiation")}
        self.contact_log = []
        self.trace = []
        self.timeline = []
        self.note = ""

    def send(self, account_id, agent, text):
        self.contact_log.append({"account_id": account_id, "agent": agent, "text": text})

    def sent_count(self, account_id):
        return sum(1 for c in self.contact_log if c["account_id"] == account_id)

    def log(self, account_id, decision, agent, reason):
        self.trace.append({"step": len(self.timeline), "account_id": account_id,
                           "decision": decision, "agent": agent, "reason": reason})

    def snapshot(self, node, account_id):
        self.timeline.append({
            "i": len(self.timeline), "node": node, "account_id": account_id,
            "note": self.note,
            "borrowers": {k: {"status": v["status"], "owner": v["owner"],
                              "contacts": v["contacts_today"]}
                          for k, v in self.borrowers.items()},
            "agents": {k: dict(v) for k, v in self.agents.items()},
            "contact_log": [dict(c) for c in self.contact_log],
            "queue": len(self.events), "held": len(self.held),
        })


class S(TypedDict, total=False):
    event: Optional[dict]
    agent: Optional[str]
    decision: str
    result: Optional[dict]
    fault: Optional[str]
    recovery: Optional[str]
    attempt: int


def build(events=EVENTS, injector=None):
    injector = injector or FaultInjector()
    store = Store(events)
    registry = build_agents(injector)

    def traced(name):
        def deco(fn):
            def wrapper(state):
                store.note = ""
                out = fn(state)
                ev = (out or {}).get("event", state.get("event"))
                store.snapshot(name, ev["account_id"] if ev else None)
                return out
            return wrapper
        return deco

    # ---- nodes -------------------------------------------------------
    @traced("consume_event")
    def consume_event(state):
        if not store.events:
            store.note = "Event bus is empty. Run finished."
            return {"event": None}
        ev = store.events.popleft()
        store.note = f"Took {ev['id']} ({ev['type']}) for {ev['account_id']} off the event bus."
        return {"event": ev, "agent": None, "decision": "", "result": None,
                "fault": None, "recovery": None, "attempt": 0}

    @traced("guardrails_route")
    def guardrails_route(state):
        ev = state["event"]; acc = ev["account_id"]; b = store.borrowers[acc]
        if b["status"] != "ACTIVE":
            store.log(acc, "SKIPPED", None, "borrower_not_active")
            store.note = f"{acc} is {b['status']}: skipped."
            return {"decision": "SKIPPED"}
        if b["owner"]:
            store.held.append(ev)
            store.log(acc, "QUEUED", None, "active_owner_conflict")
            store.note = f"{acc} already owned by {b['owner']}: event queued."
            return {"decision": "QUEUED"}
        if b["contacts_today"] >= PER_BORROWER_CAP:
            store.log(acc, "SKIPPED", None, "daily_contact_limit")
            store.note = f"{acc} already contacted today (cap {PER_BORROWER_CAP}): skipped. This is the conflict-prevention rule."
            return {"decision": "SKIPPED"}
        agent = "stub_reminder" if ev["dpd"] in ("SMA", "0-30") else "stub_negotiation"
        if store.agents[agent]["contacts_today"] >= PER_AGENT_CAP:
            store.log(acc, "SKIPPED", agent, "agent_budget_exhausted")
            store.note = f"{agent} budget exhausted: skipped."
            return {"decision": "SKIPPED"}
        rule = "early_bucket_first_contact" if agent == "stub_reminder" else "dpd_gt_30"
        store.log(acc, "ASSIGNED", agent, rule)
        store.note = f"Guardrails passed. Rule '{rule}' -> {agent}."
        return {"decision": "ASSIGNED", "agent": agent}

    @traced("assign")
    def assign(state):
        acc = state["event"]["account_id"]; agent = state["agent"]
        store.borrowers[acc]["owner"] = agent
        store.agents[agent].update(status="RUNNING", current=acc)
        store.note = f"Lock set: {agent} now owns {acc}. Cursor written: current_borrower = {acc}."
        return {}

    @traced("execute_agent")
    def execute_agent(state):
        acc = state["event"]["account_id"]; agent = state["agent"]
        attempt = state.get("attempt", 0) + 1
        out = {"attempt": attempt, "fault": None, "result": None}
        conflict = injector.conflicting_event(acc, attempt)
        if conflict:
            store.held.append(conflict)
            store.log(acc, "QUEUED", None, "active_owner_conflict")
        try:
            result = None
            for _ in range(LOOP_THRESHOLD):
                result = registry[agent].run(acc, attempt, store.send)
                if result.get("status") != "IN_PROGRESS":
                    break
            else:
                out["fault"] = "LOOP"
                store.note = f"{agent} made no progress after {LOOP_THRESHOLD} tries on {acc}: LOOP detected."
                return out
            out["result"] = result
            store.note = (f"Attempt {attempt}: {agent} returned a result for {acc}."
                          + (f" A second event for {acc} arrived meanwhile and was queued." if conflict else ""))
        except AgentCrash as e:
            out["fault"] = "CRASH"; store.note = f"Attempt {attempt}: CRASH. {e}"
        except AgentTimeout as e:
            out["fault"] = "TIMEOUT"; store.note = f"Attempt {attempt}: TIMEOUT. {e}"
        return out

    @traced("validate_output")
    def validate_output(state):
        r = state["result"] or {}
        ok = {"account_id", "status", "outcome"} <= set(r) and r["status"] == "DONE"
        if ok:
            store.note = "Output matches the agreed schema."
            return {"fault": None}
        store.note = f"Output failed schema validation: {r}"
        return {"fault": "MALFORMED"}

    @traced("monitor")
    def monitor(state):
        acc = state["event"]["account_id"]; agent = state["agent"]; fault = state["fault"]
        sent = store.sent_count(acc) > 0
        health = {"CRASH": "CRASHED", "LOOP": "LOOPING", "MALFORMED": "MALFORMED"}.get(fault, "UNRESPONSIVE")
        store.agents[agent]["status"] = health
        # monitor tools: check_health, get_progress, check_contact_log -> request_recovery
        if fault in ("CRASH", "MALFORMED") and sent:
            action, why = "RESTART_SKIP_CURRENT", "contact log shows borrower was already contacted"
        elif fault == "CRASH":
            action, why = "RESUME", "no contact sent yet, safe to re-run"
        elif fault == "MALFORMED" and state["attempt"] < 2:
            action, why = "RESUME", "retry once, nothing sent yet"
        elif fault == "LOOP":
            action, why = "REROUTE", "no progress: escalate to human review"
        elif fault == "MALFORMED":
            action, why = "REROUTE", "malformed twice: escalate to human review"
        else:
            # Catch-all for faults with no script. LLM may only pick from a safe menu.
            allowed = (["RESTART_SKIP_CURRENT", "QUARANTINE", "REROUTE"] if sent
                       else ["RESUME", "REROUTE", "QUARANTINE"])
            pick, note = llm.decide_recovery(fault, agent, acc, sent, allowed)
            if pick:
                action, why = pick, "unscripted fault: chosen by DeepSeek from the safe menu"
            else:
                action, why = "QUARANTINE", "unscripted fault: catch-all rule (LLM unavailable)"
            if note:
                why += f". Diagnosis: {note}"
        store.log(acc, "FAULT", agent, f"{fault}")
        store.note = (f"Monitor: health={health}, sent_before_fault={sent}. "
                      f"request_recovery({action}) because {why}.")
        return {"recovery": action}

    @traced("recover")
    def recover(state):
        acc = state["event"]["account_id"]; agent = state["agent"]; action = state["recovery"]
        if action == "RESUME":
            store.agents[agent]["status"] = "RUNNING"
            store.log(acc, "RECOVERED", agent, "RESUME")
            store.note = f"Supervisor executes RESUME: relaunch {agent} on {acc}."
            return {}
        if action == "RESTART_SKIP_CURRENT":
            store.log(acc, "RECOVERED", agent, "RESTART_SKIP_CURRENT")
            store.note = f"Supervisor executes RESTART_SKIP_CURRENT: {acc} NOT contacted again, state completed from contact log."
            return {"result": {"account_id": acc, "status": "DONE", "outcome": "SENT_BEFORE_FAULT"}}
        new_status = "NEEDS_REVIEW" if action == "REROUTE" else "QUARANTINED"
        store.borrowers[acc]["status"] = new_status
        store.log(acc, "RECOVERED", agent, f"{action}->{new_status}")
        store.note = f"Supervisor executes {action}: {acc} marked {new_status}. State kept, no contact sent."
        return {"result": {"account_id": acc, "status": "ESCALATED", "outcome": new_status}}

    @traced("commit")
    def commit(state):
        acc = state["event"]["account_id"]; agent = state["agent"]
        b = store.borrowers[acc]
        b["contacts_today"] = store.sent_count(acc)
        store.agents[agent]["contacts_today"] += store.sent_count(acc) and 1 or 0
        store.agents[agent]["last_committed"] = acc
        store.log(acc, "COMPLETED", agent, state["result"]["outcome"])
        store.note = f"State saved for {acc}: contacts_today={b['contacts_today']}, outcome={state['result']['outcome']}. Cursor: last_committed = {acc}."
        return {}

    @traced("release_owner")
    def release_owner(state):
        acc = state["event"]["account_id"]; agent = state["agent"]
        store.borrowers[acc]["owner"] = None
        store.agents[agent].update(status="IDLE", current=None)
        store.log(acc, "RELEASED", agent, "owner_released")
        store.note = f"Lock released: {acc} has no owner."
        return {}

    @traced("check_queue")
    def check_queue(state):
        acc = state["event"]["account_id"]
        mine = [e for e in store.held if e["account_id"] == acc]
        if mine:
            for e in mine:
                store.held.remove(e)
                store.events.appendleft(e)
            store.note = f"Held event {mine[0]['id']} for {acc} put back on the bus. It will go through guardrails again."
        else:
            store.note = f"No held events for {acc}."
        return {}

    # ---- conditional edges -------------------------------------------
    after_consume = lambda s: "guardrails_route" if s.get("event") else END
    after_route = lambda s: "assign" if s["decision"] == "ASSIGNED" else "consume_event"
    after_exec = lambda s: "monitor" if s.get("fault") else "validate_output"
    after_validate = lambda s: "monitor" if s.get("fault") else "commit"
    after_recover = lambda s: "execute_agent" if s["recovery"] == "RESUME" else "commit"

    g = StateGraph(S)
    nodes = {"consume_event": consume_event, "guardrails_route": guardrails_route,
             "assign": assign, "execute_agent": execute_agent,
             "validate_output": validate_output, "monitor": monitor, "recover": recover,
             "commit": commit, "release_owner": release_owner, "check_queue": check_queue}
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "consume_event")
    g.add_conditional_edges("consume_event", after_consume,
                            {"guardrails_route": "guardrails_route", END: END})
    g.add_conditional_edges("guardrails_route", after_route,
                            {"assign": "assign", "consume_event": "consume_event"})
    g.add_edge("assign", "execute_agent")
    g.add_conditional_edges("execute_agent", after_exec,
                            {"monitor": "monitor", "validate_output": "validate_output"})
    g.add_conditional_edges("validate_output", after_validate,
                            {"monitor": "monitor", "commit": "commit"})
    g.add_edge("monitor", "recover")
    g.add_conditional_edges("recover", after_recover,
                            {"execute_agent": "execute_agent", "commit": "commit"})
    g.add_edge("commit", "release_owner")
    g.add_edge("release_owner", "check_queue")
    g.add_edge("check_queue", "consume_event")
    return g.compile(), store
