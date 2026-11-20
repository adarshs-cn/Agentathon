"""End-of-day acceptance checks: the grading criteria, as code.

  zero conflicting contacts   no borrower got two contacts on a day (database AND providers)
  all faults recovered        every injected fault shows a monitor decision, a closed event,
                              a released lock, and borrower state that was not lost
  complete trace              every account's events are traceable from entry to exit
  plus housekeeping           every event closed, no dangling locks, no ambiguous attempts
                              left against an automated borrower
"""
from __future__ import annotations

from orchestrator.config import ACTIVE
from orchestrator.supervisor import Supervisor
from orchestrator.tracing.trace import trace_gaps


def check_day(sup: Supervisor, injector=None) -> dict:
    ctx = sup.ctx
    checks: dict[str, dict] = {}

    # 1. zero conflicting contacts
    provider: dict = {}
    for name in ctx.registry.names():
        for key in getattr(ctx.registry.get(name), "outbox", {}):
            provider[key] = provider.get(key, 0) + 1
    doubles = [k for k, c in provider.items() if c > 1]
    if ctx.engine is None:
        rows = ctx.db.query("SELECT account_id, date, COUNT(*) c FROM contact_log WHERE status='SENT' "
                            "GROUP BY account_id, date HAVING c > 1")
        checks["zero_conflicting_contacts"] = {
            "ok": not rows and not doubles,
            "detail": f"{ctx.contacts.sent_total()} contacts sent; db double-contacts={len(rows)}, "
                      f"provider double-messages={len(doubles)}"}
    else:
        # Dataset mode: several contacts a day are legitimate, so "conflicting" means breaking a policy rule.
        # An independent audit (separate code) re-checks every contact sent against D12 and D10.
        from orchestrator.simulator.audit import audit_ours, summarise
        viol = audit_ours(ctx.db)
        checks["zero_conflicting_contacts"] = {
            "ok": not viol and not doubles,
            "detail": f"{ctx.contacts.sent_total()} contacts sent; independent audit found {len(viol)} policy "
                      f"violations; provider double-messages={len(doubles)}",
            "violations": summarise(viol), "sample": viol[:5]}

    # 2. every event closed
    stats = ctx.bus.stats()
    open_ = stats.get("PENDING", 0) + stats.get("IN_PROGRESS", 0)
    checks["all_events_closed"] = {"ok": open_ == 0 and stats.get("FAILED", 0) == 0, "detail": stats}

    # 3. no dangling locks
    held = ctx.borrowers.owners_held()
    checks["no_dangling_locks"] = {"ok": not held, "detail": f"{len(held)} locks still held"}

    # 4. no ambiguous attempts against borrowers that are still on automation
    bad = [r for r in ctx.contacts.unresolved()
           if ctx.borrowers.load(r["account_id"])["status"] == ACTIVE]
    checks["no_unresolved_attempts"] = {"ok": not bad, "detail": f"{len(bad)} ambiguous on active borrowers"}

    # 5. all injected faults recovered, without losing borrower state
    if injector is not None:
        per_fault, ok = [], True
        for acc in sorted(injector.faulted_accounts()):
            monitored = [r for r in ctx.decisions.for_account(acc) if r["node"] == "monitor"]
            b = ctx.borrowers.load(acc)
            contacts = ctx.contacts.rows_for(acc)
            coherent = (b["owner"] is None
                        and (any(c["status"] == "SENT" for c in contacts) or b["status"] != ACTIVE))
            recovered = bool(monitored) and coherent
            ok &= recovered
            per_fault.append({"account": acc, "faults": [f for a, _, f in injector.fired if a == acc],
                              "actions": [r["data"]["action"] for r in monitored],
                              "status": b["status"], "contacted": any(c["status"] == "SENT" for c in contacts),
                              "recovered": recovered})
        scripted = bool(getattr(injector, "script", None))
        # Nothing scripted: nothing to recover from, so this passes. Faults scripted but none fired: that fails,
        # because the day then did not test what it claimed to.
        checks["all_faults_recovered"] = {"ok": ok and (bool(per_fault) or not scripted),
                                          "detail": (f"{len(per_fault)} faulted borrowers" if per_fault or scripted
                                                     else "no faults scripted for this run"), "faults": per_fault}

    # 6. complete trace for every account that got an event
    accounts = [r["account_id"] for r in ctx.db.query("SELECT DISTINCT account_id FROM event_queue")]
    gaps = {a: g for a in accounts if (g := trace_gaps(ctx, a))}
    checks["complete_traces"] = {"ok": not gaps, "detail": f"{len(accounts)} accounts traced, {len(gaps)} with gaps",
                                 "gaps": dict(list(gaps.items())[:5])}

    return {"passed": all(c["ok"] for c in checks.values()), "checks": checks,
            "route_p99_ms": round(ctx.percentile("route", 0.99), 3),
            "route_max_ms": round(max(ctx.metrics.get("route", [0])), 3)}
