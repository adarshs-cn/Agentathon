"""Phase 16: the continuous monitor over a pool of 15 real borrowers, inside the contact window; the walkthrough runs
on its own database and never touches the real numbers."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.state import DemoState

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


def _at(h, m=0, extra_min=0):
    return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=extra_min)


def live(tmp, faults="none"):
    st = DemoState(tmp, REAL, mode="live", faults=faults, autostart=False)
    if not st.sup.ctx.db.one("SELECT COUNT(*) n FROM event_queue")["n"]:        # a fresh pool: everyone is due now
        st.sup.ctx.db.execute("UPDATE monitor_pool SET next_due=0")
    return st


@real
def test_pool_is_fifteen_distinct_borrowers_and_is_kept_across_a_restart(tmp_path):
    a = live(tmp_path)
    pool = [r["customer_id"] for r in a.sup.ctx.db.query("SELECT customer_id FROM monitor_pool ORDER BY rowid")]
    assert len(pool) == 15 and len(set(pool)) == 15
    a.sup.close()
    b = live(tmp_path)
    assert [r["customer_id"] for r in b.sup.ctx.db.query("SELECT customer_id FROM monitor_pool ORDER BY rowid")] == pool


@real
def test_inside_the_window_it_appends_and_runs_events_and_the_tiles_move(tmp_path):
    st = live(tmp_path)
    c = TestClient(create_dashboard_app(st))
    assert c.get("/api/overview").json()["counters"]["events_total"] == 0
    r = st.monitor.tick(_at(10, 0))                                   # everyone is due by 10:30
    assert r["added"] == 15 and r["processed"] == 15 and r["state"] == "monitoring"
    ov = c.get("/api/overview").json()
    assert ov["counters"]["events_done"] == 15 and ov["monitor"]["pool_size"] == 15 and ov["monitor"]["pool_handled"] >= 1
    assert c.get("/api/journeys").json()["total"] == 15
    assert c.get("/api/overview/drilldown/borrowers").json()["rows"]
    assert st.monitor.tick(_at(10, 0))["added"] == 0                  # nothing is due again straight away


@real
def test_outside_the_window_nothing_is_appended_or_run_and_it_says_when_it_resumes(tmp_path):
    st = live(tmp_path)
    r = st.monitor.tick(_at(22, 0))
    assert r == {"added": 0, "processed": 0, "state": "outside_window"}
    s = st.monitor.status(_at(22, 0))
    assert s["state"] == "outside_window" and s["opens_at"].endswith("08:00") and "08:00" in s["label"]
    assert st.monitor.status(_at(7, 59))["opens_at"].endswith("08:00")
    assert st.monitor.status(_at(10, 0))["state"] == "monitoring"
    assert st.monitor.tick(_at(10, 0))["processed"] == 15             # when the window opens it catches up


@real
def test_pause_and_resume(tmp_path):
    st = live(tmp_path)
    c = TestClient(create_dashboard_app(st))
    assert c.post("/api/monitor/pause").json()["state"] == "paused"
    assert st.monitor.tick(_at(10, 0))["processed"] == 0
    assert c.post("/api/monitor/resume").json()["state"] == "monitoring"
    assert st.monitor.tick(_at(10, 0))["processed"] == 15


@real
def test_a_restart_keeps_the_runs_and_never_repeats_an_event(tmp_path):
    a = live(tmp_path)
    a.monitor.tick(_at(10, 0))
    a.sup.close()
    b = live(tmp_path)
    c = TestClient(create_dashboard_app(b))
    assert c.get("/api/journeys").json()["total"] == 15
    assert b.monitor.tick(_at(10, 0))["added"] == 0                   # next-due times were saved


@real
def test_walkthrough_runs_never_change_the_real_numbers(tmp_path):
    st, demo = live(tmp_path / "live"), DemoState(tmp_path / "demo", REAL, mode="scenario")
    c = TestClient(create_dashboard_app(st, demo))
    before = c.get("/api/overview").json()["counters"]
    import time
    for n in (1, 8, 13):
        assert c.post(f"/api/scenario/demo-{n:02d}/run?pace_ms=0").status_code == 200
        for _ in range(200):
            if not demo.runs.active:
                break
            time.sleep(0.05)
    assert c.get("/api/scenario").json()["done"] == 3                    # the walkthrough did run
    after = c.get("/api/overview").json()["counters"]
    for k in ("events_total", "events_done", "contacts_made", "borrowers_handled", "blocked_or_deferred", "faults_injected"):
        assert after[k] == before[k] == 0, k
    assert c.get("/api/journeys").json()["total"] == 0 and c.get("/api/notifications").json()["unseen"] == 0
    assert all(not r["event_id"].startswith("demo-") for r in c.get("/api/overview/drilldown/borrowers").json()["rows"])
    assert c.post("/api/scenario/reset").json()["done"] == 0              # resetting the demo leaves the real side alone
    st.monitor.tick(_at(10, 0))
    c.post("/api/scenario/reset")
    assert c.get("/api/journeys").json()["total"] == 15


@real
def test_scripted_faults_on_the_pool_are_recovered_and_raise_notices(tmp_path):
    st = live(tmp_path, faults="public")
    c = TestClient(create_dashboard_app(st))
    st.monitor.tick(_at(10, 0))
    n = c.get("/api/notifications").json()
    assert n["unseen"] == 2 and all(i["fault"] and i["recovery_action"] for i in n["items"])
    ov = c.get("/api/overview").json()["counters"]
    assert ov["faults_injected"] >= 2 and ov["faults_recovered"] == ov["faults_injected"]
