"""Read side of the Journey Runs screen and the notification bell: both read the journey_run table (real runs only)."""
from __future__ import annotations

import json
from datetime import datetime

from orchestrator.ui import reasons

SORT = {"finished": "finished_wall", "event_time": "event_time", "borrower_id": "r.borrower_id", "outcome": "outcome",
        "duration_ms": "duration_ms", "event_type": "event_type"}
BASE = "FROM journey_run r LEFT JOIN ds_person p ON p.borrower_id = r.borrower_id"


FIX_SHORT = {"RESUME": "retried", "RESTART_SKIP_CURRENT": "not sent again", "REROUTE_CHANNEL": "other channel",
             "ESCALATE": "sent to a person", "QUARANTINE": "held for review"}
FAULT_WORDS = {"CRASH": "crash", "TIMEOUT": "timeout", "MALFORMED": "garbled reply", "NO_PROGRESS": "stall"}


def _row(r) -> dict:
    d = dict(r)
    d["rule_ids"] = json.loads(d["rule_ids"] or "[]")
    d["outcome_label"] = reasons.OUTCOME_WORDS.get(d["outcome"], d["outcome"])
    d["finished_at"] = datetime.fromtimestamp(d["finished_wall"]).isoformat(timespec="seconds") if d["finished_wall"] else None
    d["had_fault"] = bool(d["fault"])
    d["fault_label"] = FAULT_WORDS.get(d["fault"], (d["fault"] or "").replace("_", " ").lower()) or None
    d["recovery_label"] = FIX_SHORT.get(d["recovery_action"], "recovered") if d["fault"] else None
    d["notify_seen"] = bool(d["notify_seen"])
    return d


def journey_runs(db, params: dict) -> dict:
    page = max(1, int(params.get("page") or 1))
    size = min(200, max(1, int(params.get("page_size") or 25)))
    col = SORT.get(params.get("sort_by") or "finished", "finished_wall")
    direction = "ASC" if (params.get("sort_dir") or "desc").lower() == "asc" else "DESC"
    cond, args = [], []
    if params.get("outcome"):
        cond.append("outcome=?"); args.append(params["outcome"])
    if params.get("borrower_id"):
        cond.append("r.borrower_id LIKE ?"); args.append(f"{params['borrower_id'].strip()}%")
    if str(params.get("faults_only", "")).lower() in ("1", "true", "yes"):
        cond.append("r.fault IS NOT NULL")
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    total = db.one(f"SELECT COUNT(*) n {BASE}{where}", args)["n"]
    rows = [_row(r) for r in db.query(
        f"SELECT r.*, p.name_masked {BASE}{where} ORDER BY {col} {direction}, r.id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size])]
    pin = [x for x in (params.get("pin") or "").split(",") if x]       # runs the manager was sent to: always on the page
    pinned = []
    if pin:
        ph = ",".join("?" * len(pin))
        pinned = [_row(r) for r in db.query(f"SELECT r.*, p.name_masked {BASE} WHERE r.event_id IN ({ph})", pin)]
        have = {r["event_id"] for r in rows}
        rows = pinned + [r for r in rows if r["event_id"] not in {p["event_id"] for p in pinned}]
        total += sum(1 for p in pinned if p["event_id"] not in have)
    return {"items": rows, "total": total, "page": page, "page_size": size}


# ---------------------------------------------------------------- the bell
def notifications(db, limit: int = 20) -> dict:
    """Faults the supervisor recovered that the collections manager has not opened yet."""
    n = db.one("SELECT COUNT(*) n FROM journey_run WHERE fault IS NOT NULL AND notify_seen=0")["n"]
    items = [_row(r) for r in db.query(
        f"SELECT r.*, p.name_masked {BASE} WHERE r.fault IS NOT NULL AND r.notify_seen=0 ORDER BY r.id DESC LIMIT ?", (limit,))]
    for i in items:
        i["message"] = notice_text(i)
    return {"unseen": n, "items": items}


AGENT_WORDS = {"whatsapp": "WhatsApp agent", "email": "Email agent", "voice": "Voice agent"}


def notice_text(r: dict) -> str:
    """The one-line alert: which agent, which fault, and that the supervisor is already recovering it."""
    key = (r.get("fault_agent") or "").replace("_agent", "")
    agent = AGENT_WORDS.get(key) or (f"{key.replace('_', ' ').capitalize()} agent" if key else "Channel agent")
    fault = (r.get("fault_label") or "fault").capitalize()
    return f"Alert Supervisor Agent - {agent}/{fault} happened and recovering"


def mark_seen(db, event_ids: list[str] | None) -> int:
    if event_ids:
        ph = ",".join("?" * len(event_ids))
        return db.execute(f"UPDATE journey_run SET notify_seen=1 WHERE event_id IN ({ph})", event_ids)
    return db.execute("UPDATE journey_run SET notify_seen=1 WHERE notify_seen=0")


def max_fault_id(db) -> int:
    return db.one("SELECT COALESCE(MAX(id),0) m FROM journey_run WHERE fault IS NOT NULL")["m"]


def new_faults(db, after_id: int) -> list[dict]:
    rows = db.query(f"SELECT r.*, p.name_masked {BASE} WHERE r.fault IS NOT NULL AND r.id > ? ORDER BY r.id", (after_id,))
    out = []
    for r in rows:
        d = _row(r); d["message"] = notice_text(d); out.append(d)
    return out
