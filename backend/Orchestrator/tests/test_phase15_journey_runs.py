"""Phase 15: real runs are saved (fault + recovery included), survive a restart and a walkthrough reset, and drive the
notification bell: unseen count, one notice per recovered fault, cleared when the manager opens it."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.state import DemoState

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


def _run_real(state, n=2):
    """Run n real (non-walkthrough) events straight through the supervisor."""
    return [state.sup.process_next() for _ in range(n)]


@real
def test_real_runs_are_saved_with_fault_and_recovery_and_notify_until_seen(tmp_path):
    st = DemoState(tmp_path, REAL, events=60, seed=5, faults="public", mode="day")
    st.sup.run_until_empty()
    c = TestClient(create_dashboard_app(st))
    runs = c.get("/api/journeys?page_size=200").json()
    assert runs["total"] >= 40 and all("source" not in r for r in runs["items"])
    faulty = [r for r in runs["items"] if r["had_fault"]]
    assert faulty, "the public fault script should have produced at least one fault"
    f = faulty[0]
    assert f["fault"] and f["recovery_action"] and f["notify_seen"] is False
    n = c.get("/api/notifications").json()
    assert n["unseen"] == len(faulty) and n["items"][0]["message"]
    assert c.get("/api/journeys?faults_only=1").json()["total"] == len(faulty)
    pinned = c.get(f"/api/journeys?page_size=5&sort_by=duration_ms&sort_dir=asc&pin={f['event_id']}").json()["items"]
    assert pinned[0]["event_id"] == f["event_id"]                       # the run the manager is sent to is always shown
    one = c.post("/api/notifications/seen", json={"event_ids": [f["event_id"]]}).json()
    assert one["unseen"] == len(faulty) - 1
    assert c.post("/api/notifications/seen", json={}).json()["unseen"] == 0


@real
def test_saved_runs_and_unseen_notices_survive_a_restart(tmp_path):
    a = DemoState(tmp_path, REAL, mode="scenario")
    a.sup.ctx.db.execute("INSERT INTO journey_run(event_id, borrower_id, outcome, fault, fault_agent, recovery_action, notify_seen, "
                         "finished_wall) VALUES ('real-1','BRW00001','CONTACTED','CRASH','whatsapp_agent','RESUME',0,1.0)")
    a.sup.close()
    b = DemoState(tmp_path, REAL, mode="scenario")                       # new process, same folder
    c = TestClient(create_dashboard_app(b))
    assert c.get("/api/journeys").json()["total"] == 1
    n = c.get("/api/notifications").json()
    assert n["unseen"] == 1 and "retried" in n["items"][0]["message"]
    assert c.post("/api/notifications/seen", json={}).json()["unseen"] == 0


@real
def test_walkthrough_reset_keeps_real_runs(tmp_path):
    st = DemoState(tmp_path, REAL, mode="scenario")
    st.sup.ctx.db.execute("INSERT INTO journey_run(event_id, borrower_id, outcome, fault, notify_seen, finished_wall) "
                          "VALUES ('real-1','BRW00001','CONTACTED','CRASH',0,1.0)")
    st.runs.start("demo-01", pace_ms=0, wait=True)
    c = TestClient(create_dashboard_app(st))
    assert c.post("/api/scenario/reset").json()["done"] == 0
    assert c.get("/api/journeys").json()["total"] == 1 and c.get("/api/notifications").json()["unseen"] == 1
