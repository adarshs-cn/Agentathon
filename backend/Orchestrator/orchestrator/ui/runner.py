"""The simulation clock: releases the day's events as simulated time passes.

The dashboard has a play/pause button and speeds of 1x, 60x, 300x and 900x. Speed is simulated
seconds per real second, so at 900x a 14-hour working day takes about a minute. The runner is a
background thread: every tick it advances the sim clock by (real elapsed x speed) and asks the
supervisor to process every event whose time has arrived. Nothing is faked: the same graph runs,
the same rows are written.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

DAY = 86400
SPEEDS = (1, 60, 300, 900)


class SimulationRunner(threading.Thread):
    def __init__(self, get_supervisor, date: str, start_seconds: float, tick: float = 0.2):
        super().__init__(daemon=True, name="sim-runner")
        self._sup = get_supervisor
        self.date, self.start_seconds, self.tick = date, float(start_seconds), tick
        self.position = float(start_seconds)
        self.status, self.speed = "paused", 60
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self.error: str | None = None

    # ---- the clock
    def iso(self, position: float | None = None) -> str:
        p = self.position if position is None else position
        return (datetime.fromisoformat(self.date) + timedelta(seconds=p)).replace(microsecond=0).isoformat()

    def clock(self) -> dict:
        with self._lock:
            return {"status": self.status, "sim_time": self.iso() + "Z", "speed": self.speed,
                    "position_seconds": round(self.position, 1), "day_length_seconds": DAY, "date": self.date,
                    "finished": self.position >= DAY, "start_seconds": self.start_seconds}

    def control(self, action: str, body: dict | None = None) -> dict:
        body = body or {}
        with self._lock:
            if action == "play":
                if self.position < DAY:                              # a finished day stays finished until it is reset
                    self.status = "playing"
            elif action == "pause":
                self.status = "paused"
            elif action == "speed":
                sp = int(body.get("speed", self.speed))
                if sp not in SPEEDS:
                    raise ValueError(f"speed must be one of {SPEEDS}")
                self.speed = sp
            elif action == "jump":                                   # move the clock forward (never back)
                to = float(body.get("seconds", self.position))
                self.position = min(DAY, max(self.position, to))
            else:
                raise ValueError(f"unknown action {action}")
            return self.clock()

    def reset_clock(self) -> None:
        with self._lock:
            self.position, self.status = self.start_seconds, "paused"

    # ---- the loop
    def run(self) -> None:
        last = time.perf_counter()
        while not self._halt.is_set():
            time.sleep(self.tick)
            now = time.perf_counter()
            dt, last = now - last, now
            with self._lock:
                if self.status != "playing":
                    continue
                self.position = min(DAY, self.position + dt * self.speed)
                until = self.iso()
                if self.position >= DAY:
                    self.status = "paused"
            try:
                self._sup().run_until(until, max_events=400)
            except Exception as e:  # noqa: BLE001 - a bad event must not kill the clock
                self.error = repr(e)

    def stop(self) -> None:
        self._halt.set()
