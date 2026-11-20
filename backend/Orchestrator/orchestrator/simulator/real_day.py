"""A day of events built from the REAL portfolio (D1/D6/D7/D10), as of the dataset's "today".

What happens on the day, taken from the data rather than invented:
  * every payment that landed today               -> PAYMENT_RECEIVED  (D7)
  * promises to pay due tomorrow                  -> PTP_DUE           (D6, the one reminder allowed: R063)
  * promises broken today or yesterday            -> PTP_BROKEN        (D6, ownership moves: R064)
  * borrowers with nothing overdue, then the rest -> DUE_SOON / OVERDUE (D1)
plus the deliberately awkward cases: the planted-trap borrowers (deceased, DND, opted out, heavy
touch, ...), simultaneous second events, duplicate deliveries and malformed events.
Times run 07:00-20:00 on purpose: some fall outside the legal window and must be deferred.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from orchestrator.simulator.day import Day

PLANTED_GROUPS = {
    "d4_planted_cases.json": ("deceased_borrowers_contacted_recently", "heavy_touch_borrowers"),
    "d10_planted_cases.json": ("dnd_fully_blocked_contacted", "dnd_partially_blocked_contacted", "optout_then_contact",
                               "never_consented_contacted", "expired_consent_before_contact", "suppression_breach",
                               "time_window_violation", "blank_source_granted", "consent_dnd_conflict"),
}


def _ts(d: str, minute: int) -> str:
    minute = max(0, min(23 * 60 + 59, minute))
    return f"{d}T{minute // 60:02d}:{minute % 60:02d}:00"


def _planted(folder: Path | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not folder:
        return out
    for fname, keys in PLANTED_GROUPS.items():
        p = Path(folder) / fname
        if not p.exists():
            continue
        data = json.load(open(p))
        for k in keys:
            v = data.get(k)
            ids = v.get("borrower_ids") if isinstance(v, dict) else v
            if isinstance(ids, dict):
                ids = [b for lst in ids.values() for b in lst]
            if ids:
                out[k] = [i for i in ids if isinstance(i, str) and i.startswith("BRW")]
    return out


def generate_real_day(db, n_primary: int = 800, seed: int = 1, as_of: str = "2026-10-31",
                      planted_dir: str | Path | None = None, planted_per_group: int = 8,
                      conflict_rate: float = 0.04, duplicate_rate: float = 0.02, bad_rate: float = 0.01) -> Day:
    rng = random.Random(seed)
    day = Day(date=as_of, events=[])
    day.planted = {}                                    # group -> borrower ids that were injected
    n = [0]
    used: set[str] = set()

    def eid() -> str:
        n[0] += 1
        return f"rd-{n[0]:06d}"

    def add(borrower: str, etype: str, when: str, group: str | None = None) -> dict:
        e = {"id": eid(), "type": etype, "account_id": borrower, "time": when}
        day.events.append(e)
        used.add(borrower)
        if group:
            day.planted.setdefault(group, []).append(borrower)
        return e

    tomorrow = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
    yesterday = (date.fromisoformat(as_of) - timedelta(days=1)).isoformat()
    q = db.query

    # the traps first, so they are always in the day
    for group, ids in _planted(planted_dir).items():
        for b in rng.sample(ids, min(planted_per_group, len(ids))):
            if b not in used and db.one("SELECT 1 FROM ds_person WHERE borrower_id=?", (b,)):
                add(b, "OVERDUE", _ts(as_of, rng.randint(9 * 60, 17 * 60)), group)

    pays = [dict(r) for r in q("SELECT borrower_id, at FROM ds_payment WHERE substr(at,1,10)=? AND status='success' "
                               "AND reversal=0 AND borrower_id IS NOT NULL", (as_of,))]
    for r in rng.sample(pays, min(len(pays), max(1, n_primary // 6))):
        if r["borrower_id"] not in used:
            add(r["borrower_id"], "PAYMENT_RECEIVED", r["at"][:16] + ":00")

    due = [r["borrower_id"] for r in q("SELECT DISTINCT borrower_id FROM ds_ptp WHERE status='open' AND promised_date=?", (tomorrow,))]
    for b in rng.sample(due, min(len(due), max(1, n_primary // 6))):
        if b not in used:
            add(b, "PTP_DUE", _ts(as_of, rng.randint(9 * 60, 12 * 60)))

    broken = [r["borrower_id"] for r in q("SELECT DISTINCT borrower_id FROM ds_ptp WHERE status='broken' AND promised_date IN (?,?)",
                                          (yesterday, as_of))]
    for b in rng.sample(broken, min(len(broken), max(1, n_primary // 8))):
        if b not in used:
            add(b, "PTP_BROKEN", _ts(as_of, rng.randint(9 * 60, 12 * 60)))

    rest = n_primary - len(day.events)
    if rest > 0:
        pool = [dict(r) for r in q("SELECT borrower_id, MAX(dpd) dpd FROM ds_account GROUP BY borrower_id")]
        for r in rng.sample(pool, min(len(pool), rest * 2)):
            if len(day.events) >= n_primary:
                break
            if r["borrower_id"] in used:
                continue
            add(r["borrower_id"], "DUE_SOON" if r["dpd"] == 0 else "OVERDUE", _ts(as_of, rng.randint(7 * 60, 20 * 60)))

    base = list(day.events)
    for e in base:
        if rng.random() < conflict_rate:                    # a second event for the same borrower within minutes
            h, m = int(e["time"][11:13]), int(e["time"][14:16])
            day.events.append({"id": eid(), "type": "CONTACT_REQUESTED", "account_id": e["account_id"],
                               "time": _ts(as_of, h * 60 + m + rng.randint(0, 3))})
            day.conflict_accounts.add(e["account_id"])
        if rng.random() < duplicate_rate:                   # the bus delivers the same event twice
            day.events.append(dict(e))
            day.duplicate_ids.add(e["id"])
    for _ in range(max(1, int(len(base) * bad_rate)) if bad_rate > 0 else 0):
        bad = rng.choice([{"id": eid(), "type": "OVERDUE", "account_id": "BRW-NO-SUCH", "time": _ts(as_of, 600)},
                          {"id": eid(), "account_id": base[0]["account_id"], "time": _ts(as_of, 610)},
                          {"id": eid(), "type": "OVERDUE", "account_id": base[0]["account_id"], "time": "garbage"}])
        day.bad_event_ids.add(bad["id"])
        day.events.append(bad)
    day.events.sort(key=lambda e: (e.get("time", ""), e["id"]))
    return day


def build_real_fault_script(day: Day, engine, kinds: list[str], seed: int = 3) -> dict:
    """Pick borrowers whose first event will genuinely reach an agent AND have a second channel to fail over
    to, so each fault is certain to fire and to be recoverable (found by asking the engine, which writes nothing)."""
    first: dict[str, dict] = {}
    for e in day.events:
        if e.get("account_id") and e.get("type") and e["id"] not in day.bad_event_ids:
            first.setdefault(e["account_id"], e)
    cands = []
    for b, e in first.items():
        if e["type"] not in ("OVERDUE", "DUE_SOON") or e["id"] in day.duplicate_ids or b in day.conflict_accounts:
            continue
        r = engine.evaluate(b, e)
        if r["final"] == "OK" and len(r["plan"]["channel_agents"]) >= 2 and not r["plan"].get("handoff"):
            cands.append(b)
    random.Random(seed).shuffle(cands)
    if len(cands) < len(kinds):
        raise ValueError(f"only {len(cands)} suitable borrowers for {len(kinds)} faults")
    script: dict = {}
    for kind, b in zip(kinds, cands):
        for k in ((1, 2, 3) if kind == "LOOP" else (1,)):
            script[(b, k)] = kind
    return script
