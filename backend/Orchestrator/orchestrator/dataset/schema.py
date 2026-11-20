"""Tables that hold the portfolio dataset (D1, D2, D4, D6, D7, D10, D12, D13).

All keyed by the BORROWER, because D12 makes the borrower the unit: caps count per borrower
across all their accounts (R033) and an ownership lock covers all of them (R037).

Privacy: names, dates of birth, addresses, phone numbers and email addresses are NEVER
stored. From D2 we keep only booleans (has a phone, has an email, shares a phone with
another borrower, is deceased).
"""
from __future__ import annotations

DS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ds_account (
    account_id TEXT PRIMARY KEY, borrower_id TEXT NOT NULL, dpd INTEGER, bucket TEXT,
    legal_flag INTEGER, settlement_flag INTEGER, restructure_flag INTEGER, emi REAL, total_dues REAL,
    product TEXT, city TEXT, branch TEXT, loan_amount REAL, principal_outstanding REAL);
CREATE INDEX IF NOT EXISTS ix_ds_account_b ON ds_account(borrower_id);

CREATE TABLE IF NOT EXISTS ds_person (
    borrower_id TEXT PRIMARY KEY, deceased INTEGER, has_phone INTEGER, has_email INTEGER, shared_phone INTEGER,
    name_masked TEXT, phone_masked TEXT);                -- display only: 'D*** S***' and 'XXXXXX4842'

CREATE TABLE IF NOT EXISTS ds_consent (
    borrower_id TEXT PRIMARY KEY,
    consent_call TEXT, consent_sms TEXT, consent_whatsapp TEXT, consent_email TEXT, consent_field_visit TEXT,
    optout_call TEXT, optout_sms TEXT, optout_whatsapp TEXT, optout_email TEXT, optout_field_visit TEXT,
    dnd_status TEXT, dnd_effective_from TEXT, consent_source TEXT, consent_expiry TEXT,
    requested_window TEXT, suppression_reason TEXT, suppression_from TEXT);

CREATE TABLE IF NOT EXISTS ds_history (            -- D4: contacts already made (recent days only)
    borrower_id TEXT NOT NULL, account_id TEXT, at TEXT NOT NULL, agent TEXT, channel TEXT, disposition TEXT);
CREATE INDEX IF NOT EXISTS ix_ds_history ON ds_history(borrower_id, at);

CREATE TABLE IF NOT EXISTS ds_ptp (                -- D6: promises to pay
    ptp_id TEXT PRIMARY KEY, account_id TEXT, borrower_id TEXT, promised_date TEXT, amount REAL,
    captured_by TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS ix_ds_ptp ON ds_ptp(borrower_id, status);

CREATE TABLE IF NOT EXISTS ds_payment (            -- D7: payments
    txn_id TEXT PRIMARY KEY, account_id TEXT, borrower_id TEXT, at TEXT, amount REAL, status TEXT, reversal INTEGER);
CREATE INDEX IF NOT EXISTS ix_ds_payment ON ds_payment(borrower_id, at);

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

DS_TABLES = ("ds_account", "ds_person", "ds_consent", "ds_history", "ds_ptp", "ds_payment",
             "ds_matrix", "ds_rule", "ds_capacity")
