"""SQLite wrapper and schema for the supervisor's own tables.

These are the tables the supervisor owns (it never writes to the D1/D2/D4/D6 data):
  contact_log       every contact attempt, one row per borrower per day (idempotency)
  decision_log      every decision with its reason: the audit trail
  event_queue       the event bus: persisted, so events survive a restart

LangGraph's own checkpoint tables live in a separate database file.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
-- Data model: a CUSTOMER (the person) has one or more ACCOUNTs (loans). Events arrive per ACCOUNT; the safety rules
-- (one owner, contact limits, consent) apply per CUSTOMER across all their accounts (R033, R035-R038).
CREATE TABLE IF NOT EXISTS customer (
    customer_id TEXT PRIMARY KEY, deceased INTEGER, has_phone INTEGER, has_email INTEGER, shared_phone INTEGER,
    name_masked TEXT, phone_masked TEXT);                -- display only: 'D*** S***' and 'XXXXXX4842'

CREATE TABLE IF NOT EXISTS account (
    account_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, dpd INTEGER, bucket TEXT,
    legal_flag INTEGER, settlement_flag INTEGER, restructure_flag INTEGER, emi REAL, total_dues REAL,
    product TEXT, city TEXT, branch TEXT, loan_amount REAL, principal_outstanding REAL);
CREATE INDEX IF NOT EXISTS ix_account_customer ON account(customer_id);

CREATE TABLE IF NOT EXISTS customer_profile (     -- what the supervisor needs about the customer, across accounts
    customer_id TEXT PRIMARY KEY,
    dpd        INTEGER NOT NULL,                  -- worst DPD across the customer's accounts
    legal_flag INTEGER NOT NULL DEFAULT 0,
    channels   TEXT    NOT NULL DEFAULT '[]'      -- JSON list of reachable channels
);

CREATE TABLE IF NOT EXISTS customer_state (       -- the supervisor's record per customer
    customer_id  TEXT PRIMARY KEY,
    owner        TEXT,                            -- active owner agent, NULL = nobody
    last_contact TEXT,
    commitments  TEXT NOT NULL DEFAULT '[]',      -- JSON list of open promises
    status       TEXT NOT NULL DEFAULT 'ACTIVE',
    updated_at   TEXT,
    lease_owner  TEXT,                            -- role that holds the 24h ownership lease (R038)
    lease_until  TEXT
);

CREATE TABLE IF NOT EXISTS contact_log (
    idem_key     TEXT PRIMARY KEY,                -- '<customer>|<event>' (or '<customer>|<date>' in simple mode)
    customer_id  TEXT NOT NULL,                   -- limits and ownership count per customer
    account_id   TEXT,                            -- the loan this contact was about
    date         TEXT NOT NULL,
    channel      TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    status       TEXT NOT NULL,                   -- ATTEMPTING | SENT | CANCELLED
    provider_ref TEXT,
    event_id     TEXT,
    role         TEXT,                            -- the role agent this contact is on behalf of
    at           TEXT,                            -- event time of the contact
    created_at   TEXT,
    updated_at   TEXT,
    message_json TEXT,                            -- the message the agent sent (masked), for the dashboard
    to_masked    TEXT
);
CREATE INDEX IF NOT EXISTS ix_contact_customer ON contact_log(customer_id);
CREATE INDEX IF NOT EXISTS ix_contact_channel_date ON contact_log(channel, date);

CREATE TABLE IF NOT EXISTS decision_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT,                             -- simulated/event time
    wall        REAL,                             -- real clock, for ordering evidence
    event_id    TEXT,
    customer_id TEXT,
    account_id  TEXT,
    node        TEXT,
    text        TEXT,
    data        TEXT
);
CREATE INDEX IF NOT EXISTS ix_decision_customer ON decision_log(customer_id, id);
CREATE INDEX IF NOT EXISTS ix_decision_event ON decision_log(event_id);

CREATE TABLE IF NOT EXISTS event_queue (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL UNIQUE,              -- UNIQUE: a duplicate publish is ignored
    account_id TEXT NOT NULL,                     -- events arrive per ACCOUNT (loan)
    customer_id TEXT NOT NULL DEFAULT '',         -- resolved from the account on publish ('' = unknown account)
    type       TEXT NOT NULL,
    event_time TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    status     TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING | IN_PROGRESS | DONE | FAILED
    outcome    TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_queue_status ON event_queue(status, event_time, seq);
CREATE INDEX IF NOT EXISTS ix_queue_customer ON event_queue(customer_id, status);

CREATE TABLE IF NOT EXISTS run_step (              -- one row per node of an ad-hoc run: drives hover, replay, event log
    event_id TEXT NOT NULL, seq INTEGER NOT NULL, node TEXT, station TEXT, ms REAL,
    owner_before TEXT, owner_after TEXT, did TEXT, label TEXT, rule_ids TEXT, data TEXT,
    trace TEXT,                                    -- the streamed trace-pad text {source, think, text}
    PRIMARY KEY (event_id, seq));

CREATE TABLE IF NOT EXISTS journey_run (           -- one row per finished REAL journey run (kept across restarts)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL, customer_id TEXT, account_id TEXT, event_type TEXT, event_time TEXT,
    outcome TEXT, channel TEXT, role TEXT, owner_after TEXT, rule_ids TEXT, summary TEXT,
    fault TEXT, fault_agent TEXT, recovery_action TEXT, recovery_reason TEXT,   -- set only when a fault happened
    notify_seen INTEGER NOT NULL DEFAULT 1,        -- 0 = a fault+recovery the collections manager has not looked at yet
    started_wall REAL, finished_wall REAL, duration_ms REAL, attempts INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS ux_journey_event ON journey_run(event_id);
CREATE INDEX IF NOT EXISTS ix_journey_wall ON journey_run(finished_wall);

CREATE TABLE IF NOT EXISTS demo_event (            -- the scenario: one row per demo event
    seq INTEGER PRIMARY KEY, key TEXT, label TEXT, event_id TEXT, customer_id TEXT, account_id TEXT, event_type TEXT,
    depends_on INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS demo_setup (            -- every row the scenario staged, so it is listed
    seq INTEGER, table_name TEXT, row_key TEXT);
"""

TABLES = ("customer", "account", "customer_profile", "customer_state", "contact_log", "decision_log", "event_queue")


class Database:
    """One SQLite connection guarded by a re-entrant lock.

    Autocommit by default; use `transaction()` when several statements must be atomic.
    Do not nest transactions.
    """

    def __init__(self, path: str = ":memory:", read_only: bool = False):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if read_only:
            # A second connection for readers: with WAL they never block (or get blocked by) the writer.
            self.conn.execute("PRAGMA query_only=ON")
            return
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        old = self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='borrower_state'").fetchone()
        if old:                                        # the layout before customers and accounts were separated
            raise RuntimeError(f"{self.path} uses the old borrower-keyed layout; delete it (or reset) so it is rebuilt")
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write; returns the number of rows changed."""
        with self._lock:
            return self.conn.execute(sql, params).rowcount

    def executescript(self, sql: str) -> None:
        with self._lock:
            self.conn.executescript(sql)

    def executemany(self, sql: str, rows: list) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self.conn.close()
