"""Phase 18: the account / customer data model.

A CUSTOMER (the person) holds one or more ACCOUNTs (loans). Events arrive per account. The account decides the overdue
stage (and so the role); the customer is the unit for ownership, contact limits, consent and the one-journey-at-a-time
lane. The field-visit example: one customer, a loan at 0 DPD and a loan at 60 DPD."""
import json

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.supervisor import Supervisor
from tests.dataset_fixture import Mini

NOW = "2026-10-31T10:00:00"


def system(m: Mini, tmp_path):
    sup = Supervisor(injector=FaultInjector({}))
    sup.load_dataset(m.write(tmp_path / "ds"))
    return sup


def two_loans():
    m = Mini()
    m.borrower("C1", dpd=0)                    # account C1a at 0 DPD
    m.account("C1b", "C1", dpd=60)             # account C1b at 60 DPD
    return m


def ev(id, account, type="OVERDUE", time=NOW):
    return {"id": id, "type": type, "account_id": account, "time": time}


def test_the_bus_resolves_the_customer_behind_the_account(tmp_path):
    sup = system(two_loans(), tmp_path)
    sup.publish(ev("e1", "C1b"))
    sup.publish(ev("e2", "NO-SUCH-ACCOUNT"))
    assert sup.ctx.bus.get("e1")["customer_id"] == "C1" and sup.ctx.bus.get("e1")["account_id"] == "C1b"
    assert sup.ctx.bus.get("e2")["customer_id"] == ""
    sup.run_until_empty()
    assert sup.ctx.bus.get("e2")["outcome"] == "REJECTED"
    assert "unknown account NO-SUCH-ACCOUNT" in [r for r in sup.ctx.decisions.for_event("e2") if r["node"] == "validate_event"][0]["text"]


def test_the_events_account_decides_the_role(tmp_path):
    sup = system(two_loans(), tmp_path)
    sup.publish(ev("late", "C1b"))                                   # the 60-DPD loan
    sup.run_until_empty()
    late = sup.ctx.contacts.get("C1|late")
    assert late["role"] == "negotiation" and late["account_id"] == "C1b" and late["customer_id"] == "C1"


def test_an_event_on_the_0_dpd_loan_gets_a_reminder(tmp_path):
    sup = system(two_loans(), tmp_path)
    sup.publish(ev("due", "C1a", type="DUE_SOON"))
    sup.run_until_empty()
    c = sup.ctx.contacts.get("C1|due")
    assert c["role"] == "reminder" and c["account_id"] == "C1a"


def test_ownership_and_limits_are_the_customers_across_both_loans(tmp_path):
    """After the 60-DPD loan's Negotiation contact, a Reminder on the other loan of the same person is blocked:
    one owner per customer (R035-R038), not per account."""
    sup = system(two_loans(), tmp_path)
    sup.publish_many([ev("late", "C1b", time="2026-10-31T10:00:00"), ev("due", "C1a", type="DUE_SOON", time="2026-10-31T11:30:00")])
    sup.run_until_empty()
    assert sup.ctx.bus.get("late")["outcome"] == "CONTACTED"
    assert sup.ctx.bus.get("due")["outcome"] != "CONTACTED"
    sent = sup.ctx.db.query("SELECT account_id FROM contact_log WHERE customer_id='C1' AND status='SENT'")
    assert [r["account_id"] for r in sent] == ["C1b"]


def test_one_journey_at_a_time_per_customer_not_per_account(tmp_path):
    sup = system(two_loans(), tmp_path)
    sup.publish_many([ev("a", "C1a", type="DUE_SOON"), ev("b", "C1b")])
    first = sup.ctx.bus.claim_next()
    assert first is not None and sup.ctx.bus.claim_next() is None      # the other loan of the same person waits
    sup.ctx.bus.mark_done(first["id"], "CONTACTED")
    assert sup.ctx.bus.claim_next() is not None


def test_the_message_quotes_the_events_account(tmp_path):
    m = Mini()
    m.borrower("C2", dpd=0)
    m.account("C2b", "C2", dpd=20)
    m.d1[-1]["emi"], m.d1[-1]["total_dues"] = 7777, 22222               # the second loan's own numbers
    sup = system(m, tmp_path)
    from orchestrator.agents.messages import message_context
    ctx = message_context(sup.ctx.db, "C2", {"id": "x", "account_id": "C2b"}, "overdue_reminder")
    assert ctx["dpd"] == 20 and "7,777" in ctx["emi"] and "22,222" in ctx["dues"]
    ctx_a = message_context(sup.ctx.db, "C2", {"id": "y", "account_id": "C2a"}, "overdue_reminder")
    assert ctx_a["dpd"] == 0


def test_every_record_carries_both_ids(tmp_path):
    sup = system(two_loans(), tmp_path)
    sup.publish(ev("late", "C1b"))
    sup.run_until_empty()
    rows = sup.ctx.db.query("SELECT DISTINCT customer_id, account_id FROM decision_log WHERE event_id='late'")
    assert {(r["customer_id"], r["account_id"]) for r in rows} == {("C1", "C1b")}
    j = sup.ctx.db.one("SELECT customer_id, account_id FROM journey_run WHERE event_id='late'")
    assert (j["customer_id"], j["account_id"]) == ("C1", "C1b")
    step = next(r for r in sup.ctx.decisions.for_event("late") if r["node"] in ("whatsapp", "email", "voice"))
    assert step["data"]["request"]["account_id"] == "C1b" and step["data"]["request"]["customer_id"] == "C1"


def test_the_customer_profile_rolls_up_but_the_account_keeps_its_own_stage(tmp_path):
    sup = system(two_loans(), tmp_path)
    assert sup.ctx.borrowers.load("C1")["dpd"] == 60                      # worst across the customer's loans
    assert sup.ctx.borrowers.account("C1a")["dpd"] == 0 and sup.ctx.borrowers.customer_of("C1a") == "C1"
    assert json.loads(json.dumps(sup.ctx.borrowers.account("C1b")))["customer_id"] == "C1"
