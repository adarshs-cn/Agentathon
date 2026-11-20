"""PHASE 9 integration test: the portfolio dataset loads into per-BORROWER tables, keeps no
personal data, and the real files match what their planted-case files promise."""
import json
from pathlib import Path

import pytest

from orchestrator.context import Context
from orchestrator.dataset.loader import bucket_of, load_dataset
from tests.dataset_fixture import Mini

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"


def loaded(m: Mini, tmp_path, **kw):
    ctx = Context.create(str(tmp_path / "t.db"))
    report = load_dataset(ctx.db, ctx.borrowers, m.write(tmp_path / "ds"), **kw)
    return ctx, report


# ------------------------------------------------------------------ the mini dataset
def test_bucket_boundaries_follow_the_rbi_sma_mapping():
    assert [bucket_of(d) for d in (0, 1, 30, 31, 60, 61, 90, 91, 360)] == \
           ["0", "1-30", "1-30", "31-60", "31-60", "61-90", "61-90", "90+", "90+"]


def test_borrowers_are_the_unit_and_accounts_roll_up(tmp_path):
    m = Mini()
    m.borrower("T1", dpd=45)
    m.account("T1b", "T1", dpd=120, legal=1)           # a second, legal account for the same borrower
    m.borrower("T2", dpd=5)
    ctx, rep = loaded(m, tmp_path)
    assert (rep["accounts"], rep["borrowers"], rep["multi_account_borrowers"]) == (3, 2, 1)
    b = ctx.borrowers.load("T1")
    assert b["dpd"] == 120 and b["legal_flag"] is True            # the borrower carries the worst account
    assert ctx.borrowers.load("T2")["dpd"] == 5 and ctx.borrowers.load("T2")["legal_flag"] is False
    assert ctx.borrowers.exists("T1") and not ctx.borrowers.exists("T1a")      # accounts are not borrowers


def test_reachable_channels_reflect_consent_and_contact_details(tmp_path):
    m = Mini()
    m.borrower("ALL")
    m.borrower("NOMAIL", email=False)
    m.borrower("NOPHONE", phone=False)
    m.borrower("WAUNKNOWN", consent_whatsapp="unknown")
    m.borrower("CALLDENIED", consent_call="denied")
    ctx, _ = loaded(m, tmp_path)
    ch = {b: ctx.borrowers.load(b)["channels"] for b in ("ALL", "NOMAIL", "NOPHONE", "WAUNKNOWN", "CALLDENIED")}
    assert ch["ALL"] == ["whatsapp", "email", "voice"] and ch["NOMAIL"] == ["whatsapp", "voice"]
    assert ch["NOPHONE"] == ["email"] and ch["WAUNKNOWN"] == ["email", "voice"]
    assert ch["CALLDENIED"] == ["whatsapp", "email"]


def test_open_promises_become_the_borrowers_commitments(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.borrower("T2")
    m.ptp("T1", "2026-11-05", status="open", amount=7000)
    m.ptp("T1", "2026-10-01", status="broken")
    m.ptp("T2", "2026-10-20", status="kept")
    ctx, rep = loaded(m, tmp_path)
    assert ctx.borrowers.load("T1")["commitments"] == [{"type": "PTP", "due": "2026-11-05", "amount": 7000.0}]
    assert ctx.borrowers.load("T2")["commitments"] == [] and rep["ptps_open"] == 1


def test_no_personal_data_is_stored_anywhere(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.borrower("T2", shared_phone="9111111111")
    m.borrower("T3", shared_phone="9111111111")
    m.borrower("T4", phone=False, email=False)
    m.payment("T1a", "2026-10-30 10:00:00")
    ctx, rep = loaded(m, tmp_path)
    ctx.db.conn.execute("PRAGMA wal_checkpoint(FULL)")
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("t.db*"))
    for secret in (b"Person T1", b"t1@example.in", b"9111111111", b"9000000001", b"Someone Private", b"xx***"):
        assert secret not in blob, secret
    p = {r["borrower_id"]: dict(r) for r in ctx.db.query("SELECT * FROM ds_person")}
    assert p["T1"]["has_phone"] == 1 and p["T1"]["has_email"] == 1 and p["T1"]["shared_phone"] == 0
    assert p["T2"]["shared_phone"] == 1 and p["T3"]["shared_phone"] == 1          # the pair share a number
    assert p["T4"]["has_phone"] == 0 and p["T4"]["has_email"] == 0
    assert rep["shared_phone"] == 2


def test_only_recent_history_is_kept_and_timestamps_are_iso(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.contact("T1", "2026-10-31 09:00:00", "reminder_agent", "sms")
    m.contact("T1", "2026-10-20 09:00:00", "negotiation_agent", "call")
    m.contact("T1", "2026-05-01 09:00:00", "legal_agent", "email")               # far outside the window
    ctx, rep = loaded(m, tmp_path)
    rows = [dict(r) for r in ctx.db.query("SELECT * FROM ds_history ORDER BY at")]
    assert [r["at"] for r in rows] == ["2026-10-20T09:00:00", "2026-10-31T09:00:00"]
    assert (rep["history_loaded"], rep["history_total"], rep["contacts_today"]) == (2, 3, 1)


def test_history_is_attached_to_the_borrower_through_the_account_and_keeps_the_disposition(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.account("T1b", "T1", dpd=50)
    m.contact("T1", "2026-10-31 10:00:00", "reminder_agent", "sms", account="T1b", disposition="no_answer")
    m.contact("T1", "2026-10-31 11:00:00", "reminder_agent", "sms", account="GHOST")          # account not in D1
    ctx, rep = loaded(m, tmp_path)
    rows = [dict(r) for r in ctx.db.query("SELECT * FROM ds_history")]
    assert len(rows) == 1 and rows[0]["borrower_id"] == "T1" and rows[0]["account_id"] == "T1b"
    assert rows[0]["disposition"] == "no_answer" and rep["history_unmatched"] == 1
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("t.db*"))
    assert b"9876543210" not in blob                                    # number_or_handle_used is never stored


def test_reloading_replaces_rather_than_duplicates(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.payment("T1a", "2026-10-30 10:00:00")
    ctx, first = loaded(m, tmp_path)
    again = load_dataset(ctx.db, ctx.borrowers, tmp_path / "ds")
    assert {k: v for k, v in again.items()} == {k: v for k, v in first.items()}
    assert ctx.db.one("SELECT COUNT(*) c FROM ds_account")["c"] == 1


def test_a_payment_for_an_unknown_account_is_kept_but_unmatched(tmp_path):
    m = Mini()
    m.borrower("T1")
    m.payment("T1a", "2026-10-30 10:00:00")
    m.payment("GHOST", "2026-10-30 11:00:00")
    ctx, rep = loaded(m, tmp_path)
    assert rep["payments"] == 2 and rep["payments_unmatched"] == 1
    assert ctx.db.one("SELECT borrower_id FROM ds_payment WHERE account_id='GHOST'")["borrower_id"] is None


def test_display_fields_are_masked_and_the_grid_columns_are_kept(tmp_path):
    from orchestrator.dataset.loader import mask_name, mask_phone
    assert mask_name("Deepak Shah") == "D*** S***" and mask_name("") == ""
    assert mask_phone("6197814842") == "XXXXXX4842" and mask_phone("12") == "" and mask_phone("+91 98765-43210") == "XXXXXX3210"
    m = Mini(); m.borrower("T1", dpd=45)
    ctx, _ = loaded(m, tmp_path)
    p = dict(ctx.db.one("SELECT * FROM ds_person WHERE borrower_id='T1'"))
    assert p["name_masked"] == "P*** T***" and p["phone_masked"] == "XXXXXX0001"      # 'Person T1', 9000000001
    a = dict(ctx.db.one("SELECT * FROM ds_account WHERE account_id='T1a'"))
    assert {"product", "city", "branch", "loan_amount", "principal_outstanding"} <= set(a)


def test_the_policy_files_are_loaded_as_data(tmp_path):
    m = Mini()
    m.borrower("T1")
    ctx, rep = loaded(m, tmp_path)
    assert (rep["rules"], rep["matrix"], rep["capacity"]) == (93, 35, 21)
    legal = ctx.db.one("SELECT * FROM ds_matrix WHERE agent='legal_agent' AND bucket='90+'")
    assert legal["rank"] == 1 and "legal_notice" in legal["actions"] and legal["allowed"] == 1
    assert ctx.db.one("SELECT value FROM ds_rule WHERE rule_id='R009'")["value"] == "3"
    assert ctx.db.one("SELECT daily_budget FROM ds_capacity WHERE resource_id='RES002'")["daily_budget"] == 2400


# ------------------------------------------------------------------ the REAL dataset
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present in data/portfolio/")


@pytest.fixture(scope="module")
def real_ctx():
    ctx = Context.create()
    rep = load_dataset(ctx.db, ctx.borrowers, REAL)
    return ctx, rep


def planted(name):
    return json.load(open(REAL / name))


@real
def test_real_dataset_has_the_documented_shape(real_ctx):
    ctx, rep = real_ctx
    assert (rep["accounts"], rep["borrowers"], rep["consent"], rep["persons"]) == (20000, 17000, 17000, 17000)
    assert rep["multi_account_borrowers"] == 2500 and rep["rules"] == 93 and rep["capacity"] == 21
    assert ctx.borrowers.count() == 17000
    # D1's own bucket column agrees with the SMA mapping for every account
    bad = [r["account_id"] for r in ctx.db.query("SELECT account_id, dpd, bucket FROM ds_account")
           if bucket_of(r["dpd"]) != r["bucket"]]
    assert bad == []


@real
def test_real_planted_cases_d1_d2(real_ctx):
    ctx, rep = real_ctx
    d1, d2 = planted("d1_planted_cases.json"), planted("d2_planted_cases.json")
    assert ctx.db.one("SELECT SUM(legal_flag) s FROM ds_account")["s"] == d1["legal_flag_account_count"] == 896
    for b, accs in d1["differing_flag_borrowers"].items():      # mixed legal / non-legal accounts per borrower
        flags = {r["legal_flag"] for r in ctx.db.query("SELECT legal_flag FROM ds_account WHERE borrower_id=?", (b,))}
        assert flags == {0, 1}, b
        assert ctx.borrowers.load(b)["legal_flag"] is True      # ...and the borrower is treated as legal
    deceased = {r["borrower_id"] for r in ctx.db.query("SELECT borrower_id FROM ds_person WHERE deceased=1")}
    assert deceased == set(d2["deceased_borrowers"])
    shared = {r["borrower_id"] for r in ctx.db.query("SELECT borrower_id FROM ds_person WHERE shared_phone=1")}
    assert {b for pair in d2["shared_phone_1_pairs"] for b in pair} <= shared
    nophone = {r["borrower_id"] for r in ctx.db.query("SELECT borrower_id FROM ds_person WHERE has_phone=0")}
    assert set(d2["no_phone_borrowers"]) <= nophone


@real
def test_real_planted_cases_d4_today_and_d6_d7(real_ctx):
    ctx, rep = real_ctx
    today = {r["borrower_id"]: r["n"] for r in ctx.db.query(
        "SELECT borrower_id, COUNT(*) n FROM ds_history WHERE substr(at,1,10)='2026-10-31' GROUP BY borrower_id")}
    d4 = planted("d4_planted_cases.json")["today_contacts"]
    # The planted lists are LOWER bounds: a handful of these borrowers also got an unrelated organic
    # contact today, so they sit one higher. Almost all match exactly.
    for key, n in (("1_contact", 1), ("2_contacts", 2), ("3plus_contacts", 3)):
        counts = [today.get(b, 0) for b in d4[key]]
        assert min(counts) >= n, key
        assert sum(c == n for c in counts) >= 0.95 * len(counts), key
    d6 = planted("d6_planted_cases.json")
    due = {r["ptp_id"] for r in ctx.db.query("SELECT ptp_id FROM ds_ptp WHERE status='open' AND promised_date='2026-10-31'")}
    assert set(d6["due_today"]) <= due
    d7 = planted("d7_planted_cases.json")
    assert d7["reversed_kept_ptp"]["found"] == 60
    assert ctx.db.one("SELECT COUNT(*) c FROM ds_payment WHERE reversal=1")["c"] == 280
