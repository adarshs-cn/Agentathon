"""PHASE 2 integration test: guardrails + routing, through the real stage-2 graph
(validate_event -> load_borrower -> guardrails -> route, then the run ends)."""
import pytest

from orchestrator.agents.stubs import default_agents
from orchestrator.config import Policy
from orchestrator.context import Context
from orchestrator.graph import build_graph
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS
from tests.helpers import make_event, new_checkpointer, run


def graph(ctx):
    return build_graph(ctx, new_checkpointer(), stage=2)


# ------------------------------------------------------------------ guardrails
def test_guardrails_allow_a_clean_borrower(ctx):
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["guard"]["ok"] is True and out["guard"]["rule"] == "NONE"
    assert out["decision"]["agent"] == "whatsapp"


def test_guardrail_blocks_paused_borrower(ctx):
    ctx.borrowers.set_status("B1", "NEEDS_REVIEW")
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["outcome"]["status"] == "BLOCKED" and out["guard"]["rule"] == "STATUS"
    assert out["decision"] is None                       # never reached routing


def test_guardrail_blocks_when_another_agent_owns_the_borrower(ctx):
    ctx.borrowers.try_take_owner("B1", "email")
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["guard"]["rule"] == "OWNER_LOCK" and "email" in out["outcome"]["reason"]


def test_guardrail_blocks_second_contact_same_day_any_channel(ctx):
    ctx.contacts.begin("B1|2026-11-20", "B1", "2026-11-20", "email", "reminder", "e0")
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["guard"]["rule"] == "DAILY_CAP"
    # a different day is fine
    out = run(graph(ctx), make_event("e2", account_id="B1", time="2026-11-21T09:00:00"))
    assert out["guard"]["ok"] is True


def test_guardrail_precedence_status_then_owner_then_cap(ctx):
    ctx.borrowers.try_take_owner("B1", "email")
    ctx.contacts.begin("B1|2026-11-20", "B1", "2026-11-20", "email", "reminder", "e0")
    assert run(graph(ctx), make_event(account_id="B1"))["guard"]["rule"] == "OWNER_LOCK"
    ctx.borrowers.set_status("B1", "QUARANTINED")
    assert run(graph(ctx), make_event("e2", account_id="B1"))["guard"]["rule"] == "STATUS"


# ------------------------------------------------------------------ routing: purpose + channel
ROUTE_CASES = [
    # account, event type, purpose, agent, fallbacks, rule
    ("B1", "DUE_SOON", "reminder", "whatsapp", ["email", "voice"], 7),
    ("B1", "CONTACT_REQUESTED", "reminder", "whatsapp", ["email", "voice"], 7),
    ("B1", "PAYMENT_RECEIVED", "servicing", "whatsapp", ["email"], 2),
    ("B1", "PTP_BROKEN", "negotiation", "voice", ["whatsapp", "email"], 3),
    ("B4", "DUE_SOON", "negotiation", "voice", ["whatsapp", "email"], 6),
    ("B5", "DUE_SOON", "negotiation", "voice", ["whatsapp"], 6),
    ("B6", "DUE_SOON", "reminder", "whatsapp", [], 7),            # only one channel to use
    ("B7", "DUE_SOON", "legal", "email", [], 1),                  # legal flag; legal is email only
    ("B7", "PAYMENT_RECEIVED", "legal", "email", [], 1),          # the legal flag outranks everything
]


@pytest.mark.parametrize("acc,etype,purpose,agent,fallbacks,rule", ROUTE_CASES)
def test_route_table(ctx, acc, etype, purpose, agent, fallbacks, rule):
    out = run(graph(ctx), make_event(type=etype, account_id=acc))
    d = out["decision"]
    assert (d["purpose"], d["agent"], d["fallbacks"], d["rule"]) == (purpose, agent, fallbacks, rule)
    assert d["reason"]


def test_no_reachable_channel_is_suppressed_with_a_reason(ctx):
    out = run(graph(ctx), make_event(account_id="B10"))           # B10 has no channels
    assert out["decision"]["agent"] is None and out["decision"]["rule"] == 8
    assert out["outcome"]["status"] == "SUPPRESSED"


def test_open_promise_to_pay_suppresses_contact(ctx):
    ctx.borrowers.set_commitments("B9", [{"type": "PTP", "due": "2026-11-22", "amount": 5000}])
    out = run(graph(ctx), make_event(account_id="B9"))
    assert out["outcome"]["status"] == "SUPPRESSED" and out["decision"]["rule"] == 4
    # ...but a broken promise or a payment still routes
    assert run(graph(ctx), make_event("e2", type="PTP_BROKEN", account_id="B9"))["decision"]["rule"] == 3
    assert run(graph(ctx), make_event("e3", type="PAYMENT_RECEIVED", account_id="B9"))["decision"]["rule"] == 2


@pytest.mark.parametrize("dpd,purpose", [(0, "reminder"), (29, "reminder"), (30, "negotiation"),
                                          (89, "negotiation"), (90, "legal"), (200, "legal")])
def test_dpd_boundaries(dpd, purpose):
    c = Context.create(agents=default_agents())
    c.borrowers.seed([("X", dpd, False, ["whatsapp", "email", "voice"])])
    assert run(graph(c), make_event(account_id="X"))["decision"]["purpose"] == purpose


def test_unregistered_agent_is_never_chosen():
    c = Context.create(agents=[a for a in default_agents() if a.name != "whatsapp"])
    c.borrowers.seed(SAMPLE_BORROWERS)
    out = run(graph(c), make_event(account_id="B1"))
    assert out["decision"]["agent"] == "email" and out["decision"]["fallbacks"] == ["voice"]


def test_agent_budget_moves_to_next_channel_then_suppresses():
    c = Context.create(policy=Policy(per_agent_daily_cap=1), agents=default_agents())
    c.borrowers.seed([("X", 5, False, ["whatsapp", "email"]), ("Y", 5, False, ["whatsapp", "email"]),
                      ("Z", 5, False, ["whatsapp", "email"])])
    c.contacts.begin("Q|2026-11-20", "Q", "2026-11-20", "whatsapp", "reminder", "e0")   # whatsapp budget used
    d = run(graph(c), make_event("e1", account_id="X"))["decision"]
    assert d["agent"] == "email" and d["fallbacks"] == []
    c.contacts.begin("R|2026-11-20", "R", "2026-11-20", "email", "reminder", "e0")      # email budget used too
    out = run(graph(c), make_event("e2", account_id="Y"))
    assert out["decision"]["rule"] == 9 and out["outcome"]["status"] == "SUPPRESSED"


def test_routing_is_well_under_100ms_and_every_decision_is_logged(ctx):
    g = graph(ctx)
    for i in range(200):
        run(g, make_event(f"e{i}", account_id="B1", time=f"2026-11-{(i % 28) + 1:02d}T09:00:00"))
    assert ctx.percentile("route", 0.99) < 100, "routing p99 must be under 100 ms"
    assert max(ctx.metrics["route"]) < 100
    rows = [r for r in ctx.decisions.for_account("B1") if r["node"] == "route"]
    assert len(rows) == 200 and all("rule" in r["data"] and r["data"]["reason"] for r in rows)
