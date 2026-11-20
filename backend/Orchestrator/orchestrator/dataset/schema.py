"""Tables that hold the portfolio dataset (D1, D2, D4, D6, D7, D10, D12, D13).

Customers own accounts. The D12 rules make the CUSTOMER the unit for caps (R033) and ownership (R037),
so the per-person tables are keyed by customer_id; account-level facts keep their account_id.

Privacy: names, dates of birth, addresses, phone numbers and email addresses are NEVER
stored. From D2 we keep only booleans (has a phone, has an email, shares a phone with
another borrower, is deceased).
"""
from __future__ import annotations

DS_SCHEMA = """
-- customer and account are created by the core schema (stores/db.py)
CREATE TABLE IF NOT EXISTS ds_consent (
    customer_id TEXT PRIMARY KEY,
    consent_call TEXT, consent_sms TEXT, consent_whatsapp TEXT, consent_email TEXT, consent_field_visit TEXT,
    optout_call TEXT, optout_sms TEXT, optout_whatsapp TEXT, optout_email TEXT, optout_field_visit TEXT,
    dnd_status TEXT, dnd_effective_from TEXT, consent_source TEXT, consent_expiry TEXT,
    requested_window TEXT, suppression_reason TEXT, suppression_from TEXT);

CREATE TABLE IF NOT EXISTS ds_history (            -- D4: contacts already made (recent days only)
    customer_id TEXT NOT NULL, account_id TEXT, at TEXT NOT NULL, agent TEXT, channel TEXT, disposition TEXT);
CREATE INDEX IF NOT EXISTS ix_ds_history ON ds_history(customer_id, at);

CREATE TABLE IF NOT EXISTS ds_ptp (                -- D6: promises to pay
    ptp_id TEXT PRIMARY KEY, account_id TEXT, customer_id TEXT, promised_date TEXT, amount REAL,
    captured_by TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_ds_ptp ON ds_ptp(customer_id, status);

CREATE TABLE IF NOT EXISTS ds_payment (            -- D7: payments
    txn_id TEXT PRIMARY KEY, account_id TEXT, customer_id TEXT, at TEXT, amount REAL, status TEXT, reversal INTEGER);
CREATE INDEX IF NOT EXISTS ix_ds_payment ON ds_payment(customer_id, at);

CREATE TABLE IF NOT EXISTS ds_matrix (             -- D12 agent x bucket matrix
    agent TEXT, agent_type TEXT, bucket TEXT, allowed INTEGER, channels TEXT, actions TEXT,
    rank INTEGER, contact INTEGER, note TEXT);

CREATE TABLE IF NOT EXISTS ds_rule (               -- D12 policy rules (all 93, for caps/windows and the trace)
    rule_id TEXT PRIMARY KEY, category TEXT, bucket TEXT, channel TEXT, agent TEXT, parameter TEXT,
    operator TEXT, value TEXT, severity TEXT, status TEXT, description TEXT);

CREATE TABLE IF NOT EXISTS ds_capacity (           -- D13 per agent x channel budgets
    resource_id TEXT PRIMARY KEY, agent TEXT, channel TEXT, cost REAL, daily_budget INTEGER,
    spend_cap REAL, window TEXT, buckets TEXT);
"""

DS_TABLES = ("account", "customer", "ds_consent", "ds_history", "ds_ptp", "ds_payment",
             "ds_matrix", "ds_rule", "ds_capacity")
