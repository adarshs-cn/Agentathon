"""Human-readable views of what the supervisor did. Used by the trace CLI and the live narrator.

Every line of a trace is a node saying what it decided and why. For the nodes where the
evidence matters, the structured data behind the line is shown too:
  route        the decision: purpose, channel agent, fallbacks, rule number, how long it took
  guardrails   which rule decided
  <agent>      the exact request sent to the channel agent, and exactly what came back
  monitor      what the provider said (SENT / NOT_SENT / UNKNOWN) and who decided (rules / llm)
"""
from __future__ import annotations

import json

from orchestrator.config import CHANNELS


def compact(x) -> str:
    return json.dumps(x, default=str, separators=(", ", ": "))


def format_step(row: dict, verbose: bool = False) -> list[str]:
    node, d = row["node"], row.get("data")
    lines = [f"  {node:<16} {row['text']}"]
    if not isinstance(d, dict):
        return lines
    shown = False
    if "request" in d:
        lines.append(f"      request  : {compact(d['request'])}")
        shown = True
    if "response" in d:
        lines.append(f"      response : {compact(d['response'])}   ({d.get('elapsed_ms')} ms)")
        shown = True
    if "error" in d:
        lines.append(f"      error    : {d['error']}   ({d.get('elapsed_ms')} ms)")
        shown = True
    if node == "route" and "rule" in d:
        lines.append(f"      decision : purpose={d.get('purpose')} agent={d.get('agent')} "
                     f"fallbacks={d.get('fallbacks')} rule={d.get('rule')} ({d.get('route_ms')} ms)")
        if d.get("rule_ids"):
            lines.append(f"      rules    : {', '.join(d['rule_ids'])}")
        for cand in d.get("considered") or []:
            lines.append(f"      weighed  : {cand['role']} -> {cand.get('action')}")
            for ch in cand.get("channels") or []:
                mark = {"OK": "ok     ", "BLOCKED": "BLOCKED", "DEFERRED": "DEFER  "}.get(ch.get("status"), "?      ")
                ids = f" [{', '.join(ch['rule_ids'])}]" if ch.get("rule_ids") else ""
                lines.append(f"                 {mark} {ch['channel']:<9}{ids} {ch.get('reason', '')}")
            if cand.get("status"):
                lines.append(f"                 {cand['status']} [{', '.join(cand.get('rule_ids') or [])}] {cand.get('reason', '')}")
        for w in d.get("warnings") or []:
            lines.append(f"      warning  : {w}")
        shown = True
    if node == "guardrails" and "rule" in d:
        lines.append(f"      guardrail: rule={d['rule']} ok={d['ok']}" + (f" rule_ids={d['rule_ids']}" if d.get("rule_ids") else ""))
        shown = True
    if node == "monitor" and "provider_state" in d:
        lines.append(f"      evidence : provider says {d['provider_state']}; decided by {d.get('advisor')}")
        shown = True
    if verbose and not shown:
        lines.append(f"      data     : {compact(d)}")
    return lines


def render_trace(trace: dict, verbose: bool = False) -> str:
    b = trace["customer"] or {}
    out = [f"ACCOUNT {trace['customer_id']}   trace complete: {trace['complete']}",
           f"  now: status={b.get('status')} owner={b.get('owner')} last_contact={b.get('last_contact')}",
           f"  facts: dpd={b.get('dpd')} legal_flag={b.get('legal_flag')} channels={b.get('channels')} "
           f"open_promises={len(b.get('commitments') or [])}"]
    if trace.get("checkpoints") is not None:
        out.append(f"  graph checkpoints saved: {trace['checkpoints']}")
    for c in trace["contacts"]:
        out.append(f"  contact: {c['date']} via {c['channel']} ({c['purpose']}) -> {c['status']} "
                   f"ref={c['provider_ref']}")
    for e in trace["events"]:
        out.append("")
        out.append(f"EVENT {e['event_id']}  {e['type']}  @ {e['time']}   -> {e['outcome'] or e['status']}")
        for s in e["steps"]:
            out.extend(format_step({**s}, verbose))
    return "\n".join(out)


def find_events(ctx, kind: str, limit: int = 10) -> list[dict]:
    """Pick interesting events to look at. kind: fault | blocked | suppressed | rejected | escalated
    | contacted | quarantined."""
    if kind == "fault":
        rows = ctx.db.query("SELECT DISTINCT event_id, customer_id FROM decision_log WHERE node='monitor' "
                            "ORDER BY id LIMIT ?", (limit,))
        return [{"event_id": r["event_id"], "customer_id": r["customer_id"]} for r in rows]
    if kind == "quarantined":
        rows = ctx.db.query("SELECT customer_id FROM customer_state WHERE status!='ACTIVE' ORDER BY customer_id LIMIT ?",
                            (limit,))
        return [{"event_id": None, "customer_id": r["customer_id"]} for r in rows]
    outcome = kind.upper()
    rows = ctx.db.query("SELECT event_id, customer_id FROM event_queue WHERE outcome=? ORDER BY seq LIMIT ?",
                        (outcome, limit))
    return [{"event_id": r["event_id"], "customer_id": r["customer_id"]} for r in rows]


KINDS = ("fault", "blocked", "suppressed", "rejected", "escalated", "contacted", "quarantined")
__all__ = ["render_trace", "format_step", "find_events", "compact", "CHANNELS", "KINDS"]
