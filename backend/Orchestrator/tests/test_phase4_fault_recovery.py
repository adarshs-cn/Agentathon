"""PHASE 4 integration test: every fault, through the COMPLETE graph (stage 4).

The invariants that matter, asserted in every scenario:
  * the borrower receives at most one message
  * the owner lock is released
  * the borrower's state is not lost (a status or a last_contact, never nothing)
  * the decision log shows what the monitor saw and what it chose
"""
import pytest

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.agents.stubs import default_agents
from orchestrator.context import Context
from orchestrator.graph import build_graph
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS
from tests.helpers import make_event, new_checkpointer, run


def system(script, advisor=None, lookup_available=True):
    inj = FaultInjector(script)
    agents = default_agents(inj)
    for a in agents:
        a.lookup_available = lookup_available
    ctx = Context.create(agents=agents, advisor=advisor)
    ctx.borrowers.seed(SAMPLE_BORROWERS)
    return ctx, build_graph(ctx, new_checkpointer()), inj


def messages(ctx):
    """Total messages that really reached a provider, across all channels."""
    return sum(len(a.outbox) for a in ctx.registry._agents.values())


def calls(ctx, name):
    return ctx.registry.get(name).calls


def monitor_rows(ctx, event_id):
    return [r for r in ctx.decisions.for_event(event_id) if r["node"] == "monitor"]


def assert_invariants(ctx, acc):
    assert messages(ctx) <= 1, "a borrower must never receive two messages"
    b = ctx.borrowers.load(acc)
    assert b["owner"] is None, "owner lock must be released"
    assert b["last_contact"] is not None or b["status"] != "ACTIVE", "state must not be lost"


# ------------------------------------------------------------------ crash
def test_crash_after_send_is_never_resent():
    ctx, g, _ = system({("B1", 1): "CRASH_AFTER_SEND"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "CONTACTED"
    assert out["recovery"]["action"] == "RESTART_SKIP_CURRENT" and out["recovery"]["provider_state"] == "SENT"
    assert calls(ctx, "whatsapp") == 1 and messages(ctx) == 1          # agent called once, one message
    assert ctx.contacts.get("B1|2026-11-20")["status"] == "SENT"
    assert ctx.borrowers.load("B1")["last_contact"] == "2026-11-20T09:00:00"
    assert_invariants(ctx, "B1")


def test_crash_before_send_is_retried_and_succeeds():
    ctx, g, _ = system({("B1", 1): "CRASH_BEFORE_SEND"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"] == {"status": "CONTACTED", "agent": "whatsapp", "purpose": "reminder", "attempts": 2}
    assert calls(ctx, "whatsapp") == 2 and messages(ctx) == 1
    assert out["recovery"]["action"] == "RESUME"
    assert_invariants(ctx, "B1")


def test_resume_goes_back_to_the_agent_not_to_the_start():
    ctx, g, _ = system({("B1", 1): "CRASH_BEFORE_SEND"})
    run(g, make_event("e1", account_id="B1"))
    nodes = [r["node"] for r in ctx.decisions.for_event("e1")]
    assert nodes.count("validate_event") == 1 and nodes.count("guardrails") == 1 and nodes.count("route") == 1
    assert nodes.count("whatsapp") == 2 and nodes.count("monitor") == 1 and nodes.count("recover") == 1


def test_a_crashing_channel_is_abandoned_for_the_next_one():
    ctx, g, _ = system({("B1", 1): "CRASH_BEFORE_SEND", ("B1", 2): "CRASH_BEFORE_SEND"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "CONTACTED" and out["outcome"]["agent"] == "email"
    assert ctx.contacts.get("B1|2026-11-20")["channel"] == "email" and calls(ctx, "whatsapp") == 2
    assert [r["data"]["action"] for r in monitor_rows(ctx, "e1")] == ["RESUME", "REROUTE_CHANNEL"]
    assert_invariants(ctx, "B1")


# ------------------------------------------------------------------ malformed
def test_malformed_once_is_retried():
    ctx, g, _ = system({("B1", 1): "MALFORMED"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "CONTACTED" and out["outcome"]["attempts"] == 2
    assert monitor_rows(ctx, "e1")[0]["data"]["action"] == "RESUME"
    assert_invariants(ctx, "B1")


def test_malformed_twice_reroutes_to_another_channel():
    ctx, g, _ = system({("B1", 1): "MALFORMED", ("B1", 2): "MALFORMED"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["agent"] == "email" and out["outcome"]["status"] == "CONTACTED"
    assert_invariants(ctx, "B1")


# ------------------------------------------------------------------ loop
def test_a_looping_agent_is_stopped_after_three_calls_and_rerouted():
    ctx, g, _ = system({("B1", 1): "LOOP", ("B1", 2): "LOOP", ("B1", 3): "LOOP"})
    out = run(g, make_event("e1", account_id="B1"))
    assert calls(ctx, "whatsapp") == 3                                   # exactly the loop threshold
    assert out["outcome"]["agent"] == "email" and out["outcome"]["status"] == "CONTACTED"
    assert [r["data"]["action"] for r in monitor_rows(ctx, "e1")] == ["RESUME", "RESUME", "REROUTE_CHANNEL"]
    assert_invariants(ctx, "B1")


def test_loop_with_no_other_channel_escalates_to_human_review():
    ctx, g, _ = system({("B6", 1): "LOOP", ("B6", 2): "LOOP", ("B6", 3): "LOOP"})   # B6 has only whatsapp
    out = run(g, make_event("e1", account_id="B6"))
    assert out["outcome"]["status"] == "ESCALATED" and out["recovery"]["action"] == "ESCALATE"
    assert messages(ctx) == 0
    assert ctx.borrowers.load("B6")["status"] == "NEEDS_REVIEW" and ctx.borrowers.load("B6")["owner"] is None
    assert ctx.contacts.get("B6|2026-11-20")["status"] == "CANCELLED"
    # and the pause sticks: the next event for this borrower is blocked
    again = run(g, make_event("e2", account_id="B6", time="2026-11-20T15:00:00"))
    assert again["guard"]["rule"] == "STATUS"


def test_even_the_worst_case_chain_finishes_inside_the_recursion_limit():
    script = {("B1", n): "LOOP" for n in range(1, 10)}                  # every channel loops every time
    ctx, g, _ = system(script)
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "ESCALATED" and messages(ctx) == 0
    assert [calls(ctx, c) for c in ("whatsapp", "email", "voice")] == [3, 3, 3]


# ------------------------------------------------------------------ unknown provider state
def test_unconfirmable_crash_quarantines_instead_of_risking_a_double_contact():
    ctx, g, _ = system({("B1", 1): "CRASH_AFTER_SEND"}, lookup_available=False)
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "ESCALATED" and out["recovery"]["action"] == "QUARANTINE"
    assert out["recovery"]["provider_state"] == "UNKNOWN"
    assert calls(ctx, "whatsapp") == 1 and messages(ctx) == 1            # never retried
    b = ctx.borrowers.load("B1")
    assert b["status"] == "QUARANTINED" and b["owner"] is None
    assert ctx.contacts.get("B1|2026-11-20")["status"] == "ATTEMPTING"   # left open as evidence for a human


# ------------------------------------------------------------------ unscripted fault (TIMEOUT) and the advisor
def test_timeout_without_an_advisor_is_quarantined_safely():
    ctx, g, _ = system({("B1", 1): "TIMEOUT"})
    out = run(g, make_event("e1", account_id="B1"))
    assert out["recovery"]["action"] == "QUARANTINE" and out["recovery"]["advisor"] == "rules"
    assert ctx.borrowers.load("B1")["status"] == "QUARANTINED" and messages(ctx) == 0
    assert ctx.contacts.get("B1|2026-11-20")["status"] == "CANCELLED"    # provider says nothing was sent


class Advisor:
    def __init__(self, action=None, boom=False):
        self.action, self.boom, self.seen = action, boom, []

    def advise(self, fault, agent, account_id, allowed):
        self.seen.append((fault["type"], agent, account_id, list(allowed)))
        if self.boom:
            raise RuntimeError("llm down")
        return self.action, "diagnosis text"


def test_advisor_can_choose_from_the_safe_menu():
    adv = Advisor("RESUME")
    ctx, g, _ = system({("B1", 1): "TIMEOUT"}, advisor=adv)
    out = run(g, make_event("e1", account_id="B1"))
    assert out["outcome"]["status"] == "CONTACTED" and out["recovery"]["advisor"] == "llm"
    assert adv.seen == [("TIMEOUT", "whatsapp", "B1", ["RESUME", "REROUTE_CHANNEL", "QUARANTINE"])]
    assert_invariants(ctx, "B1")


@pytest.mark.parametrize("advice", [Advisor("SEND_ANYWAY"), Advisor(None), Advisor("RESUME", boom=True)])
def test_bad_or_missing_advice_falls_back_to_quarantine(advice):
    ctx, g, _ = system({("B1", 1): "TIMEOUT"}, advisor=advice)
    out = run(g, make_event("e1", account_id="B1"))
    assert out["recovery"]["action"] == "QUARANTINE" and out["recovery"]["advisor"] == "rules"


def test_advisor_is_never_consulted_when_a_message_may_have_gone_out():
    adv = Advisor("RESUME")
    ctx, g, _ = system({("B1", 1): "CRASH_AFTER_SEND"}, advisor=adv)
    run(g, make_event("e1", account_id="B1"))
    assert adv.seen == []


# ------------------------------------------------------------------ trail + mixed day
def test_every_fault_leaves_a_complete_trail():
    ctx, g, _ = system({("B1", 1): "CRASH_AFTER_SEND"})
    run(g, make_event("e1", account_id="B1"))
    rows = ctx.decisions.for_event("e1")
    nodes = [r["node"] for r in rows]
    assert nodes == ["validate_event", "load_customer", "guardrails", "route", "assign", "whatsapp",
                     "validate_output", "monitor", "recover", "commit", "release", "close_event"]
    m = next(r for r in rows if r["node"] == "monitor")
    assert m["data"]["provider_state"] == "SENT" and "never call the agent again" in m["text"]


def test_a_day_with_five_different_faults_has_zero_double_contacts():
    script = {("B1", 1): "CRASH_AFTER_SEND", ("B2", 1): "CRASH_BEFORE_SEND", ("B4", 1): "LOOP",
              ("B4", 2): "LOOP", ("B4", 3): "LOOP", ("B5", 1): "MALFORMED", ("B8", 1): "TIMEOUT"}
    ctx, g, inj = system(script)
    outcomes = {}
    for i, (acc, *_r) in enumerate(SAMPLE_BORROWERS):
        outcomes[acc] = run(g, make_event(f"e{i}", account_id=acc))["outcome"]["status"]
    assert inj.faulted_accounts() == {"B1", "B2", "B4", "B5", "B8"}
    # at most one message per borrower, across every channel
    per_account = {}
    for a in ctx.registry._agents.values():
        for key in a.outbox:
            per_account[key.split("|")[0]] = per_account.get(key.split("|")[0], 0) + 1
    assert per_account and max(per_account.values()) == 1
    assert ctx.borrowers.owners_held() == []
    assert outcomes["B8"] == "ESCALATED"                                  # the unscripted timeout was quarantined
    assert ctx.borrowers.load("B8")["status"] == "QUARANTINED"
    assert all(outcomes[a] == "CONTACTED" for a in ("B1", "B2", "B4", "B5"))
    assert [r for r in ctx.contacts.unresolved()] == []                    # nothing left ambiguous
