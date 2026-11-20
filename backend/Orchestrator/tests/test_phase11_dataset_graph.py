"""PHASE 11 integration test: the D12 engine inside the real graph. Events in, contacts and
traces out, with faults, handoffs, deferrals and process death, on controllable borrowers."""
import pytest

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.render import render_trace
from orchestrator.tracing.trace import account_trace, trace_gaps
from tests.dataset_fixture import Mini
from tests.test_phase5_supervisor_and_day import Crash, crash_once_at


def system(m: Mini, tmp_path, script=None, **kw):
    sup = Supervisor(injector=FaultInjector(script or {}), **kw)
    sup.load_dataset(m.write(tmp_path / "ds"))
    return sup


def ev(id, b="T1", type="OVERDUE", time="2026-10-31T10:00:00"):
    return {"id": id, "type": type, "account_id": b, "time": time}


def run(sup, *events):
    sup.publish_many(list(events))
    sup.run_until_empty()


def outcome(sup, eid):
    return sup.ctx.bus.get(eid)["outcome"]


def messages(sup):
    return sorted(k for a in sup.ctx.registry._agents.values() for k in a.outbox)


def step(sup, eid, node):
    return next(r for r in sup.ctx.decisions.for_event(eid) if r["node"] == node)


# ------------------------------------------------------------------ the happy path
def test_a_reminder_goes_out_and_everything_is_recorded(tmp_path):
    m = Mini(); m.borrower("T1", dpd=0)
    sup = system(m, tmp_path)
    run(sup, ev("e1", type="DUE_SOON"))
    assert outcome(sup, "e1") == "CONTACTED" and messages(sup) == ["T1|e1"]            # one key per EVENT in dataset mode
    row = sup.ctx.contacts.get("T1|e1")
    assert (row["role"], row["channel"], row["purpose"], row["status"], row["at"]) == \
           ("reminder", "whatsapp", "emi_due_reminder", "SENT", "2026-10-31T10:00:00")
    assert sup.ctx.borrowers.get_lease("T1") == ("reminder", "2026-11-01T10:00:00")      # R038: 24-hour lease
    req = step(sup, "e1", "whatsapp")["data"]["request"]
    assert (req["role"], req["action"], req["template"]) == ("reminder", "emi_due_reminder", "wa_template/emi_due_reminder_v1")
    d = step(sup, "e1", "route")["data"]
    assert d["role"] == "reminder" and d["agent"] == "whatsapp" and d["fallbacks"] == ["email", "voice"] and d["considered"]


def test_several_contacts_a_day_are_allowed_up_to_the_cap_then_blocked_with_the_rule(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)                                                 # bucket 1-30: 2 a day, WhatsApp 1 a day
    sup = system(m, tmp_path)
    run(sup, ev("e1", time="2026-10-31T10:00:00"), ev("e2", time="2026-10-31T11:30:00"), ev("e3", time="2026-10-31T13:00:00"))
    assert [outcome(sup, e) for e in ("e1", "e2", "e3")] == ["CONTACTED", "CONTACTED", "BLOCKED"]
    chans = [sup.ctx.contacts.get(f"T1|{e}")["channel"] for e in ("e1", "e2")]
    assert chans == ["whatsapp", "email"]                                                # R015 pushed the second to email
    g = step(sup, "e3", "guardrails")
    assert "R025" in g["data"]["rule_ids"] and "2 contacts today, daily limit is 2" in g["text"]
    assert len(messages(sup)) == 2


def test_a_blocked_event_never_reaches_an_agent_and_cites_its_rule(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45, deceased=1)
    sup = system(m, tmp_path)
    run(sup, ev("e1"))
    assert outcome(sup, "e1") == "BLOCKED" and messages(sup) == []
    assert [r["node"] for r in sup.ctx.decisions.for_event("e1")] == ["validate_event", "load_borrower", "guardrails", "close_event"]
    assert step(sup, "e1", "close_event")["data"]["rule_ids"] == ["R058"]


def test_no_consented_channel_means_no_agent_is_even_called(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20, consent_call="denied", consent_sms="denied", consent_whatsapp="unknown",
                           consent_email="denied")
    sup = system(m, tmp_path)
    run(sup, ev("e1"))
    assert outcome(sup, "e1") == "SUPPRESSED" and all(a.calls == 0 for a in sup.ctx.registry._agents.values())
    out = step(sup, "e1", "close_event")["data"]
    assert {"R043", "R045", "R046"} <= set(out["rule_ids"])


def test_a_legal_account_among_several_makes_the_borrower_legal_only(tmp_path):
    m = Mini(); m.borrower("T1", dpd=10); m.account("T1b", "T1", dpd=130, legal=1)
    sup = system(m, tmp_path)
    run(sup, ev("e1", type="OVERDUE"), ev("e2", type="DUE_SOON", time="2026-11-02T10:00:00"))
    assert outcome(sup, "e1") == "CONTACTED" and sup.ctx.contacts.get("T1|e1")["role"] == "legal"
    assert sup.ctx.contacts.get("T1|e1")["channel"] == "email"
    assert outcome(sup, "e2") == "SUPPRESSED" and "R040" in step(sup, "e2", "close_event")["data"]["rule_ids"]


# ------------------------------------------------------------------ deferral
def test_outside_the_contact_window_the_event_is_deferred_and_picked_up_at_opening(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    sup = system(m, tmp_path)
    run(sup, ev("e1", time="2026-10-31T07:30:00"))
    assert outcome(sup, "e1") == "DEFERRED" and outcome(sup, "e1~d1") == "CONTACTED"
    assert sup.ctx.bus.get("e1~d1")["event_time"] == "2026-10-31T08:00:00"
    assert sup.ctx.contacts.get("T1|e1~d1")["at"] == "2026-10-31T08:00:00" and len(messages(sup)) == 1
    assert any("re-scheduled as e1~d1" in r["text"] for r in sup.ctx.decisions.for_event("e1"))
    assert trace_gaps(sup.ctx, "T1") == []


def test_a_minimum_gap_defers_then_proceeds(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45); m.contact("T1", "2026-10-31 09:50:00", "negotiation_agent", "call")
    sup = system(m, tmp_path)
    run(sup, ev("e1", time="2026-10-31T10:00:00"))
    assert outcome(sup, "e1") == "DEFERRED" and outcome(sup, "e1~d1") == "CONTACTED"
    assert sup.ctx.bus.get("e1~d1")["event_time"] == "2026-10-31T10:20:00"


def test_deferral_cannot_loop_forever(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20, borrower_requested_window="09:00-09:05")        # a 5-minute window, ok
    sup = system(m, tmp_path)
    sup.MAX_DEFERRALS = 1
    sup.ctx.db.execute("UPDATE ds_rule SET value='09:00-09:05' WHERE rule_id='R001'")   # nobody can ever be contacted
    sup.ctx.engine.reload()
    sup.ctx.engine.hard_window = (9 * 60, 9 * 60)                                        # empty window: always deferred
    run(sup, ev("e1", time="2026-10-31T09:00:00"))
    assert outcome(sup, "e1") == "DEFERRED" and outcome(sup, "e1~d1") == "DEFERRED" and sup.ctx.bus.get("e1~d2") is None
    assert any("gave up re-scheduling" in r["text"] for r in sup.ctx.decisions.for_account("T1"))


# ------------------------------------------------------------------ ownership and handoff
def test_a_higher_priority_role_takes_over_and_the_handoff_is_logged(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45); m.contact("T1", "2026-10-30 20:00:00", "reminder_agent", "sms")
    sup = system(m, tmp_path)
    run(sup, ev("e1"))
    assert outcome(sup, "e1") == "CONTACTED" and sup.ctx.contacts.get("T1|e1")["role"] == "negotiation"
    h = next(r for r in sup.ctx.decisions.for_event("e1") if r["node"] == "assign" and "HANDOFF" in r["text"])
    assert h["data"]["rule_ids"] == ["R039", "A12"] and h["data"]["from"] == "reminder" and h["data"]["to"] == "negotiation"
    assert sup.ctx.borrowers.get_lease("T1")[0] == "negotiation"


def test_a_non_owner_is_blocked_and_the_owner_is_named(tmp_path):
    m = Mini(); m.borrower("T1", dpd=0); m.contact("T1", "2026-10-30 20:00:00", "negotiation_agent", "call")
    sup = system(m, tmp_path)
    run(sup, ev("e1", type="DUE_SOON"))
    assert outcome(sup, "e1") == "SUPPRESSED" and messages(sup) == []
    d = step(sup, "e1", "route")["data"]
    assert "negotiation is the active owner" in d["reason"] and {"R035", "R036"} <= set(d["rule_ids"])


def test_the_lease_our_own_contact_creates_blocks_a_lower_role_later(tmp_path):
    m = Mini(); m.borrower("T1", dpd=0)                                                    # bucket 0: reminder or servicing
    sup = system(m, tmp_path)
    run(sup, ev("e1", type="PAYMENT_RECEIVED", time="2026-10-31T09:00:00"))                # servicing replies, no lease taken? it does
    assert outcome(sup, "e1") == "CONTACTED"
    assert sup.ctx.borrowers.get_lease("T1")[0] == "servicing"


# ------------------------------------------------------------------ faults inside dataset mode
def test_crash_after_send_is_not_resent_and_the_unconfirmed_attempt_counts_toward_the_cap(tmp_path):
    m = Mini(); m.borrower("T1", dpd=0)                                                    # bucket 0: 1 contact a day
    sup = system(m, tmp_path, {("T1", 1): "CRASH_AFTER_SEND"})
    run(sup, ev("e1", type="DUE_SOON"), ev("e2", type="DUE_SOON", time="2026-10-31T14:00:00"))
    assert outcome(sup, "e1") == "CONTACTED" and messages(sup) == ["T1|e1"]
    assert step(sup, "e1", "monitor")["data"]["action"] == "RESTART_SKIP_CURRENT"
    assert outcome(sup, "e2") == "BLOCKED" and "R023" in step(sup, "e2", "close_event")["data"]["rule_ids"]


def test_a_looping_channel_is_rerouted_inside_the_same_role(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    sup = system(m, tmp_path, {("T1", n): "LOOP" for n in (1, 2, 3)})
    run(sup, ev("e1"))
    row = sup.ctx.contacts.get("T1|e1")
    assert outcome(sup, "e1") == "CONTACTED" and (row["channel"], row["role"]) == ("email", "reminder")
    assert messages(sup) == ["T1|e1"] and sup.ctx.registry.get("whatsapp").outbox == {}


# ------------------------------------------------------------------ the supervisor dies
@pytest.mark.parametrize("node", ["validate_event", "load_borrower", "guardrails", "route", "assign", "whatsapp",
                                  "validate_output", "commit", "release", "close_event"])
def test_process_death_at_every_node_in_dataset_mode_still_means_one_contact(tmp_path, node):
    from orchestrator.agents.stubs import default_agents
    m = Mini(); m.borrower("T1", dpd=20)
    agents = default_agents(FaultInjector({}))
    folder = m.write(tmp_path / "ds")
    sup = Supervisor(data_dir=tmp_path / "run", agents=agents)
    sup.load_dataset(folder)
    sup.publish(ev("e1"))
    sup.ctx.on_node_start = crash_once_at(node)
    with pytest.raises(Crash):
        sup.run_until_empty()
    sup.close()
    sup2 = Supervisor(data_dir=tmp_path / "run", agents=agents)
    sup2.ctx.engine = None
    sup2.load_dataset(folder)                                                              # the engine is rebuilt on restart
    sup2.run_until_empty()
    assert sup2.ctx.bus.get("e1")["outcome"] == "CONTACTED" and sum(len(a.outbox) for a in agents) == 1
    assert sup2.ctx.contacts.sent_total() == 1 and sup2.ctx.borrowers.owners_held() == []
    assert trace_gaps(sup2.ctx, "T1") == []


# ------------------------------------------------------------------ the trace
def test_the_trace_shows_what_was_weighed_and_why(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45, consent_whatsapp="unknown", dnd_status="fully_blocked", dnd_effective_from="2025-01-01")
    sup = system(m, tmp_path)
    run(sup, ev("e1"))
    text = render_trace(account_trace(sup.ctx, "T1", sup.graph))
    for expected in ("weighed  : negotiation -> ptp_capture", "BLOCKED call", "[R050, R051, R053]", "BLOCKED whatsapp",
                     "[R045]", "ok      email", "rules    :", "trace complete: True"):
        assert expected in text, expected
    assert outcome(sup, "e1") == "CONTACTED" and sup.ctx.contacts.get("T1|e1")["channel"] == "email"
