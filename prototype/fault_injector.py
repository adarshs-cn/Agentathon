"""Fault injector: a script of (borrower, attempt) -> fault, plus mid-run events.
Plays the role of the 'public fault script' from the problem statement."""

FAULT_SCRIPT = {
    ("B2", 1): "CRASH_BEFORE_SEND",   # died before contacting -> safe to resume
    ("B3", 1): "CRASH_AFTER_SEND",    # died after contacting  -> must NOT contact again
    ("B4", 1): "LOOP",                # alive but stuck
    ("B5", 1): "MALFORMED",           # returns garbage on first try
    ("B7", 1): "TIMEOUT",             # unscripted fault type -> catch-all path
}

# A second event for B1 lands while B1's agent is still running (the conflict case).
CONFLICTS = {
    "B1": {"id": "E1b", "type": "CONTACT_REQUESTED", "account_id": "B1"},
}


class FaultInjector:
    def __init__(self, script=None, conflicts=None):
        self.script = script if script is not None else FAULT_SCRIPT
        self.conflicts = conflicts if conflicts is not None else CONFLICTS

    def fault_for(self, agent, account_id, attempt):
        return self.script.get((account_id, attempt))

    def conflicting_event(self, account_id, attempt):
        return self.conflicts.get(account_id) if attempt == 1 else None
