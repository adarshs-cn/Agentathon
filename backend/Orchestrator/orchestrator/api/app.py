"""HTTP API over the supervisor. This is what the CN account listing page will call.

  GET  /health                         liveness + bus depth
  POST /events                         put an event on the bus (?process=true runs it now)
  POST /run                            process whatever is waiting on the bus
  GET  /accounts                       the listing: owner, last contact, status (filter, paginate)
  GET  /accounts/{id}                  one borrower's file
  GET  /accounts/{id}/trace            the full, ordered trace for one account
  GET  /events/{id}                    where one event stands
  GET  /stats                          bus counts, contacts sent, routing latency

Malformed events are accepted on purpose (every field optional): the supervisor must see
them to reject them and leave a trace, rather than the API silently dropping them.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from orchestrator.supervisor import Supervisor
from orchestrator.tracing.trace import account_trace


class EventIn(BaseModel):
    id: Optional[str] = None
    type: Optional[str] = None
    account_id: Optional[str] = None
    time: Optional[str] = None
    payload: Optional[dict] = None


def create_app(sup: Supervisor) -> FastAPI:
    app = FastAPI(title="Journey Supervisor", version="0.1")
    ctx = sup.ctx

    @app.get("/health")
    def health():
        return {"ok": True, "bus": ctx.bus.stats(), "borrowers": ctx.borrowers.count()}

    @app.post("/events")
    def post_event(body: EventIn, process: bool = False):
        ev = body.model_dump(exclude_none=True)
        ev.setdefault("id", f"api-{uuid.uuid4().hex[:12]}")
        published = sup.publish(ev)
        if process:
            sup.run_until_empty()
        row = ctx.bus.get(ev["id"])
        return {"event_id": ev["id"], "published": published,
                "status": row["status"] if row else None, "outcome": row["outcome"] if row else None}

    @app.post("/run")
    def run(max_events: Optional[int] = Query(default=None, ge=1)):
        return {"processed": sup.run_until_empty(max_events), "bus": ctx.bus.stats()}

    @app.get("/accounts")
    def accounts(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                 status: Optional[str] = None, owner: Optional[str] = None):
        return {"total": ctx.borrowers.count(), "limit": limit, "offset": offset,
                "items": ctx.borrowers.list_accounts(limit, offset, status, owner)}

    @app.get("/accounts/{account_id}")
    def account(account_id: str):
        b = ctx.borrowers.load(account_id)
        if b is None:
            raise HTTPException(404, f"unknown account {account_id}")
        return b

    @app.get("/accounts/{account_id}/trace")
    def trace(account_id: str):
        if not ctx.borrowers.exists(account_id):
            raise HTTPException(404, f"unknown account {account_id}")
        return account_trace(ctx, account_id, sup.graph)

    @app.get("/events/{event_id}")
    def event(event_id: str):
        row = ctx.bus.get(event_id)
        if row is None:
            raise HTTPException(404, f"unknown event {event_id}")
        return {**row, "steps": ctx.decisions.for_event(event_id)}

    @app.get("/stats")
    def stats():
        return {"bus": ctx.bus.stats(), "contacts_sent": ctx.contacts.sent_total(),
                "route_p99_ms": round(ctx.percentile("route", 0.99), 3),
                "route_max_ms": round(max(ctx.metrics.get("route", [0])), 3),
                "locks_held": len(ctx.borrowers.owners_held())}

    return app
