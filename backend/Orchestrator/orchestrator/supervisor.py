"""Supervisor: the long-lived service that drives the graph from the event bus.

    bus.claim_next() -> graph.invoke({"event": ...}, thread_id=account_id) -> bus.mark_done()

Restart safety. Two things persist across a restart: the business tables (borrower_state,
contact_log, decision_log, event_queue) and LangGraph's checkpoints. An event that was
mid-run when the process died is still IN_PROGRESS on the bus, and its thread's checkpoint
says exactly which node comes next. `recover_on_start()` finishes each such event with
`graph.invoke(None, config)`, which resumes at that node; nodes are written to be safe to
repeat (owner lock is compare-and-set, contact log is keyed by '<account>|<date>', agents
dedupe on the idempotency key), so a repeated node cannot double-contact anyone.
"""
from __future__ import annotations

import json
import time

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.agents.stubs import default_agents
from orchestrator.config import NEEDS_REVIEW, RECURSION_LIMIT, Policy
from orchestrator.context import Context
from orchestrator.graph import FINAL_STAGE, build_graph


def thread_config(account_id: str | None) -> dict:
    """One LangGraph thread per account: that is what makes a per-account history."""
    return {"configurable": {"thread_id": account_id or "_invalid"}, "recursion_limit": RECURSION_LIMIT}


class Supervisor:
    def __init__(self, data_dir: str | Path | None = None, policy: Policy | None = None,
                 agents: list | None = None, injector: FaultInjector | None = None,
                 advisor=None, stage: int = FINAL_STAGE):
        if data_dir:
            d = Path(data_dir)
            d.mkdir(parents=True, exist_ok=True)
            db_path, cp_path = str(d / "orchestrator.db"), str(d / "checkpoints.db")
        else:
            db_path = cp_path = ":memory:"
        self.injector = injector
        if agents is None:
            agents = default_agents(injector)
        self.ctx = Context.create(db_path, policy, agents, advisor)
        self._cp_conn = sqlite3.connect(cp_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._cp_conn)
        self.graph = build_graph(self.ctx, self.checkpointer, stage)
        self._recovered = False
        self._run_lock = threading.RLock()     # one driver at a time (the API may call from many threads)

    def load_dataset(self, folder, as_of: str | None = None) -> dict:
        """Switch to dataset mode: load D1/D2/D4/D6/D7/D10/D12/D13 and let the D12 policy engine decide.

        Borrowers become the unit (event.account_id carries the borrower id)."""
        from orchestrator.dataset.loader import AS_OF, load_dataset
        from orchestrator.policy.d12 import D12Policy
        report = load_dataset(self.ctx.db, self.ctx.borrowers, folder, as_of or AS_OF)
        self.ctx.engine = D12Policy(self.ctx.db, self.ctx.contacts, self.ctx.borrowers, self.ctx.registry, self.ctx.policy)
        return report

    def narrate(self, verbose: bool = False, out=print):
        """Print every decision live as the supervisor makes it (reasoning, agent requests and responses)."""
        from orchestrator.tracing.narrate import Narrator
        n = Narrator(self.ctx, out, verbose)
        self.ctx.decisions.listeners.append(n)
        return n

    # ---------------------------------------------------------------- inputs
    def seed_borrowers(self, rows: list[tuple]) -> None:
        self.ctx.borrowers.seed(rows)

    def publish(self, event: dict) -> bool:
        return self.ctx.bus.publish(event)

    def publish_many(self, events: list[dict]) -> int:
        return self.ctx.bus.publish_many(events)

    # ---------------------------------------------------------------- driving the graph
    def _resume(self, ev: dict, cfg: dict) -> Optional[dict]:
        """If this very event already ran partway, continue it from its checkpoint."""
        snap = self.graph.get_state(cfg)
        vals = snap.values or {}
        if (vals.get("event") or {}).get("id") != ev["id"]:
            return None                                   # never started: run from the top
        if snap.next:
            return self.graph.invoke(None, cfg)           # resume at the next unfinished node
        if vals.get("outcome"):
            return vals                                   # finished; only the bus mark was missed
        return None

    def _fail_event(self, ev: dict, err: Exception, attempts: int) -> None:
        """Give up on a poison event without losing the borrower: release the lock, pause, log."""
        acc = ev.get("account_id")
        if acc and self.ctx.borrowers.exists(acc):
            self.ctx.borrowers.release(acc)
            self.ctx.borrowers.set_status(acc, NEEDS_REVIEW)
        self.ctx.decisions.add(ev.get("time", ""), ev["id"], acc or "", "supervisor",
                               f"event FAILED after {attempts} attempts: {err!r}; lock released, "
                               f"borrower set to {NEEDS_REVIEW}", {"error": repr(err)})
        self.ctx.bus.mark_failed(ev["id"], repr(err))

    def _execute(self, ev: dict) -> Optional[dict]:
        cfg = thread_config(ev.get("account_id"))
        while True:
            try:
                state = self._resume(ev, cfg)
                return state if state is not None else self.graph.invoke({"event": ev}, cfg)
            except Exception as e:  # noqa: BLE001 - a bug or transient failure inside a run
                n = self.ctx.bus.attempts(ev["id"])
                self.ctx.decisions.add(ev.get("time", ""), ev["id"], ev.get("account_id") or "",
                                       "supervisor", f"run failed on attempt {n}: {e!r}")
                if n >= self.ctx.policy.max_event_attempts:
                    self._fail_event(ev, e, n)
                    return None
                self.ctx.bus.bump(ev["id"])               # retry from the checkpoint

    MAX_DEFERRALS = 3

    def _after(self, ev: dict, outcome: dict) -> None:
        """A DEFERRED event is not lost: it is re-published for the moment it may proceed (the next contact
        window, the end of a minimum gap), and the new event says where it came from."""
        if outcome.get("status") != "DEFERRED" or not outcome.get("until"):
            return
        n = (ev.get("payload") or {}).get("deferrals", 0) + 1
        origin = (ev.get("payload") or {}).get("origin", ev["id"])
        if n > self.MAX_DEFERRALS:
            self.ctx.decisions.add(ev.get("time", ""), ev["id"], ev.get("account_id") or "", "supervisor",
                                   f"gave up re-scheduling after {self.MAX_DEFERRALS} deferrals")
            return
        nxt = {**ev, "id": f"{origin}~d{n}", "time": outcome["until"], "payload": {**(ev.get("payload") or {}), "deferrals": n, "origin": origin}}
        self.ctx.bus.publish(nxt)
        self.ctx.decisions.add(ev.get("time", ""), ev["id"], ev.get("account_id") or "", "supervisor",
                               f"re-scheduled as {nxt['id']} for {nxt['time']} ({', '.join(outcome.get('rule_ids') or [])})")

    def _record_run(self, ev: dict, state: Optional[dict], t0: float) -> None:
        """Save one row per finished REAL journey (the Journey Runs screen reads it; it survives restarts).
        Walkthrough (demo) events are never saved here. A fault and its recovery are read from the decision log."""
        try:
            db, now = self.ctx.db, time.time()
            if db.one("SELECT 1 FROM demo_event WHERE event_id=?", (ev["id"],)) is not None:
                return
            st = state or {}
            out, dec = st.get("outcome") or {"status": "FAILED"}, st.get("decision") or {}
            ids = out.get("rule_ids") or dec.get("rule_ids") or []
            logs = db.query("SELECT node, text, data FROM decision_log WHERE event_id=? ORDER BY id", (ev["id"],))
            summary = logs[-1]["text"] if logs else None
            fault = agent = action = reason = None
            for r in logs:
                d = json.loads(r["data"]) if r["data"] else {}
                if r["node"] == "validate_output" and (r["text"].startswith("FAULT") or r["text"].startswith("fault already")) and not fault:
                    fault = d.get("type") or r["text"].rsplit(":", 1)[-1].strip().split(" ")[-1]
                    agent = (st.get("decision") or {}).get("agent")
                elif r["node"] == "monitor":
                    action, reason = d.get("action"), d.get("reason") or r["text"]
            c = db.one("SELECT channel FROM contact_log WHERE event_id=? AND status IN ('SENT','ATTEMPTING') LIMIT 1", (ev["id"],))
            q = db.one("SELECT attempts FROM event_queue WHERE event_id=?", (ev["id"],))
            ok = out.get("status") not in ("BLOCKED", "FAILED")
            db.execute(
                "INSERT OR REPLACE INTO journey_run(event_id, borrower_id, event_type, event_time, outcome, channel, role, "
                "owner_after, rule_ids, summary, fault, fault_agent, recovery_action, recovery_reason, notify_seen, "
                "started_wall, finished_wall, duration_ms, attempts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ev["id"], ev.get("account_id"), ev.get("type"), ev.get("time"), out.get("status"),
                 c["channel"] if c else None, dec.get("role"), dec.get("role") if ok else None, json.dumps(ids), summary,
                 fault, agent, action, reason, 0 if fault else 1, t0, now, round((now - t0) * 1000, 1),
                 q["attempts"] if q else None))
        except Exception:  # noqa: BLE001  - a logging problem must never fail a journey
            pass

    def process_next(self, until: str | None = None) -> Optional[dict]:
        ev = self.ctx.bus.claim_next(until)
        if ev is None:
            return None
        t0 = time.time()
        state = self._execute(ev)
        self._record_run(ev, state, t0)
        if state is None:
            return {"event": ev, "outcome": {"status": "FAILED"}}
        self.ctx.bus.mark_done(ev["id"], state["outcome"]["status"])
        self._after(ev, state["outcome"])
        return {"event": ev, "outcome": state["outcome"]}

    def process_event(self, event_id: str) -> Optional[dict]:
        """Run one chosen event now (the dashboard's Run button). None if it cannot be claimed."""
        with self._run_lock:
            if not self._recovered:
                self.recover_on_start()
            ev = self.ctx.bus.claim(event_id)
            if ev is None:
                return None
            t0 = time.time()
            state = self._execute(ev)
            self._record_run(ev, state, t0)
            if state is None:
                return {"event": ev, "outcome": {"status": "FAILED"}, "state": None}
            self.ctx.bus.mark_done(ev["id"], state["outcome"]["status"])
            self._after(ev, state["outcome"])
            return {"event": ev, "outcome": state["outcome"], "state": state}

    def recover_on_start(self) -> dict:
        """Finish every event that was mid-run when the previous process died."""
        summary = {"resumed": 0, "finished": 0, "restarted": 0, "failed": 0}
        for ev in self.ctx.bus.in_progress():
            n = self.ctx.bus.bump(ev["id"])
            cfg = thread_config(ev.get("account_id"))
            snap = self.graph.get_state(cfg)
            vals = snap.values or {}
            same = (vals.get("event") or {}).get("id") == ev["id"]
            kind = ("resumed" if same and snap.next else "finished" if same and vals.get("outcome")
                    else "restarted")
            self.ctx.decisions.add(ev.get("time", ""), ev["id"], ev.get("account_id") or "", "supervisor",
                                   f"restart recovery: {kind} (attempt {n})")
            if n > self.ctx.policy.max_event_attempts:
                self._fail_event(ev, RuntimeError("too many restarts"), n)
                summary["failed"] += 1
                continue
            state = self._execute(ev)
            if state is None:
                summary["failed"] += 1
                continue
            self.ctx.bus.mark_done(ev["id"], state["outcome"]["status"])
            self._after(ev, state["outcome"])
            summary[kind] += 1
        self._recovered = True
        return summary

    def run_until(self, sim_time: str, max_events: int | None = None) -> int:
        """Process every event whose time has arrived by `sim_time` (events not yet due stay queued)."""
        with self._run_lock:
            if not self._recovered:
                self.recover_on_start()
            n = 0
            while max_events is None or n < max_events:
                if self.process_next(until=sim_time) is None:
                    break
                n += 1
            return n

    def run_until_empty(self, max_events: int | None = None) -> int:
        with self._run_lock:
            if not self._recovered:
                self.recover_on_start()
            n = 0
            while max_events is None or n < max_events:
                if self.process_next() is None:
                    break
                n += 1
            return n

    def close(self) -> None:
        self._cp_conn.close()
        self.ctx.db.close()
