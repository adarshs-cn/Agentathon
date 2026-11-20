"""PHASE 3 integration test: the full happy path through the stage-3 graph
(... route -> assign -> channel agent -> validate_output -> commit -> release -> close_event),
plus the agent adapters. Faults are only DETECTED at this stage; recovery arrives in phase 4."""
import time

from orchestrator.agents.base import ChannelAgent
from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.agents.runner import call_with_timeout
from orchestrator.agents.stubs import default_agents
from orchestrator.config import Policy
from orchestrator.context import Context
from orchestrator.graph import build_graph
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS
from tests.helpers import make_event, new_checkpointer, run


def graph(ctx, stage=3):
    return build_graph(ctx, new_checkpointer(), stage=stage)


def agent(ctx, name):
    return ctx.registry.get(name)


# ------------------------------------------------------------------ the happy path
def test_reminder_goes_out_on_whatsapp_and_state_is_committed(ctx):
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["outcome"] == {"status": "CONTACTED", "agent": "whatsapp", "purpose": "reminder", "attempts": 1}
    assert out["result"]["channel"] == "whatsapp" and out["result"]["template"] == "wa_template/reminder_v1"
    row = ctx.contacts.get("B1|2026-11-20")
    assert row["status"] == "SENT" and row["channel"] == "whatsapp" and row["provider_ref"] == out["result"]["provider_ref"]
    b = ctx.borrowers.load("B1")
    assert b["last_contact"] == "2026-11-20T09:00:00" and b["owner"] is None      # committed, lock released
    assert list(agent(ctx, "whatsapp").outbox) == ["B1|2026-11-20"]
    assert agent(ctx, "email").calls == 0 and agent(ctx, "voice").calls == 0


def test_node_order_is_the_documented_path(ctx):
    run(graph(ctx), make_event("e1", account_id="B1"))
    assert [r["node"] for r in ctx.decisions.for_event("e1")] == [
        "validate_event", "load_borrower", "guardrails", "route", "assign",
        "whatsapp", "validate_output", "commit", "release", "close_event"]


def test_negotiation_uses_the_ivr_voice_agent_with_its_own_template(ctx):
    out = run(graph(ctx), make_event(account_id="B4"))
    assert out["outcome"]["agent"] == "voice" and out["outcome"]["purpose"] == "negotiation"
    assert out["result"]["template"] == "ivr_script/negotiation_v1"


def test_legal_notice_goes_by_email(ctx):
    out = run(graph(ctx), make_event(account_id="B7"))
    assert out["outcome"]["agent"] == "email" and out["result"]["template"] == "email_template/legal_v1"


def test_one_contact_per_day_even_across_channels(ctx):
    g = graph(ctx)
    run(g, make_event("e1", account_id="B1", time="2026-11-20T09:00:00"))
    out = run(g, make_event("e2", type="CONTACT_REQUESTED", account_id="B1", time="2026-11-20T11:00:00"))
    assert out["outcome"]["status"] == "BLOCKED" and out["guard"]["rule"] == "DAILY_CAP"
    assert sum(len(a.outbox) for a in ctx.registry._agents.values()) == 1          # exactly one message
    # next day is a fresh allowance
    assert run(g, make_event("e3", account_id="B1", time="2026-11-21T09:00:00"))["outcome"]["status"] == "CONTACTED"


def test_whole_sample_book_processes_with_no_double_contact(ctx):
    g = graph(ctx)
    outcomes = {}
    for i, (acc, *_rest) in enumerate(SAMPLE_BORROWERS):
        outcomes[acc] = run(g, make_event(f"e{i}", account_id=acc))["outcome"]["status"]
    assert outcomes["B10"] == "SUPPRESSED"                                          # no reachable channel
    assert all(v == "CONTACTED" for k, v in outcomes.items() if k != "B10")
    assert ctx.contacts.sent_total() == 9
    assert ctx.borrowers.owners_held() == []                                        # every lock released


def test_agent_budget_is_enforced_per_channel():
    c = Context.create(policy=Policy(per_agent_daily_cap=2), agents=default_agents())
    c.borrowers.seed([(f"X{i}", 5, False, ["whatsapp", "email"]) for i in range(5)])
    g = graph(c)
    outs = [run(g, make_event(f"e{i}", account_id=f"X{i}"))["outcome"] for i in range(5)]
    assert [o.get("agent") for o in outs] == ["whatsapp", "whatsapp", "email", "email", None]
    assert outs[4]["status"] == "SUPPRESSED"                 # both channels are over budget
    assert c.contacts.agent_count("whatsapp", "2026-11-20") == 2 and c.contacts.agent_count("email", "2026-11-20") == 2


# ------------------------------------------------------------------ the owner lock
def test_losing_the_lock_between_guardrails_and_assign_stops_the_run(ctx):
    def steal(name, state):
        if name == "assign":
            ctx.borrowers.try_take_owner("B1", "email")        # another worker wins the race
    ctx.on_node_start = steal
    out = run(graph(ctx), make_event(account_id="B1"))
    assert out["outcome"]["status"] == "BLOCKED" and "lost the owner lock" in out["outcome"]["reason"]
    assert agent(ctx, "whatsapp").calls == 0 and ctx.contacts.rows_for("B1") == []
    assert ctx.borrowers.load("B1")["owner"] == "email"          # the winner keeps it


def test_assign_is_safe_to_replay(ctx):
    """If the process dies after taking the lock but before the checkpoint, assign runs again."""
    ctx.borrowers.try_take_owner("B1", "whatsapp")
    ctx.on_node_start = lambda name, state: None
    g = graph(ctx)
    # guardrails would block (owner set), so call assign directly with a prepared state
    from orchestrator.nodes.execution import make_assign
    state = {"event": make_event(), "borrower": ctx.borrowers.load("B1"),
             "decision": {"agent": "whatsapp", "purpose": "reminder", "fallbacks": []}}
    upd = make_assign(ctx)(state)
    assert "outcome" not in upd and upd["borrower"]["owner"] == "whatsapp" and upd["attempt"] == 0


# ------------------------------------------------------------------ faults are detected (not yet recovered)
def faulty(script):
    inj = FaultInjector(script)
    c = Context.create(agents=default_agents(inj))
    c.borrowers.seed(SAMPLE_BORROWERS)
    return c


def test_malformed_output_is_detected(ctx):
    c = faulty({("B1", 1): "MALFORMED"})
    out = run(graph(c), make_event(account_id="B1"))
    assert out["fault"]["type"] == "MALFORMED"
    assert c.contacts.get("B1|2026-11-20")["status"] == "ATTEMPTING"            # never marked SENT


def test_loop_is_detected_as_no_progress():
    c = faulty({("B1", 1): "LOOP"})
    out = run(graph(c), make_event(account_id="B1"))
    assert out["fault"]["type"] == "NO_PROGRESS"


def test_crash_after_send_is_detected_and_the_message_really_went_out():
    c = faulty({("B1", 1): "CRASH_AFTER_SEND"})
    out = run(graph(c), make_event(account_id="B1"))
    assert out["fault"]["type"] == "CRASH"
    assert "B1|2026-11-20" in c.registry.get("whatsapp").outbox                # the provider has it
    assert c.contacts.get("B1|2026-11-20")["status"] == "ATTEMPTING"           # ...but we never confirmed it
    assert c.borrowers.load("B1")["owner"] == "whatsapp"                       # lock still held: phase 4 recovers this


def test_crash_before_send_leaves_nothing_at_the_provider():
    c = faulty({("B1", 1): "CRASH_BEFORE_SEND"})
    out = run(graph(c), make_event(account_id="B1"))
    assert out["fault"]["type"] == "CRASH" and c.registry.get("whatsapp").outbox == {}


class SlowAgent(ChannelAgent):
    name = "whatsapp"
    def execute(self, req):
        time.sleep(0.5)
        return {}
    def lookup(self, key):
        return "UNKNOWN"


class BrokenAgent(ChannelAgent):
    name = "whatsapp"
    def execute(self, req):
        raise ValueError("provider returned 500")
    def lookup(self, key):
        return "UNKNOWN"


def test_hung_agent_becomes_a_timeout_fault():
    c = Context.create(policy=Policy(agent_timeout_s=0.05), agents=[SlowAgent()])
    c.borrowers.seed([("X", 5, False, ["whatsapp"])])
    out = run(graph(c), make_event(account_id="X"))
    assert out["fault"]["type"] == "TIMEOUT"


def test_unexpected_exception_from_a_real_agent_is_treated_as_a_crash():
    c = Context.create(agents=[BrokenAgent()])
    c.borrowers.seed([("X", 5, False, ["whatsapp"])])
    out = run(graph(c), make_event(account_id="X"))
    assert out["fault"]["type"] == "CRASH" and "ValueError" in out["fault"]["detail"]


# ------------------------------------------------------------------ the agent layer on its own
def test_call_with_timeout_returns_raises_and_times_out():
    assert call_with_timeout(lambda x: x * 2, 1.0, 21) == 42
    try:
        call_with_timeout(lambda: (_ for _ in ()).throw(KeyError("k")), 1.0)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
    t0 = time.perf_counter()
    try:
        call_with_timeout(time.sleep, 0.05, 1)
    except Exception as e:  # noqa: BLE001
        assert type(e).__name__ == "AgentTimeout"
    assert time.perf_counter() - t0 < 0.5


def test_stub_provider_dedupes_on_the_idempotency_key_and_lookup_answers():
    from orchestrator.agents.base import ContactRequest
    a = default_agents()[0]
    req = ContactRequest("B1", "reminder", "t", "B1|d", "e1", "t")
    assert a.lookup("B1|d") == "NOT_SENT"
    r1, r2 = a.execute(req), a.execute(req)
    assert r1["provider_ref"] == r2["provider_ref"] and len(a.outbox) == 1       # a replay sends nothing new
    assert a.lookup("B1|d") == "SENT"
    a.lookup_available = False
    assert a.lookup("B1|d") == "UNKNOWN"


def test_fault_injector_counts_calls_per_account_across_channels():
    inj = FaultInjector({("B1", 2): "TIMEOUT"})
    assert inj.next_fault("B1") is None and inj.next_fault("B2") is None
    assert inj.next_fault("B1") == "TIMEOUT" and inj.next_fault("B1") is None
    assert inj.fired == [("B1", 2, "TIMEOUT")] and inj.faulted_accounts() == {"B1"}
