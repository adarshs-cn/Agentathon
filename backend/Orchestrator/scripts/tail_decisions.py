"""Live-tail the decision_log for debugging (e.g. why a channel agent keeps faulting).

    python3 -m scripts.tail_decisions                       # tails data/live/orchestrator.db, every node
    python3 -m scripts.tail_decisions --node email           # only email-channel rows
    python3 -m scripts.tail_decisions --db data/demo/orchestrator.db --node email

decision_log is a SQLite table, not a flat file, so this polls for new rows (by id) instead
of a real tail -f. Read-only: opens the db exactly like the dashboard's reader connection.
"""
import argparse
import sqlite3
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/live/orchestrator.db")
    ap.add_argument("--node", default=None, help="filter to one node, e.g. email, voice, whatsapp, validate_output")
    ap.add_argument("--contains", default=None, help="filter to rows whose text contains this substring")
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()

    db_path = Path(a.db)
    if not db_path.exists():
        raise SystemExit(f"no such database: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    last_id = con.execute("SELECT COALESCE(MAX(id), 0) m FROM decision_log").fetchone()["m"]
    print(f"tailing {db_path} from id={last_id} (node={a.node or 'any'}, contains={a.contains or 'any'}) ...")
    while True:
        q = "SELECT * FROM decision_log WHERE id > ?"
        params = [last_id]
        if a.node:
            q += " AND node = ?"
            params.append(a.node)
        if a.contains:
            q += " AND text LIKE ?"
            params.append(f"%{a.contains}%")
        q += " ORDER BY id"
        rows = con.execute(q, params).fetchall()
        for r in rows:
            last_id = r["id"]
            print(f"[{r['ts']}] {r['node']:<16} {r['account_id']:<12} {r['text']}")
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
