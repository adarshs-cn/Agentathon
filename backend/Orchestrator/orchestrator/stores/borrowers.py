"""BorrowerStore: the customer's permanent file, and the account -> customer lookup.

A CUSTOMER (the person) has one or more ACCOUNTs (loans). Events arrive per account; this store resolves the
customer behind an account. Facts across the customer's accounts (worst dpd, legal flag, channels) live in
`customer_profile`; the supervisor-owned record (owner, lease, status) in `customer_state`, the only thing we write.
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
    def seed(self, rows: list[tuple], accounts: bool = True) -> None:
        """rows: (customer_id, dpd, legal_flag, channels_list). Creates profile + empty state.
        accounts=True (simple mode): each customer also gets one account with the same id, so an event on that
        account resolves to the customer. The dataset loader passes False: it loads the real accounts (D1)."""
        prof = [(a, int(d), int(bool(l)), json.dumps(list(c))) for a, d, l, c in rows]
        state = [(a, ACTIVE) for a, *_ in rows]
        with self.db.transaction():
            self.db.executemany("INSERT OR REPLACE INTO customer_profile VALUES (?,?,?,?)", prof)
            self.db.executemany(
                "INSERT OR IGNORE INTO customer_state(customer_id, status) VALUES (?,?)", state)
            if accounts:
                self.db.executemany("INSERT OR IGNORE INTO account(account_id, customer_id, dpd, legal_flag) VALUES (?,?,?,?)",
                                    [(a, a, int(d), int(bool(l))) for a, d, l, _ in rows])

    def customer_of(self, account_id: str) -> Optional[str]:
        """The customer who holds this account, or None for an unknown account."""
        r = self.db.one("SELECT customer_id FROM account WHERE account_id=?", (account_id or "",))
        return r["customer_id"] if r else None

    def account(self, account_id: str) -> Optional[dict]:
        """The loan an event is about: its own dpd, bucket and flags."""
        r = self.db.one("SELECT * FROM account WHERE account_id=?", (account_id or "",))
        if r is None:
            return None
        d = dict(r)
        for k in ("legal_flag", "settlement_flag", "restructure_flag"):
            d[k] = bool(d.get(k))
        return d

    def exists(self, customer_id: str) -> bool:
        return self.db.one("SELECT 1 FROM customer_profile WHERE customer_id=?", (customer_id,)) is not None

    def count(self) -> int:
        return self.db.one("SELECT COUNT(*) c FROM customer_profile")["c"]

    def load(self, customer_id: str) -> Optional[dict]:
        r = self.db.one(
            "SELECT p.customer_id, p.dpd, p.legal_flag, p.channels, s.owner, s.last_contact, "
            "s.commitments, s.status FROM customer_profile p "
            "JOIN customer_state s USING (customer_id) WHERE p.customer_id=?", (customer_id,))
        if r is None:
            return None
        return {"customer_id": r["customer_id"], "dpd": r["dpd"], "legal_flag": bool(r["legal_flag"]),
                "channels": json.loads(r["channels"]), "owner": r["owner"],
                "last_contact": r["last_contact"], "commitments": json.loads(r["commitments"]),
                "status": r["status"]}

    def list_accounts(self, limit: int = 50, offset: int = 0, status: str | None = None,
                      owner: str | None = None) -> list[dict]:
        sql = ("SELECT p.customer_id, p.dpd, p.legal_flag, s.owner, s.last_contact, s.status "
               "FROM customer_profile p JOIN customer_state s USING (customer_id) WHERE 1=1")
        params: list = []
        if status:
            sql += " AND s.status=?"; params.append(status)
        if owner:
            sql += " AND s.owner=?"; params.append(owner)
        sql += " ORDER BY p.customer_id LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    # ---------------------------------------------------------------- writes (supervisor only)
    def try_take_owner(self, customer_id: str, agent: str) -> bool:
        """Atomic compare-and-set: succeeds only if nobody owns the borrower right now."""
        return self.db.execute(
            "UPDATE customer_state SET owner=?, updated_at=? WHERE customer_id=? AND owner IS NULL",
            (agent, now_iso(), customer_id)) == 1

    def switch_owner(self, customer_id: str, old: str, new: str) -> bool:
        """Hand the lock from one channel agent to another (reroute). Only if `old` holds it."""
        return self.db.execute(
            "UPDATE customer_state SET owner=?, updated_at=? WHERE customer_id=? AND owner=?",
            (new, now_iso(), customer_id, old)) == 1

    def release(self, customer_id: str) -> None:
        self.db.execute("UPDATE customer_state SET owner=NULL, updated_at=? WHERE customer_id=?",
                        (now_iso(), customer_id))

    def record_contact(self, customer_id: str, when: str) -> None:
        self.db.execute("UPDATE customer_state SET last_contact=?, updated_at=? WHERE customer_id=?",
                        (when, now_iso(), customer_id))

    def set_status(self, customer_id: str, status: str) -> None:
        self.db.execute("UPDATE customer_state SET status=?, updated_at=? WHERE customer_id=?",
                        (status, now_iso(), customer_id))

    def set_commitments(self, customer_id: str, commitments: list) -> None:
        self.db.execute("UPDATE customer_state SET commitments=?, updated_at=? WHERE customer_id=?",
                        (json.dumps(commitments), now_iso(), customer_id))

    def get_lease(self, customer_id: str) -> tuple[str | None, str | None]:
        r = self.db.one("SELECT lease_owner, lease_until FROM customer_state WHERE customer_id=?", (customer_id,))
        return (r["lease_owner"], r["lease_until"]) if r else (None, None)

    def set_lease(self, customer_id: str, role: str, until: str) -> None:
        self.db.execute("UPDATE customer_state SET lease_owner=?, lease_until=?, updated_at=? WHERE customer_id=?",
                        (role, until, now_iso(), customer_id))

    def owners_held(self) -> list[dict]:
        """Borrowers that currently have an owner lock (should be empty at end of day)."""
        return [dict(r) for r in self.db.query(
            "SELECT customer_id, owner FROM customer_state WHERE owner IS NOT NULL")]
