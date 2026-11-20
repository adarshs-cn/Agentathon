"""The dashboard API (what the React frontend calls). Port 8001 by default, every route under /api.

  GET  /api/overview                        headline numbers, clock, charts data, newest feed lines
  GET  /api/stream                          Server-Sent Events: `counters` (1/s) and `event` (as decisions happen)
  POST /api/simulation/{play|pause|speed|jump|reset}
  GET  /api/accounts                        the grid (server-side filter / sort / paging over all 20,000 accounts)
  GET  /api/accounts/filter-options | /api/accounts/search?q=
  GET  /api/borrowers/{id}/state            facts, caps, holds, consent, "what would happen now" probe
  GET  /api/borrowers/{id}/trace            every event for the borrower, step by step, with rule ids
  GET  /api/agents | /api/faults | /api/ownership | /api/budgets | /api/decisions | /api/rules

Everything is read from the same SQLite database the supervisor writes (through a read-only connection).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from orchestrator.ui import accounts as acct
from orchestrator.ui import journeys as jr
from orchestrator.ui.journeys import journey_runs
from orchestrator.ui import demo_views
from orchestrator.ui import views
from orchestrator.ui.run import RunError
from orchestrator.ui.state import DemoState


def create_dashboard_app(state: DemoState, demo: DemoState | None = None) -> FastAPI:
    """`state` is the real (monitored) side: tiles, accounts, journey runs, notifications. `demo` is the walkthrough's own
    separate database (the Overview graph). With no `demo`, one state serves both (older single-database setups)."""
    demo = demo or state
    app = FastAPI(title="MT-02 Journey Supervisor: dashboard API", version="1.0")
    origins = os.environ.get("MT02_CORS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    def now() -> datetime:
        return state.sim_now()

    # ------------------------------------------------------------ overview + live stream
    @app.get("/api/overview")
    def overview():
        return state.overview()

    @app.get("/api/monitor")
    def monitor_status():
        if state.monitor is None:
            raise HTTPException(404, "this server has no live monitor")
        return state.monitor.status()

    @app.post("/api/monitor/{action}")
    def monitor_control(action: str):
        if state.monitor is None:
            raise HTTPException(404, "this server has no live monitor")
        if action not in ("pause", "resume"):
            raise HTTPException(400, "action must be pause or resume")
        state.monitor.paused = action == "pause"
        return state.monitor.status()

    @app.get("/api/simulation")
    def simulation():
        return state.runner.clock()

    @app.post("/api/simulation/{action}")
    def simulation_control(action: str, body: dict = Body(default={})):
        try:
            if action == "reset":
                state.reset()
                return state.runner.clock()
            return state.runner.control(action, body)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/stream")
    async def stream(request: Request):
        async def gen():
            q = demo.runs.subscribe()
            try:
                last_seq = await run_in_threadpool(state.max_done_seq)
                last_counters = last_poll = 0.0
                last_fault_id = await run_in_threadpool(jr.max_fault_id, state.reader)
                yield "retry: 2000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    while True:                                           # run events: drained every 40 ms for smooth animation
                        try:
                            name, payload = q.get_nowait()
                        except Exception:  # noqa: BLE001 - queue.Empty
                            break
                        yield f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"
                    if time.time() - last_poll >= 0.3:
                        last_poll = time.time()
                        head = await run_in_threadpool(state.max_done_seq)
                        if head < last_seq:                               # the data was reset
                            last_seq = 0
                            yield "event: reset\ndata: {}\n\n"
                        events, last_seq = await run_in_threadpool(state.new_events, last_seq)
                        for e in events:
                            yield f"event: event\ndata: {json.dumps(e)}\n\n"
                        for n in await run_in_threadpool(jr.new_faults, state.reader, last_fault_id):
                            last_fault_id = max(last_fault_id, n["id"])
                            yield f"event: notify\ndata: {json.dumps(n, default=str)}\n\n"
                        if time.time() - last_counters >= 1.0:
                            last_counters = time.time()
                            snap = await run_in_threadpool(state.overview, True)
                            yield f"event: counters\ndata: {json.dumps(snap)}\n\n"
                    await asyncio.sleep(0.04)
            finally:
                demo.runs.unsubscribe(q)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ the scenario (Overview walkthrough)
    @app.get("/api/scenario")
    def scenario_list():
        act = demo.runs.active
        return demo_views.scenario(demo.reader, act["event_id"] if act else None)

    @app.post("/api/scenario/reset")
    def scenario_reset():
        if demo.runs.active:
            raise HTTPException(409, "An event is running. Wait for it to finish.")
        demo.reset()
        return demo_views.scenario(demo.reader)

    @app.post("/api/scenario/{event_id}/run")
    def scenario_run(event_id: str, pace_ms: int = Query(1100, ge=0, le=4000)):
        if demo.mode != "scenario":
            raise HTTPException(400, "the server is in day mode")
        try:
            return demo.runs.start(event_id, pace_ms)
        except RunError as e:
            raise HTTPException(e.status, e.message)

    @app.get("/api/graph")
    def graph_shape():
        """Nodes and edges of the compiled LangGraph the supervisor really runs (drawn by the Workflow Studio)."""
        from orchestrator.ui.narrator import LLM_NODES, NODE_WORDS
        g = demo.sup.graph.get_graph()
        nodes = [{"id": n, "label": NODE_WORDS.get(n, (n, ""))[0], "what": NODE_WORDS.get(n, (n, ""))[1],
                  "llm": n in LLM_NODES, "kind": "terminal" if n.startswith("__") else
                  ("channel" if n in ("whatsapp", "email", "voice") else "node")} for n in g.nodes]
        edges = [{"from": e.source, "to": e.target, "conditional": bool(e.conditional)} for e in g.edges]
        nar = demo.narrator
        return {"nodes": nodes, "edges": edges, "narrator": "llm" if (nar and nar.llm is not None) else ("rules" if nar else "off")}

    @app.get("/api/scenario/{event_id}/steps")
    def scenario_steps(event_id: str):
        row = demo.reader.one("SELECT customer_id FROM demo_event WHERE event_id=?", (event_id,))
        if row is None:
            raise HTTPException(404, f"{event_id} is not one of the demo events")
        q = demo.reader.one("SELECT status, outcome FROM event_queue WHERE event_id=?", (event_id,))
        steps = demo.runs.steps(event_id)
        return {"event_id": event_id, "status": q["status"], "outcome": q["outcome"],
                "outcome_label": demo_views.reasons.OUTCOME_WORDS.get(q["outcome"]), "steps": steps,
                "message": demo.runs.message(event_id, row["customer_id"])}

    @app.get("/api/overview/drilldown/{tile}")
    def overview_drilldown(tile: str):
        if state.mode != "live":
            d = demo_views.drilldown(state.reader, state.sup.injector, state.audit, tile)
        else:
            d = demo_views.drilldown(state.reader, state.sup.injector, state.audit, tile, rows=demo_views.real_rows(state.reader),
                                     latency=views.overview_numbers(state.reader, state.sup.ctx, state.sup.injector, state.audit)["latency_ms"],
                                     live=True)
        if d is None:
            raise HTTPException(404, f"unknown tile {tile}")
        return d

    # ------------------------------------------------------------ accounts
    @app.get("/api/accounts")
    def accounts_list(request: Request):
        return acct.list_accounts(state.reader, state.engine, dict(request.query_params), now())

    @app.get("/api/journeys")
    def journeys(request: Request):
        return journey_runs(state.reader, dict(request.query_params))

    @app.get("/api/notifications")
    def notifications():
        return jr.notifications(state.reader)

    @app.post("/api/notifications/seen")
    def notifications_seen(body: dict = Body(default={})):
        n = jr.mark_seen(state.sup.ctx.db, body.get("event_ids") or None)
        return {"marked": n, **jr.notifications(state.reader)}

    @app.get("/api/accounts/filter-options")
    def accounts_filter_options():
        return acct.filter_options(state.reader)

    @app.get("/api/accounts/search")
    def accounts_search(q: str = Query("")):
        return {"items": acct.search(state.reader, q)}

    @app.get("/api/borrowers/{any_id}/state")
    def customer_state(any_id: str):
        s = acct.customer_state(state.reader, state.engine, any_id, now())
        if s is None:
            raise HTTPException(404, f"unknown account or borrower {any_id}")
        return s

    @app.get("/api/borrowers/{any_id}/trace")
    def borrower_trace(any_id: str, limit: int = Query(50, ge=1, le=500)):
        t = views.trace(state.reader, state.rctx, any_id, limit)
        if t is None:
            raise HTTPException(404, f"unknown account or borrower {any_id}")
        return t

    # ------------------------------------------------------------ the other pages
    @app.get("/api/agents")
    def agents():
        return views.agents(state.reader, state.sup.ctx)

    @app.get("/api/faults")
    def faults():
        return views.faults(state.reader, state.sup.injector)

    @app.get("/api/ownership")
    def ownership():
        return views.ownership(state.reader, now())

    @app.get("/api/budgets")
    def budgets():
        return views.budgets(state.reader, now())

    @app.get("/api/decisions")
    def decisions(request: Request):
        return views.decisions(state.reader, dict(request.query_params))

    @app.get("/api/rules")
    def rules():
        return {"items": views.rules(state.reader)}

    return app
