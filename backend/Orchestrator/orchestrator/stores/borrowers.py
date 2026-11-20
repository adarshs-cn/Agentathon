"""BorrowerStore: the borrower's permanent file.

Facts (dpd, legal flag, channels) come from `borrower_profile`, a stand-in for the
D1/D2/D4/D6 tables; replace `seed` with an adapter over the real tables. The
supervisor-owned record lives in `borrower_state` and is the only thing we write.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from orchestrator.config import ACTIVE
from orchestrator.stores.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class BorrowerStore:
    def __init__(self, db: Database):
        self.db = db

    # ---------------------------------------------------------------- seeding / reading
    def seed(self, rows: list[tuple]) -> None:
        """rows: (account_id, dpd, legal_flag, channels_list). Creates profile + empty state."""
        prof = [(a, int(d), int(bool(l)), json.dumps(list(c))) for a, d, l, c in rows]
        state = [(a, ACTIVE) for a, *_ in rows]
        with self.db.transaction():
            self.db.executemany("INSERT OR REPLACE INTO borrower_profile VALUES (?,?,?,?)", prof)
            self.db.executemany(
                "INSERT OR IGNORE INTO borrower_state(account_id, status) VALUES (?,?)", state)

    def exists(self, account_id: str) -> bool:
        return self.db.one("SELECT 1 FROM borrower_profile WHERE account_id=?", (account_id,)) is not None

    def count(self) -> int:
        return self.db.one("SELECT COUNT(*) c FROM borrower_profile")["c"]

    def load(self, account_id: str) -> Optional[dict]:
        r = self.db.one(
            "SELECT p.account_id, p.dpd, p.legal_flag, p.channels, s.owner, s.last_contact, "
            "s.commitments, s.status FROM borrower_profile p "
            "JOIN borrower_state s USING (account_id) WHERE p.account_id=?", (account_id,))
        if r is None:
            return None
        return {"account_id": r["account_id"], "dpd": r["dpd"], "legal_flag": bool(r["legal_flag"]),
                "channels": json.loads(r["channels"]), "owner": r["owner"],
                "last_contact": r["last_contact"], "commitments": json.loads(r["commitments"]),
                "status": r["status"]}

    def list_accounts(self, limit: int = 50, offset: int = 0, status: str | None = None,
                      owner: str | None = None) -> list[dict]:
        sql = ("SELECT p.account_id, p.dpd, p.legal_flag, s.owner, s.last_contact, s.status "
               "FROM borrower_profile p JOIN borrower_state s USING (account_id) WHERE 1=1")
        params: list = []
        if status:
            sql += " AND s.status=?"; params.append(status)
        if owner:
            sql += " AND s.owner=?"; params.append(owner)
        sql += " ORDER BY p.account_id LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    # ---------------------------------------------------------------- writes (supervisor only)
    def try_take_owner(self, account_id: str, agent: str) -> bool:
        """Atomic compare-and-set: succeeds only if nobody owns the borrower right now."""
        return self.db.execute(
            "UPDATE borrower_state SET owner=?, updated_at=? WHERE account_id=? AND owner IS NULL",
            (agent, now_iso(), account_id)) == 1

    def switch_owner(self, account_id: str, old: str, new: str) -> bool:
        """Hand the lock from one channel agent to another (reroute). Only if `old` holds it."""
        return self.db.execute(
            "UPDATE borrower_state SET owner=?, updated_at=? WHERE account_id=? AND owner=?",
            (new, now_iso(), account_id, old)) == 1

    def release(self, account_id: str) -> None:
        self.db.execute("UPDATE borrower_state SET owner=NULL, updated_at=? WHERE account_id=?",
                        (now_iso(), account_id))

    def record_contact(self, account_id: str, when: str) -> None:
        self.db.execute("UPDATE borrower_state SET last_contact=?, updated_at=? WHERE account_id=?",
                        (when, now_iso(), account_id))

    def set_status(self, account_id: str, status: str) -> None:
        self.db.execute("UPDATE borrower_state SET status=?, updated_at=? WHERE account_id=?",
                        (status, now_iso(), account_id))

    def set_commitments(self, account_id: str, commitments: list) -> None:
        self.db.execute("UPDATE borrower_state SET commitments=?, updated_at=? WHERE account_id=?",
                        (json.dumps(commitments), now_iso(), account_id))

    def get_lease(self, account_id: str) -> tuple[str | None, str | None]:
        r = self.db.one("SELECT lease_owner, lease_until FROM borrower_state WHERE account_id=?", (account_id,))
        return (r["lease_owner"], r["lease_until"]) if r else (None, None)

    def set_lease(self, account_id: str, role: str, until: str) -> None:
        self.db.execute("UPDATE borrower_state SET lease_owner=?, lease_until=?, updated_at=? WHERE account_id=?",
                        (role, until, now_iso(), account_id))

    def owners_held(self) -> list[dict]:
        """Borrowers that currently have an owner lock (should be empty at end of day)."""
        return [dict(r) for r in self.db.query(
            "SELECT account_id, owner FROM borrower_state WHERE owner IS NOT NULL")]
