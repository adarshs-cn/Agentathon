"""The two kinds of state, kept deliberately separate.

GraphState     scratchpad for handling ONE event. Checkpointed by LangGraph after every
               node (thread_id = account_id). Nodes return partial updates.
BorrowerState  the borrower's permanent file. Lives in OUR tables (borrower_profile +
               borrower_state). GraphState.borrower is a COPY loaded at the start of a
               run; only assign / commit / release / recover write back to the store.

Everything here is a plain dict at runtime (TypedDict is only a type hint) and must
stay JSON-serialisable, because the checkpointer serialises it after every node.
"""
from __future__ import annotations

from typing import Optional, TypedDict

# Outcome statuses (final answer for one event)
CONTACTED, BLOCKED, SUPPRESSED, REJECTED, ESCALATED, DEFERRED = (
    "CONTACTED", "BLOCKED", "SUPPRESSED", "REJECTED", "ESCALATED", "DEFERRED")

# Borrower statuses (the supervisor-owned record). Anything but ACTIVE pauses automation.
NEEDS_REVIEW_STATUS, QUARANTINED_STATUS = "NEEDS_REVIEW", "QUARANTINED"

# Fault types an agent call can produce
CRASH, TIMEOUT, MALFORMED, NO_PROGRESS = "CRASH", "TIMEOUT", "MALFORMED", "NO_PROGRESS"

# Recovery actions the monitor can choose
RESUME = "RESUME"                          # call the same agent again
SKIP = "RESTART_SKIP_CURRENT"              # the contact already went out: do not call again
REROUTE_CHANNEL = "REROUTE_CHANNEL"        # switch to the next channel agent
ESCALATE = "ESCALATE"                      # no channel left: human review
QUARANTINE = "QUARANTINE"                  # cannot verify what happened: stop, human review


class Event(TypedDict, total=False):
    id: str            # unique; a repeated id is dropped by the bus
    type: str          # one of config.EVENT_TYPES
    account_id: str
    time: str          # ISO 8601, e.g. "2026-11-20T09:00:00"
    payload: dict


class BorrowerState(TypedDict):
    # facts, read-only (stand-in for D1/D2/D4/D6)
    account_id: str
    dpd: int
    legal_flag: bool
    channels: list     # channels this borrower can be reached on
    # supervisor-owned record, read/write (our borrower_state table)
    owner: Optional[str]          # the one channel agent currently in charge
    last_contact: Optional[str]
    commitments: list             # open promises to pay
    status: str                   # ACTIVE | NEEDS_REVIEW | QUARANTINED


class Guard(TypedDict, total=False):
    ok: bool
    rule: str          # STATUS | OWNER_LOCK | DAILY_CAP | NONE (dataset mode: SUPPRESSION, PAYMENT_HOLD, ...)
    reason: str
    rule_ids: list     # D12 rule ids that decided it (dataset mode)
    defer_until: str


class Decision(TypedDict, total=False):
    purpose: Optional[str]     # reminder | negotiation | servicing | legal | None
    agent: Optional[str]       # the channel agent chosen now: whatsapp | email | voice
    fallbacks: list            # remaining channels, tried in order if this agent faults
    reason: str
    rule: int
    route_ms: float


class Fault(TypedDict):
    type: str
    detail: str


class Recovery(TypedDict, total=False):
    action: str
    reason: str
    provider_state: str        # what the agent's provider said: SENT | NOT_SENT | UNKNOWN
    advisor: str               # "rules" | "llm"


class Outcome(TypedDict, total=False):
    status: str
    reason: str
    rule_ids: list
    until: str         # DEFERRED: when to try again
    agent: str
    attempts: int


class GraphState(TypedDict, total=False):
    event: Event
    borrower: BorrowerState
    guard: Optional[Guard]
    decision: Optional[Decision]
    attempt: int
    result: Optional[dict]
    fault: Optional[Fault]
    sent: bool
    recovery: Optional[Recovery]
    outcome: Optional[Outcome]
