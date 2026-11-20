"""Load the portfolio dataset (a folder of D1/D2/D4/D6/D7/D10/D12/D13 CSVs) into the database.

    report = load_dataset(db, borrower_store, "data/portfolio/Multi_Agent_Supervisor_Dataset")

Idempotent: reloading replaces the dataset tables. Also seeds the supervisor's own borrower
tables (one row per BORROWER) so the graph can run on it.

`as_of` is the simulated "today" (the dataset was generated as of 2026-10-31). Only the last
`history_days` of D4 are kept: enough for the 7-day caps and today's counts.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from orchestrator.dataset.schema import DS_SCHEMA, DS_TABLES
from orchestrator.stores.borrowers import BorrowerStore
from orchestrator.stores.db import Database

AS_OF = "2026-10-31"


def _read(path: Path, cols: list[str]):
    """Yield dicts with only the wanted columns, stripped. Anything else in the file is never touched."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            yield {c: (r.get(c) or "").strip() for c in cols}


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def bucket_of(dpd: int) -> str:
    """RBI SMA mapping used by D12 (R073): 1-30, 31-60, 61-90; more than 90 days is NPA (R074)."""
    return "0" if dpd <= 0 else "1-30" if dpd <= 30 else "31-60" if dpd <= 60 else "61-90" if dpd <= 90 else "90+"


def _iso(ts: str) -> str:
    return ts.replace(" ", "T")


def mask_name(name: str) -> str:
    """'Deepak Shah' -> 'D*** S***': enough to recognise a row on screen, not enough to identify anyone."""
    return " ".join(w[0] + "***" for w in name.split()) if name else ""


def mask_phone(phone: str) -> str:
    """'6197814842' -> 'XXXXXX4842': the last four digits only."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return ("X" * 6 + digits[-4:]) if len(digits) >= 4 else ""


def load_dataset(db: Database, store: BorrowerStore, folder: str | Path, as_of: str = AS_OF,
                 history_days: int = 14) -> dict:
    d = Path(folder)
    db.executescript(DS_SCHEMA)
    for t in DS_TABLES:
        db.execute(f"DELETE FROM {t}")
    report: dict = {"as_of": as_of}

    # ---- D1 accounts
    acc_rows, by_borrower, acc_to_b = [], defaultdict(list), {}
    for r in _read(d / "d1_account_master.csv", ["account_id", "borrower_id", "dpd", "bucket", "legal_flag",
                                                  "settlement_flag", "restructure_flag", "emi", "total_dues",
                                                  "product", "city", "branch", "sanction_amount",
                                                  "principal_outstanding"]):
        dpd = _int(r["dpd"])
        acc_rows.append((r["account_id"], r["borrower_id"], dpd, r["bucket"] or bucket_of(dpd), _int(r["legal_flag"]),
                         _int(r["settlement_flag"]), _int(r["restructure_flag"]), float(r["emi"] or 0),
                         float(r["total_dues"] or 0), r["product"], r["city"], r["branch"],
                         float(r["sanction_amount"] or 0), float(r["principal_outstanding"] or 0)))
        by_borrower[r["borrower_id"]].append(acc_rows[-1])
        acc_to_b[r["account_id"]] = r["borrower_id"]

    # ---- D2 persons: only booleans survive
    phone_owner: dict[str, set] = defaultdict(set)
    person_raw = []
    for r in _read(d / "d2_borrower_master.csv", ["borrower_id", "name", "phone_1", "phone_2", "email", "deceased_flag"]):
        phones = {p for p in (r["phone_1"], r["phone_2"]) if p}
        for p in phones:
            phone_owner[p].add(r["borrower_id"])
        person_raw.append((r["borrower_id"], _int(r["deceased_flag"]), bool(phones), bool(r["email"]), phones,
                           mask_name(r["name"]), mask_phone(r["phone_1"] or r["phone_2"])))
    shared = {b for owners in phone_owner.values() if len(owners) > 1 for b in owners}
    person_rows = [(b, dec, int(hp), int(he), int(b in shared), nm, pm) for b, dec, hp, he, _, nm, pm in person_raw]
    del phone_owner, person_raw                                     # the numbers and addresses are gone now

    # ---- D10 consent
    cols10 = ["borrower_id", "consent_call", "consent_sms", "consent_whatsapp", "consent_email", "consent_field_visit",
              "optout_at_call", "optout_at_sms", "optout_at_whatsapp", "optout_at_email", "optout_at_field_visit",
              "dnd_status", "dnd_effective_from", "consent_source", "consent_expiry_date",
              "borrower_requested_window", "suppression_reason", "suppression_from"]
    consent_rows = [tuple(r[c] for c in cols10) for r in _read(d / "d10_consent_dnd.csv", cols10)]

    # ---- D4 contact history (recent only)
    cutoff = (date.fromisoformat(as_of) - timedelta(days=history_days)).isoformat()
    hist_rows, hist_total, hist_unmatched = [], 0, 0
    # D4 carries account_id, not borrower_id; number_or_handle_used (a phone or email) is never read.
    for r in _read(d / "d4_contact_history.csv", ["account_id", "timestamp", "agent_or_agency", "channel", "disposition"]):
        hist_total += 1
        if r["timestamp"][:10] >= cutoff or r["disposition"] == "wrong_number":    # R055 is permanent
            b = acc_to_b.get(r["account_id"])
            if b is None:
                hist_unmatched += 1
                continue
            hist_rows.append((b, r["account_id"], _iso(r["timestamp"]), r["agent_or_agency"], r["channel"],
                              r["disposition"]))

    # ---- D6 promises to pay
    ptp_rows = [(r["ptp_id"], r["account_id"], acc_to_b.get(r["account_id"]), r["promised_date"],
                 float(r["promised_amount"] or 0), r["captured_by"], r["status"])
                for r in _read(d / "d6_ptp_ledger.csv", ["ptp_id", "account_id", "promised_date", "promised_amount",
                                                        "captured_by", "status"])]

    # ---- D7 payments (payer names and handles are not read)
    pay_rows, unmatched = [], 0
    for r in _read(d / "d7_payment_feed.csv", ["txn_id", "account_id", "amount", "timestamp", "status", "reversal_flag"]):
        b = acc_to_b.get(r["account_id"])
        unmatched += b is None
        pay_rows.append((r["txn_id"], r["account_id"], b, _iso(r["timestamp"]), float(r["amount"] or 0),
                         r["status"], _int(r["reversal_flag"])))

    # ---- D12 / D13 policy
    matrix = [(r["agent"], r["agent_type"], r["bucket"], int(r["allowed"] == "Y"), r["allowed_channels"],
               r["allowed_actions"], _int(r["owner_priority_rank"], 99), int(r["borrower_contact"] == "Y"),
               r["override_note"])
              for r in _read(d / "d12_agent_bucket_matrix.csv", ["agent", "agent_type", "bucket", "allowed",
                                                                "allowed_channels", "allowed_actions",
                                                                "owner_priority_rank", "borrower_contact",
                                                                "override_note"])]
    rules = [(r["rule_id"], r["category"], r["bucket"], r["channel"], r["agent"], r["parameter"], r["operator"],
              r["value"], r["severity"], r["status"], r["description"])
             for r in _read(d / "d12_policy_rules.csv", ["rule_id", "category", "bucket", "channel", "agent",
                                                         "parameter", "operator", "value", "severity", "status",
                                                         "description"])]
    capacity = [(r["resource_id"], r["agent_or_agency"], r["channel"], float(r["cost_per_attempt_inr"] or 0),
                 _int(r["daily_attempt_budget"]), float(r["daily_spend_cap_inr"] or 0), r["operating_window"],
                 r["allowed_buckets"])
                for r in _read(d / "d13_channel_cost_capacity.csv",
                               ["resource_id", "agent_or_agency", "channel", "cost_per_attempt_inr",
                                "daily_attempt_budget", "daily_spend_cap_inr", "operating_window", "allowed_buckets"])]

    # ---- write everything in one transaction
    with db.transaction():
        db.executemany("INSERT INTO ds_account VALUES (" + ",".join("?" * 14) + ")", acc_rows)
        db.executemany("INSERT INTO ds_person VALUES (?,?,?,?,?,?,?)", person_rows)
        db.executemany("INSERT INTO ds_consent VALUES (" + ",".join("?" * 18) + ")", consent_rows)
        db.executemany("INSERT INTO ds_history VALUES (?,?,?,?,?,?)", hist_rows)
        db.executemany("INSERT INTO ds_ptp VALUES (?,?,?,?,?,?,?)", ptp_rows)
        db.executemany("INSERT INTO ds_payment VALUES (?,?,?,?,?,?,?)", pay_rows)
        db.executemany("INSERT INTO ds_matrix VALUES (?,?,?,?,?,?,?,?,?)", matrix)
        db.executemany("INSERT INTO ds_rule VALUES (?,?,?,?,?,?,?,?,?,?,?)", rules)
        db.executemany("INSERT INTO ds_capacity VALUES (?,?,?,?,?,?,?,?)", capacity)

    # ---- seed the supervisor's own per-BORROWER tables
    consent = {r[0]: r for r in consent_rows}
    persons = {r[0]: r for r in person_rows}
    seed = []
    for b, accs in by_borrower.items():
        p, c = persons.get(b), consent.get(b)
        chans = []
        if p and c:
            if p[2] and c[3] == "granted":
                chans.append("whatsapp")
            if p[3] and c[4] != "denied":
                chans.append("email")
            if p[2] and c[1] not in ("denied", "revoked"):
                chans.append("voice")
        seed.append((b, max(a[2] for a in accs), any(a[4] for a in accs), chans))
    store.seed(seed)
    open_by_b = defaultdict(list)
    for r in ptp_rows:
        if r[6] == "open" and r[2]:
            open_by_b[r[2]].append({"type": "PTP", "due": r[3], "amount": r[4]})
    for b, commits in open_by_b.items():
        store.set_commitments(b, commits)

    report.update(
        accounts=len(acc_rows), borrowers=len(by_borrower), persons=len(person_rows), consent=len(consent_rows),
        history_loaded=len(hist_rows), history_total=hist_total, history_unmatched=hist_unmatched, ptps=len(ptp_rows),
        ptps_open=sum(1 for r in ptp_rows if r[6] == "open"), payments=len(pay_rows), payments_unmatched=unmatched,
        matrix=len(matrix), rules=len(rules), capacity=len(capacity),
        deceased=sum(r[1] for r in person_rows), shared_phone=sum(r[4] for r in person_rows),
        multi_account_borrowers=sum(1 for a in by_borrower.values() if len(a) > 1),
        contacts_today=sum(1 for r in hist_rows if r[2][:10] == as_of),
        buckets=dict(Counter(a[3] for a in acc_rows)))
    return report


if __name__ == "__main__":      # quick manual check: python -m orchestrator.dataset.loader <folder>
    import sys
    from orchestrator.context import Context
    c = Context.create()
    print(json.dumps(load_dataset(c.db, c.borrowers, sys.argv[1]), indent=2))
