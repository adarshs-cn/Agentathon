"""Test the supervisor on a REAL portfolio exported as CSV (D1/D2/D4/D6 or similar).

    # 1. see how your columns were understood, BEFORE running anything
    .venv/bin/python -m scripts.portfolio inspect data/portfolio/*.csv

    # 2. run a day on a sample, narrating every decision live
    .venv/bin/python -m scripts.portfolio run data/portfolio/*.csv --sample 20 --narrate --faults hidden

    # 3. read any account's full trace afterwards
    .venv/bin/python -m scripts.trace <account_id> --data-dir data/portfolio_run

If a column is not recognised, name it:   --map dpd=Days_Overdue --map email=EMAIL_ID
If the files have no channel columns:     --assume-channels whatsapp,email,voice

SAFETY: the channel agents are STUBS. No WhatsApp, email or call is ever made. Only the
account id, DPD, legal flag and which channels are reachable are read; names, phone numbers
and addresses are never stored.
"""
import argparse
import shutil
import time
from pathlib import Path

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.config import DATA_DIR
from orchestrator.llm.deepseek import build_advisor
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import generate_day, load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, PUBLIC_KINDS, build_fault_script
from orchestrator.simulator.portfolio import load_portfolio
from orchestrator.supervisor import Supervisor


def parse_maps(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k.strip()] = v.strip()
    return out


def show_load(load):
    r = load.report
    print(f"\nPORTFOLIO: {r['accounts']} usable accounts")
    for name, f in r["files"].items():
        print(f"  file {name}: {f['rows']} rows; columns understood as {f['mapping']}")
    print(f"  DPD: {r['dpd']}   legal flag set: {r['legal_flag']}")
    print(f"  reachable by channel: {r['channels']}   unreachable on every channel: {r['unreachable']}")
    for w in load.warnings:
        print(f"  WARNING: {w}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "run"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--map", action="append", help="canonical=ColumnName, e.g. dpd=Days_Overdue")
    ap.add_argument("--assume-channels", default="", help="e.g. whatsapp,email,voice")
    ap.add_argument("--sample", type=int, default=200, help="how many borrowers get an event")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--faults", choices=["none", "public", "hidden"], default="hidden")
    ap.add_argument("--clean", action="store_true", help="no injected conflicts, duplicates or bad events")
    ap.add_argument("--narrate", action="store_true", help="print every decision live")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--data-dir", default=str(DATA_DIR / "portfolio_run"))
    a = ap.parse_args()

    assume = [c for c in a.assume_channels.split(",") if c]
    load = load_portfolio(a.files, parse_maps(a.map), assume or None)
    show_load(load)
    if a.cmd == "inspect":
        return
    if not load.rows:
        raise SystemExit("nothing to run")
    if not any(r[3] for r in load.rows):
        raise SystemExit("every borrower is unreachable on every channel: fix the channel mapping first")

    rows = load.rows
    kw = dict(conflict_rate=0, duplicate_rate=0, bad_rate=0) if a.clean else {}
    day = generate_day(rows, n_primary=a.sample, seed=a.seed, **kw)
    try:
        script = {} if a.faults == "none" else build_fault_script(
            day, rows, PUBLIC_KINDS if a.faults == "public" else HIDDEN_KINDS)
    except ValueError as e:
        print(f"  note: no faults injected ({e}); try a larger --sample or --faults none")
        script = {}
    inj = FaultInjector(script)
    advisor = build_advisor()

    d = Path(a.data_dir)
    shutil.rmtree(d, ignore_errors=True)
    sup = Supervisor(data_dir=d, injector=inj, advisor=advisor)
    sup.seed_borrowers(rows)
    n = load_day(sup, day)
    print(f"\nRUN: {len(day.events)} events ({n} accepted), {len(script)} scripted fault calls, "
          f"LLM advisor {'ON' if advisor else 'off'}.  STUB agents: nothing is really sent.")
    if a.narrate:
        sup.narrate(verbose=a.verbose)
    t0 = time.perf_counter()
    sup.run_until_empty()
    secs = time.perf_counter() - t0

    report = check_day(sup, inj)
    print(f"\n--- processed in {secs:.1f}s; routing p99 {report['route_p99_ms']} ms (limit 100) ---")
    for name, c in report["checks"].items():
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {name}: {c['detail']}")
    for f in report["checks"].get("all_faults_recovered", {}).get("faults", []):
        print(f"  fault {f['account']}: {f['faults'][0]} -> {f['actions']} contacted={f['contacted']} status={f['status']}")
    print(f"  outcomes: {sup.ctx.bus.stats()}")
    print(f"\nLook closer:  .venv/bin/python -m scripts.trace --find fault --data-dir {d}")
    print(f"              .venv/bin/python -m scripts.trace <account_id> --data-dir {d}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
