"""PHASE 5 integration test: the supervisor service (bus -> graph -> bus), restart recovery,
poison events, and a whole simulated day scored by the acceptance checks."""
import time

import pytest

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.agents.stubs import default_agents
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS, synthetic_borrowers
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import generate_day, load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, PUBLIC_KINDS, build_fault_script
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.trace import trace_gaps
from tests.helpers import make_event


class Crash(BaseException):
    """Simulates the whole process dying (BaseException so nothing in the supervisor catches it)."""


def crash_once_at(node):
    fired = {"done": False}

    def hook(name, state):
        if name == node and not fired["done"]:
            fired["done"] = True
            raise Crash(name)
    return hook


def messages(agents):
    return sum(len(a.outbox) for a in agents)


def new_sup(**kw):
    sup = Supervisor(**kw)
    sup.seed_borrowers(SAMPLE_BORROWERS)
    return sup


# ------------------------------------------------------------------ driving the bus
def test_events_are_processed_in_time_order_and_marked_done():
    sup = new_sup()
    sup.publish_many([make_event("e2", account_id="B2", time="2026-11-20T10:00:00"),
                      make_event("e1", account_id="B1", time="2026-11-20T09:00:00")])
    assert sup.run_until_empty() == 2
    assert sup.ctx.bus.stats() == {"DONE": 2}
    assert sup.ctx.bus.get("e1")["outcome"] == "CONTACTED"
    order = [r["event_id"] for r in sup.ctx.decisions.db.query(
        "select event_id from decision_log where node='close_event' order by id")]
    assert order == ["e1", "e2"]


def test_duplicates_dropped_bad_events_rejected_and_traced():
    sup = new_sup()
    assert sup.publish(make_event("e1", account_id="B1")) is True
    assert sup.publish(make_event("e1", account_id="B1")) is False                 # duplicate delivery
    sup.publish({"type": "DUE_SOON", "time": "2026-11-20T09:00:00"})              # no id, no account
    sup.publish(make_event("e3", account_id="NOPE"))
    sup.run_until_empty()
    assert sup.ctx.bus.stats() == {"DONE": 3}
    assert sup.ctx.contacts.sent_total() == 1
    assert sup.ctx.bus.get("e3")["outcome"] == "REJECTED"
    assert trace_gaps(sup.ctx, "NOPE") == [] and trace_gaps(sup.ctx, "B1") == []


def test_simultaneous_events_for_one_borrower_contact_once():
    sup = new_sup()
    sup.publish_many([make_event("e1", account_id="B1", time="2026-11-20T09:00:00"),
                      make_event("e2", type="CONTACT_REQUESTED", account_id="B1", time="2026-11-20T09:00:00"),
                      make_event("e3", type="PAYMENT_RECEIVED", account_id="B1", time="2026-11-20T09:00:00")])
    sup.run_until_empty()
    assert sup.ctx.contacts.sent_total() == 1 and messages(sup.ctx.registry._agents.values()) == 1
    outcomes = sorted(sup.ctx.bus.get(e)["outcome"] for e in ("e1", "e2", "e3"))
    assert outcomes == ["BLOCKED", "BLOCKED", "CONTACTED"]


# ------------------------------------------------------------------ the supervisor dies and restarts
HAPPY_PATH = ["validate_event", "load_customer", "guardrails", "route", "assign", "whatsapp",
              "validate_output", "commit", "release", "close_event"]


@pytest.mark.parametrize("node", HAPPY_PATH)
def test_process_death_at_every_node_then_restart_gives_exactly_one_contact(tmp_path, node):
    agents = default_agents(FaultInjector({}))             # the providers outlive the supervisor
    sup = new_sup(data_dir=tmp_path, agents=agents)
    sup.publish(make_event("e1", account_id="B1"))
    sup.ctx.on_node_start = crash_once_at(node)
    with pytest.raises(Crash):
        sup.run_until_empty()
    sup.close()

    sup2 = Supervisor(data_dir=tmp_path, agents=agents)                    # a brand-new process
    assert [e["id"] for e in sup2.ctx.bus.in_progress()] == ["e1"]         # the event survived the crash
    sup2.run_until_empty()

    assert sup2.ctx.bus.stats() == {"DONE": 1} and sup2.ctx.bus.get("e1")["outcome"] == "CONTACTED"
    assert messages(agents) == 1 and sup2.ctx.contacts.get("B1|2026-11-20")["status"] == "SENT"
    b = sup2.ctx.borrowers.load("B1")
    assert b["owner"] is None and b["last_contact"] == "2026-11-20T09:00:00"
    assert trace_gaps(sup2.ctx, "B1") == []
    assert any(r["node"] == "supervisor" and "restart recovery" in r["text"]
               for r in sup2.ctx.decisions.for_event("e1"))


def test_restart_in_the_middle_of_a_fault_recovery(tmp_path):
    agents = default_agents(FaultInjector({("B1", 1): "CRASH_BEFORE_SEND"}))
    sup = new_sup(data_dir=tmp_path, agents=agents)
    sup.publish(make_event("e1", account_id="B1"))
    sup.ctx.on_node_start = crash_once_at("recover")
    with pytest.raises(Crash):
        sup.run_until_empty()
    sup.close()
    sup2 = Supervisor(data_dir=tmp_path, agents=agents)
    sup2.run_until_empty()
    assert sup2.ctx.bus.get("e1")["outcome"] == "CONTACTED" and messages(agents) == 1


def test_process_death_with_many_events_in_flight_loses_nothing(tmp_path):
    agents = default_agents(FaultInjector({}))
    sup = Supervisor(data_dir=tmp_path, agents=agents)
    sup.seed_borrowers([(f"X{i}", 5, False, ["whatsapp", "email"]) for i in range(50)])
    sup.publish_many([make_event(f"e{i}", account_id=f"X{i}", time=f"2026-11-20T09:{i:02d}:00") for i in range(50)])

    seen = {"n": 0}

    def die_on_the_20th_commit(name, state):
        if name == "commit":
            seen["n"] += 1
            if seen["n"] == 20:
                raise Crash()
    sup.ctx.on_node_start = die_on_the_20th_commit
    with pytest.raises(Crash):
        sup.run_until_empty()
    sup.close()
    sup2 = Supervisor(data_dir=tmp_path, agents=agents)
    sup2.run_until_empty()
    assert sup2.ctx.bus.stats() == {"DONE": 50}
    assert messages(agents) == 50 and sup2.ctx.contacts.sent_total() == 50     # every borrower once, none twice
    assert sup2.ctx.borrowers.owners_held() == []


def test_an_event_finished_in_the_graph_but_not_marked_done_is_not_rerun(tmp_path):
    agents = default_agents(FaultInjector({}))
    sup = new_sup(data_dir=tmp_path, agents=agents)
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    sup.ctx.db.execute("UPDATE event_queue SET status='IN_PROGRESS', outcome=NULL WHERE event_id='e1'")
    summary = sup.recover_on_start()
    assert summary["finished"] == 1 and messages(agents) == 1 and sup.ctx.bus.get("e1")["status"] == "DONE"


# ------------------------------------------------------------------ failures inside the supervisor itself
def test_a_transient_internal_error_is_retried_from_the_checkpoint():
    sup = new_sup()
    sup.publish(make_event("e1", account_id="B1"))
    state = {"raised": False}

    def flaky(name, s):
        if name == "commit" and not state["raised"]:
            state["raised"] = True
            raise RuntimeError("db hiccup")
    sup.ctx.on_node_start = flaky
    sup.run_until_empty()
    assert sup.ctx.bus.get("e1")["outcome"] == "CONTACTED" and sup.ctx.contacts.sent_total() == 1
    assert sup.ctx.bus.attempts("e1") == 2


def test_a_poison_event_is_failed_safely_without_blocking_the_rest():
    agents = default_agents(FaultInjector({}))
    sup = new_sup(agents=agents)
    sup.publish_many([make_event("bad", account_id="B1", time="2026-11-20T09:00:00"),
                      make_event("ok", account_id="B2", time="2026-11-20T09:01:00")])

    def poison(name, s):
        if name == "commit" and s["event"]["account_id"] == "B1":
            raise RuntimeError("always fails")
    sup.ctx.on_node_start = poison
    sup.run_until_empty()
    assert sup.ctx.bus.get("bad")["status"] == "FAILED" and sup.ctx.bus.get("ok")["outcome"] == "CONTACTED"
    assert sup.ctx.bus.attempts("bad") == 3                                     # max_event_attempts
    b = sup.ctx.borrowers.load("B1")
    assert b["owner"] is None and b["status"] == "NEEDS_REVIEW"                # lock freed, paused, not lost
    assert trace_gaps(sup.ctx, "B1") == []                                     # the failure is in the trace
    assert messages(agents) == 2                                               # B1's single message did go out once


# ------------------------------------------------------------------ a whole simulated day
@pytest.fixture(scope="module")
def borrowers():
    return synthetic_borrowers(20_000, seed=7)                                 # the real scale: 20,000 accounts


def run_day(borrowers, kinds, n_primary, seed):
    day = generate_day(borrowers, n_primary=n_primary, seed=seed)
    script = build_fault_script(day, borrowers, kinds)
    inj = FaultInjector(script)
    sup = Supervisor(injector=inj)
    sup.seed_borrowers(borrowers)
    load_day(sup, day)
    t0 = time.perf_counter()
    sup.run_until_empty()
    return sup, inj, day, check_day(sup, inj), time.perf_counter() - t0


def test_a_simulated_day_with_the_hidden_style_script_passes_every_check(borrowers):
    sup, inj, day, report, secs = run_day(borrowers, HIDDEN_KINDS, n_primary=600, seed=11)
    failed = {k: v for k, v in report["checks"].items() if not v["ok"]}
    assert report["passed"], failed
    assert len(inj.faulted_accounts()) == 5                                    # all 5 faults actually fired
    kinds_fired = {f for _, _, f in inj.fired}
    assert kinds_fired == set(HIDDEN_KINDS)
    assert report["route_max_ms"] < 100 and report["route_p99_ms"] < 100        # routing under 100 ms at 20k accounts
    stats = sup.ctx.bus.stats()
    assert stats["DONE"] == len({e["id"] for e in day.events})                   # every distinct event closed
    # the injected conflicts and bad input were all handled
    assert sup.ctx.contacts.sent_total() > 100
    rejected = sum(1 for e in day.bad_event_ids if sup.ctx.bus.get(e)["outcome"] == "REJECTED")
    assert rejected == len(day.bad_event_ids)
    print(f"\nday: {len(day.events)} events in {secs:.1f}s, route p99={report['route_p99_ms']}ms, "
          f"sent={sup.ctx.contacts.sent_total()}")


def test_the_public_script_of_two_faults_also_passes(borrowers):
    sup, inj, day, report, _ = run_day(borrowers, PUBLIC_KINDS, n_primary=300, seed=5)
    assert report["passed"], report["checks"]
    assert len(inj.faulted_accounts()) == 2


# ------------------------------------------------------------------ the checks must be able to FAIL
def finished_day():
    sup = new_sup(injector=FaultInjector({("B1", 1): "CRASH_AFTER_SEND"}))
    sup.publish_many([make_event("e1", account_id="B1"), make_event("e2", account_id="B2")])
    sup.run_until_empty()
    return sup


def test_checks_pass_on_a_clean_run():
    sup = finished_day()
    assert check_day(sup, sup.injector)["passed"]


def test_checks_catch_a_double_contact():
    sup = finished_day()
    sup.ctx.db.execute("INSERT INTO contact_log(idem_key, customer_id, date, channel, purpose, status) "
                       "VALUES ('B2|2026-11-20|dup','B2','2026-11-20','email','reminder','SENT')")
    r = check_day(sup, sup.injector)
    assert not r["passed"] and not r["checks"]["zero_conflicting_contacts"]["ok"]


def test_checks_catch_a_double_message_at_the_provider():
    sup = finished_day()
    sup.ctx.registry.get("email").outbox["B2|2026-11-20"] = "email-000001"     # a 2nd message for B2
    assert not check_day(sup)["checks"]["zero_conflicting_contacts"]["ok"]


def test_checks_catch_a_dangling_lock_and_an_unfinished_event():
    sup = finished_day()
    sup.ctx.borrowers.try_take_owner("B3", "voice")
    sup.publish(make_event("e9", account_id="B3"))
    r = check_day(sup)
    assert not r["checks"]["no_dangling_locks"]["ok"] and not r["checks"]["all_events_closed"]["ok"]


def test_checks_catch_a_trace_gap_and_an_unrecovered_fault():
    sup = finished_day()
    sup.ctx.db.execute("DELETE FROM decision_log WHERE event_id='e2' AND node='close_event'")
    sup.ctx.db.execute("DELETE FROM decision_log WHERE customer_id='B1' AND node='monitor'")
    r = check_day(sup, sup.injector)
    assert not r["checks"]["complete_traces"]["ok"] and not r["checks"]["all_faults_recovered"]["ok"]


# ------------------------------------------------------------------ the simulated clock releases events as time arrives
def test_run_until_only_releases_events_whose_time_has_arrived():
    sup = new_sup()
    sup.publish_many([make_event("e1", account_id="B1", time="2026-11-20T09:00:00"),
                      make_event("e2", account_id="B2", time="2026-11-20T11:00:00"),
                      make_event("e3", account_id="B3", time="2026-11-20T15:00:00")])
    assert sup.run_until("2026-11-20T08:00:00") == 0 and sup.ctx.bus.stats() == {"PENDING": 3}
    assert sup.run_until("2026-11-20T11:00:00") == 2                       # inclusive of the boundary
    assert sup.ctx.bus.stats() == {"DONE": 2, "PENDING": 1} and sup.ctx.bus.next_event_time() == "2026-11-20T15:00:00"
    assert sup.run_until("2026-11-20T23:59:00") == 1 and sup.ctx.bus.next_event_time() is None


def test_a_second_read_only_connection_sees_the_writers_data_and_cannot_write(tmp_path):
    import sqlite3
    from orchestrator.stores.db import Database
    w = Database(tmp_path / "x.db")
    w.execute("INSERT INTO customer_profile VALUES ('B1', 5, 0, '[]')")
    r = Database(tmp_path / "x.db", read_only=True)
    assert r.one("SELECT dpd FROM customer_profile WHERE customer_id='B1'")["dpd"] == 5
    with pytest.raises(sqlite3.OperationalError):
        r.execute("INSERT INTO customer_profile VALUES ('B2', 1, 0, '[]')")
