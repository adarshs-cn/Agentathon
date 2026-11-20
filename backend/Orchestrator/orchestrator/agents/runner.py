"""A hard timeout around every agent call.

A hung agent would otherwise hang the supervisor. The call runs in a daemon thread; if it
has not finished within the timeout we stop waiting and raise AgentTimeout. (Python cannot
kill the thread, but the supervisor moves on, and the late result is ignored.)
"""
from __future__ import annotations

import threading

from orchestrator.agents.base import AgentTimeout


def call_with_timeout(fn, timeout_s: float, *args, **kwargs):
    box: dict = {}

    def target():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise AgentTimeout(f"no answer within {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]
