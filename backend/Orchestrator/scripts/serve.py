"""Start the supervisor API.

    .venv/bin/python -m scripts.serve            # http://127.0.0.1:8000/docs

State persists in data/service. On the first start it is seeded with synthetic borrowers
(a stand-in for D1/D2/D4/D6). The supervisor recovers any in-flight events on startup.
"""
import argparse

import uvicorn

from orchestrator.api.app import create_app
from orchestrator.config import DATA_DIR
from orchestrator.llm.deepseek import build_advisor
from orchestrator.simulator.borrowers import synthetic_borrowers
from orchestrator.supervisor import Supervisor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--borrowers", type=int, default=20_000)
    args = ap.parse_args()

    sup = Supervisor(data_dir=DATA_DIR / "service", advisor=build_advisor())
    if sup.ctx.borrowers.count() == 0:
        sup.seed_borrowers(synthetic_borrowers(args.borrowers))
    print("restart recovery:", sup.recover_on_start())
    uvicorn.run(create_app(sup), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
