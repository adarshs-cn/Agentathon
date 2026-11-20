"""A tiny, controllable dataset in the real file format, for precise tests.

    m = Mini()
    m.borrower("T1", dpd=45, whatsapp="granted")           # one account T1a
    m.account("T1b", "T1", dpd=10, legal=1)                 # a second account for the same borrower
    m.contact("T1", "2026-10-31 09:00:00", "reminder_agent", "sms")
    folder = m.write(tmp_path)

The real D12/D13 policy files are used as they are (copied into tests/fixtures/policy).
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

POLICY = Path(__file__).parent / "fixtures" / "policy"
AS_OF = "2026-10-31"

D1 = ["account_id", "lender_id", "borrower_id", "dpd", "bucket", "legal_flag", "settlement_flag",
      "restructure_flag", "emi", "total_dues"]
D2 = ["borrower_id", "name", "phone_1", "phone_2", "email", "deceased_flag"]
D10 = ["borrower_id", "consent_call", "consent_sms", "consent_whatsapp", "consent_email", "consent_field_visit",
       "optout_at_call", "optout_at_sms", "optout_at_whatsapp", "optout_at_email", "optout_at_field_visit",
       "dnd_status", "dnd_effective_from", "consent_source", "consent_expiry_date", "borrower_requested_window",
       "suppression_reason", "suppression_from"]
D4 = ["contact_id", "account_id", "channel", "number_or_handle_used", "timestamp", "template_id",
      "agent_or_agency", "disposition", "duration"]
D6 = ["ptp_id", "account_id", "promised_date", "promised_amount", "channel", "captured_by", "status"]
D7 = ["txn_id", "account_id", "source", "amount", "timestamp", "payer_name", "masked_payer_handle",
      "reference_text", "status", "reversal_flag"]


def bucket(dpd: int) -> str:
    return "0" if dpd <= 0 else "1-30" if dpd <= 30 else "31-60" if dpd <= 60 else "61-90" if dpd <= 90 else "90+"


class Mini:
    def __init__(self):
        self.d1, self.d2, self.d10, self.d4, self.d6, self.d7 = [], [], [], [], [], []
        self._n = {"phone": 9000000000, "c": 0, "p": 0, "t": 0}

    def account(self, account_id, borrower_id, dpd=5, legal=0, settlement=0, restructure=0):
        self.d1.append({"account_id": account_id, "lender_id": "L01", "borrower_id": borrower_id, "dpd": dpd,
                        "bucket": bucket(dpd), "legal_flag": legal, "settlement_flag": settlement,
                        "restructure_flag": restructure, "emi": 1000, "total_dues": 5000})

    def borrower(self, b, dpd=5, legal=0, settlement=0, restructure=0, phone=True, email=True, deceased=0,
                 shared_phone=None, **consent):
        """Adds the borrower, one account '<b>a', their D2 row and a fully-consenting D10 row (override via kwargs)."""
        self.account(f"{b}a", b, dpd, legal, settlement, restructure)
        self._n["phone"] += 1
        number = shared_phone or (str(self._n["phone"]) if phone else "")
        self.d2.append({"borrower_id": b, "name": f"Person {b}", "phone_1": number, "phone_2": "",
                        "email": f"{b.lower()}@example.in" if email else "", "deceased_flag": deceased})
        row = {"borrower_id": b, "consent_call": "granted", "consent_sms": "granted", "consent_whatsapp": "granted",
               "consent_email": "granted", "consent_field_visit": "granted", "dnd_status": "none",
               "consent_source": "loan_application", "suppression_reason": "none"}
        row.update(consent)
        self.d10.append(row)

    def contact(self, b, ts, agent="reminder_agent", channel="sms", account=None, disposition="delivered"):
        self._n["c"] += 1
        self.d4.append({"contact_id": f"C{self._n['c']:07d}", "account_id": account or f"{b}a", "channel": channel,
                        "number_or_handle_used": "9876543210", "timestamp": ts, "template_id": "T0001",
                        "agent_or_agency": agent, "disposition": disposition, "duration": 0})

    def ptp(self, b, promised_date, status="open", amount=5000, captured_by="negotiation_agent"):
        self._n["p"] += 1
        self.d6.append({"ptp_id": f"P{self._n['p']:07d}", "account_id": f"{b}a", "promised_date": promised_date,
                        "promised_amount": amount, "channel": "call", "captured_by": captured_by, "status": status})

    def payment(self, account, ts, amount=1000, status="success", reversal=0):
        self._n["t"] += 1
        self.d7.append({"txn_id": f"T{self._n['t']:07d}", "account_id": account, "source": "UPI", "amount": amount,
                        "timestamp": ts, "payer_name": "Someone Private", "masked_payer_handle": "xx***",
                        "reference_text": "", "status": status, "reversal_flag": reversal})

    def write(self, folder) -> Path:
        d = Path(folder)
        d.mkdir(parents=True, exist_ok=True)
        for name, cols, rows in (("d1_account_master.csv", D1, self.d1), ("d2_borrower_master.csv", D2, self.d2),
                                 ("d10_consent_dnd.csv", D10, self.d10), ("d4_contact_history.csv", D4, self.d4),
                                 ("d6_ptp_ledger.csv", D6, self.d6), ("d7_payment_feed.csv", D7, self.d7)):
            with open(d / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        for p in POLICY.glob("*.csv"):
            shutil.copy(p, d / p.name)
        return d
