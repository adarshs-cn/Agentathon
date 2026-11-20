"""Phase 14: the 15-event walkthrough: scenario builder, run one event on demand, live node stream, stored steps,
the message the agent sent, plain-language reasons and the tile drilldowns. All on the real portfolio."""
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.agents.messages import LINES, render
from orchestrator.ui import reasons
from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.state import DemoState

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")

# event number -> (outcome, role, channel)
EXPECT = {1: ("CONTACTED", "reminder", "whatsapp"), 2: ("CONTACTED", "reminder", "email"),
          3: ("CONTACTED", "negotiation", "voice"), 4: ("CONTACTED", "negotiation", "voice"),
          5: ("CONTACTED", "reminder", "whatsapp"), 6: ("CONTACTED", "negotiation", "voice"),
          7: ("CONTACTED", "servicing", "whatsapp"), 8: ("BLOCKED", None, None), 9: ("BLOCKED", None, None),
          10: ("DEFERRED", None, None), 11: ("CONTACTED", "reminder", "whatsapp"), 12: ("DEFERRED", None, None),
          13: ("CONTACTED", "reminder", "whatsapp"), 14: ("CONTACTED", "reminder", "email"),
          15: ("CONTACTED", "legal", "email")}
GRAPH_ORDER = ["validate_event", "load_borrower", "guardrails", "route", "assign"]


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    state = DemoState(tmp_path_factory.mktemp("scn"), REAL, mode="scenario")
    return TestClient(create_dashboard_app(state)), state


def run(state, n):
    return state.runs.start(f"demo-{n:02d}", pace_ms=0, wait=True)


@real
def test_builder_makes_fifteen_distinct_real_borrowers_with_listed_setup(api):
    c, state = api
    items = c.get("/api/scenario").json()["items"]
    assert [i["seq"] for i in items] == list(range(1, 16))
    assert len({i["borrower_id"] for i in items if i["seq"] != 12}) == 14           # 12 shares 11's borrower on purpose
    assert items[11]["borrower_id"] == items[10]["borrower_id"]
    assert all(i["status"] == "not_run" for i in items)
    staged = {r["table_name"] for r in state.reader.query("SELECT table_name FROM demo_setup")}
    assert staged == {"ds_history", "ds_ptp", "ds_payment"}
    assert state.reader.one("SELECT COUNT(*) n FROM event_queue WHERE status='PENDING'")["n"] == 15   # nothing ran yet


@real
def test_same_borrowers_on_every_build(api, tmp_path):
    _, state = api
    again = DemoState(tmp_path, REAL, mode="scenario")
    assert [r["borrower_id"] for r in again.scenario_rows] == [r["borrower_id"] for r in state.scenario_rows]


@real
def test_second_request_is_unavailable_until_the_first_has_run(api):
    c, _ = api
    it = c.get("/api/scenario").json()["items"][11]
    assert it["available"] is False and "first" in it["why_unavailable"].lower() or "event 11" in it["why_unavailable"]
    r = c.post("/api/scenario/demo-12/run?pace_ms=0")
    assert r.status_code == 409 and "11" in r.json()["detail"]


@real
@pytest.mark.parametrize("n", list(range(1, 16)))
def test_each_event_ends_as_the_plan_says(api, n):
    c, state = api
    if n == 12:
        run(state, 11) if state.reader.one("SELECT status FROM event_queue WHERE event_id='demo-11'")["status"] == "PENDING" else None
    if state.reader.one("SELECT status FROM event_queue WHERE event_id=?", (f"demo-{n:02d}",))["status"] == "PENDING":
        run(state, n)
    s = c.get(f"/api/scenario/demo-{n:02d}/steps").json()
    outcome, role, channel = EXPECT[n]
    assert s["outcome"] == outcome, s["steps"][-1]["did"]
    item = c.get("/api/scenario").json()["items"][n - 1]
    assert (item["role"], item["channel"]) == (role, channel)
    assert (s["message"] is not None) == (outcome == "CONTACTED")


@real
def test_replay_does_not_execute_twice(api):
    c, state = api
    before = state.reader.one("SELECT COUNT(*) n FROM contact_log WHERE status='SENT'")["n"]
    r = c.post("/api/scenario/demo-01/run?pace_ms=0").json()
    assert r["replay"] is True
    assert state.reader.one("SELECT COUNT(*) n FROM contact_log WHERE status='SENT'")["n"] == before


@real
def test_stored_steps_cover_the_graph_in_order_with_plain_sentences_and_owners(api):
    c, _ = api
    for n in (1, 8, 13, 14):
        steps = c.get(f"/api/scenario/demo-{n:02d}/steps").json()["steps"]
        assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
        assert steps[0]["node"] == "validate_event" and steps[-1]["node"] == "close_event"
        assert all(s["did"] and s["label"] and s["station"] for s in steps)
        assert not any(re.match(r"^\s*(R\d{3}|A12|D12)", s["did"]) for s in steps)           # a code is never the headline
    happy = c.get("/api/scenario/demo-01/steps").json()["steps"]
    assign = next(s for s in happy if s["node"] == "assign")
    assert assign["owner_before"] is None and assign["owner_after"] == "reminder"            # fresh account: nobody, then Reminder
    assert [s["node"] for s in happy][:4] == GRAPH_ORDER[:4]
    handoff = next(s for s in c.get("/api/scenario/demo-04/steps").json()["steps"] if s["node"] == "assign")
    assert handoff["owner_before"] == "reminder" and handoff["owner_after"] == "negotiation" and "Reminder → Negotiation" in handoff["did"]
    stopped = c.get("/api/scenario/demo-08/steps").json()["steps"]
    assert stopped[-1]["station"] == "stopped" and "promise" in stopped[-1]["did"].lower()
    for n, station in ((13, "recover"), (14, "recover")):
        assert station in [s["station"] for s in c.get(f"/api/scenario/demo-{n}/steps").json()["steps"]]


@real
def test_crash_after_send_sends_exactly_once(api):
    _, state = api
    b = state.reader.one("SELECT borrower_id FROM demo_event WHERE seq=13")["borrower_id"]
    assert state.reader.one("SELECT COUNT(*) n FROM contact_log WHERE account_id=? AND status='SENT'", (b,))["n"] == 1
    assert state.reader.one("SELECT COUNT(*) n FROM decision_log WHERE event_id='demo-13' AND text LIKE 'SKIP%'")["n"] == 1


@real
def test_live_stream_announces_start_then_end_for_every_node_in_order(tmp_path):
    state = DemoState(tmp_path, REAL, mode="scenario")
    q = state.runs.subscribe()
    state.runs.start("demo-13", pace_ms=0, wait=True)
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    names = [e[0] for e in evs]
    assert names[0] == "run_start" and names[-1] == "run_end"
    steps = [p for n, p in evs if n == "step"]
    starts = [s["node"] for s in steps if s["phase"] == "start"]
    ends = [s["node"] for s in steps if s["phase"] == "end"]
    assert starts == ends and starts[0] == "validate_event" and "monitor" in starts and "recover" in starts
    for i in range(0, len(steps), 2):                                   # strictly start, end, start, end
        assert steps[i]["phase"] == "start" and steps[i + 1]["phase"] == "end" and steps[i]["node"] == steps[i + 1]["node"]
    end = evs[-1][1]
    assert end["outcome"] == "CONTACTED" and end["message"]["channel"] == "whatsapp"


@real
def test_only_one_run_at_a_time(api):
    c, state = api
    state.runs.active = {"run_id": "x", "event_id": "demo-01"}
    try:
        state.runs._lock.acquire(); state.runs._lock.release()
        # demo events 1..15 not all done in every ordering, so use a fresh pending one if any, else reset
        pending = state.reader.one("SELECT d.event_id FROM demo_event d JOIN event_queue q USING(event_id) WHERE q.status='PENDING' LIMIT 1")
        if pending is not None:
            assert c.post(f"/api/scenario/{pending['event_id']}/run?pace_ms=0").status_code in (409,)
        assert c.post("/api/scenario/reset").status_code == 409
    finally:
        state.runs.active = None


@real
def test_messages_are_complete_masked_and_leak_nothing(api):
    c, state = api
    seen = 0
    for n in range(1, 16):
        m = c.get(f"/api/scenario/demo-{n:02d}/steps").json()["message"]
        if not m:
            continue
        seen += 1
        assert m["body"].strip() and "{" not in m["body"] and "None" not in m["body"]
        assert m["channel"] in ("whatsapp", "email", "voice")
        assert "CreditNirvana" in m["body"] or "Dear" in m["body"]
        assert m["to"] and not re.search(r"\d{8,}", m["to"])                           # a masked or placeholder contact only
        assert "@" not in (m["to"] or "") or "***" in m["to"] or m["to"] == "your demo email"
    assert seen == 11


def test_every_template_and_channel_renders():
    ctx = {"name": "Customer", "emi": "₹1,000", "dues": "₹2,000", "dpd": 5, "amount": "₹1,000", "to_phone": "XXXXXX1234", "to_email": "d***@x.com"}
    for action in LINES:
        for ch in ("whatsapp", "email", "voice"):
            m = render(action, ch, ctx)
            assert m["body"] and "{" not in m["body"]


@real
def test_every_rule_in_the_policy_has_a_plain_label(api):
    _, state = api
    for r in state.reader.query("SELECT * FROM ds_rule"):
        head, why = reasons.label(r["rule_id"], dict(r))
        assert head != "Policy rule applied", f"{r['rule_id']} ({r['parameter']}) has no plain label"
    for rid in reasons.RULES:
        assert reasons.RULES[rid][0]


@real
def test_drilldown_rows_add_up_to_the_tiles(api):
    c, state = api
    for n in range(1, 16):
        if state.reader.one("SELECT status FROM event_queue WHERE event_id=?", (f"demo-{n:02d}",))["status"] == "PENDING":
            run(state, n)
    time.sleep(2.0)                                                     # let the background audit finish
    counters = c.get("/api/overview").json()["counters"]
    d = {t: c.get(f"/api/overview/drilldown/{t}").json() for t in ("contacts", "blocked", "borrowers", "faults", "conflicts", "latency")}
    assert len(d["contacts"]["rows"]) == counters["contacts_made"] == 11
    assert len(d["blocked"]["rows"]) == 4                                # 8, 9, 10, 12
    assert counters["conflicting_contacts"] == 0 and d["conflicts"]["rows"] == []
    assert len(d["faults"]["rows"]) == 2 and all(r["recovered"] == "Yes" for r in d["faults"]["rows"])
    assert all(float(r["ms"].split()[0]) < 100 for r in d["latency"]["rows"]) and len(d["latency"]["rows"]) == 12      # events stopped before routing have no routing time
    assert c.get("/api/overview/drilldown/nope").status_code == 404


@real
def test_reset_returns_every_event_to_not_run(api):
    c, _ = api
    body = c.post("/api/scenario/reset").json()
    assert body["done"] == 0 and all(i["status"] == "not_run" for i in body["items"])


@real
def test_a_second_run_while_one_is_active_is_refused(tmp_path):
    state = DemoState(tmp_path, REAL, mode="scenario")
    c = TestClient(create_dashboard_app(state))
    first = c.post("/api/scenario/demo-01/run?pace_ms=150").json()
    assert first["replay"] is False
    r = c.post("/api/scenario/demo-02/run?pace_ms=0")
    assert r.status_code == 409 and "running" in r.json()["detail"]
    assert c.post("/api/scenario/reset").status_code == 409
    for _ in range(100):                                               # let the first finish (about 11 nodes x 150 ms)
        if state.runs.active is None:
            break
        time.sleep(0.1)
    assert state.runs.active is None
    assert c.post("/api/scenario/demo-02/run?pace_ms=0").status_code == 200


@real
def test_a_restart_keeps_the_run_and_only_reset_clears_it(tmp_path):
    a = DemoState(tmp_path, REAL, mode="scenario")
    for n in (1, 8, 13):
        a.runs.start(f"demo-{n:02d}", pace_ms=0, wait=True)
    steps_before = a.runs.steps("demo-13")
    msg_before = a.runs.message("demo-01", a.scenario_rows[0]["borrower_id"])
    a.sup.close()
    b = DemoState(tmp_path, REAL, mode="scenario")                       # a new process, same folder
    c = TestClient(create_dashboard_app(b))
    items = c.get("/api/scenario").json()
    assert items["done"] == 3 and [i["seq"] for i in items["items"] if i["status"] == "done"] == [1, 8, 13]
    assert b.runs.steps("demo-13") == steps_before and b.runs.message("demo-01", b.scenario_rows[0]["borrower_id"]) == msg_before
    ov = c.get("/api/overview").json()["counters"]
    assert ov["contacts_made"] == 2 and ov["faults_injected"] == 1 and ov["faults_recovered"] == 1
    b.runs.start("demo-02", pace_ms=0, wait=True)                         # the reopened supervisor still works
    assert c.get("/api/scenario").json()["done"] == 4
    assert c.post("/api/scenario/reset").json()["done"] == 0


@real
def test_walkthrough_runs_are_never_saved_as_journey_runs(tmp_path):
    a = DemoState(tmp_path, REAL, mode="scenario")
    for n in (1, 8, 13):
        a.runs.start(f"demo-{n:02d}", pace_ms=0, wait=True)
    c = TestClient(create_dashboard_app(a))
    assert c.get("/api/journeys").json()["total"] == 0 and c.get("/api/notifications").json()["unseen"] == 0
