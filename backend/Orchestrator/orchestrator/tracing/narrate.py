"""Narrator: prints every decision as the supervisor makes it, so a run is not a black box.

    sup.narrate()            # then sup.run_until_empty() prints the reasoning live

It subscribes to the decision log, so what you see is exactly what is stored in the trace.
A failure inside the narrator can never affect the run.
"""
from __future__ import annotations

from orchestrator.tracing.render import format_step


class Narrator:
    def __init__(self, ctx, out=print, verbose: bool = False):
        self.ctx, self.out, self.verbose = ctx, out, verbose
        self._current = None

    def __call__(self, row: dict) -> None:
        eid = row["event_id"]
        if eid != self._current:
            self._current = eid
            q = self.ctx.bus.get(eid) or {}
            self.out("")
            self.out(f"== EVENT {eid}  {q.get('type', '?')}  account={row['customer_id'] or '-'}  "
                     f"@ {q.get('event_time') or row['ts']}")
        for line in format_step(row, self.verbose):
            self.out(line)
