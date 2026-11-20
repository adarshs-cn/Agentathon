"""Edge decisions: small pure functions that read the state and name the next node."""
from __future__ import annotations

from orchestrator.state.models import REROUTE_CHANNEL, RESUME


def after_validate_event(s) -> str:
    return "close_event" if s.get("outcome") else "load_customer"


def after_guardrails(s) -> str:
    return "route" if s["guard"]["ok"] else "close_event"


def after_route(s) -> str:
    return "assign" if s["decision"]["agent"] else "close_event"


def after_assign(s) -> str:
    # outcome is set only if the lock was lost between guardrails and assign
    return "close_event" if s.get("outcome") else s["decision"]["agent"]


def after_validate_output(s) -> str:
    return "monitor" if s.get("fault") else "commit"


def after_recover(s) -> str:
    # RESUME retries the same agent; REROUTE_CHANNEL has already put the next one in decision.agent
    if s["recovery"]["action"] in (RESUME, REROUTE_CHANNEL):
        return s["decision"]["agent"]
    return "commit"
