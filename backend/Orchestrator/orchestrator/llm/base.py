"""The advisor contract. The monitor calls `advise` only for a fault no rule covers, and
only after the provider has confirmed nothing was sent."""
from __future__ import annotations

from typing import Optional, Protocol


class RecoveryAdvisor(Protocol):
    def advise(self, fault: dict, agent: str, customer_id: str, allowed: list[str]) -> tuple[Optional[str], Optional[str]]:
        """Return (action, short diagnosis). `action` must be one of `allowed`, or None to
        decline; the monitor ignores anything else and falls back to QUARANTINE."""
        ...
