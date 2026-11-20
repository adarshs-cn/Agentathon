"""Read the full trace of any account from a finished run. Read-only.

    .venv/bin/python -m scripts.trace A00017                      # the story of one account
    .venv/bin/python -m scripts.trace A00017 -v                   # plus the raw data behind every line
    .venv/bin/python -m scripts.trace --find fault                # which accounts had an agent fault?
    .venv/bin/python -m scripts.trace --find blocked --limit 5    # blocked / suppressed / rejected / escalated / contacted
    .venv/bin/python -m scripts.trace A00017 --json               # machine-readable

--data-dir defaults to data/day (run_day) ; use data/portfolio_run for scripts.portfolio.
"""
import argparse
import json

from orchestrator.config import DATA_DIR
from orchestrator.context import Context
from orchestrator.tracing.render import KINDS, find_events, render_trace
from orchestrator.tracing.trace import account_trace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("account", nargs="?")
    ap.add_argument("--data-dir", default=str(DATA_DIR / "day"))
    ap.add_argument("--find", choices=KINDS)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ctx = Context.create(f"{a.data_dir}/orchestrator.db")
    if a.find:
        for r in find_events(ctx, a.find, a.limit):
            print(f"{r['account_id'] or '-':<12} {r['event_id'] or ''}")
        return
    if not a.account:
        ap.error("give an account id, or --find <kind>")
    if not ctx.borrowers.exists(a.account):
        raise SystemExit(f"unknown account {a.account}")
    t = account_trace(ctx, a.account)
    print(json.dumps(t, indent=2, default=str) if a.json else render_trace(t, a.verbose))


if __name__ == "__main__":
    main()
