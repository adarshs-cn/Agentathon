"""PHASE 13 integration test: the dashboard API the React frontend calls.

Every endpoint is checked against the exact fields the frontend reads (see frontend/src/api/client.js and
the pages), against a real simulated day on the real portfolio, with the database as the only source of data.
"""
import csv
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.supervisor import Supervisor
from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.events import ui_events_for
from orchestrator.ui.runner import DAY, SimulationRunner
from orchestrator.ui.state import DemoState
from orchestrator.ui import views
from tests.dataset_fixture import Mini

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"
UI_EVENT_TYPES = {"ROUTING_DECISION", "OWNER_ASSIGNED", "OWNER_RELEASED", "CONTACT_ATTEMPTED", "FAULT_DETECTED",
                  "RECOVERY_ACTION", "COMMITMENT_RECORDED", "REQUEST_REFUSED"}        # the eight the frontend draws
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


# ================================================================== translating the log into the eight event types
def run_mini(m: Mini, tmp_path, events, script=None):
    sup = Supervisor(injector=FaultInjector(script or {}))
    sup.load_dataset(m.write(tmp_path / "ds"))
    sup.publish_many(events)
    sup.run_until_empty()
    return sup


def ev(id, b, type="OVERDUE", time="2026-10-31T10:00:00"):
    """An event on customer b's first account (the fixture names it '<b>a')."""
    return {"id": id, "type": type, "account_id": f"{b}a", "time": time}


def feed(sup, eid):
    rows = [{**r, "data": r["data"]} for r in sup.ctx.decisions.for_event(eid)]
    return ui_events_for(rows)


def test_a_contact_becomes_a_readable_story_with_only_known_types(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    sup = run_mini(m, tmp_path, [ev("e1", "T1")])
    out = feed(sup, "e1")
    assert [e["type"] for e in out] == ["ROUTING_DECISION", "OWNER_ASSIGNED", "CONTACT_ATTEMPTED", "COMMITMENT_RECORDED", "OWNER_RELEASED"]
    assert {e["type"] for e in out} <= UI_EVENT_TYPES
    assert all(e["ts"].endswith("Z") and e["customer_id"] == "T1" and e["account_id"] == "T1a" and e["event_id"].startswith("d") for e in out)
    assert len({e["event_id"] for e in out}) == len(out)                                   # unique keys for React
    route = out[0]
    assert route["agent"] == "whatsapp" and "reminder" in route["decision"] and "whatsapp ok" in route["reason"]


def test_a_refusal_carries_its_rule_ids_and_the_outcome_word(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45, deceased=1); m.borrower("T2", dpd=20, borrower_requested_window="10:00-12:00")
    sup = run_mini(m, tmp_path, [ev("e1", "T1"), ev("e2", "T2", time="2026-10-31T09:00:00"), ev("e3", "NOPE")])
    a, b, c = feed(sup, "e1"), feed(sup, "e2"), feed(sup, "e3")
    assert [e["type"] for e in a] == ["REQUEST_REFUSED"] and a[0]["decision"] == "BLOCKED" and a[0]["rule_ids"] == ["R058"]
    assert b[0]["decision"] == "DEFERRED" and "R006" in b[0]["rule_ids"]
    assert c[0]["decision"] == "REJECTED" and c[0]["agent"] == "supervisor"


def test_a_fault_and_its_recovery_appear_in_order(tmp_path):
    m = Mini(); m.borrower("T1", dpd=20)
    sup = run_mini(m, tmp_path, [ev("e1", "T1")], {("T1", 1): "CRASH_AFTER_SEND"})
    types = [e["type"] for e in feed(sup, "e1")]
    assert types.index("CONTACT_ATTEMPTED") < types.index("FAULT_DETECTED") < types.index("RECOVERY_ACTION") < types.index("COMMITMENT_RECORDED")
    rec = next(e for e in feed(sup, "e1") if e["type"] == "RECOVERY_ACTION")
    assert rec["decision"] == "RESTART_SKIP_CURRENT" and rec["provider_state"] == "SENT"
    crash = next(e for e in feed(sup, "e1") if e["type"] == "CONTACT_ATTEMPTED")
    assert crash["decision"] == "crashed" and "died after sending" in crash["reason"]


def test_a_handoff_is_announced_as_an_owner_change(tmp_path):
    m = Mini(); m.borrower("T1", dpd=45); m.contact("T1", "2026-10-30 20:00:00", "reminder_agent", "sms")
    sup = run_mini(m, tmp_path, [ev("e1", "T1")])
    h = [e for e in feed(sup, "e1") if e["type"] == "OWNER_ASSIGNED" and "handoff" in e["decision"]]
    assert h and h[0]["decision"] == "handoff reminder → negotiation" and "R039" in h[0]["rule_ids"]


# ================================================================== the simulation clock
def test_the_clock_validates_speed_and_never_runs_backwards():
    r = SimulationRunner(lambda: None, "2026-10-31", 6 * 3600)
    assert r.clock()["status"] == "paused" and r.clock()["sim_time"] == "2026-10-31T06:00:00Z"
    r.control("speed", {"speed": 300})
    assert r.clock()["speed"] == 300
    with pytest.raises(ValueError):
        r.control("speed", {"speed": 7})
    with pytest.raises(ValueError):
        r.control("explode")
    assert r.control("jump", {"seconds": 9 * 3600})["sim_time"] == "2026-10-31T09:00:00Z"
    assert r.control("jump", {"seconds": 7 * 3600})["sim_time"] == "2026-10-31T09:00:00Z"        # forward only
    assert r.control("jump", {"seconds": DAY + 999})["finished"] is True
    assert r.control("play")["status"] == "paused"                                               # a finished day cannot play


# ================================================================== the whole API, on the real portfolio and a real day
@pytest.fixture(scope="module")
def api(tmp_path_factory):
    state = DemoState(tmp_path_factory.mktemp("ui"), REAL, events=160, seed=5, faults="hidden", mode="day")
    state.sup.run_until_empty()                 # run the whole day now, deterministically (the runner stays paused)
    time.sleep(2.2)                              # let the background audit see the final contacts
    state.runner.control("jump", {"seconds": DAY - 1})
    return TestClient(create_dashboard_app(state)), state


@real
def test_overview_has_every_field_the_overview_page_reads(api):
    c, _ = api
    d = c.get("/api/overview").json()
    for k in ("conflicting_contacts", "faults_injected", "faults_recovered", "borrowers_handled", "contacts_made",
              "blocked_or_deferred", "events_done", "events_total", "trace_gaps", "faults_scheduled"):
        assert k in d["counters"], k
    assert {"median", "p95", "target_ms"} <= set(d["latency_ms"]) and d["latency_ms"]["target_ms"] == 100
    sc = d["sim_clock"]
    assert {"status", "sim_time", "speed", "position_seconds", "day_length_seconds", "finished"} <= set(sc) and sc["day_length_seconds"] == 86400
    assert d["recent_decisions"] and all({"event_id", "ts", "account_id", "agent", "type", "decision"} <= set(e) for e in d["recent_decisions"])
    assert {e["type"] for e in d["recent_decisions"]} <= UI_EVENT_TYPES
    assert all(e["ts"].endswith("Z") for e in d["recent_decisions"])
    assert d["timeline"] and d["rules_cited"] and d["channel_mix"] and "outcomes" in d


@real
def test_the_headline_numbers_agree_with_the_database(api):
    c, st = api
    d = c.get("/api/overview").json()["counters"]
    db = st.sup.ctx.db
    assert d["contacts_made"] == db.one("SELECT COUNT(*) n FROM contact_log WHERE status='SENT'")["n"] > 20
    assert d["events_done"] == db.one("SELECT COUNT(*) n FROM event_queue WHERE status IN ('DONE','FAILED')")["n"]
    assert d["conflicting_contacts"] == 0 and d["trace_gaps"] == 0
    assert d["faults_injected"] == d["faults_recovered"] == 5 and d["faults_scheduled"] == 5


@real
def test_accounts_grid_filters_sorts_and_pages_over_all_20000(api):
    c, _ = api
    r = c.get("/api/accounts", params={"page": 1, "page_size": 25, "sort_by": "dpd", "sort_dir": "desc"}).json()
    assert r["total"] == 20000 and len(r["items"]) == 25
    row = r["items"][0]
    columns = ["account_id", "customer_id", "borrower_name", "product", "loan_amount", "total_outstanding", "principal_outstanding",
               "total_overdue", "installment_amount", "installment_overdue", "dpd", "delinquency_bucket", "account_status",
               "restructure_flag", "settlement_flag", "legal_flag", "case_owner_user_id", "last_disposition_date", "contact_no", "city"]
    assert set(columns) <= set(row)                                              # every column the grid defines
    assert isinstance(row["legal_flag"], bool) and r["items"][0]["dpd"] >= r["items"][-1]["dpd"] == r["items"][-1]["dpd"]
    legal = c.get("/api/accounts", params={"account_status": "legal", "page_size": 5}).json()
    assert legal["total"] == 896 and all(i["account_status"] == "legal" and i["legal_flag"] for i in legal["items"])
    band = c.get("/api/accounts", params={"bucket": "31-60", "dpd_min": 50, "dpd_max": 55, "page_size": 100}).json()
    assert band["total"] > 0 and all(31 <= i["dpd"] <= 60 and 50 <= i["dpd"] <= 55 for i in band["items"])
    p2 = c.get("/api/accounts", params={"page": 2, "page_size": 25, "sort_by": "dpd", "sort_dir": "desc"}).json()
    assert {i["account_id"] for i in p2["items"]}.isdisjoint({i["account_id"] for i in r["items"]})
    opts = c.get("/api/accounts/filter-options").json()
    assert set(opts["buckets"]) == {"0", "1-30", "31-60", "61-90", "90+"} and "Personal Loan" in opts["products"] and len(opts["cities"]) == 12
    assert c.get("/api/accounts", params={"page_size": 5000}).json()["page_size"] == 200                   # paging is capped


@real
def test_search_finds_by_account_or_customer_number(api):
    c, _ = api
    a = c.get("/api/accounts/search", params={"q": "ACC0000"}).json()["items"]
    assert a and all(x["account_id"].startswith("ACC0000") for x in a)
    assert c.get("/api/accounts/search", params={"q": "A"}).json()["items"] == []                        # too short to search
    b = c.get("/api/accounts/search", params={"q": a[0]["customer_id"]}).json()["items"]
    assert any(x["customer_id"] == a[0]["customer_id"] for x in b)


@real
def test_a_borrower_opens_by_account_or_customer_number_with_state_and_trace(api):
    c, st = api
    row = st.reader.one("SELECT a.account_id, a.customer_id FROM event_queue q JOIN account a ON a.account_id=q.account_id "
                        "WHERE q.outcome='CONTACTED' LIMIT 1")
    for any_id in (row["account_id"], row["customer_id"]):
        s = c.get(f"/api/borrowers/{any_id}/state").json()
        assert s["customer_id"] == row["customer_id"] and s["accounts"]
        for k in ("facts", "state", "ownership", "caps", "holds", "probe", "recent_contacts", "consent"):
            assert k in s, k
        assert {"today", "week", "by_channel"} <= set(s["caps"]) and "guard" in s["probe"]
        t = c.get(f"/api/borrowers/{any_id}/trace").json()
        assert t["customer_id"] == row["customer_id"] and t["complete"] is True and t["events"]
        e = t["events"][0]
        assert {"event_id", "type", "time", "outcome", "steps", "feed"} <= set(e) and e["time"].endswith("Z")
        assert e["steps"][0]["node"] == "validate_event" and e["steps"][-1]["node"] == "close_event"
        assert {x["type"] for x in e["feed"]} <= UI_EVENT_TYPES
    assert c.get("/api/borrowers/NOPE/state").status_code == 404 and c.get("/api/borrowers/NOPE/trace").status_code == 404


@real
def test_faults_page_lists_every_incident_with_what_the_provider_said(api):
    c, _ = api
    d = c.get("/api/faults").json()
    assert d["summary"]["injected"] == d["summary"]["recovered"] == 5 and d["summary"]["scheduled"] == 5
    inc = d["incidents"]
    assert {"fault_type", "agent", "action", "provider_state", "outcome", "account_id", "ts"} <= set(inc[0])
    assert {"CRASH", "MALFORMED", "NO_PROGRESS", "TIMEOUT"} <= {i["fault_type"] for i in inc}
    skip = [i for i in inc if i["action"] == "RESTART_SKIP_CURRENT"]
    assert skip and all(i["provider_state"] == "SENT" and i["recovered"] for i in skip)
    assert d["summary"]["resends_prevented"] == len(skip) and len(d["script"]) >= 5 and all(s["fired"] for s in d["script"])


@real
def test_agents_ownership_budgets_decisions_and_rules(api):
    c, _ = api
    a = c.get("/api/agents").json()
    assert {x["name"] for x in a["channel_agents"]} == {"whatsapp", "email", "voice"}
    assert all(x["status"] in ("healthy", "degraded", "fault") and x["calls"] >= x["contacts_sent"] for x in a["channel_agents"])
    assert {r["name"] for r in a["role_agents"]} == {"reminder", "negotiation", "servicing", "legal"}
    o = c.get("/api/ownership").json()
    assert {"active_leases", "handoffs", "simultaneous", "locks_held"} <= set(o["summary"]) and o["summary"]["locks_held"] == 0
    assert all(h["rule_ids"] == ["R039", "A12"] for h in o["handoffs"])
    b = c.get("/api/budgets").json()
    assert len(b["resources"]) == 21 and b["as_of"] == "2026-10-31"               # the day stays 'today' after midnight
    assert b["totals"]["by_supervisor"] > 0 and any(r["by_supervisor"] > 0 for r in b["resources"])
    assert all(r["used_today"] == r["from_history"] + r["by_supervisor"] for r in b["resources"])
    d = c.get("/api/decisions", params={"page_size": 10}).json()
    assert d["total"] > 100 and len(d["items"]) == 10 and {"event_id", "ts", "account_id", "type", "outcome", "rule_ids", "reason"} <= set(d["items"][0])
    blocked = c.get("/api/decisions", params={"outcome": "BLOCKED", "page_size": 200}).json()
    assert blocked["total"] > 0 and all(i["outcome"] == "BLOCKED" and i["rule_ids"] for i in blocked["items"])
    rid = blocked["items"][0]["rule_ids"][0]
    by_rule = c.get("/api/decisions", params={"rule_id": rid, "page_size": 200}).json()
    assert by_rule["total"] > 0 and all(rid in i["rule_ids"] for i in by_rule["items"])
    rules = {r["rule_id"]: r for r in c.get("/api/rules").json()["items"]}
    assert len(rules) == 95 and rules["R009"]["description"] and "D12-matrix" in rules and "A12" in rules      # 93 + 2 explainers


@real
def test_the_stream_emits_the_same_events_as_the_overview_feed(api):
    _, st = api
    events, last = st.new_events(0, limit=1000)
    assert events and last == st.max_done_seq() and {e["type"] for e in events} <= UI_EVENT_TYPES
    again, same = st.new_events(last)
    assert again == [] and same == last
    snap = st.overview(light=True)
    assert "recent_decisions" not in snap and snap["counters"]["contacts_made"] > 0


@real
def test_no_personal_data_ever_leaves_the_api(api):
    c, st = api
    names = []
    with open(REAL / "d2_borrower_master.csv", newline="", encoding="utf-8-sig") as f:
        for i, r in enumerate(csv.DictReader(f)):
            names.append((r["name"], r["phone_1"], r["email"]))
            if i == 400:
                break
    bodies = [c.get("/api/accounts", params={"page_size": 200}).text, c.get("/api/overview").text, c.get("/api/decisions", params={"page_size": 200}).text]
    some = st.reader.one("SELECT account_id FROM account LIMIT 1")["account_id"]
    bodies += [c.get(f"/api/borrowers/{some}/state").text, c.get(f"/api/borrowers/{some}/trace").text]
    blob = " ".join(bodies)
    leaks = [x for n, p, e in names for x in (n, p, e) if x and x in blob]
    assert leaks == []
    sample = json.loads(bodies[0])["items"][0]
    assert "***" in sample["borrower_name"] and sample["contact_no"].startswith("XXXXXX")                 # masked forms only


@real
def test_reset_rebuilds_the_day_and_the_clock_controls_work(api):
    c, st = api
    assert c.post("/api/simulation/speed", json={"speed": 5}).status_code == 400
    assert c.post("/api/simulation/speed", json={"speed": 300}).json()["speed"] == 300
    assert c.post("/api/simulation/pause").json()["status"] == "paused"
    clock = c.post("/api/simulation/reset").json()
    assert clock["status"] == "paused" and clock["finished"] is False and clock["position_seconds"] == clock["start_seconds"]
    d = c.get("/api/overview").json()
    assert d["counters"]["events_done"] == 0 and d["counters"]["contacts_made"] == 0 and d["counters"]["events_total"] > 100
    assert d["recent_decisions"] == []


@real
def test_playing_the_clock_processes_events_through_the_real_supervisor(tmp_path):
    state = DemoState(tmp_path, REAL, events=80, seed=3, faults="none", mode="day")
    c = TestClient(create_dashboard_app(state))
    assert c.get("/api/overview").json()["counters"]["events_done"] == 0
    c.post("/api/simulation/speed", json={"speed": 900})
    c.post("/api/simulation/jump", json={"seconds": 12 * 3600})       # skip ahead so a few seconds of play covers the morning
    c.post("/api/simulation/play")
    deadline = time.time() + 20
    while time.time() < deadline and c.get("/api/overview").json()["counters"]["events_done"] < 40:
        time.sleep(0.4)
    d = c.get("/api/overview").json()
    assert d["counters"]["events_done"] >= 40 and d["sim_clock"]["status"] in ("playing", "paused")
    assert d["counters"]["contacts_made"] > 0 and d["recent_decisions"]
    state.runner.control("pause")
