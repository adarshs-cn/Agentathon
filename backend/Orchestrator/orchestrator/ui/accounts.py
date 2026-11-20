"""Read-side queries behind the Accounts grid, the borrower search and the borrower state card.

Everything here is a SELECT against the same SQLite database the supervisor writes.
Names and phone numbers are the MASKED forms stored at load time ('D*** S***', 'XXXXXX4842').
"""
from __future__ import annotations

from datetime import datetime

from orchestrator.policy.d12 import CHANNEL_AGENT

# The UI's five account statuses, derived from the D1 flags (legal outranks restructured outranks settlement).
STATUS_SQL = ("CASE WHEN a.legal_flag=1 THEN 'legal' WHEN a.restructure_flag=1 THEN 'restructured' "
              "WHEN a.settlement_flag=1 THEN 'settled' WHEN a.dpd>0 THEN 'overdue' ELSE 'current' END")
SORT_COLUMNS = {
    "account_id": "a.account_id", "customer_id": "a.customer_id", "borrower_name": "p.name_masked",
    "product": "a.product", "loan_amount": "a.loan_amount", "principal_outstanding": "a.principal_outstanding",
    "total_overdue": "a.total_dues", "installment_amount": "a.emi", "dpd": "a.dpd", "delinquency_bucket": "a.dpd",
    "account_status": STATUS_SQL, "city": "a.city", "contact_no": "p.phone_masked",
}
BUCKETS = ["0", "1-30", "31-60", "61-90", "90+"]
SELECT = (f"SELECT a.account_id, a.customer_id, p.name_masked AS borrower_name, a.product, a.loan_amount, "
          f"a.principal_outstanding, a.total_dues AS total_overdue, a.emi AS installment_amount, a.dpd, "
          f"a.bucket AS delinquency_bucket, {STATUS_SQL} AS account_status, a.restructure_flag, a.settlement_flag, "
          f"a.legal_flag, a.city, p.phone_masked AS contact_no "
          f"FROM account a JOIN customer p ON p.customer_id = a.customer_id")


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def _where(params: dict) -> tuple[str, list]:
    cond, args = [], []
    like = {"account_id": "a.account_id", "customer_id": "a.customer_id"}
    for key, col in like.items():
        if params.get(key):
            cond.append(f"{col} LIKE ?"); args.append(f"{params[key].strip()}%")
    if params.get("borrower_name"):
        cond.append("p.name_masked LIKE ?"); args.append(f"%{params['borrower_name'].strip()}%")
    if params.get("contact_number"):
        cond.append("p.phone_masked LIKE ?"); args.append(f"%{params['contact_number'].strip()}%")
    if params.get("account_status"):
        cond.append(f"{STATUS_SQL} = ?"); args.append(params["account_status"])
    for key, col in (("product", "a.product"), ("bucket", "a.bucket"), ("city", "a.city")):
        if params.get(key):
            cond.append(f"{col} = ?"); args.append(params[key])
    for key, col, op in (("dpd_min", "a.dpd", ">="), ("dpd_max", "a.dpd", "<="),
                         ("loan_min", "a.loan_amount", ">="), ("loan_max", "a.loan_amount", "<=")):
        if params.get(key) not in (None, ""):
            try:
                cond.append(f"{col} {op} ?"); args.append(float(params[key]))
            except ValueError:
                cond.pop()
    for key, col in (("restructure", "a.restructure_flag"), ("settlement", "a.settlement_flag"), ("legal", "a.legal_flag")):
        if _truthy(params.get(key, "")):
            cond.append(f"{col} = 1")
    return (" WHERE " + " AND ".join(cond)) if cond else "", args


def filter_options(db) -> dict:
    q = db.query
    return {"products": [r[0] for r in q("SELECT DISTINCT product FROM account WHERE product != '' ORDER BY 1")],
            "buckets": BUCKETS,
            "cities": [r[0] for r in q("SELECT DISTINCT city FROM account WHERE city != '' ORDER BY 1")]}


def search(db, text: str, limit: int = 8) -> list[dict]:
    text = (text or "").strip()
    if len(text) < 2:
        return []
    rows = db.query(SELECT + " WHERE a.account_id LIKE ? OR a.customer_id LIKE ? ORDER BY a.dpd DESC LIMIT ?",
                    (f"{text}%", f"{text}%", limit))
    return [{"account_id": r["account_id"], "customer_id": r["customer_id"], "name": r["borrower_name"],
             "dpd": r["dpd"], "bucket": r["delinquency_bucket"], "status": r["account_status"]} for r in rows]


def resolve_borrower(db, any_id: str) -> str | None:
    """Accept an account id (ACC...) or a borrower id (BRW...)."""
    r = db.one("SELECT customer_id FROM account WHERE account_id=?", (any_id,))
    if r:
        return r["customer_id"]
    r = db.one("SELECT customer_id FROM customer WHERE customer_id=?", (any_id,))
    return r["customer_id"] if r else None


def _last_contact_and_owner(db, engine, borrowers: list[str], now: datetime) -> dict:
    out = {b: {"owner": None, "last": None} for b in borrowers}
    if not borrowers:
        return out
    ph = ",".join("?" * len(borrowers))
    for r in db.query(f"SELECT customer_id b, MAX(at) t FROM ds_history WHERE customer_id IN ({ph}) GROUP BY customer_id", borrowers):
        out[r["b"]]["last"] = r["t"]
    for r in db.query(f"SELECT customer_id b, MAX(at) t FROM contact_log WHERE customer_id IN ({ph}) "
                      f"AND status IN ('ATTEMPTING','SENT') GROUP BY customer_id", borrowers):
        if r["t"] and (out[r["b"]]["last"] is None or r["t"] > out[r["b"]]["last"]):
            out[r["b"]]["last"] = r["t"]
    for b in borrowers:
        owner, until = engine.current_owner(engine.facts(b, now))
        out[b]["owner"] = f"{owner}_agent" if owner and not owner.startswith("AGY") else owner
    return out


def list_accounts(db, engine, params: dict, now: datetime) -> dict:
    page = max(1, int(params.get("page") or 1))
    size = min(200, max(1, int(params.get("page_size") or 25)))
    col = SORT_COLUMNS.get(params.get("sort_by") or "dpd", "a.dpd")
    direction = "ASC" if (params.get("sort_dir") or "desc").lower() == "asc" else "DESC"
    where, args = _where(params)
    total = db.one(f"SELECT COUNT(*) n FROM account a JOIN customer p ON p.customer_id = a.customer_id{where}", args)["n"]
    rows = [dict(r) for r in db.query(f"{SELECT}{where} ORDER BY {col} {direction}, a.account_id LIMIT ? OFFSET ?",
                                      args + [size, (page - 1) * size])]
    extra = _last_contact_and_owner(db, engine, sorted({r["customer_id"] for r in rows}), now)
    for r in rows:
        for flag in ("restructure_flag", "settlement_flag", "legal_flag"):
            r[flag] = bool(r[flag])
        e = extra[r["customer_id"]]
        r["case_owner_user_id"] = e["owner"]
        r["last_disposition_date"] = e["last"][:10] if e["last"] else None
        r["total_outstanding"] = None          # not in D1: left empty rather than invented
        r["installment_overdue"] = None
    return {"items": rows, "total": total, "page": page, "page_size": size}


# ---------------------------------------------------------------------- one borrower
def customer_state(db, engine, any_id: str, now: datetime) -> dict | None:
    b = resolve_borrower(db, any_id)
    if b is None:
        return None
    f = engine.facts(b, now)
    worst = db.one("SELECT account_id FROM account WHERE customer_id=? ORDER BY dpd DESC LIMIT 1", (b,))
    probe = {"id": "probe", "type": "DUE_SOON" if f.dpd == 0 else "OVERDUE", "account_id": worst["account_id"] if worst else b,
             "customer_id": b, "time": now.isoformat()}
    guard = engine.guard(f, probe)
    plan = engine.plan(f, probe) if guard["status"] == "OK" else None
    owner, until = engine.current_owner(f)

    day_cap, day_ids = engine._cap(engine.day_caps, f.bucket, "ALL")
    wk_cap, wk_ids = engine._cap(engine.week_caps, f.bucket, "ALL")
    used_day = engine._count(f, None, f.today)
    from datetime import timedelta
    used_wk = engine._count(f, None, (now.date() - timedelta(days=6)).isoformat())
    by_channel = {}
    for ch in ("whatsapp", "email", "call", "sms"):
        cap, ids = engine._cap(engine.day_caps, f.bucket, ch)
        by_channel[ch] = {"used": engine._count(f, ch, f.today), "cap": cap, "rule_ids": ids,
                          "integrated": ch in CHANNEL_AGENT}

    holds = []
    sup = (f.consent.get("suppression_reason") or "none")
    if f.person.get("deceased"):
        holds.append({"kind": "deceased", "rule": "R058", "detail": "borrower is deceased"})
    elif sup != "none":
        holds.append({"kind": "suppression", "rule": {"customer_request": "R059", "complaint": "R060", "dispute": "R061"}.get(sup, "R058"),
                      "detail": f"{sup} since {f.consent.get('suppression_from') or 'unknown'}"})
    for p in f.ptps:
        if p["status"] == "open" and p["promised_date"] >= f.today:
            holds.append({"kind": "open_ptp", "rule": "R062", "detail": f"promise of ₹{p['amount']:,.0f} due {p['promised_date']}"})
    for p in f.payments:
        if p["status"] == "success" and not p["reversal"] and datetime.fromisoformat(p["at"]) + timedelta(hours=48) > now:
            holds.append({"kind": "payment_hold", "rule": "R066", "detail": f"payment of ₹{p['amount']:,.0f} at {p['at'][:16]} (48 h hold)"})

    contacts = sorted(f.contacts, key=lambda c: c.at, reverse=True)
    consent = {k: f.consent.get(k) for k in ("consent_call", "consent_sms", "consent_whatsapp", "consent_email", "dnd_status",
                                              "requested_window", "suppression_reason", "consent_expiry", "consent_source")}
    accounts = [dict(r) for r in db.query(
        f"{SELECT} WHERE a.customer_id=? ORDER BY a.dpd DESC", (b,))]
    for a in accounts:
        for flag in ("restructure_flag", "settlement_flag", "legal_flag"):
            a[flag] = bool(a[flag])
    state = db.one("SELECT owner, last_contact, status, commitments FROM customer_state WHERE customer_id=?", (b,))
    return {
        "customer_id": b, "requested_id": any_id,
        "name": accounts[0]["borrower_name"] if accounts else "", "phone": accounts[0]["contact_no"] if accounts else "",
        "accounts": accounts,
        "facts": {"dpd": f.dpd, "bucket": f.bucket, "legal": f.legal, "settlement": f.settlement, "restructure": f.restructure,
                  "deceased": bool(f.person.get("deceased")), "shared_phone": bool(f.person.get("shared_phone")),
                  "has_phone": bool(f.person.get("has_phone")), "has_email": bool(f.person.get("has_email"))},
        "state": {"status": state["status"] if state else None, "in_flight_owner": state["owner"] if state else None,
                  "last_contact": state["last_contact"] if state else None},
        "ownership": {"role": owner, "until": until.isoformat() if until else None},
        "consent": consent,
        "caps": {"today": {"used": used_day, "cap": day_cap, "rule_ids": day_ids},
                 "week": {"used": used_wk, "cap": wk_cap, "rule_ids": wk_ids}, "by_channel": by_channel},
        "holds": holds,
        "probe": {"as_of": now.isoformat(), "event_type": probe["type"], "guard": {k: guard[k] for k in ("status", "rule_ids", "reason")},
                  "plan": None if plan is None else {
                      "status": plan["status"], "role": plan.get("role"), "action": plan.get("action"),
                      "channel_agents": plan.get("channel_agents", []), "rule_ids": plan["rule_ids"],
                      "reason": plan.get("reason", ""), "handoff": plan.get("handoff"),
                      "considered": [{"role": c["role"], "action": c.get("action"),
                                      "channels": [{k: r.get(k) for k in ("channel", "status", "rule_ids", "reason", "defer_until")}
                                                   for r in c.get("channels", [])],
                                      "status": c.get("status"), "reason": c.get("reason"), "rule_ids": c.get("rule_ids")}
                                     for c in plan["considered"]],
                      "excluded": plan.get("excluded", [])}},
        "recent_contacts": [{"at": c.at.isoformat(), "channel": c.channel, "role": c.role, "source": c.source,
                             "disposition": c.disposition} for c in contacts[:15]],
        "ptps": [{"promised_date": p["promised_date"], "amount": p["amount"], "status": p["status"],
                  "captured_by": p["captured_by"]} for p in sorted(f.ptps, key=lambda x: x["promised_date"], reverse=True)[:6]],
    }

