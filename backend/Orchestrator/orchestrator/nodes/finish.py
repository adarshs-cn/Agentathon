"""Closing nodes: commit, release, close_event.

commit, release and recover are the only code that writes to the borrower's file.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from orchestrator.config import ACTIVE
from orchestrator.context import Context
from orchestrator.state.models import CONTACTED, ESCALATE, ESCALATED, NEEDS_REVIEW_STATUS, QUARANTINED_STATUS, GraphState


def make_commit(ctx: Context):
    def commit(state: GraphState) -> dict:
        acc, ev, res = state["borrower"]["account_id"], state["event"], state["result"]
        b = dict(state["borrower"])
        if res["status"] == "DONE":
            ctx.borrowers.record_contact(acc, ev["time"])
            b["last_contact"] = ev["time"]
            role = (state.get("decision") or {}).get("role")
            if ctx.engine is not None and role:                  # R038: a 24-hour ownership lease from the contact
                until = (datetime.fromisoformat(ev["time"]) + timedelta(hours=24)).isoformat()
                ctx.borrowers.set_lease(acc, role, until)
                ctx.log(state, "commit", f"contact recorded, last_contact={ev['time']}; {role} holds the lease until {until}")
            else:
                ctx.log(state, "commit", f"contact recorded, last_contact={ev['time']}")
        else:
            status = NEEDS_REVIEW_STATUS if res.get("outcome") == ESCALATE else QUARANTINED_STATUS
            ctx.borrowers.set_status(acc, status)
            b["status"] = status
            ctx.log(state, "commit", f"no contact made; borrower status set to {status}")
        return {"borrower": b}
    return commit


def make_release(ctx: Context):
    def release(state: GraphState) -> dict:
        acc = state["borrower"]["account_id"]
        ctx.borrowers.release(acc)
        ctx.log(state, "release", "owner lock released")
        return {"borrower": {**state["borrower"], "owner": None}}
    return release


def make_close_event(ctx: Context):
    def close_event(state: GraphState) -> dict:
        ev = state["event"]
        out = state.get("outcome")
        if not out:
            res = state.get("result") or {}
            dec = state.get("decision") or {}
            if res.get("status") == "DONE":
                out = {"status": CONTACTED, "agent": dec.get("agent"), "purpose": dec.get("purpose"),
                       "attempts": state.get("attempt", 0)}
            else:
                out = {"status": ESCALATED, "agent": dec.get("agent"), "reason": res.get("outcome"),
                       "attempts": state.get("attempt", 0)}
        ctx.log(state, "close_event", f"event {ev.get('id')} closed as {out['status']}", out)
        return {"outcome": out}
    return close_event
