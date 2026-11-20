"""Fault scripts: which borrower's agent call misbehaves, and how.

`build_fault_script` picks borrowers that really reach an agent on their first event (a
DUE_SOON event, reachable on two or more channels, not legal, no open promise), so every
fault in the script is guaranteed to fire and has a fallback channel to recover onto.
"""
from __future__ import annotations

import random

# The public script has 2 faults; our stand-in for the hidden script has 5, one of each kind.
PUBLIC_KINDS = ["CRASH_AFTER_SEND", "LOOP"]
HIDDEN_KINDS = ["CRASH_AFTER_SEND", "CRASH_BEFORE_SEND", "LOOP", "MALFORMED", "TIMEOUT"]


def build_fault_script(day, borrowers: list[tuple], kinds: list[str] = HIDDEN_KINDS, seed: int = 3) -> dict:
    profiles = {r[0]: r for r in borrowers}
    first: dict[str, dict] = {}
    for e in day.events:
        if e.get("account_id") in profiles:
            first.setdefault(e["account_id"], e)
    candidates = []
    for acc, e in first.items():
        _, dpd, legal, channels = profiles[acc]
        if e.get("type") == "DUE_SOON" and dpd < 90 and not legal and len(channels) >= 2 \
                and acc not in day.commitments and e["id"] not in day.bad_event_ids:
            candidates.append(acc)
    random.Random(seed).shuffle(candidates)
    if len(candidates) < len(kinds):
        raise ValueError(f"only {len(candidates)} suitable borrowers for {len(kinds)} faults")
    script: dict = {}
    for kind, acc in zip(kinds, candidates):
        for n in ((1, 2, 3) if kind == "LOOP" else (1,)):      # a loop never answers, three calls running
            script[(acc, n)] = kind
    return script
