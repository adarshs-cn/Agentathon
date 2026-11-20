"""RunManager: runs ONE demo event on demand and announces every node as it happens.

The animation on the Overview follows the real execution: the supervisor's own nodes call our listener (start, then
end), so a station lights up because that node is really running, and the sentence under it is built from what the
node really decided. Pacing (a short sleep before each node) only exists so a human can watch; tests use pace_ms=0.

Each finished node is also stored in `run_step`, so hover facts, Replay and the event log read exact history.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime

from orchestrator.ui import reasons


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class RunManager:
    def __init__(self, state):
        self.state = state
        self._lock = threading.Lock()
        self.active: dict | None = None
        self._subs: list[queue.Queue] = []
        self._run_no = 0

    # ---------------------------------------------------------------- stream
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=20000)
        self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def _emit(self, name: str, payload: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((name, payload))
            except queue.Full:
                pass

    # ---------------------------------------------------------------- start
    def start(self, event_id: str, pace_ms: int = 650, wait: bool = False) -> dict:
        st = self.state
        row = st.reader.one("SELECT * FROM demo_event WHERE event_id=?", (event_id,))
        if row is None:
            raise RunError(404, f"{event_id} is not one of the demo events")
        q = st.reader.one("SELECT status FROM event_queue WHERE event_id=?", (event_id,))
        if q and q["status"] != "PENDING":
            return {"replay": True, "event_id": event_id}            # already ran: nothing executes again
        if row["depends_on"]:
            dep = st.reader.one("SELECT e.status FROM demo_event d JOIN event_queue e ON e.event_id=d.event_id WHERE d.seq=?",
                                (row["depends_on"],))
            if not dep or dep["status"] != "DONE":
                raise RunError(409, f"Run event {row['depends_on']} first: this one is its second request.")
        with self._lock:
            if self.active:
                raise RunError(409, "Another event is running. Wait for it to finish.")
            self._run_no += 1
            run = {"run_id": f"run-{self._run_no}", "event_id": event_id, "customer_id": row["customer_id"],
                   "pace_ms": max(0, int(pace_ms))}
            self.active = run
        th = threading.Thread(target=self._run, args=(run,), daemon=True, name=run["run_id"])
        th.start()
        if wait:
            th.join()
        return {"replay": False, **run}

    # ---------------------------------------------------------------- the run itself
    def _run(self, run: dict) -> None:
        st, sup = self.state, self.state.sup
        db, ctx = sup.ctx.db, sup.ctx
        eid, b = run["event_id"], run["customer_id"]
        ev = ctx.bus.get(eid)
        owner = {"now": None, "seq": 0}
        try:
            f = ctx.engine.facts(b, datetime.fromisoformat(ev["event_time"]))
            owner["now"] = ctx.engine.current_owner(f)[0]
        except Exception:  # noqa: BLE001
            pass
        db.execute("DELETE FROM run_step WHERE event_id=?", (eid,))
        self._emit("run_start", run)

        def listener(phase: str, node: str, info: dict) -> None:
            if ((info.get("state") or {}).get("event") or {}).get("id") != eid:
                return
            if phase == "start":
                owner["seq"] += 1
                nar = self.state.narrator
                self._emit("step", {"run_id": run["run_id"], "seq": owner["seq"], "node": node,
                                    "station": reasons.station_of(node) if node != "close_event" else "done",
                                    "phase": "start", "owner_before": owner["now"],
                                    "llm": bool(nar and nar.uses_llm(node))})
                if run["pace_ms"]:
                    time.sleep(run["pace_ms"] / 1000)
                return
            merged = {**(info.get("state") or {}), **(info.get("update") or {})}
            did, label = reasons.sentence(node, db, merged, info.get("ms"))
            before = owner["now"]
            d = merged.get("decision") or {}
            out = merged.get("outcome") or {}
            if node == "assign" and out.get("status") != "BLOCKED" and d.get("role"):
                owner["now"] = d["role"]
            elif node == "commit" and (merged.get("result") or {}).get("status") != "DONE":
                owner["now"] = before
            ids = out.get("rule_ids") or (merged.get("guard") or {}).get("rule_ids") or d.get("rule_ids") or []
            station = reasons.station_of(node, out)
            trace = None
            nar = self.state.narrator
            if nar is not None:                       # stream the trace pad while the node is still shown as working
                seq = owner["seq"]

                def emit(kind: str, text: str, _seq=seq, _node=node) -> None:
                    self._emit("trace", {"run_id": run["run_id"], "seq": _seq, "node": _node, "kind": kind, "text": text})
                try:
                    # pacing: words appear at a reading speed tied to the chosen pace; after the trace, a pause to read it
                    word = run["pace_ms"] / 1000 * 0.08 if run["pace_ms"] else 0
                    trace = nar.narrate(node, db, merged, emit, info.get("ms"), word_delay_s=word)
                    if run["pace_ms"]:
                        time.sleep(run["pace_ms"] / 1000 * 0.9)
                except Exception as e:  # noqa: BLE001 - narration must never break a run
                    trace = {"source": "error", "think": "", "text": repr(e)}
            rec = {"run_id": run["run_id"], "seq": owner["seq"], "node": node, "station": station, "phase": "end",
                   "did": did, "label": label, "owner_before": before, "owner_after": owner["now"],
                   "ms": round(info.get("ms") or 0, 2), "rule_ids": ids,
                   "stop": bool(out) and node != "close_event", "trace": trace}
            db.execute("INSERT OR REPLACE INTO run_step(event_id, seq, node, station, ms, owner_before, owner_after, did, "
                       "label, rule_ids, data, trace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (eid, owner["seq"], node, station, rec["ms"], before, owner["now"], did, label, json.dumps(ids),
                        json.dumps({"outcome": out or None, "fault": merged.get("fault"), "recovery": merged.get("recovery")},
                                   default=str), json.dumps(trace) if trace else None))
            self._emit("step", rec)

        ctx.node_listeners.append(listener)
        try:
            res = sup.process_event(eid)
            status = ((res or {}).get("outcome") or {}).get("status", "FAILED")
            self._emit("run_end", self._end_payload(run, status, owner["now"]))
        except Exception as e:  # noqa: BLE001
            self._emit("run_end", {**self._end_payload(run, "FAILED", owner["now"]), "error": repr(e)})
        finally:
            if listener in ctx.node_listeners:
                ctx.node_listeners.remove(listener)
            with self._lock:
                self.active = None

    def _end_payload(self, run: dict, status: str, owner_after) -> dict:
        steps = self.steps(run["event_id"])
        last = steps[-1]["did"] if steps else ""
        return {"run_id": run["run_id"], "event_id": run["event_id"], "outcome": status,
                "outcome_label": reasons.OUTCOME_WORDS.get(status, status), "summary": last,
                "owner_after": owner_after, "message": self.message(run["event_id"], run["customer_id"])}

    # ---------------------------------------------------------------- reading back
    def message(self, event_id: str, customer_id: str):
        r = self.state.reader.one("SELECT message_json, status FROM contact_log WHERE idem_key=?", (f"{customer_id}|{event_id}",))
        return json.loads(r["message_json"]) if r and r["message_json"] else None

    def steps(self, event_id: str) -> list[dict]:
        out = []
        for r in self.state.reader.query("SELECT * FROM run_step WHERE event_id=? ORDER BY seq", (event_id,)):
            d = dict(r)
            d["rule_ids"] = json.loads(d["rule_ids"] or "[]")
            d["data"] = json.loads(d["data"]) if d["data"] else None
            d["trace"] = json.loads(d["trace"]) if d.get("trace") else None
            out.append(d)
        return out
