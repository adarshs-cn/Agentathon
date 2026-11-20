"""Borrower data for development and tests.

The real data is D1/D2/D4/D6 (20,000 accounts). Until an adapter over those tables is
written, `synthetic_borrowers` produces a realistic stand-in so the whole system can be
exercised at the real scale. Rows are (account_id, dpd, legal_flag, channels).
"""
from __future__ import annotations

import random

# Ten hand-picked borrowers, each one chosen to exercise a particular rule.
SAMPLE_BORROWERS = [
    ("B1", 5, False, ["whatsapp", "email", "voice"]),
    ("B2", 12, False, ["whatsapp", "email"]),
    ("B3", 20, False, ["whatsapp", "email"]),
    ("B4", 45, False, ["voice", "whatsapp", "email"]),
    ("B5", 60, False, ["voice", "whatsapp"]),
    ("B6", 8, False, ["whatsapp"]),
    ("B7", 95, True, ["email"]),
    ("B8", 3, False, ["whatsapp", "email"]),
    ("B9", 33, False, ["whatsapp", "email"]),
    ("B10", 15, False, []),                 # unreachable on every channel
]


def synthetic_borrowers(n: int = 20_000, seed: int = 7) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        r = rng.random()
        dpd = rng.randint(0, 29) if r < 0.60 else rng.randint(30, 89) if r < 0.88 else rng.randint(90, 240)
        legal = dpd >= 120 and rng.random() < 0.4
        channels = [c for c, p in (("whatsapp", 0.80), ("email", 0.70), ("voice", 0.60))
                    if rng.random() < p]
        rows.append((f"A{i:05d}", dpd, legal, channels))
    return rows
