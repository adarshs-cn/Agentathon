"""PHASE 12 integration test: a day on the REAL portfolio, scored by an independent audit.

Two halves:
  * the audit must be able to SEE violations (otherwise "zero violations" proves nothing): it is
    pointed at deliberately broken contacts, and at the historical D4 contacts where the dataset
    planted real ones;
  * a real-data day must pass every acceptance check with the audit finding nothing.
"""
from collections import Counter
from pathlib import Path

import pytest

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.agents.stubs import default_agents
from orchestrator.simulator.audit import audit_history, audit_ours, summarise
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.faults import HIDDEN_KINDS
from orchestrator.simulator.real_day import build_real_fault_script, generate_real_day
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.trace import trace_gaps
from tests.dataset_fixture import Mini
from tests.test_phase5_supervisor_and_day import Crash

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"


# ================================================================== the audit can see violations
def planted(m: Mini, tmp_path, rows):
    """Load the mini dataset, then write contacts straight into the contact log, bypassing the engine."""
    sup = Supervisor()
    sup.load_dataset(m.write(tmp_path / "ds"))
    for i, (b, at, role, channel, action) in enumerate(rows):
        sup.ctx.db.execute("INSERT INTO contact_log(idem_key, customer_id, date, channel, purpose, status, role, at) "
                           "VALUES (?,?,?,?,?,'SENT',?,?)", (f"{b}|x{i}", b, at[:10], channel, action, role, at))
    return audit_ours(sup.ctx.db)


def codes(v):
    return {c for c, *_ in v}


def test_a_clean_contact_passes_the_audit(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    assert planted(m, tmp_path, [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")]) == []


@pytest.mark.parametrize("label,borrower,rows,expected", [
    ("deceased", dict(dpd=45, deceased=1), [("T1", "2026-10-31T10:00:00", "negotiation", "voice", "ptp_capture")], "DECEASED"),
    ("opted out", dict(dpd=20, optout_at_whatsapp="2026-10-01 10:00:00"), [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")], "OPTED_OUT"),
    ("whatsapp not granted", dict(dpd=20, consent_whatsapp="unknown"), [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")], "NO_CONSENT"),
    ("call denied", dict(dpd=45, consent_call="denied"), [("T1", "2026-10-31T10:00:00", "negotiation", "voice", "ptp_capture")], "NO_CONSENT"),
    ("dnd", dict(dpd=45, dnd_status="fully_blocked", dnd_effective_from="2025-01-01"), [("T1", "2026-10-31T10:00:00", "negotiation", "voice", "ptp_capture")], "DND"),
    ("out of hours", dict(dpd=20), [("T1", "2026-10-31T20:30:00", "reminder", "whatsapp", "overdue_reminder")], "OUT_OF_HOURS"),
    ("requested window", dict(dpd=20, borrower_requested_window="10:00-12:00"), [("T1", "2026-10-31T15:00:00", "reminder", "whatsapp", "overdue_reminder")], "OUTSIDE_REQUESTED_WINDOW"),
    ("no phone", dict(dpd=20, phone=False), [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")], "NO_CONTACT_DETAIL"),
    ("over the daily cap", dict(dpd=0), [("T1", "2026-10-31T09:00:00", "reminder", "whatsapp", "emi_due_reminder"),
                                         ("T1", "2026-10-31T11:00:00", "reminder", "email", "emi_due_reminder")], "OVER_CAP"),
    ("legal flag, wrong agent", dict(dpd=20, legal=1), [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")], "WRONG_AGENT"),
    ("legal below 91 days", dict(dpd=50), [("T1", "2026-10-31T10:00:00", "legal", "email", "legal_notice")], "WRONG_AGENT"),
    ("reminder at 90+", dict(dpd=120), [("T1", "2026-10-31T10:00:00", "reminder", "email", "overdue_reminder")], "WRONG_AGENT"),
    ("non-owner", dict(dpd=50), [("T1", "2026-10-31T09:00:00", "negotiation", "voice", "ptp_capture"),
                                  ("T1", "2026-10-31T12:00:00", "reminder", "email", "overdue_reminder")], "NON_OWNER"),
])
def test_the_audit_catches_each_kind_of_violation(tmp_path, label, borrower, rows, expected):
    m = Mini(); m.borrower("T1", **borrower)
    assert expected in codes(planted(m, tmp_path, rows)), label


def test_the_audit_catches_a_contact_during_a_payment_hold_and_an_open_promise(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20); m.borrower("T2", dpd=20)
    m.payment("T1a", "2026-10-31 08:00:00"); m.ptp("T2", "2026-11-05")
    rows = [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder"),
            ("T2", "2026-10-31T10:00:00", "reminder", "whatsapp", "overdue_reminder")]
    assert {"PAYMENT_HOLD", "OPEN_PTP"} <= codes(planted(m, tmp_path, rows))


def test_the_allowed_exceptions_are_not_flagged(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20, dnd_status="fully_blocked", dnd_effective_from="2025-01-01"); m.ptp("T1", "2026-11-01")
    m.payment("T1a", "2026-10-31 08:00:00")
    ok = [("T1", "2026-10-31T10:00:00", "servicing", "voice", "payment_confirmation")]          # R051 + the payment's own confirmation
    assert planted(m, tmp_path, ok) == []
    m2 = Mini(); m2.borrower("T1", dpd=20); m2.ptp("T1", "2026-11-01", captured_by="reminder_agent")
    assert planted(m2, tmp_path / "b", [("T1", "2026-10-31T10:00:00", "reminder", "whatsapp", "ptp_reminder")]) == []   # R063


# ================================================================== the real portfolio
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


@real
def test_the_audit_finds_the_violations_planted_in_the_historical_contacts():
    sup = Supervisor()
    rep = sup.load_dataset(REAL)
    found = summarise(audit_history(sup.ctx.db, rep["as_of"]))
    kinds = {k.split(" ")[0] for k in found}
    assert {"DECEASED", "OPTED_OUT", "NO_CONSENT", "DND", "OUT_OF_HOURS", "SUPPRESSED", "CONSENT_EXPIRED",
            "OUTSIDE_REQUESTED_WINDOW"} <= kinds, found
    assert found["DECEASED (R058)"] >= 73                          # the dataset planted 73 deceased borrowers contacted recently
    assert found["OPTED_OUT (R047)"] >= 250                        # ...and 250 contacts after an opt-out


@pytest.fixture(scope="module")
def real_day():
    inj = FaultInjector({})
    sup = Supervisor(injector=inj)
    sup.load_dataset(REAL)
    day = generate_real_day(sup.ctx.db, n_primary=450, seed=5, planted_dir=REAL)
    inj.script = build_real_fault_script(day, sup.ctx.engine, HIDDEN_KINDS)
    sup.publish_many(day.events)
    sup.run_until_empty()
    return sup, inj, day, check_day(sup, inj)


@real
def test_a_real_day_passes_every_acceptance_check_with_a_clean_audit(real_day):
    sup, inj, day, report = real_day
    failed = {k: v for k, v in report["checks"].items() if not v["ok"]}
    assert report["passed"], failed
    assert "independent audit found 0 policy violations" in report["checks"]["zero_conflicting_contacts"]["detail"]
    assert len(inj.faulted_accounts()) == 5 and {f for _, _, f in inj.fired} == set(HIDDEN_KINDS)
    assert report["route_p99_ms"] < 100 and report["route_max_ms"] < 100


@real
def test_the_day_exercises_every_kind_of_outcome(real_day):
    sup, _, day, _ = real_day
    out = Counter(r["outcome"] for r in sup.ctx.db.query("SELECT outcome FROM event_queue"))
    assert {"CONTACTED", "BLOCKED", "SUPPRESSED", "DEFERRED", "REJECTED"} <= set(out), out
    assert out["CONTACTED"] > 100 and sup.ctx.contacts.sent_total() == sum(
        1 for _ in sup.ctx.db.query("SELECT 1 FROM contact_log WHERE status='SENT'"))


@real
def test_every_refusal_in_the_real_day_cites_a_rule(real_day):
    sup, *_ = real_day
    rows = sup.ctx.db.query("SELECT event_id, data FROM decision_log WHERE node='close_event'")
    import json
    bare = []
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        if d.get("status") in ("BLOCKED", "SUPPRESSED", "DEFERRED") and not d.get("rule_ids"):
            bare.append((r["event_id"], d))
    assert bare == [], bare[:3]


@real
def test_deferred_events_are_never_lost(real_day):
    sup, *_ = real_day
    deferred = [r["event_id"] for r in sup.ctx.db.query("SELECT event_id FROM event_queue WHERE outcome='DEFERRED'")]
    assert deferred
    for eid in deferred:
        origin = eid.split("~d")[0]
        nxt = sup.ctx.db.one("SELECT event_id FROM event_queue WHERE event_id=?", (origin + "~d" + str(int(eid.split("~d")[1]) + 1 if "~d" in eid else 1),))
        assert nxt is not None or any("gave up re-scheduling" in r["text"] for r in sup.ctx.decisions.for_event(eid)), eid


@real
def test_planted_trap_borrowers_are_handled_by_the_rules_not_by_luck(real_day):
    sup, _, day, _ = real_day
    db = sup.ctx.db
    first = {}
    for e in day.events:
        if e["id"] not in day.bad_event_ids:                 # the malformed events reuse real accounts
            first.setdefault(e["customer_id"], e)

    def status_of(b):
        r = db.one("SELECT outcome FROM event_queue WHERE event_id=?", (first[b]["id"],))
        return r["outcome"]

    for b in day.planted.get("deceased_borrowers_contacted_recently", []):
        assert status_of(b) == "BLOCKED", b                                   # R058: never
    for b in day.planted.get("dnd_fully_blocked_contacted", []):
        rows = db.query("SELECT channel FROM contact_log WHERE customer_id=? AND status='SENT'", (b,))
        assert all(r["channel"] != "voice" for r in rows), b                  # R050: no calls to DND borrowers
    for b in day.planted.get("optout_then_contact", []):
        c = dict(db.one("SELECT * FROM ds_consent WHERE customer_id=?", (b,)))
        for r in db.query("SELECT channel FROM contact_log WHERE customer_id=? AND status='SENT'", (b,)):
            ch = "call" if r["channel"] == "voice" else r["channel"]
            assert not c.get(f"optout_{ch}"), (b, ch)                         # R047: respect the opt-out
    for b in day.planted.get("expired_consent_before_contact", []):
        rows = db.query("SELECT channel FROM contact_log WHERE customer_id=? AND status='SENT'", (b,))
        assert all(r["channel"] != "whatsapp" for r in rows), b               # R048: expired consent = unknown = no WhatsApp


@real
def test_a_real_day_survives_the_supervisor_dying_part_way(tmp_path):
    agents = default_agents(FaultInjector({}))
    sup = Supervisor(data_dir=tmp_path / "run", agents=agents)
    sup.load_dataset(REAL)
    day = generate_real_day(sup.ctx.db, n_primary=200, seed=9, planted_dir=REAL)
    sup.publish_many(day.events)
    seen = {"n": 0}

    def die(name, state):
        if name == "commit":
            seen["n"] += 1
            if seen["n"] == 40:
                raise Crash()
    sup.ctx.on_node_start = die
    with pytest.raises(Crash):
        sup.run_until_empty()
    sup.close()

    sup2 = Supervisor(data_dir=tmp_path / "run", agents=agents)
    sup2.load_dataset(REAL)                                                   # the engine is rebuilt; our own tables persist
    sup2.run_until_empty()
    report = check_day(sup2, None)
    assert report["passed"], {k: v for k, v in report["checks"].items() if not v["ok"]}
    sent = sup2.ctx.contacts.sent_total()
    assert sent == sum(len(a.outbox) for a in agents) > 30                    # every contact is exactly one real message
    accounts = [r["account_id"] for r in sup2.ctx.db.query("SELECT DISTINCT account_id FROM event_queue")]
    assert all(trace_gaps(sup2.ctx, a) == [] for a in accounts[:200])
