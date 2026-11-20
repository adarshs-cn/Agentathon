"""Context: the supervisor's dependency container.

Every node is built by a factory `make_x(ctx)` that closes over this object, so nodes
never import global state and tests can build as many isolated supervisors as they like.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from orchestrator.agents.registry import AgentRegistry
from orchestrator.bus.event_queue import EventQueue
from orchestrator.config import Policy
from orchestrator.stores.borrowers import BorrowerStore
from orchestrator.stores.contacts import ContactLog
from orchestrator.stores.db import Database
from orchestrator.stores.decisions import DecisionLog


@dataclass
class Context:
    policy: Policy
    db: Database
    borrowers: BorrowerStore
    contacts: ContactLog
    decisions: DecisionLog
    bus: EventQueue
    registry: AgentRegistry
    advisor: Optional[Any] = None                       # recovery advisor (LLM); optional
    engine: Optional[Any] = None                        # D12 policy engine; None = the simple built-in rules
    metrics: dict = field(default_factory=dict)         # node name -> list of durations (ms)
    on_node_start: Optional[Callable[[str, dict], None]] = None   # test hook (crash injection)
    node_listeners: list = field(default_factory=list)            # callables(phase, node, info): live run streaming

    @classmethod
    def create(cls, db_path: str = ":memory:", policy: Policy | None = None, agents=(),
               advisor=None) -> "Context":
        db = Database(db_path)
        return cls(policy=policy or Policy(), db=db, borrowers=BorrowerStore(db),
                   contacts=ContactLog(db), decisions=DecisionLog(db), bus=EventQueue(db),
                   registry=AgentRegistry(list(agents)), advisor=advisor)

    def idem_key(self, customer_id: str, event: dict) -> str:
        """The contact's idempotency key. Simple mode: one contact per customer per day. Dataset mode: one per
        event, because D12 allows several contacts a day and the caps are enforced by counting (R009-R034)."""
        return f"{customer_id}|{event['id']}" if self.engine is not None else f"{customer_id}|{event['time'][:10]}"

    def log(self, state: dict, node: str, text: str, data: dict | None = None) -> None:
        ev = state.get("event") or {}
        self.decisions.add(ev.get("time", ""), ev.get("id", ""), ev.get("customer_id", ""),
                           node, text, data, account_id=ev.get("account_id"))

    def instrument(self, name: str, fn: Callable) -> Callable:
        """Wrap a node: fire the test hook, and record how long it took."""
        def wrapped(state):
            if self.on_node_start:
                self.on_node_start(name, state)
            for ls in list(self.node_listeners):
                ls("start", name, {"state": state})
            t0 = time.perf_counter()
            out = None
            try:
                out = fn(state)
                return out
            finally:
                ms = (time.perf_counter() - t0) * 1000
                self.metrics.setdefault(name, []).append(ms)
                for ls in list(self.node_listeners):
                    ls("end", name, {"state": state, "update": out, "ms": ms})
        wrapped.__name__ = name
        return wrapped

    def percentile(self, node: str, p: float) -> float:
        xs = sorted(self.metrics.get(node, []))
        if not xs:
            return 0.0
        return xs[min(len(xs) - 1, int(len(xs) * p))]
