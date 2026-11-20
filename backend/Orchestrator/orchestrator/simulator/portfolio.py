"""Load a REAL portfolio from CSV exports (e.g. D1, D2, D4, D6) into the supervisor's borrower table.

What it reads, per borrower, and nothing else:
    account id, days past due, legal flag, and which channels the borrower can be reached on.
Names, phone numbers and email addresses are never stored: for a channel column such as
"Email" or "Mobile", only whether a value is PRESENT is kept (a boolean).

Several files can be given; they are joined on the account id, so the facts may be spread
across tables. Column names are matched flexibly (see ALIASES) and can be forced with
`overrides`, e.g. {"dpd": "Days_Overdue", "whatsapp": "WA_OptIn"}.

Nothing here sends anything: the supervisor still talks to STUB channel agents.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ALIASES = {
    "account_id": ["account_id", "accountid", "account", "account_no", "account_number", "acc_no", "loan_id",
                   "loan_account_number", "loan_no", "lan", "customer_id", "cust_id", "id"],
    "dpd": ["dpd", "days_past_due", "dayspastdue", "current_dpd", "dpd_days", "overdue_days", "days_overdue"],
    "legal": ["legal_flag", "legal", "is_legal", "in_legal", "legal_status", "legal_case", "legal_stage"],
    "channels": ["channels", "reachable_channels", "contact_channels"],
    "whatsapp": ["whatsapp", "has_whatsapp", "whatsapp_opt_in", "whatsapp_consent", "wa_enabled", "whatsapp_flag",
                 "whatsapp_number"],
    "email": ["email", "has_email", "email_opt_in", "email_consent", "email_valid", "email_flag", "email_id"],
    "voice": ["voice", "has_voice", "phone", "has_phone", "mobile", "mobile_number", "phone_number",
              "voice_opt_in", "call_consent", "ivr_enabled"],
}
CHANNEL_KEYS = ("whatsapp", "email", "voice")
FALSY = {"", "0", "n", "no", "false", "f", "none", "null", "nan", "na", "n/a", "-", "nil", "dnd"}
LEGAL_TRUE = {"1", "y", "yes", "true", "t", "legal", "in_legal", "in legal"}


def _norm(header: str) -> str:
    return re.sub(r"[\s\-\.]+", "_", header.strip().lower())


def _present(v) -> bool:
    """A channel value counts as 'reachable' if something non-empty is there (a number, an address, Y)."""
    return str(v).strip().lower() not in FALSY


def _channels_from_text(v: str) -> set:
    return {c for c in re.split(r"[,\|;/ ]+", str(v).strip().lower()) if c in CHANNEL_KEYS}


def detect_columns(columns: list[str], overrides: dict | None = None) -> dict:
    """canonical name -> original column header."""
    by_norm = {_norm(c): c for c in columns}
    found: dict = {}
    for canon, aliases in ALIASES.items():
        forced = (overrides or {}).get(canon)
        if forced:
            if _norm(forced) in by_norm:
                found[canon] = by_norm[_norm(forced)]
            continue
        for a in aliases:
            if a in by_norm:
                found[canon] = by_norm[a]
                break
    return found


@dataclass
class PortfolioLoad:
    rows: list[tuple] = field(default_factory=list)        # (account_id, dpd, legal_flag, channels)
    warnings: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def _open_csv(path: Path):
    f = open(path, newline="", encoding="utf-8-sig", errors="replace")
    sample = f.read(4096)
    f.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return f, csv.DictReader(f, dialect=dialect)


def load_portfolio(paths, overrides: dict | None = None, assume_channels: list | None = None) -> PortfolioLoad:
    out = PortfolioLoad()
    recs: dict[str, dict] = {}
    files_report, dup_rows, bad_dpd, conflicts = {}, 0, 0, 0

    for p in map(Path, paths):
        f, rd = _open_csv(p)
        with f:
            mapping = detect_columns(rd.fieldnames or [], overrides)
            files_report[p.name] = {"columns": len(rd.fieldnames or []),
                                    "mapping": {k: v for k, v in mapping.items()}, "rows": 0}
            if "account_id" not in mapping:
                out.warnings.append(f"{p.name}: no account-id column found among {rd.fieldnames}; "
                                    f"use overrides={{'account_id': '<column>'}}")
                continue
            seen_in_file = set()
            for row in rd:
                acc = str(row.get(mapping["account_id"], "")).strip()
                if not acc:
                    continue
                files_report[p.name]["rows"] += 1
                if acc in seen_in_file:
                    dup_rows += 1
                    continue
                seen_in_file.add(acc)
                rec = recs.setdefault(acc, {"dpd": None, "legal": False, "channels": set(), "chan_info": False})
                if "dpd" in mapping:
                    raw = str(row.get(mapping["dpd"], "")).strip()
                    try:
                        dpd = int(float(raw)) if raw else None
                    except ValueError:
                        dpd, bad_dpd = None, bad_dpd + 1
                    if dpd is not None:
                        if rec["dpd"] is not None and rec["dpd"] != dpd:
                            conflicts += 1
                        rec["dpd"] = rec["dpd"] if rec["dpd"] is not None else max(dpd, 0)
                if "legal" in mapping:
                    rec["legal"] |= str(row.get(mapping["legal"], "")).strip().lower() in LEGAL_TRUE
                if "channels" in mapping:
                    rec["chan_info"] = True
                    rec["channels"] |= _channels_from_text(row.get(mapping["channels"], ""))
                for ch in CHANNEL_KEYS:
                    if ch in mapping:
                        rec["chan_info"] = True
                        if _present(row.get(mapping[ch], "")):
                            rec["channels"].add(ch)

    any_chan_info = any(r["chan_info"] for r in recs.values())
    no_dpd = 0
    for acc, r in recs.items():
        if r["dpd"] is None:
            no_dpd += 1
            continue
        chans = sorted(r["channels"], key=CHANNEL_KEYS.index) if r["chan_info"] else list(assume_channels or [])
        out.rows.append((acc, r["dpd"], r["legal"], chans))

    # ---- warnings the reader must see before trusting a run
    if not recs:
        out.warnings.append("no borrowers found")
    if recs and not any_chan_info and not assume_channels:
        out.warnings.append("NO CHANNEL INFORMATION found: every borrower would be unreachable. Map the channel "
                            "columns (overrides) or pass assume_channels to test with an assumed reachability.")
    if recs and not any_chan_info and assume_channels:
        out.warnings.append(f"no channel columns in the data: assuming EVERY borrower is reachable on {assume_channels}")
    if not any("legal" in f["mapping"] for f in files_report.values()):
        out.warnings.append("no legal-flag column found: nobody will be routed to Legal by flag")
    if no_dpd:
        out.warnings.append(f"{no_dpd} accounts skipped: no usable DPD")
    if bad_dpd:
        out.warnings.append(f"{bad_dpd} rows had a non-numeric DPD")
    if dup_rows:
        out.warnings.append(f"{dup_rows} duplicate account rows ignored (first one kept)")
    if conflicts:
        out.warnings.append(f"{conflicts} accounts had different DPD values across files (first one kept)")

    dpds = [r[1] for r in out.rows]
    out.report = {
        "accounts": len(out.rows), "files": files_report,
        "dpd": {"<30": sum(d < 30 for d in dpds), "30-89": sum(30 <= d < 90 for d in dpds), "90+": sum(d >= 90 for d in dpds)},
        "legal_flag": sum(1 for r in out.rows if r[2]),
        "channels": {c: sum(1 for r in out.rows if c in r[3]) for c in CHANNEL_KEYS},
        "unreachable": sum(1 for r in out.rows if not r[3]),
    }
    return out
