"""Stage 2: guardrails. Hard yes/no safety checks, no AI.

Checked in this order; the first failure blocks the event and records why:
  1. STATUS      the borrower is paused (NEEDS_REVIEW / QUARANTINED)
  2. OWNER_LOCK  another agent is already the active owner
  3. DAILY_CAP   the borrower already has the maximum contacts for today (any channel)
"""
from __future__ import annotations

from datetime import datetime

from orchestrator.config import ACTIVE
from orchestrator.context import Context
from orchestrator.state.models import BLOCKED, DEFERRED, GraphState


def _guard_d12(ctx: Context, state: GraphState) -> dict:
    """Borrower-level D12 checks: suppression, payment hold, open promise, frequency caps, minimum gap."""
    ev, b = state["event"], state["borrower"]
    paused = b["status"] != ACTIVE
    if paused:                                    # the supervisor's own pause (after an escalation) comes first
        g = {"ok": False, "rule": "STATUS", "rule_ids": [], "reason": f"borrower is {b['status']}, automation paused"}
        status = "BLOCKED"
    else:
        f = ctx.engine.facts(b["account_id"], datetime.fromisoformat(ev["time"]))
        v = ctx.engine.guard(f, ev)
        g = {"ok": v["ok"], "rule": v["rule"], "rule_ids": v["rule_ids"], "reason": v["reason"]}
        if v.get("defer_until"):
            g["defer_until"] = v["defer_until"]
        status = v["status"]
    ids = ", ".join(g["rule_ids"])
    ctx.log(state, "guardrails", f"{'ALLOWED' if g['ok'] else status}{(' [' + ids + ']') if ids else ''}: {g['reason']}", g)
    out: dict = {"guard": g}
    if status == "BLOCKED":
        out["outcome"] = {"status": BLOCKED, "reason": g["reason"], "rule_ids": g["rule_ids"]}
    elif status == "DEFERRED":
        out["guard"]["ok"] = False
        out["outcome"] = {"status": DEFERRED, "reason": g["reason"], "rule_ids": g["rule_ids"], "until": g["defer_until"]}
    return out


def make_guardrails(ctx: Context):
    def guardrails(state: GraphState) -> dict:
        if ctx.engine is not None:
            return _guard_d12(ctx, state)
        b, ev = state["borrower"], state["event"]
        acc, date = b["account_id"], ev["time"][:10]
        used = ctx.contacts.daily_count(acc, date)
        cap = ctx.policy.per_borrower_daily_cap
        if b["status"] != ACTIVE:
            g = {"ok": False, "rule": "STATUS",
                 "reason": f"borrower is {b['status']}, automation paused"}
        elif b["owner"]:
            g = {"ok": False, "rule": "OWNER_LOCK",
                 "reason": f"{b['owner']} is already the active owner"}
        elif used >= cap:
            g = {"ok": False, "rule": "DAILY_CAP",
                 "reason": f"already contacted today ({used}/{cap})"}
        else:
            g = {"ok": True, "rule": "NONE",
                 "reason": f"no owner, contacts today {used}/{cap}, status ACTIVE"}
        ctx.log(state, "guardrails", ("ALLOWED: " if g["ok"] else "BLOCKED: ") + g["reason"], g)
        out: dict = {"guard": g}
        if not g["ok"]:
            out["outcome"] = {"status": BLOCKED, "reason": g["reason"]}
        return out
    return guardrails
