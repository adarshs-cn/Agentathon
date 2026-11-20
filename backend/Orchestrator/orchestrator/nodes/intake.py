"""Stage 1 nodes: take an event in (it names an ACCOUNT), and load that account and the CUSTOMER who holds it."""
from __future__ import annotations

from datetime import datetime

from orchestrator.config import EVENT_TYPES
from orchestrator.context import Context
from orchestrator.state.models import REJECTED, GraphState

# LangGraph keeps one saved state per customer (thread_id = customer_id), so a new event
# starts with the previous run's leftovers. validate_event clears every scratch field.
RESET = {"guard": None, "decision": None, "attempt": 0, "result": None,
         "fault": None, "sent": False, "recovery": None, "outcome": None}


def make_validate_event(ctx: Context):
    def validate_event(state: GraphState) -> dict:
        ev = state["event"]
        missing = [k for k in ("id", "type", "account_id", "time") if not ev.get(k)]
        why = None
        if missing:
            why = f"event is missing {missing}"
        elif ev["type"] not in EVENT_TYPES:
            why = f"unknown event type {ev['type']}"
        else:
            cust = ev.get("customer_id") or ctx.borrowers.customer_of(ev["account_id"])   # the bus usually resolved it
            if not cust or not ctx.borrowers.exists(cust):
                why = f"unknown account {ev['account_id']}"      # no customer holds this account
            else:
                ev = {**ev, "customer_id": cust}
                try:
                    datetime.fromisoformat(ev["time"])
                except ValueError:
                    why = f"bad time {ev['time']!r}"
        if why:
            ctx.log(state, "validate_event", f"REJECTED: {why}")
            return {**RESET, "outcome": {"status": REJECTED, "reason": why}}
        ctx.log({**state, "event": ev}, "validate_event", "event is well-formed, scratch fields reset")
        return {**RESET, "event": ev}
    return validate_event


def make_load_customer(ctx: Context):
    def load_customer(state: GraphState) -> dict:
        ev = state["event"]
        b = ctx.borrowers.load(ev["customer_id"])
        a = ctx.borrowers.account(ev["account_id"]) or {"account_id": ev["account_id"], "dpd": b["dpd"]}
        ctx.log(state, "load_customer",
                f"account {ev['account_id']} (dpd={a.get('dpd')}) of customer {ev['customer_id']}: "
                f"owner={b['owner']} status={b['status']} channels={b['channels']}")
        return {"customer": b, "account": a}
    return load_customer
