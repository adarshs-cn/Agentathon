"""Stage 2: routing. Pure rules, so it takes microseconds (requirement: under 100 ms).

Two questions, answered in order:
  1. PURPOSE  what should we say?  reminder | negotiation | servicing | legal | nobody
  2. CHANNEL  which agent says it? the first channel in config.CHANNEL_PREFERENCE[purpose]
              that the borrower can be reached on, whose agent is registered, and whose
              daily budget is not used up. The remaining usable channels become
              `fallbacks`, tried in order if the chosen agent faults.

Purpose rules, first match wins (ASSUMPTION: thresholds and order are business policy):
  1 legal flag set            -> legal
  2 PAYMENT_RECEIVED          -> servicing
  3 PTP_BROKEN                -> negotiation
  4 open promise to pay       -> nobody (do not contact)
  5 DPD >= 90                 -> legal
  6 DPD >= 30                 -> negotiation
  7 otherwise                 -> reminder
Channel outcomes: 8 = no usable channel, 9 = every usable channel is over budget.
"""
from __future__ import annotations

import time

from orchestrator.config import CHANNEL_PREFERENCE, Policy
from orchestrator.context import Context
from datetime import datetime

from orchestrator.state.models import DEFERRED, SUPPRESSED, GraphState


def _compact(considered: list) -> list:
    """What the engine weighed, small enough to keep in the state and the trace."""
    out = []
    for c in considered:
        row = {"role": c["role"], "action": c.get("action")}
        if "channels" in c:
            row["channels"] = [{k: r.get(k) for k in ("channel", "status", "rule_ids", "reason", "defer_until") if r.get(k)}
                               for r in c["channels"]]
        else:
            row.update(status=c.get("status"), rule_ids=c.get("rule_ids"), reason=c.get("reason"))
        out.append(row)
    return out


def _route_d12(ctx: Context, state: GraphState) -> dict:
    t0 = time.perf_counter()
    b, ev = state["borrower"], state["event"]
    f = ctx.engine.facts(b["account_id"], datetime.fromisoformat(ev["time"]))
    p = ctx.engine.plan(f, ev)
    ms = round((time.perf_counter() - t0) * 1000, 4)
    ids = p["rule_ids"]
    d = {"purpose": p.get("role"), "role": p.get("role"), "action": p.get("action"), "agent": None, "fallbacks": [],
         "reason": "", "rule": ids[0] if ids else "D12-matrix", "rule_ids": ids, "route_ms": ms,
         "handoff": p.get("handoff"), "warnings": p.get("warnings", []), "considered": _compact(p["considered"])}
    out: dict = {}
    tag = f" [{', '.join(ids)}]" if ids else ""
    if p["status"] == "OK":
        d["agent"], d["fallbacks"] = p["channel_agents"][0], p["channel_agents"][1:]
        d["reason"] = (f"{p['role']} ({p['action']}) via {d['agent']}; fallbacks {d['fallbacks']}"
                        + (f"; HANDOFF from {p['handoff']['from']}" if p.get("handoff") else ""))
        ctx.log(state, "route", f"{d['reason']}{tag}", d)
    elif p["status"] == "DEFERRED":
        d["reason"] = p["reason"]
        ctx.log(state, "route", f"DEFERRED{tag}: {p['reason']}", d)
        out["outcome"] = {"status": DEFERRED, "reason": p["reason"], "rule_ids": ids, "until": p["defer_until"]}
    else:
        d["reason"] = p["reason"]
        ctx.log(state, "route", f"NO AGENT{tag}: {p['reason']}", d)
        out["outcome"] = {"status": SUPPRESSED, "reason": p["reason"], "rule_ids": ids}
    out["decision"] = d
    return out


def decide_purpose(b: dict, ev: dict, policy: Policy):
    """Returns (purpose or None, reason, rule number)."""
    if b["legal_flag"]:
        return "legal", "legal flag is set", 1
    if ev["type"] == "PAYMENT_RECEIVED":
        return "servicing", "payment received", 2
    if ev["type"] == "PTP_BROKEN":
        return "negotiation", "promise to pay was broken", 3
    if b["commitments"]:
        return None, f"open promise to pay ({b['commitments'][0].get('due', '?')}), do not contact", 4
    if b["dpd"] >= policy.dpd_legal:
        return "legal", f"DPD {b['dpd']} is {policy.dpd_legal} or more", 5
    if b["dpd"] >= policy.dpd_negotiation:
        return "negotiation", f"DPD {b['dpd']} is between {policy.dpd_negotiation} and {policy.dpd_legal - 1}", 6
    return "reminder", f"DPD {b['dpd']} is below {policy.dpd_negotiation}", 7


def make_route(ctx: Context):
    def route(state: GraphState) -> dict:
        if ctx.engine is not None:
            return _route_d12(ctx, state)
        t0 = time.perf_counter()
        b, ev = state["borrower"], state["event"]
        date = ev["time"][:10]
        purpose, why, rule = decide_purpose(b, ev, ctx.policy)
        agent, fallbacks = None, []

        if purpose is not None:
            usable = [c for c in CHANNEL_PREFERENCE[purpose]
                      if c in b["channels"] and c in ctx.registry]
            within = [c for c in usable
                      if ctx.contacts.agent_count(c, date) < ctx.policy.per_agent_daily_cap]
            if not usable:
                why, rule = f"{purpose}, but no usable channel (borrower reachable on {b['channels']})", 8
            elif not within:
                why, rule = f"{purpose}, but every usable channel {usable} is over its daily budget", 9
            else:
                agent, fallbacks = within[0], within[1:]
                why = f"{purpose}: {why}; channel {agent} is the first usable of {usable}"

        ms = round((time.perf_counter() - t0) * 1000, 4)
        decision = {"purpose": purpose, "agent": agent, "fallbacks": fallbacks,
                    "reason": why, "rule": rule, "route_ms": ms}
        ctx.log(state, "route", f"rule {rule}: {agent or 'NO AGENT'} | {why}", decision)
        out: dict = {"decision": decision}
        if agent is None:
            out["outcome"] = {"status": SUPPRESSED, "reason": why}
        return out
    return route
