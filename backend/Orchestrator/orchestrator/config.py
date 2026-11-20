"""Central configuration: paths, policy knobs, channel preferences.

No secrets live here. API keys are read from environment variables (optionally
loaded from a git-ignored .env file by `load_env`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# The three channel agents built by the other teams. Each is one agent from the
# supervisor's point of view. Which one acts is a routing decision.
CHANNELS = ("whatsapp", "email", "voice")

# The *journey purpose* of a contact (what we want to say), independent of channel.
PURPOSES = ("reminder", "negotiation", "servicing", "legal")

# For each purpose, channels in order of preference. The first one the borrower can
# be reached on wins; the rest become fallbacks if that agent faults.
# ASSUMPTION: this ordering is a business decision to be confirmed.
CHANNEL_PREFERENCE: dict[str, tuple[str, ...]] = {
    "reminder": ("whatsapp", "email", "voice"),
    "negotiation": ("voice", "whatsapp", "email"),
    "servicing": ("whatsapp", "email"),
    "legal": ("email",),
}

# LangGraph aborts a run after 25 steps by default. A fault that retries and then reroutes
# across all three channels needs more (worst case is roughly 60), so set it explicitly.
RECURSION_LIMIT = 200

EVENT_TYPES = ("DUE_SOON", "PAYMENT_RECEIVED", "PTP_BROKEN", "CONTACT_REQUESTED",
               "OVERDUE", "PTP_DUE", "SERVICE_REQUEST")        # the last three are used by the dataset (D12) mode

# Borrower statuses. Anything other than ACTIVE pauses automation.
ACTIVE, NEEDS_REVIEW, QUARANTINED = "ACTIVE", "NEEDS_REVIEW", "QUARANTINED"  # (also in state.models)


@dataclass(frozen=True)
class Policy:
    """Tunable business rules. All values are assumptions until confirmed."""
    per_borrower_daily_cap: int = 1        # contacts per borrower per day, any channel
    per_agent_daily_cap: int = 10_000      # contacts per channel agent per day
    dpd_negotiation: int = 30              # DPD at or above this -> negotiation
    dpd_legal: int = 90                    # DPD at or above this -> legal
    max_no_progress_attempts: int = 3      # IN_PROGRESS answers before we call it a loop
    max_attempts_crash: int = 2            # calls before giving up on a crashing agent
    max_attempts_malformed: int = 2        # calls before giving up on bad output
    agent_timeout_s: float = 5.0           # hard timeout around every agent call
    max_event_attempts: int = 3            # driver attempts before an event is marked FAILED


def load_env(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE per line). Never overrides real env vars."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
