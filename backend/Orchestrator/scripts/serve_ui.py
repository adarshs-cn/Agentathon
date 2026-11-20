"""Start the dashboard API on the real portfolio (the React app in ../../frontend talks to this).

    .venv/bin/python -m scripts.serve_ui                     # http://localhost:8001
    .venv/bin/python -m scripts.serve_ui --events 400 --faults hidden --autoplay

The day starts PAUSED at just before the first event; press play in the UI (or --autoplay). Data lives in
data/ui/orchestrator.db and is rebuilt whenever you press reset. Nothing is ever sent: the channel agents are stubs.
"""
import argparse
import os
from pathlib import Path

import uvicorn

from orchestrator.config import DATA_DIR, load_env
from orchestrator.llm.deepseek import build_advisor
from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.state import DemoState

DEFAULT = DATA_DIR / "portfolio" / "Multi_Agent_Supervisor_Dataset"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MT02_PORT", 8001)))
    ap.add_argument("--dataset", default=os.environ.get("MT02_DATASET", str(DEFAULT)))
    ap.add_argument("--events", type=int, default=int(os.environ.get("MT02_EVENTS", 700)))
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--faults", choices=["none", "public", "hidden"], default=os.environ.get("MT02_FAULTS", "hidden"))
    ap.add_argument("--data-dir", default=str(DATA_DIR / "ui"))
    ap.add_argument("--mode", choices=["live", "scenario", "day"], default=os.environ.get("MT02_MODE", "live"),
                    help="live (default): a continuous monitor over a pool of real borrowers inside the contact window, plus the "
                         "walkthrough on its own separate database; scenario: walkthrough only; day: a simulated day on a clock")
    ap.add_argument("--autoplay", action="store_true")
    ap.add_argument("--speed", type=int, default=60, choices=[1, 60, 300, 900], help="starting speed of the sim clock")
    a = ap.parse_args()
    load_env()
    if not Path(a.dataset).exists():
        raise SystemExit(f"dataset folder not found: {a.dataset}")
    advisor = build_advisor()
    print(f"loading the dataset and building the day ({a.events} events, faults={a.faults}, LLM advisor "
          f"{'on' if advisor else 'off'}) ...")
    if a.mode == "live":
        demo = DemoState(Path(a.data_dir).parent / "demo", a.dataset, a.events, a.seed, "none", advisor, mode="scenario")
        state = DemoState(Path(a.data_dir).parent / "live", a.dataset, a.events, a.seed, a.faults, advisor, mode="live")
        print(f"monitor: {state.monitor.status()['label']} (window {state.monitor.window[0] // 60:02d}:00-{state.monitor.window[1] // 60:02d}:00), "
              f"pool of {state.monitor.status()['pool_size']} borrowers")
    else:
        state = demo = DemoState(a.data_dir, a.dataset, a.events, a.seed, a.faults, advisor, mode=a.mode)
    demo.runner.control("speed", {"speed": a.speed})
    if a.autoplay and a.mode == "day":
        state.runner.control("play")
    print(f"ready: http://{a.host}:{a.port}/api/overview   (frontend: cd ../../frontend && npm run dev)")
    uvicorn.run(create_dashboard_app(state, demo), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
