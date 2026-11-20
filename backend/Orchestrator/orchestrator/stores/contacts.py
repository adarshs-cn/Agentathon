"""ContactLog: the truth about what was (or may have been) sent.

One row per borrower per day: idem_key = '<account>|<date>'. That is the daily cap
enforced by the database itself: a second contact the same day cannot even be
inserted. Status:
  ATTEMPTING  we called (or are about to call) an agent; the outcome is not confirmed
  SENT        confirmed sent
  CANCELLED   we gave up without sending

An ATTEMPTING row left behind by a crash is *ambiguous*: the message may or may not
have gone out. The monitor resolves it by asking the agent's provider (`lookup`). Until
resolved, it still counts against the daily cap, so no second contact can sneak in.
"""
from __future__ import annotations

from typing import Optional

from orchestrator.stores.borrowers import now_iso
from orchestrator.stores.db import Database

COUNTED = ("ATTEMPTING", "SENT")


def idem_key(account_id: str, date: str) -> str:
    return f"{account_id}|{date}"


class ContactLog:
    def __init__(self, db: Database):
        self.db = db

    def begin(self, key: str, account_id: str, date: str, channel: str, purpose: str,
              event_id: str, role: str | None = None, at: str | None = None) -> str:
        """Record the intent to contact, before calling the agent. Idempotent.

        Returns NEW | RESUMED (retry or reroute of an unconfirmed attempt) |
        REOPENED (earlier attempt was cancelled) | ALREADY_SENT (do not call the agent).
        """
        with self.db.transaction():
            row = self.db.one("SELECT status FROM contact_log WHERE idem_key=?", (key,))
            ts = now_iso()
            if row is None:
                self.db.execute(
                    "INSERT INTO contact_log(idem_key, account_id, date, channel, purpose, status, "
                    "event_id, role, at, created_at, updated_at) VALUES (?,?,?,?,?,'ATTEMPTING',?,?,?,?,?)",
                    (key, account_id, date, channel, purpose, event_id, role or purpose, at, ts, ts))
                return "NEW"
            if row["status"] == "SENT":
                return "ALREADY_SENT"
            self.db.execute(
                "UPDATE contact_log SET channel=?, purpose=?, status='ATTEMPTING', event_id=?, "
                "role=COALESCE(?, role), updated_at=? WHERE idem_key=?", (channel, purpose, event_id, role, ts, key))
            return "RESUMED" if row["status"] == "ATTEMPTING" else "REOPENED"

    def mark_sent(self, key: str, provider_ref: str | None = None, message: dict | None = None) -> None:
        import json
        self.db.execute("UPDATE contact_log SET status='SENT', provider_ref=?, updated_at=?, "
                        "message_json=COALESCE(?, message_json), to_masked=COALESCE(?, to_masked) WHERE idem_key=?",
                        (provider_ref, now_iso(), json.dumps(message) if message else None,
                         (message or {}).get("to"), key))

    def cancel(self, key: str) -> bool:
        """Give up on an unconfirmed attempt. Never cancels a confirmed send."""
        return self.db.execute("UPDATE contact_log SET status='CANCELLED', updated_at=? "
                               "WHERE idem_key=? AND status='ATTEMPTING'", (now_iso(), key)) == 1

    def get(self, key: str) -> Optional[dict]:
        r = self.db.one("SELECT * FROM contact_log WHERE idem_key=?", (key,))
        return dict(r) if r else None

    def daily_count(self, account_id: str, date: str) -> int:
        return self.db.one(
            "SELECT COUNT(*) c FROM contact_log WHERE account_id=? AND date=? "
            "AND status IN ('ATTEMPTING','SENT')", (account_id, date))["c"]

    def recent(self, account_id: str, since_date: str, until_date: str) -> list[dict]:
        """This supervisor's own contacts for a borrower between two dates (inclusive), unconfirmed ones included."""
        return [dict(r) for r in self.db.query(
            "SELECT channel, role, purpose, status, at, date FROM contact_log WHERE account_id=? "
            "AND date BETWEEN ? AND ? AND status IN ('ATTEMPTING','SENT')", (account_id, since_date, until_date))]

    def agent_count(self, channel: str, date: str) -> int:
        return self.db.one(
            "SELECT COUNT(*) c FROM contact_log WHERE channel=? AND date=? "
            "AND status IN ('ATTEMPTING','SENT')", (channel, date))["c"]

    def rows_for(self, account_id: str) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM contact_log WHERE account_id=? ORDER BY date, created_at", (account_id,))]

    def unresolved(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM contact_log WHERE status='ATTEMPTING'")]

    def sent_total(self) -> int:
        return self.db.one("SELECT COUNT(*) c FROM contact_log WHERE status='SENT'")["c"]
