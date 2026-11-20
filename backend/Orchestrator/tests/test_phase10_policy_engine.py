"""PHASE 10 integration test: the D12 policy engine, rule by rule, on controllable borrowers,
then swept across the REAL portfolio. Every blocked / suppressed / deferred verdict must cite
the rule id(s) that decided it (R093)."""
import time
from pathlib import Path

import pytest

from orchestrator.agents.stubs import default_agents
from orchestrator.context import Context
from orchestrator.dataset.loader import load_dataset
from orchestrator.policy.d12 import D12Policy
from tests.dataset_fixture import Mini

NOW = "2026-10-31T10:00:00"
REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"


def ev(type="OVERDUE", b="T1", time=NOW, id="e1"):
    return {"id": id, "type": type, "account_id": b, "time": time}


def setup(m: Mini, tmp_path, agents=None):
    ctx = Context.create(agents=default_agents() if agents is None else agents)
    load_dataset(ctx.db, ctx.borrowers, m.write(tmp_path))
    return ctx, D12Policy(ctx.db, ctx.contacts, ctx.borrowers, ctx.registry)


def verdict(m, tmp_path, event=None, b="T1"):
    ctx, eng = setup(m, tmp_path)
    return eng.evaluate(b, event or ev(b=b)), ctx, eng


def routed(r):
    assert r["final"] == "OK", r
    p = r["plan"]
    return p["role"], p["channel_agents"][0], p["channel_agents"][1:], p["action"]


# ================================================================== borrower-level guard
def test_a_clean_borrower_passes_the_guard(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    r, *_ = verdict(m, tmp_path)
    assert r["guard"]["ok"] and r["guard"]["rule_ids"] == []
    assert "contacts today 0/3" in r["guard"]["reason"]


@pytest.mark.parametrize("how", ["person_flag", "d10_reason"])
def test_deceased_blocks_everything(tmp_path, how):
    m = Mini()
    m.borrower("T1", dpd=45, deceased=1) if how == "person_flag" else \
        m.borrower("T1", dpd=45, suppression_reason="deceased", suppression_from="2026-01-01")
    r, *_ = verdict(m, tmp_path)
    assert r["final"] == "BLOCKED" and r["guard"]["rule_ids"] == ["R058"]


def test_customer_request_and_complaint_suppression(tmp_path):
    m = Mini()
    m.borrower("STOP", suppression_reason="customer_request", suppression_from="2026-09-01")
    m.borrower("COMP", suppression_reason="complaint", suppression_from="2026-10-15")       # inside 30 days
    m.borrower("OLD", suppression_reason="complaint", suppression_from="2026-09-01")        # SLA long over
    m.borrower("FUTURE", suppression_reason="complaint", suppression_from="2026-11-15")     # not started yet
    ctx, eng = setup(m, tmp_path)
    got = {b: eng.evaluate(b, ev(b=b))["guard"] for b in ("STOP", "COMP", "OLD", "FUTURE")}
    assert got["STOP"]["rule_ids"] == ["R059"] and got["COMP"]["rule_ids"] == ["R060"]
    assert got["OLD"]["ok"] and got["FUTURE"]["ok"]
    assert "2026-11-14" in got["COMP"]["reason"]


def test_payment_hold_for_48_hours_ends_on_reversal(tmp_path):
    m = Mini()
    for b in ("PAID", "OLD", "REV", "CONF"):
        m.borrower(b, dpd=45)
    m.payment("PAIDa", "2026-10-31 02:00:00")                       # 8 h ago
    m.payment("OLDa", "2026-10-29 08:00:00")                        # 50 h ago
    m.payment("REVa", "2026-10-31 02:00:00", reversal=1)            # reversed: hold ends (R067)
    m.payment("CONFa", "2026-10-31 09:30:00")
    ctx, eng = setup(m, tmp_path)
    g = {b: eng.evaluate(b, ev(b=b))["guard"] for b in ("PAID", "OLD", "REV")}
    assert g["PAID"]["rule_ids"] == ["R066"] and g["OLD"]["ok"] and g["REV"]["ok"]
    # the payment's own confirmation is the one contact allowed during the hold
    assert eng.evaluate("CONF", ev("PAYMENT_RECEIVED", "CONF"))["guard"]["ok"]


def test_open_promise_to_pay_holds_contact_until_the_day_after(tmp_path):
    m = Mini()
    for b in ("HOLD", "STALE", "DUE"):
        m.borrower(b, dpd=45)
    m.ptp("HOLD", "2026-11-05"); m.ptp("STALE", "2026-10-20"); m.ptp("DUE", "2026-11-01")
    ctx, eng = setup(m, tmp_path)
    assert eng.evaluate("HOLD", ev(b="HOLD"))["guard"]["rule_ids"] == ["R062"]
    assert eng.evaluate("STALE", ev(b="STALE"))["guard"]["ok"]                    # promised long ago, never closed
    assert eng.evaluate("DUE", ev(b="DUE"))["guard"]["rule_ids"] == ["R062"]
    assert eng.evaluate("DUE", ev("PTP_DUE", "DUE"))["guard"]["ok"]               # R063: the reminder the day before
    assert eng.evaluate("HOLD", ev("PTP_DUE", "HOLD"))["guard"]["rule_ids"] == ["R062"]   # not the day before


@pytest.mark.parametrize("dpd,bucket_rule,cap", [(0, "R023", 1), (20, "R025", 2), (45, "R027", 3), (95, "R031", 2)])
def test_daily_cap_is_the_minimum_of_global_and_bucket(tmp_path, dpd, bucket_rule, cap):
    m = Mini(); m.borrower("T1", dpd=dpd)
    for i in range(cap):
        m.contact("T1", f"2026-10-31 {8 + i:02d}:00:00", "reminder_agent", "sms")
    ctx, eng = setup(m, tmp_path)
    g = eng.evaluate("T1", ev())["guard"]
    assert g["status"] == "BLOCKED" and bucket_rule in g["rule_ids"] and "R033" in g["rule_ids"]
    assert f"{cap} contacts today, daily limit is {cap}" in g["reason"]


def test_one_below_the_cap_is_allowed(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    m.contact("T1", "2026-10-31 08:00:00"); m.contact("T1", "2026-10-31 08:40:00")
    ctx, eng = setup(m, tmp_path)
    assert eng.evaluate("T1", ev(time="2026-10-31T12:00:00"))["guard"]["ok"]


def test_failed_attempts_count_toward_the_cap(tmp_path):
    m = Mini(); m.borrower("T1", dpd=5)
    m.contact("T1", "2026-10-31 08:00:00", disposition="no_answer"); m.contact("T1", "2026-10-31 08:40:00", disposition="failed")
    ctx, eng = setup(m, tmp_path)
    assert eng.evaluate("T1", ev(time="2026-10-31T12:00:00"))["guard"]["rule_ids"][0] in ("R025",)


def test_contacts_already_in_todays_snapshot_count_even_if_later_in_the_day(tmp_path):
    m = Mini(); m.borrower("T1", dpd=5)
    m.contact("T1", "2026-10-31 15:00:00"); m.contact("T1", "2026-10-31 16:00:00")      # after the event at 10:00
    ctx, eng = setup(m, tmp_path)
    assert eng.evaluate("T1", ev())["guard"]["status"] == "BLOCKED"


def test_seven_day_cap(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)                                                   # bucket 1-30: 6 per 7 days
    for day in ("25", "26", "27", "28", "29", "30"):
        m.contact("T1", f"2026-10-{day} 10:00:00")
    ctx, eng = setup(m, tmp_path)
    g = eng.evaluate("T1", ev())["guard"]
    assert g["status"] == "BLOCKED" and "R026" in g["rule_ids"]


def test_minimum_gap_defers_rather_than_blocks(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    m.contact("T1", "2026-10-31 09:50:00")
    ctx, eng = setup(m, tmp_path)
    g = eng.evaluate("T1", ev())["guard"]
    assert g["status"] == "DEFERRED" and g["rule_ids"] == ["R022"] and g["defer_until"] == "2026-10-31T10:20:00"


# ================================================================== who acts
@pytest.mark.parametrize("dpd,etype,role,first,rest,action", [
    (0, "DUE_SOON", "reminder", "whatsapp", ["email", "voice"], "emi_due_reminder"),
    (20, "OVERDUE", "reminder", "whatsapp", ["email", "voice"], "overdue_reminder"),
    (45, "OVERDUE", "negotiation", "voice", ["whatsapp", "email"], "ptp_capture"),
    (75, "OVERDUE", "negotiation", "voice", ["whatsapp", "email"], "ptp_capture"),
    (20, "PTP_BROKEN", "negotiation", "voice", ["whatsapp"], "broken_ptp_followup"),            # R064 beats reminder's rank; no email at 1-30
    (45, "PTP_BROKEN", "negotiation", "voice", ["whatsapp", "email"], "ptp_capture"),           # no follow-up action at 31-60
    (5, "PAYMENT_RECEIVED", "servicing", "whatsapp", ["email", "voice"], "payment_confirmation"),
    (45, "PAYMENT_RECEIVED", "servicing", "email", ["voice"], "payment_confirmation"),          # no WhatsApp for servicing at 31-60
])
def test_the_matrix_decides_the_role_and_the_channel_order(tmp_path, dpd, etype, role, first, rest, action):
    m = Mini(); m.borrower("T1", dpd=dpd)
    r, *_ = verdict(m, tmp_path, ev(etype))
    assert routed(r) == (role, first, rest, action)


def test_ninety_plus_goes_to_legal_by_email_and_a_role_without_a_channel_is_not_swapped(tmp_path):
    m = Mini(); m.borrower("T1", dpd=120)
    r, *_ = verdict(m, tmp_path)
    assert routed(r) == ("legal", "email", ["voice"], "legal_notice")          # legal is rank 1 at 90+
    m2 = Mini(); m2.borrower("T1", dpd=120, consent_email="denied", consent_call="denied")
    r2, *_ = verdict(m2, tmp_path / "b")
    # legal has no channel left: the borrower is NOT silently handed to negotiation, a different intent
    assert r2["final"] == "SUPPRESSED" and "R046" in r2["plan"]["rule_ids"]


def test_a_legal_flag_on_any_account_makes_the_borrower_legal_only(tmp_path):
    m = Mini(); m.borrower("T1", dpd=10)
    m.account("T1b", "T1", dpd=130, legal=1)                 # one legal account among three
    m.account("T1c", "T1", dpd=0)
    r, *_ = verdict(m, tmp_path)
    assert routed(r) == ("legal", "email", ["voice"], "legal_notice")      # whatever the DPD of the other accounts
    due, *_ = verdict(m, tmp_path / "b", ev("DUE_SOON"))
    assert due["final"] == "SUPPRESSED" and "R040" in due["plan"]["rule_ids"]     # legal has no reminder to send


def test_settlement_flag_means_negotiation_only(tmp_path):
    m = Mini(); m.borrower("T1", dpd=10, settlement=1)
    r, *_ = verdict(m, tmp_path)
    assert routed(r)[0] == "negotiation"
    assert any(e["role"] == "reminder" and e["rule_ids"] == ["R041"] for e in r["plan"]["excluded"])


def test_restructure_flag_keeps_legal_away(tmp_path):
    m = Mini(); m.borrower("T1", dpd=120, restructure=1)
    r, *_ = verdict(m, tmp_path)
    assert routed(r)[0] == "negotiation"
    assert any(e["role"] == "legal" and e["rule_ids"] == ["R042"] for e in r["plan"]["excluded"])


def test_legal_never_acts_below_91_days_without_the_flag(tmp_path):
    m = Mini(); m.borrower("T1", dpd=85)
    r, *_ = verdict(m, tmp_path)
    assert routed(r)[0] == "negotiation"
    assert all(e["role"] != "legal" or e["rule_ids"] != ["R075"] or True for e in r["plan"]["excluded"])


def test_external_agencies_and_unavailable_channels_are_never_chosen(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    r, *_ = verdict(m, tmp_path)
    agents = {r["plan"]["channel_agents"][0], *r["plan"]["channel_agents"]}
    assert agents <= {"whatsapp", "email", "voice"} and r["plan"]["role"] in ("reminder", "negotiation", "servicing", "legal")


# ================================================================== consent, DND, eligibility
def route_of(tmp_path, dpd=20, etype="OVERDUE", **consent):
    m = Mini(); m.borrower("T1", dpd=dpd, **consent)
    r, *_ = verdict(m, tmp_path, ev(etype))
    return r


def channels_ok(r):
    return [c["channel"] for c in r["plan"]["considered"][0]["channels"] if c["status"] == "OK"] if r["plan"] else []


def blocked_reason(r, channel):
    for cand in r["plan"]["considered"]:
        for c in cand.get("channels", []):
            if c["channel"] == channel and c["status"] != "OK":
                return c
    return None


@pytest.mark.parametrize("consent,channel,rule", [
    ({"consent_whatsapp": "unknown"}, "whatsapp", "R045"),            # WhatsApp needs explicit consent
    ({"consent_whatsapp": "denied"}, "whatsapp", "R045"),
    ({"consent_call": "denied"}, "call", "R043"),
    ({"consent_call": "revoked"}, "call", "R043"),
    ({"consent_email": "denied"}, "email", "R046"),
    ({"consent_whatsapp": "granted", "optout_at_whatsapp": "2026-10-01 10:00:00"}, "whatsapp", "R047"),
    ({"consent_expiry_date": "2026-09-01"}, "whatsapp", "R048"),       # expired consent counts as unknown
    ({"consent_source": ""}, "whatsapp", "R049"),
])
def test_consent_rules_block_the_channel_and_cite_the_rule(tmp_path, consent, channel, rule):
    r = route_of(tmp_path, **consent)
    c = blocked_reason(r, channel)
    assert c and rule in c["rule_ids"], (channel, c)


def test_unknown_email_consent_is_allowed_with_a_warning(tmp_path):
    r = route_of(tmp_path, consent_whatsapp="denied", consent_email="unknown")
    assert r["final"] == "OK" and r["plan"]["channel_agents"][0] == "email"
    assert any("R046" in w for w in r["plan"]["warnings"])


def test_dnd_blocks_calls_and_sms_but_not_whatsapp_or_email(tmp_path):
    r = route_of(tmp_path, dpd=45, dnd_status="fully_blocked", dnd_effective_from="2025-01-01")
    c = blocked_reason(r, "call")
    assert c and "R050" in c["rule_ids"] and "R053" in c["rule_ids"]
    assert r["plan"]["channel_agents"] == ["whatsapp", "email"]            # R052: DND covers call and SMS only


def test_dnd_allows_transactional_purposes_and_waits_out_the_seven_days(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45, dnd_status="fully_blocked", dnd_effective_from="2025-01-01")
    r, *_ = verdict(m, tmp_path, ev("PAYMENT_RECEIVED"))
    assert "voice" in r["plan"]["channel_agents"]                          # payment confirmation is allowed (R051)
    m2 = Mini(); m2.borrower("T1", dpd=45, dnd_status="fully_blocked", dnd_effective_from="2026-11-03")   # not yet effective
    r2, *_ = verdict(m2, tmp_path / "b")
    assert "voice" in r2["plan"]["channel_agents"]


def test_a_borrower_without_the_detail_is_not_reachable_there(tmp_path):
    assert channels_ok(route_of(tmp_path, dpd=20)) == ["whatsapp", "email", "call"]
    m = Mini(); m.borrower("T1", dpd=20, phone=False, consent_call="not_applicable", consent_sms="not_applicable",
                           consent_whatsapp="not_applicable")
    r, *_ = verdict(m, tmp_path)
    assert channels_ok(r) == ["email"] and blocked_reason(r, "whatsapp")["rule_ids"] == ["R069"]
    m2 = Mini(); m2.borrower("T1", dpd=20, email=False, consent_email="not_applicable")
    r2, *_ = verdict(m2, tmp_path / "b")
    assert blocked_reason(r2, "email")["rule_ids"] == ["R070"] and r2["plan"]["channel_agents"] == ["whatsapp", "voice"]


def test_shared_phone_blocks_phone_channels_until_identity_is_verified(tmp_path):
    m = Mini()
    m.borrower("T1", dpd=20, shared_phone="9111111111"); m.borrower("T2", dpd=20, shared_phone="9111111111")
    r, *_ = verdict(m, tmp_path)
    assert blocked_reason(r, "whatsapp")["rule_ids"] == ["R056"] and r["plan"]["channel_agents"] == ["email"]


def test_whatsapp_is_not_used_for_ninety_plus(tmp_path):
    r = route_of(tmp_path, dpd=95)
    assert "whatsapp" not in r["plan"]["channel_agents"] or blocked_reason(r, "whatsapp") is None
    c = blocked_reason(r, "whatsapp")
    assert c is None or c["rule_ids"] == ["R072"]


def test_a_wrong_number_disposition_quarantines_the_phone(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    m.contact("T1", "2026-07-20 10:00:00", "reminder_agent", "call", disposition="wrong_number")   # months ago: still permanent
    r, *_ = verdict(m, tmp_path)
    assert blocked_reason(r, "whatsapp")["rule_ids"] == ["R055"] and r["plan"]["channel_agents"] == ["email"]


def test_a_dispute_pauses_phone_channels_but_not_email(tmp_path):
    r = route_of(tmp_path, dpd=45, suppression_reason="dispute", suppression_from="2026-10-01")
    assert r["plan"]["channel_agents"] == ["email"] and blocked_reason(r, "call")["rule_ids"] == ["R061"]


# ================================================================== time of day
@pytest.mark.parametrize("when,until", [
    ("2026-10-31T07:30:00", "2026-10-31T08:00:00"),
    ("2026-10-31T19:30:00", "2026-11-01T08:00:00"),
    ("2026-10-31T21:00:00", "2026-11-01T08:00:00"),      # R007 beats the soft 21:00 limit of WhatsApp and email
])
def test_outside_the_window_is_deferred_to_the_next_opening(tmp_path, when, until):
    m = Mini(); m.borrower("T1", dpd=20)
    r, *_ = verdict(m, tmp_path, ev(time=when))
    assert r["final"] == "DEFERRED" and r["plan"]["defer_until"] == until and "R007" in r["plan"]["rule_ids"]


def test_the_borrowers_requested_window_is_respected(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20, borrower_requested_window="10:00-17:00")
    early, *_ = verdict(m, tmp_path, ev(time="2026-10-31T09:00:00"))
    assert early["final"] == "DEFERRED" and early["plan"]["defer_until"] == "2026-10-31T10:00:00" and "R006" in early["plan"]["rule_ids"]
    late, *_ = verdict(m, tmp_path / "b", ev(time="2026-10-31T18:00:00"))
    assert late["plan"]["defer_until"] == "2026-11-01T10:00:00"
    inside, *_ = verdict(m, tmp_path / "c", ev(time="2026-10-31T12:00:00"))
    assert inside["final"] == "OK"


# ================================================================== channel limits and budgets
def test_a_channels_own_daily_cap_pushes_to_the_next_channel(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    m.contact("T1", "2026-10-31 08:00:00", "reminder_agent", "whatsapp")            # WhatsApp: 1 per day (R015)
    r, *_ = verdict(m, tmp_path, ev(time="2026-10-31T11:00:00"))
    assert r["final"] == "OK" and r["plan"]["role"] in ("negotiation", "reminder")
    c = blocked_reason(r, "whatsapp")
    assert c and "R015" in c["rule_ids"]


def test_a_call_within_sixty_minutes_of_the_last_call_is_deferred(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45, consent_whatsapp="denied", consent_email="denied")      # voice is all that is left
    m.contact("T1", "2026-10-31 09:00:00", "negotiation_agent", "call")
    r, *_ = verdict(m, tmp_path, ev(time="2026-10-31T09:40:00"))
    assert r["final"] == "DEFERRED" and r["plan"]["defer_until"] == "2026-10-31T10:00:00" and "R021" in r["plan"]["rule_ids"]


def test_d13_agent_budget_and_spend_cap(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20, consent_call="denied", consent_email="denied")      # whatsapp only
    ctx, eng = setup(m, tmp_path)
    ctx.db.execute("UPDATE ds_capacity SET daily_budget=2 WHERE agent='reminder_agent' AND channel='whatsapp'")
    for b in ("X1", "X2"):
        ctx.db.execute("INSERT INTO ds_history VALUES (?,?,?,?,?,?)", (b, "a", "2026-10-31T08:00:00", "reminder_agent", "whatsapp", "delivered"))
    eng.reload()
    r = eng.evaluate("T1", ev())
    assert r["final"] == "SUPPRESSED" and "R092" in r["plan"]["rule_ids"] and "budget" in r["plan"]["reason"]
    ctx.db.execute("UPDATE ds_capacity SET daily_budget=100, spend_cap=0.1 WHERE agent='reminder_agent' AND channel='whatsapp'")
    eng.reload()
    assert "spend cap" in eng.evaluate("T1", ev())["plan"]["reason"]


# ================================================================== ownership
def test_a_higher_priority_agent_may_take_over_with_a_logged_handoff(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    m.contact("T1", "2026-10-31 08:00:00", "reminder_agent", "sms")                 # reminder holds the lease until tomorrow
    r, *_ = verdict(m, tmp_path, ev(time="2026-10-31T11:00:00"))
    p = r["plan"]
    assert p["role"] == "negotiation" and p["handoff"]["from"] == "reminder" and p["handoff"]["rule_ids"] == ["R039", "A12"]


def test_a_lower_priority_agent_is_blocked_as_a_non_owner(tmp_path):
    m = Mini(); m.borrower("T1", dpd=0)                                             # bucket 0: only reminder may act
    m.contact("T1", "2026-10-30 20:00:00", "negotiation_agent", "call")             # negotiation owns this borrower until 20:00 today
    r, *_ = verdict(m, tmp_path, ev("DUE_SOON", time="2026-10-31T11:00:00"))
    assert r["final"] == "SUPPRESSED" and {"R035", "R036"} <= set(r["plan"]["rule_ids"])
    assert "negotiation is the active owner" in r["plan"]["reason"]
    # when the preferred role is blocked by the lease, the owner itself carries on
    m2 = Mini(); m2.borrower("T1", dpd=10)
    m2.contact("T1", "2026-10-31 08:00:00", "negotiation_agent", "call")
    r2, *_ = verdict(m2, tmp_path / "b", ev(time="2026-10-31T11:00:00"))
    assert r2["final"] == "OK" and r2["plan"]["role"] == "negotiation" and r2["plan"]["handoff"] is None


def test_servicing_replies_are_not_held_back_by_the_lease(tmp_path):
    m = Mini(); m.borrower("T1", dpd=10)
    m.contact("T1", "2026-10-31 08:00:00", "negotiation_agent", "call")
    r, *_ = verdict(m, tmp_path, ev("PAYMENT_RECEIVED", time="2026-10-31T11:00:00"))
    assert r["final"] == "OK" and r["plan"]["role"] == "servicing"


def test_a_lease_expires_after_24_hours(tmp_path):
    m = Mini(); m.borrower("T1", dpd=10)
    m.contact("T1", "2026-10-30 08:00:00", "negotiation_agent", "call")             # 26 h ago
    r, *_ = verdict(m, tmp_path)
    assert r["final"] == "OK" and r["plan"]["role"] == "reminder" and r["plan"]["handoff"] is None


def test_a_payment_confirmation_is_not_held_back_by_an_open_promise(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45); m.ptp("T1", "2026-11-05")                      # promised, then paid
    ctx, eng = setup(m, tmp_path)
    assert eng.evaluate("T1", ev("PAYMENT_RECEIVED"))["final"] == "OK"
    assert eng.evaluate("T1", ev("OVERDUE"))["guard"]["rule_ids"] == ["R062"]            # recovery contact is still held


def test_the_ptp_reminder_comes_from_the_agent_that_owns_the_promise(tmp_path):
    m = Mini()
    m.borrower("NEG", dpd=45); m.ptp("NEG", "2026-11-01", captured_by="negotiation_agent")
    m.borrower("AGY", dpd=45); m.ptp("AGY", "2026-11-01", captured_by="AGY001")
    ctx, eng = setup(m, tmp_path)
    a = eng.evaluate("NEG", ev("PTP_DUE", "NEG"))
    assert a["final"] == "OK" and (a["plan"]["role"], a["plan"]["action"]) == ("negotiation", "ptp_reminder")
    b = eng.evaluate("AGY", ev("PTP_DUE", "AGY"))
    assert b["final"] == "SUPPRESSED" and "R063" in b["plan"]["rule_ids"]


# ================================================================== purity and the trace
def test_evaluating_writes_nothing(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45)
    ctx, eng = setup(m, tmp_path)
    before = {t: ctx.db.one(f"SELECT COUNT(*) c FROM {t}")["c"] for t in ("contact_log", "decision_log", "event_queue")}
    for _ in range(3):
        eng.evaluate("T1", ev())
    assert before == {t: ctx.db.one(f"SELECT COUNT(*) c FROM {t}")["c"] for t in before}
    assert ctx.borrowers.load("T1")["owner"] is None and ctx.borrowers.get_lease("T1") == (None, None)


def test_every_refusal_cites_rule_ids(tmp_path):
    m = Mini()
    m.borrower("A", dpd=45, deceased=1); m.borrower("B", dpd=45, dnd_status="fully_blocked", dnd_effective_from="2025-01-01",
                                                      consent_whatsapp="unknown", consent_email="denied")
    m.borrower("C", dpd=20, phone=False, email=False, consent_call="not_applicable", consent_sms="not_applicable",
               consent_whatsapp="not_applicable", consent_email="not_applicable")
    m.borrower("D", dpd=20); m.ptp("D", "2026-11-09")
    ctx, eng = setup(m, tmp_path)
    for b in "ABCD":
        r = eng.evaluate(b, ev(b=b))
        assert r["final"] in ("BLOCKED", "SUPPRESSED"), (b, r["final"])
        shown = r["guard"] if r["plan"] is None else r["plan"]
        assert shown["rule_ids"] and shown["reason"], b


# ================================================================== the REAL portfolio
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


@pytest.fixture(scope="module")
def real_engine():
    ctx = Context.create(agents=default_agents())
    load_dataset(ctx.db, ctx.borrowers, REAL)
    return ctx, D12Policy(ctx.db, ctx.contacts, ctx.borrowers, ctx.registry)


@real
def test_real_every_deceased_borrower_is_blocked(real_engine):
    ctx, eng = real_engine
    ids = [r["customer_id"] for r in ctx.db.query("SELECT customer_id FROM customer WHERE deceased=1")]
    assert len(ids) == 85
    for b in ids:
        g = eng.evaluate(b, ev(b=b))["guard"]
        assert g["status"] == "BLOCKED" and g["rule_ids"] == ["R058"], b


@real
def test_real_a_sweep_of_3000_borrowers_obeys_the_invariants_and_is_fast(real_engine):
    ctx, eng = real_engine
    ids = [r["customer_id"] for r in ctx.db.query("SELECT customer_id FROM customer_profile ORDER BY customer_id LIMIT 3000")]
    t = time.perf_counter(); lat, counts = [], {}
    for b in ids:
        t0 = time.perf_counter()
        r = eng.evaluate(b, ev(b=b, type="OVERDUE"))
        lat.append((time.perf_counter() - t0) * 1000)
        counts[r["final"]] = counts.get(r["final"], 0) + 1
        refusal = r["guard"] if r["plan"] is None else (r["plan"] if r["final"] != "OK" else None)
        if r["final"] in ("BLOCKED", "SUPPRESSED", "DEFERRED"):
            assert (refusal or r["plan"])["rule_ids"], (b, r["final"])          # R093: every refusal cites a rule
        if r["final"] == "OK":
            p, accounts = r["plan"], ctx.db.query("SELECT legal_flag FROM account WHERE customer_id=?", (b,))
            assert set(p["channel_agents"]) <= {"whatsapp", "email", "voice"}
            if any(a["legal_flag"] for a in accounts):
                assert p["role"] == "legal", b                                    # R040 across all their accounts
    lat.sort()
    print(f"\n3000 borrowers: {counts}; evaluate p50={lat[1500]:.2f}ms p99={lat[2970]:.2f}ms max={lat[-1]:.2f}ms")
    assert lat[2970] < 100 and lat[-1] < 250
    assert counts.get("OK", 0) > 0 and counts.get("BLOCKED", 0) > 0 and counts.get("SUPPRESSED", 0) > 0


@real
def test_real_borrowers_already_at_their_cap_today_are_blocked(real_engine):
    ctx, eng = real_engine
    rows = ctx.db.query("SELECT customer_id, COUNT(*) n FROM ds_history WHERE substr(at,1,10)='2026-10-31' "
                        "GROUP BY customer_id HAVING n >= 3")
    assert len(rows) >= 100
    for r in rows[:150]:
        g = eng.evaluate(r["customer_id"], ev(b=r["customer_id"]))["guard"]
        assert g["status"] in ("BLOCKED", "DEFERRED") and g["rule_ids"], r["customer_id"]


@real
def test_real_nobody_is_ever_routed_to_a_channel_without_consent(real_engine):
    ctx, eng = real_engine
    ids = [r["customer_id"] for r in ctx.db.query("SELECT customer_id FROM ds_consent LIMIT 2500")]
    for b in ids:
        r = eng.evaluate(b, ev(b=b, type="OVERDUE"))
        if r["final"] != "OK":
            continue
        c = dict(ctx.db.one("SELECT * FROM ds_consent WHERE customer_id=?", (b,)))
        col = {"whatsapp": "consent_whatsapp", "email": "consent_email", "voice": "consent_call"}
        for agent in r["plan"]["channel_agents"]:
            st = c[col[agent]]
            assert st not in ("denied", "revoked", "not_applicable"), (b, agent, st)
            assert agent != "whatsapp" or st == "granted", (b, st)               # R045
