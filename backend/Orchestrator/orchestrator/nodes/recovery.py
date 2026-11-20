"""Stage 4: fault handling. `monitor` diagnoses, `recover` applies. Neither writes to the bus.

THE KEY MOVE: the monitor never takes the agent's word for what happened. It asks the
agent's provider (`lookup`) whether a message with this idempotency key went out:

  provider says SENT      -> RESTART_SKIP_CURRENT: finish the record, never call again
  provider says UNKNOWN   -> QUARANTINE: we cannot tell, so we refuse to risk a second message
  provider says NOT_SENT  -> nothing went out, so a retry cannot double-contact. Then by fault:

      CRASH        retry, up to max_attempts_crash calls, then give up
      MALFORMED    retry, up to max_attempts_malformed calls, then give up
      NO_PROGRESS  retry, up to max_no_progress_attempts calls (that is a loop), then give up
      anything else (TIMEOUT and faults nobody scripted): ask the advisor (the LLM) to pick
                   one action from a short safe menu; with no advisor, or a bad answer,
                   QUARANTINE.

  "give up" = REROUTE_CHANNEL (next fallback channel agent) if one is left, else ESCALATE
  (the borrower goes to human review).

The advisor can only choose from the menu the rules built; it can never pick an action the
guardrails would forbid, and it is never consulted when a message may already have gone out.
"""
from __future__ import annotations

from orchestrator.context import Context
from orchestrator.state.models import (CRASH, ESCALATE, MALFORMED, NO_PROGRESS, QUARANTINE,
                                       REROUTE_CHANNEL, RESUME, SKIP, GraphState)


def _decide(ctx: Context, state: dict, provider: str, sent: bool) -> tuple[str, str, str]:
    """Returns (action, reason, who decided: 'rules' | 'llm')."""
    fault, n, dec = state["fault"], state["attempt"], state["decision"]
    t, pol = fault["type"], ctx.policy
    if sent:
        return SKIP, f"{t}, but the provider confirms the message went out: never call the agent again", "rules"
    if provider != "NOT_SENT":
        return (QUARANTINE, f"{t} and the provider cannot confirm whether the message went out "
                            f"(lookup={provider}): refusing to risk a second contact", "rules")

    give_up = REROUTE_CHANNEL if dec["fallbacks"] else ESCALATE
    give_up_text = (f"reroute to {dec['fallbacks'][0]}" if dec["fallbacks"]
                    else "no channel left: escalate to human review")
    limits = {CRASH: pol.max_attempts_crash, MALFORMED: pol.max_attempts_malformed,
              NO_PROGRESS: pol.max_no_progress_attempts}
    if t in limits:
        if n < limits[t]:
            return RESUME, f"{t}, provider confirms nothing was sent: retry (call {n} of {limits[t]})", "rules"
        return give_up, f"{t} persisted for {n} calls: {give_up_text}", "rules"

    # Unscripted fault: build the safe menu and let the advisor choose, if there is one.
    allowed = ([RESUME] if n < pol.max_attempts_crash else []) + [give_up, QUARANTINE]
    if ctx.advisor is not None:
        try:
            action, note = ctx.advisor.advise(fault, dec["agent"], state["customer"]["customer_id"], allowed)
        except Exception:  # noqa: BLE001 - an advisor failure must never break recovery
            action, note = None, None
        if action in allowed:
            return action, f"unscripted fault {t}: advisor chose {action}" + (f". {note}" if note else ""), "llm"
    return QUARANTINE, f"unscripted fault {t}: no rule and no valid advice, hold for human review", "rules"


def make_monitor(ctx: Context):
    def monitor(state: GraphState) -> dict:
        ev, dec = state["event"], state["decision"]
        acc = state["customer"]["customer_id"]
        key = ctx.idem_key(acc, ev)
        try:
            provider = ctx.registry.get(dec["agent"]).lookup(key)
        except Exception:  # noqa: BLE001
            provider = "UNKNOWN"
        row = ctx.contacts.get(key)
        sent = provider == "SENT" or bool(row and row["status"] == "SENT")
        action, why, who = _decide(ctx, state, provider, sent)
        rec = {"action": action, "reason": why, "provider_state": provider, "advisor": who}
        ctx.log(state, "monitor", f"{state['fault']['type']} on {dec['agent']} -> {action}: {why}", rec)
        return {"sent": sent, "recovery": rec}
    return monitor


def make_recover(ctx: Context):
    def recover(state: GraphState) -> dict:
        rec, dec, b, ev = state["recovery"], state["decision"], state["customer"], state["event"]
        acc = b["customer_id"]
        key = ctx.idem_key(acc, ev)
        action = rec["action"]

        if action == RESUME:
            ctx.log(state, "recover", f"RESUME: calling {dec['agent']} again")
            return {"fault": None}

        if action == SKIP:
            try:                              # ask the provider what it sent, so the message is not lost with the crash
                msg = ctx.registry.get(dec["agent"]).sent_message(key)
            except Exception:  # noqa: BLE001
                msg = None
            ctx.contacts.mark_sent(key, None, msg)
            res = {"customer_id": acc, "status": "DONE", "outcome": "CONTACTED",
                   "channel": dec["agent"], "via": "recovery"}
            ctx.log(state, "recover", "SKIP: contact confirmed by the provider, recorded as sent")
            return {"fault": None, "result": res}

        if action == REROUTE_CHANNEL:
            nxt, rest = dec["fallbacks"][0], dec["fallbacks"][1:]
            ctx.borrowers.switch_owner(acc, dec["agent"], nxt)
            new_dec = {**dec, "agent": nxt, "fallbacks": rest,
                       "reason": f"{dec['reason']} | rerouted {dec['agent']} -> {nxt} after {state['fault']['type']}"}
            ctx.log(state, "recover", f"REROUTE_CHANNEL: {dec['agent']} -> {nxt}", new_dec)
            return {"decision": new_dec, "attempt": 0, "fault": None, "customer": {**b, "owner": nxt}}

        # ESCALATE or QUARANTINE: stop automation for this borrower, keep every record.
        if rec["provider_state"] == "NOT_SENT":
            ctx.contacts.cancel(key)          # certain nothing went out: close the open attempt
        # else leave the ATTEMPTING row in place: it still counts against the daily cap and
        # is the evidence a human needs to resolve the unknown.
        ctx.log(state, "recover", f"{action}: automation stopped for {acc}, humans take over")
        return {"fault": None, "result": {"customer_id": acc, "status": "ESCALATED", "outcome": action}}
    return recover
