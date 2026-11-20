"""PHASE 6 integration test: the HTTP API and the per-account trace, end to end
(HTTP request -> bus -> graph -> stores -> HTTP response)."""
import pytest
from fastapi.testclient import TestClient

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.api.app import create_app
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS, synthetic_borrowers
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import generate_day, load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, build_fault_script
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.trace import account_trace, trace_gaps


@pytest.fixture
def api():
    sup = Supervisor(injector=FaultInjector({("B2", 1): "CRASH_AFTER_SEND", ("B8", 1): "TIMEOUT"}))
    sup.seed_borrowers(SAMPLE_BORROWERS)
    return TestClient(create_app(sup)), sup


def ev(id="e1", acc="B1", type="DUE_SOON", time="2026-11-20T09:00:00"):
    return {"id": id, "type": type, "account_id": acc, "time": time}


def test_health_and_empty_stats(api):
    c, _ = api
    assert c.get("/health").json() == {"ok": True, "bus": {}, "borrowers": 10}
    assert c.get("/stats").json()["contacts_sent"] == 0


def test_post_event_then_process_returns_the_outcome(api):
    c, _ = api
    r = c.post("/events?process=true", json=ev()).json()
    assert r == {"event_id": "e1", "published": True, "status": "DONE", "outcome": "CONTACTED"}
    again = c.post("/events?process=true", json=ev()).json()
    assert again["published"] is False                                           # duplicate delivery ignored


def test_post_without_processing_queues_it_and_run_drains_it(api):
    c, _ = api
    assert c.post("/events", json=ev("e1")).json()["status"] == "PENDING"
    c.post("/events", json=ev("e2", acc="B2"))
    assert c.get("/health").json()["bus"] == {"PENDING": 2}
    assert c.post("/run").json()["processed"] == 2
    assert c.get("/events/e1").json()["status"] == "DONE"


def test_the_account_listing_shows_owner_last_contact_and_status(api):
    c, _ = api
    c.post("/events?process=true", json=ev("e1", "B1"))
    c.post("/events?process=true", json=ev("e2", "B8"))                          # B8's agent times out -> quarantined
    page = c.get("/accounts?limit=10").json()
    assert page["total"] == 10 and len(page["items"]) == 10
    by = {i["account_id"]: i for i in page["items"]}
    assert by["B1"]["last_contact"] == "2026-11-20T09:00:00" and by["B1"]["owner"] is None
    assert by["B8"]["status"] == "QUARANTINED" and by["B2"]["last_contact"] is None
    assert [i["account_id"] for i in c.get("/accounts?status=QUARANTINED").json()["items"]] == ["B8"]
    assert len(c.get("/accounts?limit=3&offset=3").json()["items"]) == 3
    assert c.get("/accounts?limit=0").status_code == 422                         # bad pagination is rejected


def test_account_and_trace_404_for_unknown_accounts(api):
    c, _ = api
    assert c.get("/accounts/NOPE").status_code == 404
    assert c.get("/accounts/NOPE/trace").status_code == 404
    assert c.get("/events/nope").status_code == 404


def test_trace_tells_the_whole_story_of_a_faulted_account(api):
    c, _ = api
    c.post("/events?process=true", json=ev("e1", "B2"))                          # crashes after sending
    c.post("/events?process=true", json=ev("e2", "B2", "CONTACT_REQUESTED", "2026-11-20T11:00:00"))
    t = c.get("/accounts/B2/trace").json()
    assert t["complete"] is True and t["borrower"]["last_contact"] == "2026-11-20T09:00:00"
    first, second = t["events"]
    assert first["outcome"] == "CONTACTED"
    nodes = [s["node"] for s in first["steps"]]
    assert "monitor" in nodes and "recover" in nodes and nodes[0] == "validate_event" and nodes[-1] == "close_event"
    monitor = next(s for s in first["steps"] if s["node"] == "monitor")
    assert monitor["data"]["provider_state"] == "SENT" and "never call the agent again" in monitor["text"]
    assert second["outcome"] == "BLOCKED" and "already contacted today" in second["steps"][2]["text"]
    assert [x["status"] for x in t["contacts"]] == ["SENT"] and t["checkpoints"] > 10


def test_every_step_in_a_trace_carries_its_reason(api):
    c, _ = api
    c.post("/events?process=true", json=ev("e1", "B4"))
    steps = c.get("/events/e1").json()["steps"]
    assert all(s["text"] for s in steps)
    route = next(s for s in steps if s["node"] == "route")
    assert route["data"]["agent"] == "voice" and "negotiation" in route["data"]["reason"]


def test_a_malformed_event_over_http_is_rejected_and_traced_not_dropped(api):
    c, _ = api
    r = c.post("/events?process=true", json={"type": "DUE_SOON", "account_id": "NOPE", "time": "2026-11-20T09:00:00"})
    assert r.status_code == 200 and r.json()["outcome"] == "REJECTED"
    steps = c.get(f"/events/{r.json()['event_id']}").json()["steps"]
    assert [s["node"] for s in steps] == ["validate_event", "close_event"]
    r2 = c.post("/events?process=true", json={}).json()                           # an entirely empty event
    assert r2["published"] and r2["outcome"] == "REJECTED"


def test_stats_report_routing_latency(api):
    c, _ = api
    c.post("/events?process=true", json=ev())
    s = c.get("/stats").json()
    assert s["contacts_sent"] == 1 and s["locks_held"] == 0 and 0 < s["route_max_ms"] < 100


def test_any_account_a_judge_picks_has_a_complete_trace_after_a_full_day():
    rows = synthetic_borrowers(20_000, seed=7)
    day = generate_day(rows, n_primary=250, seed=21)
    inj = FaultInjector(build_fault_script(day, rows, HIDDEN_KINDS))
    sup = Supervisor(injector=inj)
    sup.seed_borrowers(rows)
    load_day(sup, day)
    sup.run_until_empty()
    assert check_day(sup, inj)["passed"]
    client = TestClient(create_app(sup))
    touched = sorted({e["account_id"] for e in day.events if e.get("account_id") in {r[0] for r in rows}})
    for acc in touched:                                                           # every touched account, not a sample
        t = client.get(f"/accounts/{acc}/trace").json()
        assert t["complete"] is True, acc
        assert all(e["steps"] and e["steps"][-1]["node"] == "close_event" for e in t["events"] if e["status"] == "DONE")
    # an account nobody touched is still traceable: it simply has no events
    idle = next(r[0] for r in rows if r[0] not in touched)
    assert client.get(f"/accounts/{idle}/trace").json()["events"] == []
    # the faulted accounts show their recovery in the trace
    for acc in inj.faulted_accounts():
        steps = [s["node"] for e in client.get(f"/accounts/{acc}/trace").json()["events"] for s in e["steps"]]
        assert "monitor" in steps and "recover" in steps
