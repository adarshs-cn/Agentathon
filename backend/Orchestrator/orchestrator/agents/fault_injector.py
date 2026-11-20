"""FaultInjector: the test double that makes stub agents misbehave on cue.

The supervisor never sees this object. A stub agent asks it "do I fail now?" every time
it is called; the answer comes from a plain dict script:

    {("A00017", 1): "CRASH_AFTER_SEND", ("A00230", 1): "LOOP", ("A00230", 2): "LOOP"}

The key is (account_id, call_number): the Nth time ANY agent is called for that borrower.
A fault on call 1 only means the retry (call 2) behaves, which is what makes recovery
possible; listing calls 1, 2 and 3 makes an agent that never recovers.

Fault names: CRASH_BEFORE_SEND, CRASH_AFTER_SEND, LOOP, MALFORMED, TIMEOUT.
"""
from __future__ import annotations

FAULTS = ("CRASH_BEFORE_SEND", "CRASH_AFTER_SEND", "LOOP", "MALFORMED", "TIMEOUT")


class FaultInjector:
    def __init__(self, script: dict | None = None):
        self.script = dict(script or {})
        self.calls: dict[str, int] = {}
        self.fired: list[tuple[str, int, str]] = []     # (account, call_number, fault) actually injected

    def next_fault(self, account_id: str):
        n = self.calls[account_id] = self.calls.get(account_id, 0) + 1
        fault = self.script.get((account_id, n))
        if fault:
            self.fired.append((account_id, n, fault))
        return fault

    def faulted_accounts(self) -> set[str]:
        return {a for a, _, _ in self.fired}
