"""Stage 1 nodes: take an event in and load the borrower."""
from __future__ import annotations

from datetime import datetime

from orchestrator.config import EVENT_TYPES
from orchestrator.context import Context
from orchestrator.state.models import REJECTED, GraphState

# LangGraph keeps one saved state per account (thread_id = account_id), so a new event
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
        elif not ctx.borrowers.exists(ev["account_id"]):
            why = f"unknown account {ev['account_id']}"
        else:
            try:
                datetime.fromisoformat(ev["time"])
            except ValueError:
                why = f"bad time {ev['time']!r}"
        if why:
            ctx.log(state, "validate_event", f"REJECTED: {why}")
            return {**RESET, "outcome": {"status": REJECTED, "reason": why}}
        ctx.log(state, "validate_event", "event is well-formed, scratch fields reset")
        return dict(RESET)
    return validate_event


def make_load_borrower(ctx: Context):
    def load_borrower(state: GraphState) -> dict:
        acc = state["event"]["account_id"]
        b = ctx.borrowers.load(acc)
        ctx.log(state, "load_borrower",
                f"loaded {acc}: dpd={b['dpd']} owner={b['owner']} status={b['status']} "
                f"channels={b['channels']}")
        return {"borrower": b}
    return load_borrower
