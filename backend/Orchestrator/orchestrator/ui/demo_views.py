"""Read-side views for the scenario Overview: the 15-event list and the rows behind each hero tile."""
from __future__ import annotations

import json

from orchestrator.agents.messages import demo_contact
from orchestrator.ui import reasons


def _demo_rows(db) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT d.*, q.status AS q_status, q.outcome AS q_outcome, q.event_time, p.name_masked, "
        "(SELECT dpd FROM account a WHERE a.account_id=d.account_id) AS dpd "
        "FROM demo_event d JOIN event_queue q ON q.event_id=d.event_id "
        "LEFT JOIN customer p ON p.customer_id=d.customer_id ORDER BY d.seq")]


def real_rows(db, limit: int = 300) -> list[dict]:
    """Real (monitored) events, newest first, in the same shape as the walkthrough rows."""
    rows = [dict(r) for r in db.query(
        "SELECT q.seq, q.event_id, q.customer_id, q.account_id, q.type AS event_type, q.status AS q_status, "
        "q.outcome AS q_outcome, q.event_time, p.name_masked FROM event_queue q "
        "LEFT JOIN customer p ON p.customer_id=q.customer_id WHERE q.event_id NOT LIKE 'demo-%' "
        "ORDER BY q.seq DESC LIMIT ?", (limit,))]
    for r in rows:
        r["label"] = reasons.EVENT_WORDS.get(r["event_type"], r["event_type"])
    return rows


def _contact(db, event_id: str, borrower: str):
    r = db.one("SELECT channel, role, status, message_json FROM contact_log WHERE idem_key=?", (f"{borrower}|{event_id}",))
    return dict(r) if r else None


def scenario(db, running_event: str | None = None) -> dict:
    rows = _demo_rows(db)
    by_seq = {r["seq"]: r for r in rows}
    items = []
    for r in rows:
        done = r["q_status"] in ("DONE", "FAILED")
        c = _contact(db, r["event_id"], r["customer_id"]) if done else None
        dep_ok = not r["depends_on"] or by_seq[r["depends_on"]]["q_status"] == "DONE"
        status = "running" if running_event == r["event_id"] else ("done" if done else "not_run")
        items.append({
            "seq": r["seq"], "key": r["key"], "label": r["label"], "event_id": r["event_id"],
            "event_type": r["event_type"], "event_label": reasons.EVENT_WORDS.get(r["event_type"], r["event_type"]),
            "time": r["event_time"][11:16], "customer_id": r["customer_id"], "account_id": r.get("account_id"),
            "borrower_masked": r["name_masked"], "dpd": r["dpd"],
            "status": status, "outcome": r["q_outcome"] if done else None,
            "outcome_label": reasons.OUTCOME_WORDS.get(r["q_outcome"]) if done else None,
            "channel": c["channel"] if c else None, "role": c["role"] if c else None,
            "available": dep_ok, "why_unavailable": None if dep_ok else f"Run event {r['depends_on']} first: this is its second request.",
            "note": r["note"]})
    return {"items": items, "demo_contact": {k: v for k, v in demo_contact().items() if k != "name"},
            "done": sum(1 for i in items if i["status"] == "done"), "total": len(items)}


def drilldown(db, injector, audit: dict, tile: str, rows: list[dict] | None = None, latency: dict | None = None,
              live: bool = False) -> dict | None:
    rows = _demo_rows(db) if rows is None else rows
    done = [r for r in rows if r["q_status"] in ("DONE", "FAILED")]

    def base(r, **extra):
        return {"event_id": r["event_id"], "seq": r["seq"], "event": r["label"], "borrower": r["name_masked"] or r["customer_id"],
                "account": r.get("account_id"),
                **extra}

    if tile == "contacts":
        out = []
        for r in done:
            c = _contact(db, r["event_id"], r["customer_id"])
            if c and c["status"] == "SENT":
                m = json.loads(c["message_json"]) if c["message_json"] else {}
                out.append(base(r, channel=reasons.CHANNEL_WORDS.get(c["channel"], c["channel"]),
                                agent=reasons.ROLE_WORDS.get(c["role"], c["role"]), message=(m.get("body") or "")[:90]))
        return {"tile": tile, "title": "Messages sent", "empty": "Nothing has been sent yet. The monitor sends within contact hours." if live else "Nothing has been sent yet. Run an event.",
                "columns": [["event", "Event"], ["borrower", "Customer"], ["agent", "Agent"], ["channel", "Channel"],
                            ["message", "Message"]], "rows": out}
    if tile == "blocked":
        out = []
        for r in done:
            if r["q_outcome"] in ("BLOCKED", "SUPPRESSED", "DEFERRED"):
                d = db.one("SELECT data FROM decision_log WHERE event_id=? AND node='close_event' ORDER BY id DESC LIMIT 1",
                           (r["event_id"],))
                o = json.loads(d["data"]) if d and d["data"] else {}
                why = reasons.headline(db, o.get("rule_ids") or [], o.get("reason") or "")
                out.append(base(r, result=reasons.OUTCOME_WORDS.get(r["q_outcome"]), why=why, rules=", ".join(o.get("rule_ids") or [])))
        return {"tile": tile, "title": "Stopped or waiting", "empty": "Nothing has been stopped yet.",
                "columns": [["event", "Event"], ["borrower", "Customer"], ["result", "Result"], ["why", "Why"]], "rows": out}
    if tile == "borrowers":
        out = [base(r, result=reasons.OUTCOME_WORDS.get(r["q_outcome"], r["q_outcome"]), event_type=reasons.EVENT_WORDS.get(r["event_type"]))
               for r in done if r["q_outcome"] != "REJECTED"]
        return {"tile": tile, "title": "Borrowers handled", "empty": "No borrower has been handled yet.",
                "columns": [["borrower", "Customer"], ["event", "Event"], ["result", "Result"]], "rows": out}
    if tile == "faults":
        fired = {}
        for a, n, k in getattr(injector, "fired", []):
            fired.setdefault(a, []).append(k)
        sc = {a for (a, _) in (injector.script if injector else {})}
        out = []
        for r in rows:
            if r["customer_id"] in sc:
                happened = r["customer_id"] in fired
                rec = db.one("SELECT data FROM decision_log WHERE event_id=? AND node='monitor' ORDER BY id DESC LIMIT 1", (r["event_id"],))
                act = (json.loads(rec["data"]).get("action") if rec and rec["data"] else None)
                out.append(base(r, fault={"CRASH_AFTER_SEND": "Agent crashed after sending", "LOOP": "Agent kept saying it was still working"}
                                .get(fired.get(r["customer_id"], [""])[0], "Not yet triggered") if happened else "Not yet triggered",
                                recovered="Yes" if (happened and r["q_outcome"] == "CONTACTED") else ("Pending" if not happened else "No"),
                                how=reasons.RECOVERY_WORDS.get(act, "") if act else ""))
        return {"tile": tile, "title": "Faults and recovery", "empty": "No fault is scripted for the monitored borrowers." if live else "No fault is scripted for this scenario.",
                "columns": [["event", "Event"], ["fault", "What went wrong"], ["how", "What the supervisor did"],
                            ["recovered", "Recovered"]], "rows": out}
    if tile == "conflicts":
        det = audit.get("detail") or []
        return {"tile": tile, "title": "Conflicting contacts",
                "summary": f"{audit.get('checked', 0)} contacts re-checked by an independent audit; {audit.get('violations', 0)} conflicts found.",
                "empty": "None found. Every contact that went out was re-checked against the policy by a separate audit.",
                "columns": [["borrower", "Customer"], ["why", "What was wrong"]],
                "rows": [{"borrower": str(v.get("borrower") or v.get("account_id") or ""), "why": str(v.get("reason") or v)[:140]} for v in det]}
    if tile == "latency" and live:
        lat = latency or {}
        return {"tile": tile, "title": "How fast the supervisor chose an agent", "summary": "The target is under 100 ms.",
                "empty": "No decisions yet.", "columns": [["event", "Measure"], ["ms", "Time to choose"]],
                "rows": [{"event": f"{k} ({lat.get('samples', 0)} decisions)" if k == "Median" else k, "borrower": "", "ms": f"{lat.get(v, 0):.1f} ms"}
                         for k, v in (("Median", "median"), ("Slowest 5%", "p95"), ("Slowest", "max"))] if lat.get("samples") else []}
    if tile == "latency":
        out = []
        for r in rows:
            s = db.one("SELECT ms FROM run_step WHERE event_id=? AND node='route'", (r["event_id"],))
            if s:
                out.append(base(r, ms=f"{s['ms']:.1f} ms"))
        return {"tile": tile, "title": "How fast the supervisor chose an agent", "summary": "The target is under 100 ms.",
                "empty": "Run an event to measure it.",
                "columns": [["event", "Event"], ["borrower", "Customer"], ["ms", "Time to choose"]], "rows": out}
    return None
