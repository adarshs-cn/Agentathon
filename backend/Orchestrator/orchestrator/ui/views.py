"""Read-side views for the dashboard pages. Pure SELECTs over the supervisor's own SQLite tables:
event_queue (the bus), decision_log (the audit trail), contact_log, customer_state, and the ds_* dataset tables.

Nothing here is computed from anything the supervisor did not write to the database.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from orchestrator.policy.d12 import CHANNEL_AGENT
from orchestrator.ui.accounts import resolve_borrower
from orchestrator.ui.events import CHANNEL_NODES, _z, ui_events_for

REFUSALS = ("BLOCKED", "SUPPRESSED", "DEFERRED")
MONITOR_RE = re.compile(r"^(\w+) on (\w+) -> (\w+)")


def _data(raw):
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _rows(db, sql, args=()):
    return [dict(r) for r in db.query(sql, tuple(args))]


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0.0


# ---------------------------------------------------------------------- faults
def fault_report(db, injector) -> list[dict]:
    """One entry per borrower that had a scripted fault fire, saying whether it was recovered without losing state."""
    out = []
    fired = getattr(injector, "fired", []) if injector else []
    for b in sorted({a for a, _, _ in fired}):
        mon = _rows(db, "SELECT id FROM decision_log WHERE customer_id=? AND node='monitor'", (b,))
        st = db.one("SELECT owner, status FROM customer_state WHERE customer_id=?", (b,))
        sent = db.one("SELECT COUNT(*) n FROM contact_log WHERE customer_id=? AND status='SENT'", (b,))["n"]
        open_ev = db.one("SELECT COUNT(*) n FROM event_queue WHERE customer_id=? AND status IN ('PENDING','IN_PROGRESS')", (b,))["n"]
        coherent = st is not None and st["owner"] is None and (sent > 0 or st["status"] != "ACTIVE")
        out.append({"customer_id": b, "faults": [f for a, _, f in fired if a == b], "monitored": bool(mon),
                    "recovered": bool(mon) and coherent and open_ev == 0, "contacts_sent": sent,
                    "status": st["status"] if st else None})
    return out


def faults(db, injector) -> dict:
    mon = _rows(db, "SELECT m.id, m.ts, m.event_id, m.customer_id, m.account_id, m.text, m.data, q.outcome "
                    "FROM decision_log m LEFT JOIN event_queue q ON q.event_id = m.event_id "
                    "WHERE m.node='monitor' ORDER BY m.id DESC")
    incidents = []
    for m in mon:
        d, rx = _data(m["data"]), MONITOR_RE.match(m["text"] or "")
        incidents.append({
            "id": f"d{m['id']}", "event_id": m["event_id"], "ts": _z(m["ts"]), "customer_id": m["customer_id"],
            "account_id": m["account_id"], "fault_type": rx.group(1) if rx else "?", "agent": rx.group(2) if rx else "?",
            "action": d.get("action") or (rx.group(3) if rx else "?"), "reason": d.get("reason") or "",
            "provider_state": d.get("provider_state"), "advisor": d.get("advisor"),
            "outcome": m["outcome"],
            "recovered": m["outcome"] == "CONTACTED", "escalated": m["outcome"] == "ESCALATED",
            "sent_once": d.get("action") == "RESTART_SKIP_CURRENT"})
    report = fault_report(db, injector)
    scripted = Counter()
    if injector:
        for (_, _), kind in injector.script.items():
            scripted[kind] += 1
    return {
        "summary": {"injected": len(report), "recovered": sum(1 for r in report if r["recovered"]),
                    "scheduled": len({a for (a, _) in injector.script}) if injector else 0,
                    "by_type": dict(Counter(i["fault_type"] for i in incidents)),
                    "by_action": dict(Counter(i["action"] for i in incidents)),
                    "resends_prevented": sum(1 for i in incidents if i["action"] == "RESTART_SKIP_CURRENT"),
                    "escalated": sum(1 for i in incidents if i["escalated"])},
        "incidents": incidents, "borrowers": report,
        "script": [{"customer_id": a, "call": n, "fault": k, "fired": (a, n, k) in set(injector.fired)}
                   for (a, n), k in sorted(injector.script.items())] if injector else [],
    }


# ---------------------------------------------------------------------- overview numbers
def overview_numbers(db, ctx, injector, audit: dict) -> dict:
    q = db.one
    outcomes = {r["outcome"] or "PENDING": r["n"] for r in db.query(
        "SELECT outcome, COUNT(*) n FROM event_queue WHERE status IN ('DONE','FAILED') GROUP BY outcome")}
    gaps = q("SELECT COUNT(*) n FROM event_queue q WHERE q.status='DONE' AND (NOT EXISTS (SELECT 1 FROM decision_log d "
             "WHERE d.event_id=q.event_id AND d.node='validate_event') OR NOT EXISTS (SELECT 1 FROM decision_log d "
             "WHERE d.event_id=q.event_id AND d.node='close_event'))")["n"]
    rep = fault_report(db, injector)
    route = list(ctx.metrics.get("route", []))
    done = q("SELECT COUNT(*) n FROM event_queue WHERE status IN ('DONE','FAILED')")["n"]
    return {
        "counters": {
            "conflicting_contacts": audit.get("violations", 0),
            "faults_injected": len(rep), "faults_recovered": sum(1 for r in rep if r["recovered"]),
            "faults_scheduled": len({a for (a, _) in injector.script}) if injector else 0,
            "borrowers_handled": q("SELECT COUNT(DISTINCT customer_id) n FROM event_queue WHERE status='DONE' "
                                   "AND outcome != 'REJECTED' AND customer_id != ''")["n"],
            "contacts_made": q("SELECT COUNT(*) n FROM contact_log WHERE status='SENT'")["n"],
            "blocked_or_deferred": sum(outcomes.get(k, 0) for k in REFUSALS),
            "events_total": q("SELECT COUNT(*) n FROM event_queue")["n"], "events_done": done,
            "trace_gaps": gaps, "audit_checked_contacts": audit.get("checked", 0),
            "audit_ran": audit.get("ran", False),
        },
        "latency_ms": {"median": _pct(route, 0.5), "p95": _pct(route, 0.95), "max": max(route) if route else 0.0,
                       "samples": len(route), "target_ms": 100},
        "outcomes": outcomes,
    }


def timeline(db) -> list[dict]:
    """Events per sim hour by outcome: how the day is going."""
    buckets: dict = defaultdict(lambda: Counter())
    for r in db.query("SELECT substr(event_time,12,2) h, outcome, COUNT(*) n FROM event_queue "
                      "WHERE status='DONE' AND event_time != '' GROUP BY h, outcome"):
        buckets[r["h"]][r["outcome"] or "?"] += r["n"]
    return [{"hour": f"{h}:00", **{k: buckets[h].get(k, 0) for k in ("CONTACTED", "BLOCKED", "SUPPRESSED", "DEFERRED", "ESCALATED", "REJECTED")}}
            for h in sorted(buckets)]


def rules_cited(db, limit: int = 8) -> list[dict]:
    """Which D12 rules actually stopped or steered contacts today, most-cited first."""
    cnt: Counter = Counter()
    for r in db.query("SELECT data FROM decision_log WHERE node='close_event'"):
        d = _data(r["data"])
        if d.get("status") in REFUSALS:
            for rid in d.get("rule_ids") or []:
                cnt[rid] += 1
    desc = {r["rule_id"]: dict(r) for r in db.query("SELECT rule_id, category, parameter, channel, description FROM ds_rule")}
    from orchestrator.ui import reasons
    out = []
    for rid, n in cnt.most_common(limit):
        row = desc.get(rid, {})
        headline, why = reasons.label(rid, row or None)
        out.append({"rule_id": rid, "count": n, "category": row.get("category"), "description": row.get("description", ""),
                    "headline": headline, "why": why})
    return out


def channel_mix(db) -> list[dict]:
    return _rows(db, "SELECT channel, role, COUNT(*) n FROM contact_log WHERE status='SENT' GROUP BY channel, role ORDER BY n DESC")


def recent_events(db, limit: int = 40) -> list[dict]:
    """The newest dashboard-feed lines, newest first."""
    ids = [r["event_id"] for r in db.query(
        "SELECT event_id FROM event_queue WHERE status IN ('DONE','FAILED') ORDER BY seq DESC LIMIT ?", (max(1, limit // 3),))]
    out: list[dict] = []
    for eid in ids:
        rows = [{**r, "data": _data(r["data"])} for r in _rows(db, "SELECT * FROM decision_log WHERE event_id=? ORDER BY id", (eid,))]
        out += ui_events_for(rows)[::-1]                       # newest line first
        if len(out) >= limit:
            break
    return out[:limit]


# ---------------------------------------------------------------------- agents
def agents(db, ctx) -> dict:
    stats = {n: {"calls": 0, "faults": 0, "ms": [], "last_fault": None} for n in CHANNEL_NODES}
    for r in db.query("SELECT id, ts, event_id, customer_id, node, data FROM decision_log WHERE node IN ('whatsapp','email','voice') ORDER BY id"):
        d, s = _data(r["data"]), stats[r["node"]]
        s["calls"] += 1
        if "elapsed_ms" in d:
            s["ms"].append(d["elapsed_ms"])
        resp = d.get("response") or {}
        if d.get("error") or (d.get("response") is not None and resp.get("status") != "DONE"):
            s["faults"] += 1
            s["last_fault"] = {"ts": _z(r["ts"]), "customer_id": r["customer_id"], "event_id": r["event_id"],
                               "what": d.get("error") or f"returned {resp.get('status') or 'junk'}"}
    sent = {r["channel"]: r["n"] for r in db.query("SELECT channel, COUNT(*) n FROM contact_log WHERE status='SENT' GROUP BY channel")}
    escalated = Counter(_data(r["data"]).get("agent") for r in db.query(
        "SELECT data FROM decision_log WHERE node='close_event'") if _data(r["data"]).get("status") == "ESCALATED")
    channel_agents = []
    for name in ctx.registry.names():
        s = stats.get(name, {"calls": 0, "faults": 0, "ms": [], "last_fault": None})
        recent = db.query("SELECT data FROM decision_log WHERE node=? ORDER BY id DESC LIMIT 10", (name,))
        recent_faults = sum(1 for r in recent if (_data(r["data"]).get("error") or
                            (_data(r["data"]).get("response") or {}).get("status", "DONE") != "DONE"))
        # Judged from the last 10 calls: no failure = healthy, some = degraded, half or more = fault.
        status = "fault" if recent_faults >= 5 else "degraded" if recent_faults else "healthy"
        channel_agents.append({
            "name": name, "d12_channel": next((k for k, v in CHANNEL_AGENT.items() if v == name), name),
            "status": status, "calls": s["calls"], "contacts_sent": sent.get(name, 0), "faults": s["faults"],
            "recent_faults": recent_faults, "avg_ms": round(sum(s["ms"]) / len(s["ms"]), 3) if s["ms"] else 0.0,
            "p95_ms": round(_pct(s["ms"], 0.95), 3), "last_fault": s["last_fault"], "escalations": escalated.get(name, 0)})
    # role agents: who is allowed where (D12 matrix) and what they did today
    matrix = _rows(db, "SELECT agent, bucket, allowed, contact, rank, channels, actions FROM ds_matrix WHERE agent_type='ai_agent'")
    by_role: dict = defaultdict(lambda: {"buckets": {}, "contacts": 0, "decisions": 0})
    for m in matrix:
        role = m["agent"][:-6]
        by_role[role]["buckets"][m["bucket"]] = {"allowed": bool(m["allowed"] and m["contact"]), "rank": m["rank"],
                                                 "channels": m["channels"].split("|") if m["channels"] else [],
                                                 "actions": m["actions"].split("|") if m["actions"] else []}
    for r in db.query("SELECT role, COUNT(*) n FROM contact_log WHERE status='SENT' GROUP BY role"):
        by_role[r["role"]]["contacts"] = r["n"]
    for r in db.query("SELECT data FROM decision_log WHERE node='route'"):
        role = _data(r["data"]).get("role")
        if role:
            by_role[role]["decisions"] += 1
    handoffs = Counter()
    for r in db.query("SELECT data FROM decision_log WHERE node='assign' AND text LIKE 'HANDOFF%'"):
        d = _data(r["data"]); handoffs[("in", d.get("to"))] += 1; handoffs[("out", d.get("from"))] += 1
    roles = [{"name": role, "contacts_sent": v["contacts"], "decisions": v["decisions"], "buckets": v["buckets"],
              "handoffs_in": handoffs[("in", role)], "handoffs_out": handoffs[("out", role)]}
             for role, v in sorted(by_role.items(), key=lambda kv: kv[0])]
    return {"channel_agents": channel_agents, "role_agents": roles}


# ---------------------------------------------------------------------- ownership
def ownership(db, now: datetime) -> dict:
    now_s = now.isoformat()
    leases = _rows(db, "SELECT customer_id customer_id, lease_owner role, lease_until until, last_contact, owner in_flight "
                       "FROM customer_state WHERE lease_owner IS NOT NULL AND lease_until > ? ORDER BY lease_until DESC LIMIT 100", (now_s,))
    n_leases = db.one("SELECT COUNT(*) n FROM customer_state WHERE lease_owner IS NOT NULL AND lease_until > ?", (now_s,))["n"]
    handoffs = []
    for r in db.query("SELECT id, ts, event_id, customer_id, text, data FROM decision_log WHERE node='assign' AND text LIKE 'HANDOFF%' ORDER BY id DESC LIMIT 100"):
        d = _data(r["data"])
        handoffs.append({"id": f"d{r['id']}", "ts": _z(r["ts"]), "event_id": r["event_id"], "customer_id": r["customer_id"],
                         "from": d.get("from"), "to": d.get("to"), "rule_ids": d.get("rule_ids", []), "why": d.get("why", "")})
    conflicts = []
    for r in db.query("SELECT id, ts, event_id, customer_id, data FROM decision_log WHERE node='route' AND data LIKE '%R036%' ORDER BY id DESC LIMIT 200"):
        d = _data(r["data"])
        for cand in d.get("considered", []):
            if "R036" in (cand.get("rule_ids") or []):
                conflicts.append({"id": f"d{r['id']}", "ts": _z(r["ts"]), "event_id": r["event_id"], "customer_id": r["customer_id"],
                                  "blocked_role": cand["role"], "action": cand.get("action"), "rule_ids": cand["rule_ids"],
                                  "reason": cand.get("reason", "")})
    locks = db.one("SELECT COUNT(*) n FROM customer_state WHERE owner IS NOT NULL")["n"]
    simultaneous = []
    for r in db.query(
            "SELECT a.customer_id b, a.event_id a_id, a.event_time a_time, a.type a_type, a.outcome a_out, "
            "b.event_id b_id, b.event_time b_time, b.type b_type, b.outcome b_out FROM event_queue a "
            "JOIN event_queue b ON a.customer_id = b.customer_id AND a.seq < b.seq "
            "WHERE a.status='DONE' AND b.status='DONE' AND a.customer_id != '' AND a.event_id NOT LIKE '%~d%' "
            "AND b.event_id NOT LIKE '%~d%' AND (julianday(b.event_time) - julianday(a.event_time)) * 1440 BETWEEN 0 AND 5 "
            "ORDER BY b.event_time DESC LIMIT 100"):
        close = db.one("SELECT data FROM decision_log WHERE event_id=? AND node='close_event' ORDER BY id DESC LIMIT 1", (r["b_id"],))
        d = _data(close["data"]) if close else {}
        simultaneous.append({
            "customer_id": r["b"],
            "first": {"event_id": r["a_id"], "time": _z(r["a_time"]), "type": r["a_type"], "outcome": r["a_out"]},
            "second": {"event_id": r["b_id"], "time": _z(r["b_time"]), "type": r["b_type"], "outcome": r["b_out"],
                       "rule_ids": d.get("rule_ids", []), "reason": d.get("reason", "")},
            "single_contact": not (r["a_out"] == "CONTACTED" and r["b_out"] == "CONTACTED")})
    return {"summary": {"active_leases": n_leases, "handoffs": len(handoffs), "conflicts_prevented": len(conflicts),
                        "locks_held": locks, "simultaneous": len(simultaneous),
                        "simultaneous_single_contact": sum(1 for s in simultaneous if s["single_contact"])},
            "leases": leases, "handoffs": handoffs, "conflicts": conflicts[:100], "simultaneous": simultaneous,
            "by_role": dict(Counter(l["role"] for l in leases))}


# ---------------------------------------------------------------------- budgets
def budgets(db, now: datetime) -> dict:
    today = now.date().isoformat()
    hist = Counter()
    for r in db.query("SELECT agent, channel, COUNT(*) n FROM ds_history WHERE substr(at,1,10)=? GROUP BY agent, channel", (today,)):
        hist[(r["agent"], "call" if r["channel"] == "ivr" else r["channel"])] += r["n"]
    ours = Counter()
    for r in db.query("SELECT role, channel, COUNT(*) n FROM contact_log WHERE date=? AND status IN ('ATTEMPTING','SENT') GROUP BY role, channel", (today,)):
        ours[(f"{r['role']}_agent", "call" if r["channel"] == "voice" else r["channel"])] += r["n"]
    resources = []
    for c in _rows(db, "SELECT * FROM ds_capacity ORDER BY resource_id"):
        used_hist, used_ours = hist[(c["agent"], c["channel"])], ours[(c["agent"], c["channel"])]
        used = used_hist + used_ours
        integrated = c["agent"].endswith("_agent") and c["channel"] in CHANNEL_AGENT
        resources.append({"resource_id": c["resource_id"], "agent": c["agent"], "channel": c["channel"],
                          "integrated": integrated, "external": not c["agent"].endswith("_agent"),
                          "used_today": used, "from_history": used_hist, "by_supervisor": used_ours,
                          "daily_budget": c["daily_budget"], "cost": c["cost"], "spend_used": round(used * c["cost"], 2),
                          "spend_cap": c["spend_cap"], "window": c["window"], "buckets": c["buckets"].split("|"),
                          "utilisation": round(used / c["daily_budget"], 4) if c["daily_budget"] else 0.0})
    dist: Counter = Counter()
    for r in db.query("SELECT n, COUNT(*) k FROM (SELECT b, COUNT(*) n FROM (SELECT customer_id b FROM ds_history WHERE substr(at,1,10)=? "
                      "UNION ALL SELECT customer_id b FROM contact_log WHERE date=? AND status IN ('ATTEMPTING','SENT')) GROUP BY b) GROUP BY n", (today, today)):
        dist["3+" if r["n"] >= 3 else str(r["n"])] += r["k"]
    return {"as_of": today, "resources": resources,
            "per_borrower_today": {k: dist.get(k, 0) for k in ("1", "2", "3+")},
            "totals": {"attempts_today": sum(r["used_today"] for r in resources),
                       "spend_today": round(sum(r["spend_used"] for r in resources), 2),
                       "by_supervisor": sum(r["by_supervisor"] for r in resources)}}


# ---------------------------------------------------------------------- decisions
def decisions(db, params: dict) -> dict:
    page, size = max(1, int(params.get("page") or 1)), min(200, max(1, int(params.get("page_size") or 25)))
    cond, args = ["q.status IN ('DONE','FAILED')"], []
    if params.get("outcome"):
        cond.append("q.outcome = ?"); args.append(params["outcome"])
    if params.get("customer_id"):
        cond.append("q.customer_id LIKE ?"); args.append(params["customer_id"].strip() + "%")
    if params.get("account_id"):
        cond.append("q.account_id LIKE ?"); args.append(params["account_id"].strip() + "%")
    if params.get("type"):
        cond.append("q.type = ?"); args.append(params["type"])
    if params.get("rule_id"):
        cond.append("EXISTS (SELECT 1 FROM decision_log x WHERE x.event_id=q.event_id AND x.node IN ('route','guardrails','close_event') "
                    "AND x.data LIKE ?)"); args.append(f'%"{params["rule_id"]}"%')
    if params.get("agent"):
        cond.append("EXISTS (SELECT 1 FROM decision_log x WHERE x.event_id=q.event_id AND x.node='route' AND x.data LIKE ?)")
        args.append(f'%"agent": "{params["agent"]}"%')
    where = " WHERE " + " AND ".join(cond)
    total = db.one(f"SELECT COUNT(*) n FROM event_queue q{where}", args)["n"]
    rows = _rows(db, "SELECT q.event_id, q.event_time, q.customer_id, q.account_id, q.type, q.outcome, q.attempts, "
                     "(SELECT data FROM decision_log d WHERE d.event_id=q.event_id AND d.node='close_event' ORDER BY d.id DESC LIMIT 1) close_data, "
                     "(SELECT data FROM decision_log d WHERE d.event_id=q.event_id AND d.node='route' ORDER BY d.id DESC LIMIT 1) route_data "
                     f"FROM event_queue q{where} ORDER BY q.event_time DESC, q.seq DESC LIMIT ? OFFSET ?", args + [size, (page - 1) * size])
    items = []
    for r in rows:
        c, ro = _data(r["close_data"]), _data(r["route_data"])
        ids = c.get("rule_ids") or ro.get("rule_ids") or []
        items.append({"event_id": r["event_id"], "ts": _z(r["event_time"]), "customer_id": r["customer_id"],
                      "account_id": r["account_id"], "type": r["type"],
                      "outcome": r["outcome"], "agent": ro.get("agent") or c.get("agent"), "role": ro.get("role"),
                      "action": ro.get("action"), "rule_ids": ids, "attempts": r["attempts"],
                      "reason": c.get("reason") or ro.get("reason") or ""})
    return {"items": items, "total": total, "page": page, "page_size": size}


EXTRA_RULES = [
    {"rule_id": "D12-matrix", "category": "agent_bucket_matrix", "bucket": "ALL", "channel": "ALL", "agent": "ALL", "parameter": "allowed",
     "operator": "", "value": "", "severity": "hard", "status": "active",
     "description": "D12 agent x bucket matrix: no in-house agent has an action for this event in this borrower's bucket."},
    {"rule_id": "A12", "category": "approval", "bucket": "ALL", "channel": "ALL", "agent": "supervisor", "parameter": "agent_handoff",
     "operator": "", "value": "", "severity": "hard", "status": "active",
     "description": "D12 approval matrix: any ownership change between agents is approved by the supervisor and logged with its reason."},
]


def rules(db) -> list[dict]:
    return _rows(db, "SELECT rule_id, category, bucket, channel, agent, parameter, operator, value, severity, status, description "
                     "FROM ds_rule ORDER BY rule_id") + EXTRA_RULES


# ---------------------------------------------------------------------- one borrower's trace
def trace(db, reader_ctx, any_id: str, limit: int = 50) -> dict | None:
    from orchestrator.tracing.trace import account_trace
    b = resolve_borrower(db, any_id)
    if b is None:
        return None
    t = account_trace(reader_ctx, b)
    events = t["events"][-limit:][::-1]
    for e in events:
        rows = [{**r, "data": _data(r["data"]) if not isinstance(r["data"], dict) else r["data"]}
                for r in _rows(db, "SELECT * FROM decision_log WHERE event_id=? ORDER BY id", (e["event_id"],))]
        e["feed"] = ui_events_for(rows)
        e["time"] = _z(e["time"])
        for s in e["steps"]:
            s["ts"] = _z(s["ts"]) if s.get("ts") else s.get("ts")
    return {"customer_id": b, "requested_id": any_id, "complete": t["complete"], "events": events,
            "contacts": t["contacts"], "event_count": len(t["events"])}
