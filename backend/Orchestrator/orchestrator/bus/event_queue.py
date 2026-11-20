"""EventQueue: the event bus, persisted in the `event_queue` table.

Why a table: it is the simplest bus that survives a restart and needs no extra
infrastructure. The interface (publish / claim_next / mark_done) is what a real queue
(SQS, Kafka, ...) would also provide, so swapping it later only touches this file.

Guarantees
  * publish() ignores an event id it has seen before (duplicate delivery is harmless)
  * events arrive per ACCOUNT; publish() resolves the CUSTOMER who holds it (customer_id, '' if unknown)
  * claim_next() returns events in (event_time, arrival) order, and never hands out an
    event for a CUSTOMER who already has one IN_PROGRESS (one lane per customer: two loans of the same
    person never run at once, so two agents can never contact them together, R035-R037)
  * a crash leaves events IN_PROGRESS, so the supervisor can find and finish them
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Optional

from orchestrator.stores.db import Database


class EventQueue:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _to_event(r) -> dict:
        return {"id": r["event_id"], "type": r["type"], "account_id": r["account_id"], "customer_id": r["customer_id"],
                "time": r["event_time"], "payload": json.loads(r["payload"])}

    def publish(self, event: dict) -> bool:
        """Add an event. Returns False only if this event id was already published.

        A malformed event (no id, no account, ...) is NOT dropped: it is stored so the
        supervisor's validate_event node can reject it and leave a trace. An event with
        no id gets a generated one.
        """
        event_id = event.get("id") or f"auto-{uuid.uuid4().hex[:12]}"
        acc = event.get("account_id") or ""
        c = self.db.one("SELECT customer_id FROM account WHERE account_id=?", (acc,)) if acc else None
        try:
            self.db.execute(
                "INSERT INTO event_queue(event_id, account_id, customer_id, type, event_time, payload) "
                "VALUES (?,?,?,?,?,?)",
                (event_id, acc, c["customer_id"] if c else "", event.get("type") or "",
                 event.get("time") or "", json.dumps(event.get("payload") or {})))
            return True
        except sqlite3.IntegrityError:
            return False

    def publish_many(self, events: list[dict]) -> int:
        return sum(1 for e in events if self.publish(e))

    def claim_next(self, until: str | None = None) -> Optional[dict]:
        """The next event in time order. With `until`, only events whose time has already arrived
        (event_time <= until): that is how a simulated clock releases the day's events."""
        with self.db.transaction():
            r = self.db.one(
                "SELECT * FROM event_queue WHERE status='PENDING' AND (customer_id = '' OR customer_id NOT IN (SELECT customer_id FROM event_queue WHERE status='IN_PROGRESS' AND customer_id != '')) "
                + ("AND event_time <= ? " if until else "") + "ORDER BY event_time, seq LIMIT 1",
                (until,) if until else ())
            if r is None:
                return None
            self.db.execute("UPDATE event_queue SET status='IN_PROGRESS', attempts=attempts+1 "
                            "WHERE seq=?", (r["seq"],))
            return self._to_event(r)

    def claim(self, event_id: str) -> Optional[dict]:
        """Take one specific PENDING event (an ad-hoc run), still respecting one lane per customer.
        Returns None if it is not PENDING or the customer already has an event in progress."""
        with self.db.transaction():
            r = self.db.one("SELECT * FROM event_queue WHERE event_id=? AND status='PENDING' AND (customer_id = '' OR customer_id NOT IN (SELECT customer_id FROM event_queue WHERE status='IN_PROGRESS' AND customer_id != ''))", (event_id,))
            if r is None:
                return None
            self.db.execute("UPDATE event_queue SET status='IN_PROGRESS', attempts=attempts+1 WHERE seq=?", (r["seq"],))
            return self._to_event(r)

    def next_event_time(self) -> Optional[str]:
        r = self.db.one("SELECT MIN(event_time) t FROM event_queue WHERE status='PENDING'")
        return r["t"] if r else None

    def mark_done(self, event_id: str, outcome: str) -> None:
        self.db.execute("UPDATE event_queue SET status='DONE', outcome=? WHERE event_id=?",
                        (outcome, event_id))

    def mark_failed(self, event_id: str, reason: str) -> None:
        self.db.execute("UPDATE event_queue SET status='FAILED', outcome=? WHERE event_id=?",
                        (reason, event_id))

    def requeue(self, event_id: str) -> None:
        self.db.execute("UPDATE event_queue SET status='PENDING' WHERE event_id=?", (event_id,))

    def bump(self, event_id: str) -> int:
        """Count another processing attempt (used on retry and on restart). Returns the new total."""
        self.db.execute("UPDATE event_queue SET attempts=attempts+1 WHERE event_id=?", (event_id,))
        return self.attempts(event_id)

    def attempts(self, event_id: str) -> int:
        r = self.db.one("SELECT attempts FROM event_queue WHERE event_id=?", (event_id,))
        return r["attempts"] if r else 0

    def in_progress(self) -> list[dict]:
        return [self._to_event(r) for r in self.db.query(
            "SELECT * FROM event_queue WHERE status='IN_PROGRESS' ORDER BY seq")]

    def stats(self) -> dict:
        return {r["status"]: r["c"] for r in self.db.query(
            "SELECT status, COUNT(*) c FROM event_queue GROUP BY status")}

    def get(self, event_id: str) -> Optional[dict]:
        r = self.db.one("SELECT * FROM event_queue WHERE event_id=?", (event_id,))
        return dict(r) if r else None

    def for_customer(self, customer_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM event_queue WHERE customer_id=? ORDER BY event_time, seq", (customer_id,))]
