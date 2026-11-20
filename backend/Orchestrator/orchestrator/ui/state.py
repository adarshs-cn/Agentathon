"""DemoState: everything the dashboard server needs, built once and rebuilt on reset.

  supervisor   the real supervisor (writes the SQLite database)
  reader       a second, read-only connection to the same database for the dashboard's queries
  runner       the simulation clock that feeds the supervisor the day's events
  audit        the independent policy audit, re-run in the background when new contacts appear
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.bus.event_queue import EventQueue
from orchestrator.dataset.loader import AS_OF
from orchestrator.policy.d12 import D12Policy
from orchestrator.simulator.audit import audit_ours
from orchestrator.simulator.day import load_day
from orchestrator.simulator.faults import HIDDEN_KINDS, PUBLIC_KINDS
from orchestrator.simulator.real_day import build_real_fault_script, generate_real_day
from orchestrator.stores.borrowers import BorrowerStore
from orchestrator.stores.contacts import ContactLog
from orchestrator.stores.db import Database
from orchestrator.stores.decisions import DecisionLog
from orchestrator.supervisor import Supervisor
from orchestrator.ui import views
from orchestrator.ui.events import ui_events_for
from orchestrator.ui import scenario
from orchestrator.ui.monitor import LiveMonitor, setup_pool
from orchestrator.ui.run import RunManager
from orchestrator.ui.runner import SimulationRunner


<<<<<<< Updated upstream
POOL = 15
=======
def _agents_override(inj) -> list | None:
    """None keeps the pure stub trio (default_agents); set MT02_REAL_VOICE=1 (after .env is
    loaded, before this is called) to swap in the real Twilio negotiation agent instead of
    the voice stub. Never on by accident: nothing here calls load_env() itself, so pytest
    runs (which never load the .env file) are unaffected."""
    if os.environ.get("MT02_REAL_VOICE") != "1":
        return None
    from orchestrator.agents.real.negotiation import NegotiationAgent
    from orchestrator.agents.stubs import EmailAgent, WhatsAppAgent
    return [WhatsAppAgent(inj), EmailAgent(inj), NegotiationAgent(inj)]
>>>>>>> Stashed changes


class DemoState:
    def __init__(self, data_dir: str | Path, dataset_dir: str | Path, events: int = 700, seed: int = 5,
                 faults: str = "hidden", advisor=None, mode: str = "scenario", autostart: bool = True):
        self.data_dir, self.dataset_dir = Path(data_dir), Path(dataset_dir)
        self.n_events, self.seed, self.faults, self.advisor = events, seed, faults, advisor
        if mode not in ("scenario", "day", "live"):
            raise ValueError("mode must be 'scenario', 'day' or 'live'")
        self.mode = mode
        self.scenario_rows: list[dict] = []
        self.runs = RunManager(self)
        self.narrator = None                       # set by the server for the Workflow Studio (trace pad); None in tests
        self.lock = threading.RLock()
        self.sup: Supervisor | None = None
        self.audit = {"violations": 0, "checked": 0, "ran": False, "at": 0.0, "detail": []}
        self._audit_marker = -1
        self.runner = SimulationRunner(lambda: self.sup, AS_OF, 6 * 3600 + 55 * 60)
        if not self._reopen():                      # a saved scenario run is picked up again; nothing is rebuilt
            self.build()
        self.monitor = None
        if self.mode == "day":
            self.runner.start()
        elif self.mode == "live":
            self.monitor = LiveMonitor(self)
            if autostart:
                self.monitor.start()
        threading.Thread(target=self._audit_loop, daemon=True, name="audit").start()

    # ---------------------------------------------------------------- build / reset
    def build(self) -> None:
        with self.lock:
            self.runner.control("pause")
            shutil.rmtree(self.data_dir, ignore_errors=True)
            inj = FaultInjector({})
            sup = Supervisor(data_dir=self.data_dir, injector=inj, advisor=self.advisor,
                              agents=_agents_override(inj))
            sup.load_dataset(self.dataset_dir)
            if self.mode == "live":
                pool = setup_pool(sup, AS_OF, self.seed)
                if self.faults != "none" and len(pool) >= 7:                    # two scripted agent faults, first call only
                    inj.script = {(pool[2]["borrower_id"], 1): "CRASH_AFTER_SEND", **{(pool[6]["borrower_id"], n): "LOOP" for n in (1, 2, 3)}}
                self.day = None
                self.runner.position = 86400 - 60
            elif self.mode == "scenario":
                self.scenario_rows = scenario.build(sup, AS_OF, inj)      # the 15 demo events, published, not processed
                self.day = None
                self.runner.position = 86400 - 60                         # "today" is the whole dataset day; no clock runs
            else:
                day = generate_real_day(sup.ctx.db, n_primary=self.n_events, seed=self.seed, planted_dir=self.dataset_dir,
                                        planted_per_group=max(1, min(8, self.n_events // 50)))
                kinds = {"none": [], "public": PUBLIC_KINDS, "hidden": HIDDEN_KINDS}[self.faults]
                try:
                    inj.script = build_real_fault_script(day, sup.ctx.engine, kinds, self.seed) if kinds else {}
                except ValueError:
                    inj.script = {}
                load_day(sup, day)
                first = sup.ctx.bus.next_event_time()
                if first:
                    h, m = int(first[11:13]), int(first[14:16])
                    self.runner.start_seconds = max(0, (h * 60 + m - 5) * 60)
                self.runner.reset_clock()
                self.day = day
            self._attach_reader(sup)

    def _reopen(self) -> bool:
        """Restart safety for the demo: if the previous run's database is on disk, reopen it (events already run, steps,
        messages, checkpoints) instead of rebuilding. Only 'Reset demo' starts from scratch."""
        db_file = self.data_dir / "orchestrator.db"
        if self.mode == "day" or not db_file.exists():
            return False
        probe = Database(db_file, read_only=True)
        try:
            n = probe.one("SELECT COUNT(*) n FROM " + ("monitor_pool" if self.mode == "live" else "demo_event"))["n"]
            ds = probe.one("SELECT COUNT(*) n FROM ds_account")["n"]
        except Exception:  # noqa: BLE001 - an older or damaged file: rebuild
            return False
        finally:
            probe.close()
        if n != (POOL if self.mode == "live" else len(scenario.SPECS)) or ds == 0:
            return False
        with self.lock:
            inj = FaultInjector({})
            sup = Supervisor(data_dir=self.data_dir, injector=inj, advisor=self.advisor,
                              agents=_agents_override(inj))
            sup.ctx.engine = D12Policy(sup.ctx.db, sup.ctx.contacts, sup.ctx.borrowers, sup.ctx.registry, sup.ctx.policy)
            if self.mode == "scenario":
                self.scenario_rows = [dict(r) for r in sup.ctx.db.query("SELECT * FROM demo_event ORDER BY seq")]
                scenario.restore_faults(sup, inj, self.scenario_rows)
            sup.recover_on_start()                    # finishes any event that was mid-run when the process stopped
            self.day = None
            self.runner.position = 86400 - 60
            self._attach_reader(sup)
        return True

    def _attach_reader(self, sup) -> None:
        self.reader = Database(self.data_dir / "orchestrator.db", read_only=True)
        self.rctx = SimpleNamespace(bus=EventQueue(self.reader), decisions=DecisionLog(self.reader),
                                    contacts=ContactLog(self.reader), borrowers=BorrowerStore(self.reader))
        self.engine = D12Policy(self.reader, self.rctx.contacts, self.rctx.borrowers, sup.ctx.registry)
        self.audit = {"violations": 0, "checked": 0, "ran": False, "at": 0.0, "detail": []}
        self._audit_marker = -1
        self.sup = sup

    def reset(self) -> None:
        """Rebuild from scratch. Only the walkthrough's own database is ever reset from the UI."""
        self.build()

    # ---------------------------------------------------------------- time
    def sim_now(self) -> datetime:
        """The time the dashboard's queries are 'as of'. Clamped to 23:59 of the simulated date, so that when the
        day ends, 'today' still means the day that was just simulated (its caps and budgets stay visible)."""
        if self.mode == "live":
            return datetime.now().replace(microsecond=0)
        from orchestrator.ui.runner import DAY
        return datetime.fromisoformat(self.runner.iso(min(self.runner.position, DAY - 60)))

    # ---------------------------------------------------------------- audit (independent re-check of every contact sent)
    def _audit_loop(self) -> None:
        while True:
            time.sleep(1.5)
            try:
                sent = self.reader.one("SELECT COUNT(*) n FROM contact_log WHERE status IN ('SENT','ATTEMPTING')")["n"]
                if sent != self._audit_marker:
                    self._audit_marker = sent
                    viol = audit_ours(self.reader)
                    self.audit = {"violations": len(viol), "checked": sent, "ran": True, "at": time.time(),
                                  "detail": viol[:20]}
            except Exception:  # noqa: BLE001 - the audit must never take the server down
                pass

    # ---------------------------------------------------------------- snapshots for the API
    def overview(self, light: bool = False) -> dict:
        nums = views.overview_numbers(self.reader, self.sup.ctx, self.sup.injector, self.audit)
        out = {**nums, "sim_clock": self.runner.clock() if self.mode == "day" else None,
               "monitor": self.monitor.status() if self.monitor else None, "timeline": views.timeline(self.reader),
               "rules_cited": views.rules_cited(self.reader), "channel_mix": views.channel_mix(self.reader)}
        if not light:
            out["recent_decisions"] = views.recent_events(self.reader, 40)
        return out

    def max_done_seq(self) -> int:
        r = self.reader.one("SELECT COALESCE(MAX(seq),0) m FROM event_queue WHERE status IN ('DONE','FAILED')")
        return r["m"]

    def new_events(self, after_seq: int, limit: int = 30) -> tuple[list[dict], int]:
        rows = self.reader.query("SELECT seq, event_id FROM event_queue WHERE status IN ('DONE','FAILED') AND seq > ? "
                                 "ORDER BY seq LIMIT ?", (after_seq, limit))
        out, last = [], after_seq
        for r in rows:
            drows = [{**dict(x), "data": views._data(x["data"])} for x in self.reader.query(
                "SELECT * FROM decision_log WHERE event_id=? ORDER BY id", (r["event_id"],))]
            out += ui_events_for(drows)
            last = r["seq"]
        return out, last
