"""An INDEPENDENT audit of contacts against the D12/D10 policy.

The policy engine decides what to send. This module re-checks what was actually sent, using its
own code and its own plain reading of the rules, so a mistake in the engine cannot hide itself:
a rule the engine applies wrongly every time would still pass the engine's own tests.

It is also pointed at the HISTORICAL contacts in D4 (the world before the supervisor), where it
should find the violations the dataset deliberately planted. That proves the audit can see them.

    violations = audit_ours(db)                 # what this supervisor sent
    violations = audit_history(db, as_of)       # what D4 says happened before

Each violation is (code, rule id, borrower, time, detail).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

HARD_WINDOW = (8 * 60, 19 * 60)
DAY_CAP_GLOBAL, WEEK_CAP_GLOBAL = 3, 10
DAY_CAP_BUCKET = {"0": 1, "1-30": 2, "31-60": 3, "61-90": 3, "90+": 2}
DAY_CAP_CHANNEL = {"call": 2, "sms": 2, "whatsapp": 1, "email": 1, "field_visit": 1}
CONSENT_COL = {"call": "consent_call", "sms": "consent_sms", "whatsapp": "consent_whatsapp", "email": "consent_email"}
DENIED_RULE = {"call": "R043", "sms": "R044", "whatsapp": "R045", "email": "R046"}
DND_PURPOSES = {"payment_confirmation", "emi_due_reminder", "ptp_reminder", "statement", "service_request"}
PRIORITY = {"legal": 1, "negotiation": 2, "agency": 3, "servicing": 4, "reminder": 5}
LEASE_EXEMPT = {"payment_confirmation", "statement", "service_request", "closure_letter"}
OUR_CHANNEL = {"voice": "call"}


def _role(a: str) -> str:
    a = a or ""
    return a[:-6] if a.endswith("_agent") else ("agency" if a.startswith("AGY") else a)


def _chan(c: str) -> str:
    c = (c or "").lower()
    return OUR_CHANNEL.get(c, "call" if c == "ivr" else c)


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T"))


class _Data:
    """Lazily loads what the checks need for each borrower."""
    def __init__(self, db):
        self.db, self._c = db, {}

    def get(self, b: str) -> dict:
        if b not in self._c:
            q = self.db.query
            accounts = [dict(r) for r in q("SELECT * FROM account WHERE customer_id=?", (b,))]
            worst = max(accounts, key=lambda a: a["dpd"]) if accounts else {"dpd": 0, "bucket": "0"}
            self._c[b] = {
                "person": dict(self.db.one("SELECT * FROM customer WHERE customer_id=?", (b,)) or {}),
                "consent": dict(self.db.one("SELECT * FROM ds_consent WHERE customer_id=?", (b,)) or {}),
                "accounts": accounts, "dpd": worst["dpd"], "bucket": worst["bucket"],
                "legal": any(a["legal_flag"] for a in accounts), "settlement": any(a["settlement_flag"] for a in accounts),
                "restructure": any(a["restructure_flag"] for a in accounts),
                "ptps": [dict(r) for r in q("SELECT * FROM ds_ptp WHERE customer_id=?", (b,))],
                "payments": [dict(r) for r in q("SELECT * FROM ds_payment WHERE customer_id=?", (b,))],
                "history": [dict(r) for r in q("SELECT at, agent, channel, disposition FROM ds_history WHERE customer_id=?", (b,))],
                "wrong_number": self.db.one("SELECT 1 FROM ds_history WHERE customer_id=? AND disposition='wrong_number' LIMIT 1", (b,)) is not None,
            }
        return self._c[b]


def check_contact(d: dict, c: dict, strict_purpose: bool = True) -> list[tuple]:
    """Violations of rules that concern ONE contact. c = {borrower, at, role, channel, action}."""
    out = []
    at, ch, role, action = _t(c["at"]), c["channel"], c["role"], c.get("action")
    today = at.date().isoformat()
    p, k = d["person"], d["consent"]
    sup, sup_from = k.get("suppression_reason") or "none", k.get("suppression_from") or ""
    sup_active = sup != "none" and (not sup_from or sup_from[:10] <= today)

    if p.get("deceased") or (sup_active and sup == "deceased"):
        out.append(("DECEASED", "R058", "contacted a deceased borrower"))
    if sup_active and sup == "customer_request":
        out.append(("SUPPRESSED", "R059", "customer asked to stop"))
    if sup_active and sup == "complaint" and (not sup_from or today <= (_t(sup_from[:10]) + timedelta(days=30)).date().isoformat()):
        out.append(("SUPPRESSED", "R060", "open complaint"))
    if sup_active and sup == "dispute" and ch in ("call", "sms", "whatsapp", "field_visit"):
        out.append(("SUPPRESSED", "R061", f"disputed debt, {ch} contact"))

    if ch in CONSENT_COL:
        st = k.get(CONSENT_COL[ch]) or "unknown"
        opt = k.get(f"optout_{ch}") or ""
        if opt and _t(opt).date() <= at.date():
            out.append(("OPTED_OUT", "R047", f"opted out of {ch} on {opt[:10]}"))
        if st in ("denied", "revoked"):
            out.append(("NO_CONSENT", DENIED_RULE[ch], f"{ch} consent {st}"))
        if ch == "whatsapp":
            if st != "granted":
                out.append(("NO_CONSENT", "R045", f"WhatsApp consent is {st}"))
            if k.get("consent_expiry_date") or k.get("consent_expiry"):
                exp = k.get("consent_expiry") or k.get("consent_expiry_date")
                if exp and exp[:10] < today:
                    out.append(("CONSENT_EXPIRED", "R048", f"WhatsApp consent expired {exp[:10]}"))
    if ch in ("call", "sms") and (k.get("dnd_status") or "none") in ("fully_blocked", "partially_blocked"):
        eff = k.get("dnd_effective_from") or ""
        if (not eff or eff[:10] <= today) and (action not in DND_PURPOSES):
            out.append(("DND", "R050", f"DND {k['dnd_status']}, {ch}" + (f", purpose {action}" if action else "")))

    m = at.hour * 60 + at.minute
    if not (HARD_WINDOW[0] <= m < HARD_WINDOW[1]):
        out.append(("OUT_OF_HOURS", "R007", f"contact at {at.time().isoformat(timespec='minutes')}"))
    rw = (k.get("requested_window") or k.get("borrower_requested_window") or "")
    if rw and "-" in rw:
        s, e = rw.split("-")
        lo, hi = int(s[:2]) * 60 + int(s[3:5]), int(e[:2]) * 60 + int(e[3:5])
        if not (lo <= m < hi):
            out.append(("OUTSIDE_REQUESTED_WINDOW", "R006", f"asked for {rw}, contacted {at.time().isoformat(timespec='minutes')}"))

    if ch in ("call", "sms", "whatsapp") and not p.get("has_phone"):
        out.append(("NO_CONTACT_DETAIL", "R069", "no phone on record"))
    if ch == "email" and not p.get("has_email"):
        out.append(("NO_CONTACT_DETAIL", "R070", "no email on record"))
    return out


def audit_ours(db) -> list[tuple]:
    """Everything this supervisor sent, against every rule (caps and ownership included)."""
    data, v = _Data(db), []
    rows = db.query("SELECT customer_id b, channel, role, purpose action, at, event_id FROM contact_log "
                    "WHERE status IN ('SENT','ATTEMPTING') ORDER BY at")
    ours = defaultdict(list)
    for r in rows:
        ours[r["b"]].append({"borrower": r["b"], "at": r["at"], "role": r["role"], "channel": _chan(r["channel"]),
                             "action": r["action"], "event": r["event_id"]})
    for b, contacts in ours.items():
        d = data.get(b)
        for c in contacts:
            for code, rule, why in check_contact(d, c):
                v.append((code, rule, b, c["at"], why))
            at = _t(c["at"])
            if c["channel"] in ("call", "sms", "whatsapp") and d["person"].get("shared_phone"):
                v.append(("SHARED_PHONE", "R056", b, c["at"], "phone shared with another borrower"))
            if c["channel"] in ("call", "sms", "whatsapp") and d["wrong_number"]:
                v.append(("WRONG_NUMBER", "R055", b, c["at"], "wrong-number quarantine"))
            if c["action"] != "payment_confirmation":
                for pay in d["payments"]:
                    if pay["status"] == "success" and not pay["reversal"] and _t(pay["at"]) <= at < _t(pay["at"]) + timedelta(hours=48):
                        v.append(("PAYMENT_HOLD", "R066", b, c["at"], f"payment at {pay['at']}"))
            future = [pt for pt in d["ptps"] if pt["status"] == "open" and pt["promised_date"] >= at.date().isoformat()]
            if future and c["action"] not in LEASE_EXEMPT:           # R062 holds recovery, not service replies                                    # R062: held; R063: except the one reminder the day before
                nxt = (at.date() + timedelta(days=1)).isoformat()
                if not (c["action"] == "ptp_reminder" and any(pt["promised_date"] == nxt for pt in future)):
                    v.append(("OPEN_PTP", "R062", b, c["at"], f"promise due {min(pt['promised_date'] for pt in future)}"))
            role = c["role"]
            if d["legal"] and role != "legal":
                v.append(("WRONG_AGENT", "R040", b, c["at"], f"{role} contacted a legal-flag borrower"))
            if d["settlement"] and role not in ("negotiation", "legal"):
                v.append(("WRONG_AGENT", "R041", b, c["at"], f"{role} contacted a settlement-flag borrower"))
            if d["restructure"] and role == "legal":
                v.append(("WRONG_AGENT", "R042", b, c["at"], "legal contacted a restructure-flag borrower"))
            if role == "legal" and d["dpd"] < 91 and not d["legal"]:
                v.append(("WRONG_AGENT", "R075", b, c["at"], f"legal at {d['dpd']} DPD"))
            m = db.one("SELECT allowed, contact FROM ds_matrix WHERE agent=? AND bucket=?", (f"{role}_agent", d["bucket"]))
            if not (d["legal"] and role == "legal") and (m is None or not m["allowed"] or not m["contact"]):
                v.append(("WRONG_AGENT", "D12-matrix", b, c["at"], f"{role}_agent may not contact bucket {d['bucket']}"))

        # ---- frequency caps: history + ours, per borrower (R033), failed attempts included (R034)
        hist = [{"at": _t(h["at"]), "channel": _chan(h["channel"]), "role": _role(h["agent"])} for h in d["history"]]
        mine = [{"at": _t(c["at"]), "channel": c["channel"], "role": c["role"]} for c in contacts]
        for day in sorted({x["at"].date() for x in mine}):
            both = [x for x in hist + mine if x["at"].date() == day]
            cap = min(DAY_CAP_GLOBAL, DAY_CAP_BUCKET[d["bucket"]])
            if len(both) > cap:
                v.append(("OVER_CAP", "R009", b, day.isoformat(), f"{len(both)} contacts, cap {cap} for bucket {d['bucket']}"))
            for ch in {x["channel"] for x in mine if x["at"].date() == day}:
                n = sum(1 for x in both if x["channel"] == ch)
                if ch in DAY_CAP_CHANNEL and n > DAY_CAP_CHANNEL[ch]:
                    v.append(("OVER_CAP", "R011-R019", b, day.isoformat(), f"{n} {ch} contacts, cap {DAY_CAP_CHANNEL[ch]}"))
            week = [x for x in hist + mine if day - timedelta(days=6) <= x["at"].date() <= day]
            if len(week) > WEEK_CAP_GLOBAL:
                v.append(("OVER_CAP", "R010", b, day.isoformat(), f"{len(week)} contacts in 7 days"))

        # ---- ownership (R035/R036/R039): the holder is whoever made the latest contact in the previous 24 hours.
        # A different role may only contact if it outranks the holder, or if it is sending a service reply.
        timeline = sorted(hist + mine, key=lambda x: x["at"])
        action_at = {(_t(c["at"]), c["channel"]): c["action"] for c in contacts}
        for i, x in enumerate(timeline):
            if x not in mine or action_at.get((x["at"], x["channel"])) in LEASE_EXEMPT:
                continue
            before = [y for y in timeline[:i] if timedelta(0) <= x["at"] - y["at"] < timedelta(hours=24)]
            if not before:
                continue
            holder = before[-1]
            hr = _role(holder["role"]) if _role(holder["role"]) in PRIORITY else "agency"
            if holder["role"] != x["role"] and PRIORITY[x["role"]] >= PRIORITY[hr]:
                v.append(("NON_OWNER", "R036", b, x["at"].isoformat(),
                          f"{x['role']} contacted while {holder['role']} held the lease"))
    return v


def audit_history(db, as_of: str) -> list[tuple]:
    """The historical D4 contacts, checked with the single-contact rules (no purpose is known for them, so
    DND is checked strictly). Shows what the world looked like before there was a supervisor."""
    data, v = _Data(db), []
    for r in db.query("SELECT customer_id b, at, agent, channel FROM ds_history WHERE substr(at,1,10) <= ?", (as_of,)):
        c = {"borrower": r["b"], "at": r["at"], "role": _role(r["agent"]), "channel": _chan(r["channel"]), "action": None}
        for code, rule, why in check_contact(data.get(r["b"]), c, strict_purpose=True):
            v.append((code, rule, r["b"], r["at"], why))
    return v


def summarise(violations: list[tuple]) -> dict:
    out: dict = defaultdict(int)
    for code, rule, *_ in violations:
        out[f"{code} ({rule})"] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
