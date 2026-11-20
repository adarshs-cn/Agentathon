"""The 15 demo events (documentation/04-demo-scenario.md), built from the REAL loaded portfolio.

For each row the builder runs a selection query against the dataset (first match in borrower-id order, so the same
borrowers every time), applies a small, listed setup where a situation must be staged (a promise to pay, a payment,
a contact made yesterday), publishes ONE event, and records it in `demo_event`. Nothing is processed until Run.
If a selection finds nobody the builder raises: it never quietly substitutes another borrower.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from orchestrator.agents.fault_injector import FaultInjector

CLEAN = """
  a.borrower_id IN (SELECT borrower_id FROM ds_account GROUP BY borrower_id HAVING COUNT(*)=1)
  AND p.deceased=0 AND p.shared_phone=0 AND p.has_phone=1
  AND c.suppression_reason='none' AND c.dnd_status='none' AND c.requested_window=''
  AND c.consent_source<>'' AND c.consent_expiry=''
  AND c.optout_call='' AND c.optout_sms='' AND c.optout_whatsapp='' AND c.optout_email=''
  AND a.settlement_flag=0 AND a.restructure_flag=0
  AND NOT EXISTS (SELECT 1 FROM ds_history h WHERE h.borrower_id=a.borrower_id AND h.at >= ?)
  AND NOT EXISTS (SELECT 1 FROM ds_ptp t WHERE t.borrower_id=a.borrower_id AND t.status='open')
  AND NOT EXISTS (SELECT 1 FROM ds_payment y WHERE y.borrower_id=a.borrower_id AND y.at >= ?)
"""
WA = "c.consent_whatsapp='granted'"
CALL = "c.consent_call='granted'"
EMAIL = "c.consent_email='granted' AND p.has_email=1"


@dataclass
class Spec:
    key: str
    label: str
    etype: str
    time: str                 # HH:MM on the dataset's "today"
    where: str                # extra selection on a (account), c (consent), p (person)
    setup: str = ""           # what is staged beforehand (see _setup)
    depends_on: int | None = None
    fault: str = ""           # fault script for this borrower
    note: str = ""


SPECS = [
    Spec("happy", "Reminder due", "DUE_SOON", "09:00", f"a.dpd=0 AND a.legal_flag=0 AND {WA}",
         note="The happy path, start to finish."),
    Spec("fallback", "Reminder due, WhatsApp not allowed", "DUE_SOON", "09:05",
         f"a.dpd=0 AND a.legal_flag=0 AND c.consent_whatsapp='unknown' AND {EMAIL}",
         note="Consent is read, and the supervisor falls back to another channel."),
    Spec("stage", "Payment overdue, 31 to 60 days", "OVERDUE", "09:10",
         f"a.dpd BETWEEN 31 AND 60 AND a.legal_flag=0 AND {CALL}", note="A different role and channel for a later stage."),
    Spec("handoff", "A higher-priority agent takes over", "OVERDUE", "09:15",
         f"a.dpd BETWEEN 31 AND 60 AND a.legal_flag=0 AND {CALL}", setup="reminder_contact_yesterday",
         note="One owner at a time; ownership can pass to a higher-priority agent, and it is logged."),
    Spec("ptp_due", "Promise due tomorrow", "PTP_DUE", "09:20", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA}",
         setup="open_promise_tomorrow", note="Only the promise's owner may remind."),
    Spec("ptp_broken", "Promise broken", "PTP_BROKEN", "09:25", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {CALL}",
         setup="broken_promise", note="A broken promise moves ownership to Negotiation."),
    Spec("paid", "Payment received", "PAYMENT_RECEIVED", "09:30", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA}",
         setup="payment_today", note="Confirmations are allowed even during the 48-hour payment hold."),
    Spec("promise_open", "Overdue, but a promise is open", "OVERDUE", "09:35",
         "a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0", setup="open_promise_in_3_days",
         note="The supervisor refuses, and says why in words."),
    Spec("stop_request", "Borrower asked us to stop", "OVERDUE", "09:40", "SUPPRESSED:customer_request",
         note="Suppression beats everything else."),
    Spec("hours", "Outside contact hours", "OVERDUE", "07:30", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA}",
         note="Nothing is lost; it is rescheduled."),
    Spec("pair_1", "Two requests at once: the first", "OVERDUE", "14:00", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA}",
         note="First of a pair."),
    Spec("pair_2", "Two requests at once: the second", "CONTACT_REQUESTED", "14:02", "SAME_AS:pair_1", depends_on=11,
         note="Two agents fire on the same borrower at once and exactly one contact goes out."),
    Spec("crash_after", "Agent crashes after sending", "OVERDUE", "10:00", f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA}",
         fault="CRASH_AFTER_SEND", note="The hardest fault: a crash after the send must not double-contact."),
    Spec("loop", "Agent stops making progress", "OVERDUE", "10:05",
         f"a.dpd BETWEEN 1 AND 30 AND a.legal_flag=0 AND {WA} AND {EMAIL}", fault="LOOP",
         note="Loop detection, then switching channel."),
    Spec("legal", "Legal case", "OVERDUE", "10:10", f"a.legal_flag=1 AND a.dpd>=91 AND {EMAIL}",
         note="A legal flag means only the Legal agent may act."),
]


def _setup(db, seq: int, kind: str, b: str, acc: str, as_of: str) -> None:
    d = date.fromisoformat(as_of)
    tomorrow, yesterday = (d + timedelta(days=1)).isoformat(), (d - timedelta(days=1)).isoformat()
    in3 = (d + timedelta(days=3)).isoformat()

    def log(table, key):
        db.execute("INSERT INTO demo_setup(seq, table_name, row_key) VALUES (?,?,?)", (seq, table, key))

    def ptp(pid, when, status):
        db.execute("INSERT INTO ds_ptp(ptp_id, account_id, borrower_id, promised_date, amount, captured_by, status) "
                   "VALUES (?,?,?,?,?,?,?)", (pid, acc, b, when, 5000, "reminder_agent", status))
        log("ds_ptp", pid)
    if kind == "reminder_contact_yesterday":
        db.execute("INSERT INTO ds_history(borrower_id, account_id, at, agent, channel, disposition) VALUES (?,?,?,?,?,?)",
                   (b, acc, f"{yesterday}T18:00:00", "reminder_agent", "whatsapp", "delivered"))
        log("ds_history", f"{b}@{yesterday}T18:00")
    elif kind == "open_promise_tomorrow":
        ptp(f"DEMO-{seq}", tomorrow, "open")
    elif kind == "broken_promise":
        ptp(f"DEMO-{seq}", yesterday, "broken")
    elif kind == "open_promise_in_3_days":
        ptp(f"DEMO-{seq}", in3, "open")
    elif kind == "payment_today":
        db.execute("INSERT INTO ds_payment(txn_id, account_id, borrower_id, at, amount, status, reversal) "
                   "VALUES (?,?,?,?,?,?,?)", (f"DEMO-{seq}", acc, b, f"{as_of}T08:30:00", 5000, "success", 0))
        log("ds_payment", f"DEMO-{seq}")


def _pick(db, spec: Spec, used: set, chosen: dict, as_of: str):
    since = (date.fromisoformat(as_of) - timedelta(days=8)).isoformat()
    paid_since = (date.fromisoformat(as_of) - timedelta(days=3)).isoformat()
    if spec.where.startswith("SAME_AS:"):
        r = chosen[spec.where.split(":", 1)[1]]
        return r["borrower_id"], r["account_id"], r["dpd"]
    where = spec.where
    if where.startswith("SUPPRESSED:"):
        reason = where.split(":", 1)[1]
        sql = ("SELECT a.borrower_id, a.account_id, a.dpd FROM ds_account a JOIN ds_consent c ON c.borrower_id=a.borrower_id "
               "JOIN ds_person p ON p.borrower_id=a.borrower_id WHERE c.suppression_reason=? AND a.dpd BETWEEN 1 AND 60 "
               "AND a.borrower_id IN (SELECT borrower_id FROM ds_account GROUP BY borrower_id HAVING COUNT(*)=1) "
               "ORDER BY a.borrower_id")
        rows = db.query(sql, (reason,))
    else:
        sql = ("SELECT a.borrower_id, a.account_id, a.dpd FROM ds_account a JOIN ds_consent c ON c.borrower_id=a.borrower_id "
               f"JOIN ds_person p ON p.borrower_id=a.borrower_id WHERE {CLEAN} AND {where} ORDER BY a.borrower_id")
        rows = db.query(sql, (since, paid_since))
    for r in rows:
        if r["borrower_id"] not in used:
            return r["borrower_id"], r["account_id"], r["dpd"]
    raise LookupError(f"demo event '{spec.label}': the dataset has no borrower matching [{spec.where}]")


def build(sup, as_of: str, injector: FaultInjector) -> list[dict]:
    """Stage and publish the 15 events on `sup` (a Supervisor with the dataset loaded). Returns the demo rows."""
    db = sup.ctx.db
    used: set[str] = set()
    chosen: dict[str, dict] = {}
    rows: list[dict] = []
    script: dict = {}
    for seq, spec in enumerate(SPECS, 1):
        b, acc, dpd = _pick(db, spec, used, chosen, as_of)
        used.add(b)
        chosen[spec.key] = {"borrower_id": b, "account_id": acc, "dpd": dpd}
        if spec.setup:
            _setup(db, seq, spec.setup, b, acc, as_of)
        eid = f"demo-{seq:02d}"
        sup.publish({"id": eid, "type": spec.etype, "account_id": b, "time": f"{as_of}T{spec.time}:00"})
        n_calls = 3 if spec.fault == "LOOP" else 1
        if spec.fault:
            for n in range(1, n_calls + 1):
                script[(b, n)] = spec.fault
        db.execute("INSERT INTO demo_event(seq, key, label, event_id, borrower_id, event_type, depends_on, note) "
                   "VALUES (?,?,?,?,?,?,?,?)", (seq, spec.key, spec.label, eid, b, spec.etype, spec.depends_on, spec.note))
        rows.append({"seq": seq, "key": spec.key, "label": spec.label, "event_id": eid, "borrower_id": b,
                     "event_type": spec.etype, "depends_on": spec.depends_on, "note": spec.note})
    injector.script = script
    return rows


def restore_faults(sup, injector: FaultInjector, rows: list[dict]) -> None:
    """After a restart: rebuild the fault script, and mark the faults that already fired (read from what the agents were
    actually called, so the Faults tile and the Recovery list stay truthful)."""
    by_key = {s.key: s for s in SPECS}
    for r in rows:
        spec = by_key.get(r["key"])
        if not spec or not spec.fault:
            continue
        n_calls = 3 if spec.fault == "LOOP" else 1
        for n in range(1, n_calls + 1):
            injector.script[(r["borrower_id"], n)] = spec.fault
        calls = sup.ctx.db.one("SELECT COUNT(*) n FROM decision_log WHERE event_id=? AND text LIKE 'attempt %' "
                               "AND node IN ('whatsapp','email','voice')", (r["event_id"],))["n"]
        if calls:
            injector.calls[r["borrower_id"]] = calls
            for n in range(1, calls + 1):
                if (r["borrower_id"], n) in injector.script:
                    injector.fired.append((r["borrower_id"], n, injector.script[(r["borrower_id"], n)]))
