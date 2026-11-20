"""Run the supervisor on the REAL portfolio (D1/D2/D4/D6/D7/D10 + the D12 policy and D13 capacity).

    .venv/bin/python -m scripts.dataset check                       # load it, cross-check the planted cases
    .venv/bin/python -m scripts.dataset run --events 40 --narrate   # a small day, every decision printed live
    .venv/bin/python -m scripts.dataset run --events 800            # a bigger day, with the acceptance report

Then read any borrower's story, and see why an event went the way it did:

    .venv/bin/python -m scripts.trace --find fault   --data-dir data/dataset_run
    .venv/bin/python -m scripts.trace --find blocked --data-dir data/dataset_run
    .venv/bin/python -m scripts.trace BRW01234       --data-dir data/dataset_run

SAFETY: the channel agents are STUBS. Nothing is ever sent. Names, phone numbers and email addresses
in the files are never stored (see orchestrator/dataset/loader.py).
"""
import argparse
import shutil
import time
from collections import Counter
from pathlib import Path

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.config import DATA_DIR
from orchestrator.llm.deepseek import build_advisor
from orchestrator.simulator.audit import audit_history, summarise
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, PUBLIC_KINDS
from orchestrator.simulator.real_day import build_real_fault_script, generate_real_day
from orchestrator.supervisor import Supervisor

DEFAULT = DATA_DIR / "portfolio" / "Multi_Agent_Supervisor_Dataset"


def show_load(rep: dict) -> None:
    print(f"\nDATASET as of {rep['as_of']}: {rep['accounts']} accounts -> {rep['borrowers']} borrowers "
          f"({rep['multi_account_borrowers']} have several accounts)")
    print(f"  consent rows {rep['consent']} | deceased {rep['deceased']} | shared phone {rep['shared_phone']} | "
          f"open promises {rep['ptps_open']}")
    print(f"  contacts already made in the last 14 days {rep['history_loaded']} (today: {rep['contacts_today']})")
    print(f"  policy loaded: {rep['rules']} D12 rules, {rep['matrix']} matrix rows, {rep['capacity']} D13 resources")


def cmd_check(sup: Supervisor, folder: Path) -> None:
    rep = sup.load_dataset(folder)
    show_load(rep)
    print("\nBASELINE: the same policy checks applied to the contacts ALREADY in D4 (the world before a supervisor).")
    print("  (DND is judged strictly here because D4 does not record the purpose of each contact.)")
    for k, v in summarise(audit_history(sup.ctx.db, rep["as_of"])).items():
        print(f"  {v:>7}  {k}")


def cmd_run(sup: Supervisor, folder: Path, a) -> int:
    inj = sup.injector
    rep = sup.load_dataset(folder)
    show_load(rep)
    per = a.planted if a.planted is not None else max(1, min(8, a.events // 50))     # small runs get few traps
    day = generate_real_day(sup.ctx.db, n_primary=a.events, seed=a.seed, planted_dir=folder if per else None,
                            planted_per_group=per)
    kinds = {"none": [], "public": PUBLIC_KINDS, "hidden": HIDDEN_KINDS}[a.faults]
    try:
        inj.script = build_real_fault_script(day, sup.ctx.engine, kinds, a.seed) if kinds else {}
    except ValueError as e:
        print(f"  note: no faults injected ({e}); use a larger --events")
        inj.script = {}
    n = sup.publish_many(day.events)
    print(f"\nRUN: {len(day.events)} events ({n} accepted) | planted traps injected: "
          f"{ {k: len(v) for k, v in day.planted.items()} or 'none' }")
    print(f"     {len(inj.script)} scripted fault calls | LLM advisor {'ON' if sup.ctx.advisor else 'off'} | "
          f"STUB agents: nothing is really sent")
    if a.narrate:
        sup.narrate(verbose=a.verbose)
    t0 = time.perf_counter()
    sup.run_until_empty()
    secs = time.perf_counter() - t0
    report = check_day(sup, inj)

    print(f"\n--- processed in {secs:.1f}s; routing p99 {report['route_p99_ms']} ms (limit 100) ---")
    outcomes = Counter(r["outcome"] for r in sup.ctx.db.query("SELECT outcome FROM event_queue"))
    print("  outcomes:", dict(outcomes))
    for name, c in report["checks"].items():
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {name}: {c['detail']}")
        if c.get("violations"):
            print("         violations:", c["violations"])
    for f in report["checks"].get("all_faults_recovered", {}).get("faults", []):
        print(f"  fault {f['account']}: {f['faults'][0]} -> {f['actions']} contacted={f['contacted']} status={f['status']}")
    print(f"\nLook closer:  .venv/bin/python -m scripts.trace --find blocked --data-dir {a.data_dir}")
    print(f"              .venv/bin/python -m scripts.trace --find fault   --data-dir {a.data_dir}")
    print(f"              .venv/bin/python -m scripts.trace <borrower_id>  --data-dir {a.data_dir}")
    return 0 if report["passed"] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "run"])
    ap.add_argument("--folder", default=str(DEFAULT))
    ap.add_argument("--events", type=int, default=800)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--faults", choices=["none", "public", "hidden"], default="hidden")
    ap.add_argument("--planted", type=int, default=None, help="trap borrowers per group (0 = none); default scales with --events")
    ap.add_argument("--narrate", action="store_true", help="print every decision live (use a small --events)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--data-dir", default=str(DATA_DIR / "dataset_run"))
    a = ap.parse_args()
    folder = Path(a.folder)
    if not folder.exists():
        raise SystemExit(f"dataset folder not found: {folder}\nPut the CSVs there or pass --folder")
    inj = FaultInjector({})
    if a.cmd == "check":
        cmd_check(Supervisor(injector=inj), folder)
        return
    shutil.rmtree(a.data_dir, ignore_errors=True)
    sup = Supervisor(data_dir=a.data_dir, injector=inj, advisor=build_advisor())
    raise SystemExit(cmd_run(sup, folder, a))


if __name__ == "__main__":
    main()
