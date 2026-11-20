"""Run one simulated day end to end and print the acceptance report.

    .venv/bin/python -m scripts.run_day --events 1500 --faults hidden

Uses file-backed databases under data/day so you can inspect the tables afterwards
(sqlite3 data/day/orchestrator.db). The DeepSeek advisor is used only if DEEPSEEK_API_KEY is set.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.config import DATA_DIR
from orchestrator.llm.deepseek import build_advisor
from orchestrator.simulator.borrowers import synthetic_borrowers
from orchestrator.simulator.checks import check_day
from orchestrator.simulator.day import generate_day, load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, PUBLIC_KINDS, build_fault_script
from orchestrator.supervisor import Supervisor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--borrowers", type=int, default=20_000)
    ap.add_argument("--events", type=int, default=1500, help="primary events (conflicts, duplicates, bad events are added)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--faults", choices=["public", "hidden"], default="hidden")
    ap.add_argument("--data-dir", default=str(DATA_DIR / "day"))
    ap.add_argument("--narrate", action="store_true", help="print every decision live (use with a small --events)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    d = Path(args.data_dir)
    shutil.rmtree(d, ignore_errors=True)

    rows = synthetic_borrowers(args.borrowers, args.seed)
    day = generate_day(rows, n_primary=args.events, seed=args.seed)
    script = build_fault_script(day, rows, PUBLIC_KINDS if args.faults == "public" else HIDDEN_KINDS)
    inj = FaultInjector(script)
    advisor = build_advisor()
    sup = Supervisor(data_dir=d, injector=inj, advisor=advisor)
    sup.seed_borrowers(rows)
    n = load_day(sup, day)
    print(f"{args.borrowers} borrowers | {len(day.events)} events generated, {n} accepted by the bus "
          f"({len(day.events) - n} duplicates dropped) | {len(script)} scripted fault calls | "
          f"LLM advisor: {'on' if advisor else 'off (rules only)'}")

    if args.narrate:
        sup.narrate(verbose=args.verbose)
    t0 = time.perf_counter()
    processed = sup.run_until_empty()
    secs = time.perf_counter() - t0
    report = check_day(sup, inj)

    print(f"processed {processed} events in {secs:.1f}s ({1000 * secs / max(processed, 1):.1f} ms/event)")
    print(f"routing latency: p99 {report['route_p99_ms']} ms, max {report['route_max_ms']} ms (limit 100 ms)\n")
    for name, c in report["checks"].items():
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {name}: {c['detail']}")
    print("\nfaults injected and how each was handled:")
    for f in report["checks"].get("all_faults_recovered", {}).get("faults", []):
        print(f"  {f['account']}: {f['faults'][0]:<18} -> actions {f['actions']}, "
              f"contacted={f['contacted']}, status={f['status']}")
    print(f"\nbus: {json.dumps(sup.ctx.bus.stats())}   ACCEPTANCE: {'PASSED' if report['passed'] else 'FAILED'}")
    print(f"databases in {d}")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
