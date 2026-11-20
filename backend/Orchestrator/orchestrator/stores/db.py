"""SQLite wrapper and schema for the supervisor's own tables.

These are the tables the supervisor owns (it never writes to the D1/D2/D4/D6 data):
  borrower_profile  read-only facts about a borrower (stand-in for D1/D2/D4/D6)
  borrower_state    the supervisor's record per borrower: owner, last contact, ...
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
CREATE TABLE IF NOT EXISTS borrower_profile (
    account_id TEXT PRIMARY KEY,
    dpd        INTEGER NOT NULL,
    legal_flag INTEGER NOT NULL DEFAULT 0,
    channels   TEXT    NOT NULL DEFAULT '[]'      -- JSON list of reachable channels
);

CREATE TABLE IF NOT EXISTS borrower_state (
    account_id   TEXT PRIMARY KEY,
    owner        TEXT,                            -- active owner agent, NULL = nobody
    last_contact TEXT,
    commitments  TEXT NOT NULL DEFAULT '[]',      -- JSON list of open promises
    status       TEXT NOT NULL DEFAULT 'ACTIVE',
    updated_at   TEXT,
    lease_owner  TEXT,                            -- role that holds the 24h ownership lease (R038)
    lease_until  TEXT
);

CREATE TABLE IF NOT EXISTS contact_log (
    idem_key     TEXT PRIMARY KEY,                -- '<account>|<date>': one contact per day
    account_id   TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS ix_contact_account ON contact_log(account_id);
CREATE INDEX IF NOT EXISTS ix_contact_channel_date ON contact_log(channel, date);

CREATE TABLE IF NOT EXISTS decision_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT,                              -- simulated/event time
    wall       REAL,                              -- real clock, for ordering evidence
    event_id   TEXT,
    account_id TEXT,
    node       TEXT,
    text       TEXT,
    data       TEXT
);
CREATE INDEX IF NOT EXISTS ix_decision_account ON decision_log(account_id, id);
CREATE INDEX IF NOT EXISTS ix_decision_event ON decision_log(event_id);

CREATE TABLE IF NOT EXISTS event_queue (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL UNIQUE,              -- UNIQUE: a duplicate publish is ignored
    account_id TEXT NOT NULL,
    type       TEXT NOT NULL,
    event_time TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    status     TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING | IN_PROGRESS | DONE | FAILED
    outcome    TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_queue_status ON event_queue(status, event_time, seq);
CREATE INDEX IF NOT EXISTS ix_queue_account ON event_queue(account_id);

CREATE TABLE IF NOT EXISTS run_step (              -- one row per node of an ad-hoc run: drives hover, replay, event log
    event_id TEXT NOT NULL, seq INTEGER NOT NULL, node TEXT, station TEXT, ms REAL,
    owner_before TEXT, owner_after TEXT, did TEXT, label TEXT, rule_ids TEXT, data TEXT,
    PRIMARY KEY (event_id, seq));

CREATE TABLE IF NOT EXISTS demo_event (            -- the scenario: one row per demo event
    seq INTEGER PRIMARY KEY, key TEXT, label TEXT, event_id TEXT, borrower_id TEXT, event_type TEXT,
    depends_on INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS demo_setup (            -- every row the scenario staged, so it is listed
    seq INTEGER, table_name TEXT, row_key TEXT);
"""

TABLES = ("borrower_profile", "borrower_state", "contact_log", "decision_log", "event_queue")


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
        self.conn.executescript(SCHEMA)
        for col in ('message_json', 'to_masked'):      # databases created before messages existed
            try:
                self.conn.execute(f'ALTER TABLE contact_log ADD COLUMN {col} TEXT')
            except sqlite3.OperationalError:
                pass

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
