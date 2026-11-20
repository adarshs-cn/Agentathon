"""PHASE 8 integration test: nothing is a black box. The trace shows the agent's request and
response, the narrator prints reasoning live, and a real portfolio (CSV exports) can be
loaded and run end to end."""
import csv

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import generate_day, load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, build_fault_script
from orchestrator.simulator.portfolio import detect_columns, load_portfolio
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.render import find_events, render_trace
from orchestrator.tracing.trace import account_trace
from tests.helpers import make_event


def sup_with(script=None):
    sup = Supervisor(injector=FaultInjector(script or {}))
    sup.seed_borrowers(SAMPLE_BORROWERS)
    return sup


# ------------------------------------------------------------------ the trace shows what the agent saw and said
def test_trace_records_the_exact_request_and_response_of_the_agent():
    sup = sup_with()
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    step = next(r for r in sup.ctx.decisions.for_event("e1") if r["node"] == "whatsapp")
    d = step["data"]
    assert d["request"] == {"account_id": "B1", "purpose": "reminder", "template": "wa_template/reminder_v1",
                            "idempotency_key": "B1|2026-11-20", "event_id": "e1", "time": "2026-11-20T09:00:00",
                            "role": "", "action": ""}
    assert d["response"]["status"] == "DONE" and d["response"]["provider_ref"].startswith("whatsapp-")
    assert d["elapsed_ms"] >= 0


def test_a_crash_is_recorded_with_the_error_and_the_request_that_caused_it():
    sup = sup_with({("B1", 1): "CRASH_AFTER_SEND"})
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    d = next(r for r in sup.ctx.decisions.for_event("e1") if r["node"] == "whatsapp")["data"]
    assert "died after sending" in d["error"] and d["request"]["idempotency_key"] == "B1|2026-11-20"
    garbage = sup_with({("B2", 1): "MALFORMED"})
    garbage.publish(make_event("e2", account_id="B2"))
    garbage.run_until_empty()
    first = next(r for r in garbage.ctx.decisions.for_event("e2") if r["node"] == "whatsapp")["data"]
    assert first["response"] == {"oops": "garbage"}                       # the junk the agent returned is preserved


def test_rendered_trace_reads_like_a_story():
    sup = sup_with({("B1", 1): "CRASH_AFTER_SEND"})
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    text = render_trace(account_trace(sup.ctx, "B1", sup.graph))
    for expected in ("ACCOUNT B1", "EVENT e1", "request  :", "error    :", "provider says SENT; decided by rules",
                     "decision : purpose=reminder agent=whatsapp", "never call the agent again", "close_event"):
        assert expected in text, expected
    assert "trace complete: True" in text and "contact: 2026-11-20 via whatsapp (reminder) -> SENT" in text


def test_find_events_picks_out_the_interesting_cases():
    sup = sup_with({("B2", 1): "CRASH_BEFORE_SEND"})
    sup.publish_many([make_event("e1", account_id="B1"), make_event("e2", account_id="B2"),
                      make_event("e3", type="CONTACT_REQUESTED", account_id="B1", time="2026-11-20T10:00:00"),
                      make_event("e4", account_id="B10"), make_event("e5", account_id="NOPE")])
    sup.run_until_empty()
    kinds = {k: [r["event_id"] for r in find_events(sup.ctx, k)] for k in
             ("fault", "blocked", "suppressed", "rejected", "contacted")}
    assert kinds == {"fault": ["e2"], "blocked": ["e3"], "suppressed": ["e4"], "rejected": ["e5"],
                     "contacted": ["e1", "e2"]}


# ------------------------------------------------------------------ the narrator
def test_the_narrator_prints_the_reasoning_live_in_order():
    lines = []
    sup = sup_with({("B2", 1): "CRASH_AFTER_SEND"})
    sup.narrate(out=lines.append)
    sup.publish(make_event("e1", account_id="B2"))
    sup.run_until_empty()
    text = "\n".join(lines)
    assert "== EVENT e1  DUE_SOON  account=B2" in text
    nodes = ("validate_event", "load_borrower", "guardrails", "route", "assign", "whatsapp", "validate_output",
             "monitor", "recover", "commit", "release", "close_event")
    order = [text.index(f"\n  {n:<16} ") for n in nodes]            # match the node column, not stray words
    assert order == sorted(order)
    assert "request  :" in text and "provider says SENT" in text


def test_a_broken_narrator_cannot_break_the_supervisor():
    sup = sup_with()
    sup.ctx.decisions.listeners.append(lambda row: 1 / 0)
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    assert sup.ctx.bus.get("e1")["outcome"] == "CONTACTED"


# ------------------------------------------------------------------ a real portfolio, as CSV exports
def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def test_columns_are_recognised_flexibly_and_can_be_forced():
    cols = ["Loan Account Number", "Days Past Due", "Legal Status", "Email ID", "Mobile Number", "WhatsApp Opt In"]
    assert detect_columns(cols) == {"account_id": "Loan Account Number", "dpd": "Days Past Due", "legal": "Legal Status",
                                    "email": "Email ID", "voice": "Mobile Number", "whatsapp": "WhatsApp Opt In"}
    assert detect_columns(["X", "Overdue"], {"account_id": "x", "dpd": "overdue"}) == {"account_id": "X", "dpd": "Overdue"}


def test_tables_are_joined_on_account_id_and_no_pii_is_kept(tmp_path):
    d1 = write_csv(tmp_path / "d1.csv", ["LAN", "DPD", "Legal Status", "Customer Name"],
                   [["L1", "12", "No", "Asha Rao"], ["L2", "45", "Y", "Ravi K"], ["L3", "95", "No", "Meera"],
                    ["L3", "99", "No", "Meera again"], ["L4", "abc", "No", "Bad"], ["", "5", "No", "NoId"]])
    d2 = write_csv(tmp_path / "d2.csv", ["LAN", "Email", "Mobile", "WhatsApp Opt In"],
                   [["L1", "asha@example.com", "9876500001", "Y"], ["L2", "", "9876500002", "N"],
                    ["L3", "meera@example.com", "", "0"], ["L9", "x@y.z", "1", "Y"]])
    load = load_portfolio([d1, d2])
    assert sorted(load.rows) == [("L1", 12, False, ["whatsapp", "email", "voice"]),
                                 ("L2", 45, True, ["voice"]),
                                 ("L3", 95, False, ["email"])]
    assert load.report["accounts"] == 3 and load.report["dpd"] == {"<30": 1, "30-89": 1, "90+": 1}
    assert load.report["legal_flag"] == 1 and load.report["unreachable"] == 0
    joined = " | ".join(load.warnings)
    assert "duplicate" in joined and "non-numeric DPD" in joined and "no usable DPD" in joined   # L9 has no DPD
    # names, emails and phone numbers appear nowhere in what we keep
    blob = repr(load.rows) + repr(load.report)
    for secret in ("Asha", "asha@example.com", "9876500001", "Ravi"):
        assert secret not in blob


def test_missing_channel_data_is_a_loud_warning_not_a_silent_empty_run(tmp_path):
    f = write_csv(tmp_path / "a.csv", ["account_id", "dpd"], [["A", 5], ["B", 50]])
    load = load_portfolio([f])
    assert load.report["unreachable"] == 2 and any("NO CHANNEL INFORMATION" in w for w in load.warnings)
    assumed = load_portfolio([f], assume_channels=["whatsapp", "email"])
    assert assumed.report["unreachable"] == 0 and any("assuming EVERY borrower" in w for w in assumed.warnings)
    assert any("no legal-flag column" in w for w in assumed.warnings)


def test_a_file_without_an_account_column_is_reported(tmp_path):
    f = write_csv(tmp_path / "a.csv", ["foo", "bar"], [[1, 2]])
    load = load_portfolio([f])
    assert load.rows == [] and any("no account-id column" in w for w in load.warnings)


def test_a_loaded_portfolio_runs_a_full_day_and_passes_every_check(tmp_path):
    import random
    rng = random.Random(3)
    d1 = write_csv(tmp_path / "loans.csv", ["Loan No", "DPD", "Legal"],
                   [[f"LN{i:04d}", rng.choice([0, 3, 12, 29, 31, 55, 88, 92, 150]), "Y" if rng.random() < 0.02 else "N"]
                    for i in range(400)])
    d2 = write_csv(tmp_path / "contact.csv", ["Loan No", "Email", "Phone", "WhatsApp"],
                   [[f"LN{i:04d}", "a@b.c" if rng.random() < 0.7 else "", "9" if rng.random() < 0.8 else "",
                     "Y" if rng.random() < 0.6 else "N"] for i in range(400)])
    load = load_portfolio([d1, d2])
    assert load.report["accounts"] == 400
    day = generate_day(load.rows, n_primary=150, seed=2)
    inj = FaultInjector(build_fault_script(day, load.rows, HIDDEN_KINDS))
    sup = Supervisor(injector=inj)
    sup.seed_borrowers(load.rows)
    load_day(sup, day)
    sup.run_until_empty()
    report = check_day(sup, inj)
    assert report["passed"], {k: v for k, v in report["checks"].items() if not v["ok"]}
    assert len(inj.faulted_accounts()) == 5
