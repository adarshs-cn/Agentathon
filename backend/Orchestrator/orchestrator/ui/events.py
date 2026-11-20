"""Turn the supervisor's decision-log rows into the eight event types the dashboard knows.

The decision log has one row per graph node, which is too fine for a live feed. This module
reads ALL the rows of one processed event and emits the few lines a person wants to see:

    ROUTING_DECISION     who was chosen and why (with what was weighed)
    REQUEST_REFUSED      blocked / suppressed / deferred / rejected, with the rule ids
    OWNER_ASSIGNED       the lock was taken (or a handoff between roles)
    OWNER_RELEASED       the lock was released
    CONTACT_ATTEMPTED    the channel agent was called: what came back
    FAULT_DETECTED       the agent crashed, hung, looped or returned junk
    RECOVERY_ACTION      what the monitor decided to do about it
    COMMITMENT_RECORDED  the result was written to the borrower's file

Everything is derived from the log, so what the dashboard shows is exactly what is stored.
"""
from __future__ import annotations

CHANNEL_NODES = ("whatsapp", "email", "voice")


def _z(ts: str) -> str:
    """The dashboard parses times with `new Date(ts)`; a trailing Z keeps the simulated wall-clock time as written."""
    return ts if not ts or ts.endswith("Z") else ts + "Z"


def _short(s: str, n: int = 260) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def weighed(considered: list) -> str:
    """'whatsapp ok · call blocked R050 · email blocked R070': what the engine weighed, in one line."""
    parts = []
    for cand in (considered or [])[:1]:
        for ch in cand.get("channels") or []:
            ids = " ".join(ch.get("rule_ids") or [])
            parts.append(f"{ch['channel']} ok" if ch.get("status") == "OK"
                         else f"{ch['channel']} {ch.get('status', '').lower()} {ids}".strip())
    return " · ".join(parts)


def ui_events_for(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    agent = role = None
    for r in rows:
        node, text, d = r["node"], r["text"] or "", r["data"] if isinstance(r["data"], dict) else {}
        base = {"event_id": f"d{r['id']}", "ts": _z(r["ts"]), "customer_id": r["customer_id"] or "-",
                "account_id": r.get("account_id") or "-",
                "source_event_id": r["event_id"], "rule_ids": list(d.get("rule_ids") or [])}

        def emit(type_, who, decision, reason, **extra):
            out.append({**base, "type": type_, "agent": who, "decision": decision, "reason": _short(reason), **extra})

        if node == "validate_event" and text.startswith("REJECTED"):
            emit("REQUEST_REFUSED", "supervisor", "REJECTED", text.split(":", 1)[-1].strip())
        elif node == "guardrails" and d.get("ok") is False:
            word = text.split(" ")[0].split("[")[0].strip(":") or "BLOCKED"
            emit("REQUEST_REFUSED", "supervisor", word, d.get("reason") or text)
        elif node == "route":
            if d.get("agent"):
                agent, role = d["agent"], d.get("role") or d.get("purpose")
                what = d.get("action") or role
                why = weighed(d.get("considered")) or d.get("reason", "")
                if d.get("handoff"):
                    why = f"handoff from {d['handoff']['from']}. " + why
                emit("ROUTING_DECISION", agent, f"{role} ({what}) via {agent}", why)
            else:
                word = "DEFERRED" if text.startswith("DEFERRED") else "SUPPRESSED"
                emit("REQUEST_REFUSED", d.get("role") or "supervisor", word, d.get("reason") or text)
        elif node == "assign":
            if text.startswith("BLOCKED"):
                emit("REQUEST_REFUSED", agent or "supervisor", "LOCK LOST", text)
            elif text.startswith("HANDOFF"):
                emit("OWNER_ASSIGNED", d.get("to") or agent or "supervisor", f"handoff {d.get('from')} → {d.get('to')}",
                     d.get("why") or text)
            else:
                emit("OWNER_ASSIGNED", agent or "supervisor", f"{agent} owns the borrower", text)
        elif node == "release":
            emit("OWNER_RELEASED", agent or "supervisor", "lock released", "")
        elif node in CHANNEL_NODES:
            if d.get("error"):
                decision = ("timed out" if "Timeout" in d["error"] else "crashed")
                emit("CONTACT_ATTEMPTED", node, decision, d["error"])
            else:
                resp = d.get("response") or {}
                ok = resp.get("status") == "DONE"
                decision = "contact sent" if ok else f"returned {resp.get('status') or 'junk'}"
                tmpl = (d.get("request") or {}).get("template", "")
                emit("CONTACT_ATTEMPTED", node, decision, f"{tmpl} · {d.get('elapsed_ms', '?')} ms")
        elif node == "validate_output" and (text.startswith("FAULT") or text.startswith("fault already")):
            ftype = d.get("type") or text.rsplit(":", 1)[-1].strip().split(" ")[-1]
            emit("FAULT_DETECTED", agent or "supervisor", ftype, d.get("detail") or text)
        elif node == "monitor":
            emit("RECOVERY_ACTION", agent or "supervisor", d.get("action") or "recovery", d.get("reason") or text,
                 provider_state=d.get("provider_state"), advisor=d.get("advisor"))
        elif node == "commit":
            held = text.startswith("no contact")
            emit("COMMITMENT_RECORDED", role or agent or "supervisor",
                 "held for human review" if held else "contact committed", text)
    return out
