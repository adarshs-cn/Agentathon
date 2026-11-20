"""Day simulator: one simulated day of events, generated from the borrower snapshot.

Stand-in for the judges' "event simulator" (1 simulated day, a public fault script of 2 and
a hidden one of 5). The mix includes the nasty cases on purpose:
  * simultaneous events: a second event for the same borrower within minutes
  * duplicate deliveries: the same event id published twice
  * bad events: unknown account, missing type, unparseable time
  * open promises to pay: borrowers who must not be contacted
Agent faults are NOT events; they come from the FaultInjector script (simulator/faults.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

TYPE_WEIGHTS = (("DUE_SOON", 0.70), ("PTP_BROKEN", 0.12), ("PAYMENT_RECEIVED", 0.10), ("CONTACT_REQUESTED", 0.08))


@dataclass
class Day:
    date: str
    events: list[dict]
    commitments: dict[str, list] = field(default_factory=dict)   # accounts with an open promise to pay
    duplicate_ids: set = field(default_factory=set)
    bad_event_ids: set = field(default_factory=set)
    conflict_accounts: set = field(default_factory=set)


def _ts(date: str, minute: int) -> str:
    minute = max(0, min(23 * 60 + 59, minute))
    return f"{date}T{minute // 60:02d}:{minute % 60:02d}:00"


def generate_day(borrowers: list[tuple], n_primary: int = 1000, seed: int = 1, date: str = "2026-11-20",
                 conflict_rate: float = 0.08, duplicate_rate: float = 0.03, bad_rate: float = 0.01,
                 commitment_rate: float = 0.05) -> Day:
    rng = random.Random(seed)
    day = Day(date=date, events=[])
    counter = [0]

    def eid() -> str:
        counter[0] += 1
        return f"evt-{counter[0]:06d}"

    types, weights = zip(*TYPE_WEIGHTS)
    for row in rng.sample(borrowers, min(n_primary, len(borrowers))):
        acc = row[0]
        t0 = rng.randint(8 * 60, 19 * 60 + 50)
        ev = {"id": eid(), "type": rng.choices(types, weights)[0], "account_id": acc, "time": _ts(date, t0)}
        day.events.append(ev)
        if rng.random() < conflict_rate:                       # a second event, seconds-to-minutes later
            day.events.append({"id": eid(), "type": "CONTACT_REQUESTED", "account_id": acc,
                               "time": _ts(date, t0 + rng.randint(0, 3))})
            day.conflict_accounts.add(acc)
        if rng.random() < duplicate_rate:                      # the bus delivers the same event twice
            day.events.append(dict(ev))
            day.duplicate_ids.add(ev["id"])
        if rng.random() < commitment_rate and ev["type"] == "DUE_SOON":
            day.commitments[acc] = [{"type": "PTP", "due": "2026-11-25", "amount": rng.randint(1000, 9000)}]

    for _ in range(max(1, int(len(day.events) * bad_rate)) if bad_rate > 0 else 0):   # malformed input
        bad = rng.choice([
            {"id": eid(), "type": "DUE_SOON", "account_id": "NO-SUCH-ACCOUNT", "time": _ts(date, 600)},
            {"id": eid(), "account_id": rng.choice(borrowers)[0], "time": _ts(date, 610)},          # no type
            {"id": eid(), "type": "DUE_SOON", "account_id": rng.choice(borrowers)[0], "time": "garbage"},
        ])
        day.bad_event_ids.add(bad["id"])
        day.events.append(bad)

    day.events.sort(key=lambda e: e.get("time", ""))
    return day


def load_day(sup, day: Day) -> int:
    """Apply the day's setup to a supervisor and put its events on the bus."""
    for acc, commitments in day.commitments.items():
        sup.ctx.borrowers.set_commitments(acc, commitments)
    return sup.publish_many(day.events)
