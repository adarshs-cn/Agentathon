"""Stage 3: take the lock, call the channel agent, check what it returned.

The three channel agents (whatsapp, email, voice) are three nodes built from one factory.
A LangGraph node that raises aborts the whole run, so the agent node catches every
failure and writes it into the state as data (`fault`); the graph then routes it to the
monitor.

Order of operations around an agent call (this is what makes crashes safe):
  1. contacts.begin(key)   record the INTENT in the contact_log first (status ATTEMPTING)
  2. agent.execute(req)    the agent sends, carrying the same idempotency key
  3. validate_output       only after the result checks out: contacts.mark_sent(key)
A crash between 2 and 3 leaves an ATTEMPTING row; the monitor then asks the agent's
provider (`lookup`) whether the message went out, and never guesses.
"""
from __future__ import annotations

import time

from orchestrator.agents.base import AgentCrash, AgentTimeout, ContactRequest
from orchestrator.agents.runner import call_with_timeout
from orchestrator.context import Context
from orchestrator.state.models import BLOCKED, CRASH, MALFORMED, NO_PROGRESS, TIMEOUT, GraphState

REQUIRED_OUTPUT = {"customer_id", "status", "outcome"}


def make_assign(ctx: Context):
    def assign(state: GraphState) -> dict:
        b, dec = state["customer"], state["decision"]
        acc, agent = b["customer_id"], dec["agent"]
        if not ctx.borrowers.try_take_owner(acc, agent):
            holder = ctx.borrowers.load(acc)["owner"]
            if holder != agent:
                why = f"lost the owner lock: {holder} took {acc} first"
                ctx.log(state, "assign", f"BLOCKED: {why}")
                return {"outcome": {"status": BLOCKED, "reason": why}}
            # Same agent already holds it: this is a replay of assign after a crash. Carry on.
            ctx.log(state, "assign", f"lock already held by {agent} (replay), continuing")
        else:
            ctx.log(state, "assign", f"owner lock taken: {agent} owns {acc}")
        h = dec.get("handoff")
        if h:                                                    # A12: every ownership change is logged with its reason
            ctx.log(state, "assign", f"HANDOFF {h['from']} -> {h['to']} [{', '.join(h['rule_ids'])}]: {h['why']}", h)
        return {"customer": {**b, "owner": agent}, "attempt": 0}
    return assign


def make_agent_node(ctx: Context, name: str):
    def agent_node(state: GraphState) -> dict:
        ev, b, dec = state["event"], state["customer"], state["decision"]
        acc, date = b["customer_id"], ev["time"][:10]
        key = ctx.idem_key(acc, ev)
        attempt = state.get("attempt", 0) + 1
        agent = ctx.registry.get(name)

        what = dec.get("action") or dec["purpose"]
        began = ctx.contacts.begin(key, acc, date, name, what, ev["id"], role=dec.get("role") or dec["purpose"], at=ev["time"],
                                   account_id=ev.get("account_id"))
        if began == "ALREADY_SENT":
            row = ctx.contacts.get(key)
            res = {"customer_id": acc, "status": "DONE", "outcome": "CONTACTED",
                   "channel": row["channel"], "provider_ref": row["provider_ref"], "via": "already_sent"}
            ctx.log(state, name, f"attempt {attempt}: contact for today is already SENT, agent not called")
            return {"attempt": attempt, "result": res, "fault": None}

        mctx = ()
        if ctx.engine is not None:                    # dataset mode: the text needs the borrower's real numbers
            from orchestrator.agents.messages import message_context
            mctx = tuple(message_context(ctx.db, acc, ev, dec.get("action") or what).items())  # numbers of ev's account
        req = ContactRequest(acc, what, agent.template_for(what), key, ev["id"], ev["time"],
                             role=dec.get("role") or "", action=dec.get("action") or "", context=mctx,
                             account_id=ev.get("account_id") or "")
        t0 = time.perf_counter()

        def evidence(**extra) -> dict:       # what we sent the agent, and what came back
            return {"request": req.to_dict(), "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2), **extra}
        try:
            out = call_with_timeout(agent.execute, ctx.policy.agent_timeout_s, req)
        except AgentTimeout as e:
            ctx.log(state, name, f"attempt {attempt}: agent TIMED OUT ({e})", evidence(error=f"AgentTimeout: {e}"))
            return {"attempt": attempt, "result": None, "fault": {"type": TIMEOUT, "detail": str(e)}}
        except AgentCrash as e:
            ctx.log(state, name, f"attempt {attempt}: agent CRASHED ({e})", evidence(error=f"AgentCrash: {e}"))
            return {"attempt": attempt, "result": None, "fault": {"type": CRASH, "detail": str(e)}}
        except Exception as e:  # noqa: BLE001 - any exception from a real agent is a crash to us
            ctx.log(state, name, f"attempt {attempt}: agent raised {type(e).__name__}: {e}", evidence(error=f"{type(e).__name__}: {e}"))
            return {"attempt": attempt, "result": None,
                    "fault": {"type": CRASH, "detail": f"{type(e).__name__}: {e}"}}
        ctx.log(state, name, f"attempt {attempt}: agent returned status={out.get('status') if isinstance(out, dict) else type(out).__name__}",
                evidence(response=out))
        return {"attempt": attempt, "result": out, "fault": None}
    agent_node.__name__ = name
    return agent_node


def make_validate_output(ctx: Context):
    def validate_output(state: GraphState) -> dict:
        if state.get("fault"):                       # the agent node already reported an exception
            ctx.log(state, "validate_output", f"fault already reported: {state['fault']['type']}")
            return {}
        acc = state["customer"]["customer_id"]
        res = state.get("result")
        keys = set(res) if isinstance(res, dict) else set()
        if isinstance(res, dict) and res.get("status") == "IN_PROGRESS":
            f = {"type": NO_PROGRESS, "detail": f"still IN_PROGRESS after attempt {state['attempt']}"}
        elif (not REQUIRED_OUTPUT <= keys or res.get("status") != "DONE"
              or res.get("customer_id") != acc):
            f = {"type": MALFORMED, "detail": f"got keys {sorted(keys)}, expected {sorted(REQUIRED_OUTPUT)} "
                                              f"with status DONE for {acc}"}
        else:
            ctx.contacts.mark_sent(ctx.idem_key(acc, state["event"]), res.get("provider_ref"), res.get("message"))
            ctx.log(state, "validate_output", "output is well-formed; contact confirmed SENT")
            return {"fault": None}
        ctx.log(state, "validate_output", f"FAULT {f['type']}: {f['detail']}", f)
        return {"fault": f}
    return validate_output
