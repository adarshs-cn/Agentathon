"""DecisionLog: the audit trail. Every node writes one line saying what it decided and why."""
from __future__ import annotations

import json
import time
from typing import Optional

from orchestrator.stores.db import Database


class DecisionLog:
    def __init__(self, db: Database):
        self.db = db
        self.listeners: list = []      # callables(row_dict), e.g. a live narrator

    def add(self, ts: str, event_id: str, customer_id: str, node: str, text: str,
            data: Optional[dict] = None, account_id: Optional[str] = None) -> None:
        self.db.execute(
            "INSERT INTO decision_log(ts, wall, event_id, customer_id, account_id, node, text, data) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ts, time.time(), event_id, customer_id, account_id, node, text,
             json.dumps(data, default=str) if data is not None else None))
        for fn in self.listeners:
            try:
                fn({"ts": ts, "event_id": event_id, "customer_id": customer_id, "account_id": account_id, "node": node,
                    "text": text, "data": data})
            except Exception:  # noqa: BLE001 - observing must never break the supervisor
                pass

    def _rows(self, sql: str, params: tuple) -> list[dict]:
        out = []
        for r in self.db.query(sql, params):
            d = dict(r)
            d["data"] = json.loads(d["data"]) if d["data"] else None
            out.append(d)
        return out

    def for_customer(self, customer_id: str) -> list[dict]:
        return self._rows("SELECT * FROM decision_log WHERE customer_id=? ORDER BY id", (customer_id,))

    def for_event(self, event_id: str) -> list[dict]:
        return self._rows("SELECT * FROM decision_log WHERE event_id=? ORDER BY id", (event_id,))

    def count(self) -> int:
        return self.db.one("SELECT COUNT(*) c FROM decision_log")["c"]
