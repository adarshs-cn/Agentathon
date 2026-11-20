"""PHASE 1 integration test: stores, event bus, and the stage-1 graph
(validate_event -> load_customer, with close_event for rejects), run through the real
LangGraph checkpointer."""
from orchestrator.graph import build_graph
from orchestrator.state.models import REJECTED
from tests.helpers import make_event, new_checkpointer, run, thread_cfg


# ------------------------------------------------------------------ stores
def test_borrower_load_merges_facts_and_record(ctx):
    b = ctx.borrowers.load("B4")
    assert b["dpd"] == 45 and b["legal_flag"] is False
    assert b["channels"] == ["voice", "whatsapp", "email"]
    assert b["owner"] is None and b["status"] == "ACTIVE" and b["commitments"] == []
    assert ctx.borrowers.load("NOPE") is None


def test_owner_lock_is_compare_and_set(ctx):
    assert ctx.borrowers.try_take_owner("B1", "whatsapp") is True
    assert ctx.borrowers.try_take_owner("B1", "email") is False       # second agent refused
    assert ctx.borrowers.load("B1")["owner"] == "whatsapp"
    assert ctx.borrowers.switch_owner("B1", "email", "voice") is False  # only the holder may hand over
    assert ctx.borrowers.switch_owner("B1", "whatsapp", "email") is True
    ctx.borrowers.release("B1")
    assert ctx.borrowers.try_take_owner("B1", "voice") is True


def test_contact_log_one_row_per_borrower_per_day(ctx):
    c, key = ctx.contacts, "B1|2026-11-20"
    assert c.begin(key, "B1", "2026-11-20", "whatsapp", "reminder", "e1") == "NEW"
    assert c.begin(key, "B1", "2026-11-20", "email", "reminder", "e1") == "RESUMED"   # reroute reuses the row
    assert len(c.rows_for("B1")) == 1 and c.get(key)["channel"] == "email"
    assert c.daily_count("B1", "2026-11-20") == 1       # an unconfirmed attempt already counts
    c.mark_sent(key, "msg-1")
    assert c.begin(key, "B1", "2026-11-20", "voice", "reminder", "e2") == "ALREADY_SENT"
    assert c.cancel(key) is False                        # a confirmed send can never be cancelled
    assert c.get(key)["channel"] == "email"


def test_contact_log_cancel_and_reopen(ctx):
    c, key = ctx.contacts, "B2|2026-11-20"
    c.begin(key, "B2", "2026-11-20", "whatsapp", "reminder", "e1")
    assert c.cancel(key) is True
    assert c.daily_count("B2", "2026-11-20") == 0        # cancelled attempts do not count
    assert c.begin(key, "B2", "2026-11-20", "email", "reminder", "e9") == "REOPENED"


def test_agent_count(ctx):
    for acc, ch in (("B1", "email"), ("B2", "email"), ("B3", "voice")):
        ctx.contacts.begin(f"{acc}|d", acc, "d", ch, "reminder", "e")
    assert ctx.contacts.agent_count("email", "d") == 2 and ctx.contacts.agent_count("voice", "d") == 1


# ------------------------------------------------------------------ event bus
def test_bus_deduplicates_and_orders(ctx):
    bus = ctx.bus
    assert bus.publish(make_event("e2", account_id="B2", time="2026-11-20T10:00:00"))
    assert bus.publish(make_event("e1", account_id="B1", time="2026-11-20T09:00:00"))
    assert bus.publish(make_event("e1", account_id="B1", time="2026-11-20T09:00:00")) is False  # duplicate
    assert bus.claim_next()["id"] == "e1"                 # earlier event time first
    assert bus.claim_next()["id"] == "e2"
    assert bus.claim_next() is None


def test_bus_one_lane_per_account(ctx):
    bus = ctx.bus
    bus.publish(make_event("e1", account_id="B1", time="2026-11-20T09:00:00"))
    bus.publish(make_event("e2", account_id="B1", time="2026-11-20T09:05:00"))
    bus.publish(make_event("e3", account_id="B2", time="2026-11-20T09:10:00"))
    assert bus.claim_next()["id"] == "e1"
    assert bus.claim_next()["id"] == "e3"                 # e2 must wait: B1 already has one in progress
    assert bus.claim_next() is None
    bus.mark_done("e1", "CONTACTED")
    assert bus.claim_next()["id"] == "e2"


def test_bus_keeps_malformed_events_so_they_can_be_rejected_and_traced(ctx):
    assert ctx.bus.publish({"type": "DUE_SOON", "time": "2026-11-20T09:00:00"}) is True   # no id, no account
    ev = ctx.bus.claim_next()
    assert ev["id"].startswith("auto-") and ev["account_id"] == ""


def test_bus_in_progress_survives_and_can_be_requeued(ctx):
    ctx.bus.publish(make_event("e1"))
    ctx.bus.claim_next()
    assert [e["id"] for e in ctx.bus.in_progress()] == ["e1"]
    ctx.bus.requeue("e1")
    assert ctx.bus.stats() == {"PENDING": 1}
    assert ctx.bus.attempts("e1") == 1


# ------------------------------------------------------------------ stage-1 graph
def test_stage1_loads_borrower_into_graph_state(ctx):
    g = build_graph(ctx, new_checkpointer(), stage=1)
    out = run(g, make_event("e1", account_id="B4"))
    assert out["customer"]["dpd"] == 45
    assert out["customer"]["customer_id"] == "B4"
    assert out["attempt"] == 0 and out["fault"] is None and out["outcome"] is None
    # the graph state holds a COPY: the store row is untouched
    assert ctx.borrowers.load("B4")["owner"] is None


def test_stage1_rejects_bad_events(ctx):
    g = build_graph(ctx, new_checkpointer(), stage=1)
    cases = {
        "unknown account": (make_event("e1", account_id="ZZZ"), "unknown account ZZZ"),
        "unknown event type": (make_event("e2", type="WAT"), "unknown event type WAT"),
        "missing id": ({"type": "DUE_SOON", "account_id": "B1", "time": "2026-11-20T09:00:00"}, "missing ['id']"),
        "bad time": (make_event("e4", time="yesterday-ish"), "bad time"),
    }
    for label, (ev, expected) in cases.items():
        out = run(g, ev)
        assert out["outcome"]["status"] == REJECTED, label
        assert expected in out["outcome"]["reason"], label
        assert "borrower" not in out, label          # rejected before any borrower was loaded


def test_second_event_on_same_account_starts_clean(ctx):
    """The checkpoint keeps the previous run's state; validate_event must wipe the scratch fields."""
    g = build_graph(ctx, new_checkpointer(), stage=1)
    run(g, make_event("e1", account_id="B1"))
    g.update_state(thread_cfg("B1"), {"fault": {"type": "CRASH", "detail": "stale"}, "attempt": 5,
                                      "outcome": {"status": "CONTACTED"}})
    out = run(g, make_event("e2", account_id="B1", time="2026-11-20T11:00:00"))
    assert out["fault"] is None and out["attempt"] == 0 and out["outcome"] is None
    assert out["event"]["id"] == "e2"


def test_every_node_writes_to_the_decision_log(ctx):
    g = build_graph(ctx, new_checkpointer(), stage=1)
    run(g, make_event("e1", account_id="B1"))
    nodes = [r["node"] for r in ctx.decisions.for_event("e1")]
    assert nodes == ["validate_event", "load_customer"]
    run(g, make_event("e2", account_id="NOPE"))
    assert [r["node"] for r in ctx.decisions.for_event("e2")] == ["validate_event", "close_event"]


def test_checkpoints_are_persisted_per_account(ctx):
    cp = new_checkpointer()
    g = build_graph(ctx, cp, stage=1)
    run(g, make_event("e1", account_id="B1"))
    run(g, make_event("e2", account_id="B2"))
    h1 = list(g.get_state_history(thread_cfg("B1")))
    h2 = list(g.get_state_history(thread_cfg("B2")))
    assert len(h1) >= 3 and len(h2) >= 3                    # input + one per node
    # a brand-new graph object on the same checkpointer reads the saved state back (restart)
    g2 = build_graph(ctx, cp, stage=1)
    assert g2.get_state(thread_cfg("B1")).values["customer"]["customer_id"] == "B1"
    assert g2.get_state(thread_cfg("B2")).values["customer"]["customer_id"] == "B2"
