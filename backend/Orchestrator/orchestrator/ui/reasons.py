"""Plain-language layer: every code the supervisor emits, in words a stranger understands.

One module holds all wording (documentation/05-plain-language-reasons.md); the frontend never translates.
Rule codes stay available as a secondary detail; they are never the headline.
"""
from __future__ import annotations

EVENT_WORDS = {"DUE_SOON": "Reminder due", "OVERDUE": "Payment overdue", "PTP_DUE": "Promise to pay due tomorrow",
               "PTP_BROKEN": "Promise to pay broken", "PAYMENT_RECEIVED": "Payment received",
               "CONTACT_REQUESTED": "Contact requested", "SERVICE_REQUEST": "Service request"}
OUTCOME_WORDS = {"CONTACTED": "Message sent", "BLOCKED": "Not allowed", "SUPPRESSED": "Nobody could act",
                 "DEFERRED": "Waiting for a better time", "ESCALATED": "Sent to a person", "REJECTED": "Invalid event",
                 "FAILED": "Run failed"}
ROLE_WORDS = {"reminder": "Reminder", "negotiation": "Negotiation", "servicing": "Servicing", "legal": "Legal"}
CHANNEL_WORDS = {"whatsapp": "WhatsApp", "email": "Email", "voice": "Voice call (IVR)"}
FAULT_WORDS = {"CRASH": "crashed", "TIMEOUT": "stopped answering", "MALFORMED": "returned an unreadable answer",
               "NO_PROGRESS": "kept saying it was still working"}
RECOVERY_WORDS = {"RESUME": "Asked the same agent to try again", "RESTART_SKIP_CURRENT": "Did not send again",
                  "REROUTE_CHANNEL": "Switched to the next channel", "ESCALATE": "Handed to a person",
                  "QUARANTINE": "Stopped and handed to a person"}
PROVIDER_WORDS = {"SENT": "it was sent", "NOT_SENT": "it was not sent", "UNKNOWN": "it could not tell"}

RULES = {
    "R058": ("Borrower has passed away", "No contact on any channel; the legal-heir desk handles this account."),
    "R059": ("Borrower asked us to stop", "The customer asked us not to contact them."),
    "R060": ("A complaint is open", "Contact is frozen for 30 days while the complaint is handled."),
    "R061": ("The debt is disputed", "Calls, SMS and WhatsApp are paused until the dispute is settled."),
    "R062": ("A promise to pay is open", "No collection contact until the day after the promised date."),
    "R063": ("Only the promise's owner may remind", "The one reminder the day before comes from the agent that took the promise."),
    "R064": ("A broken promise goes to Negotiation", "Negotiation takes over when a promise is broken."),
    "R066": ("A payment just came in", "No contact for 48 hours while it is reconciled (except the confirmation)."),
    "R021": ("Calls must be an hour apart", "The last call was less than 60 minutes ago."),
    "R022": ("Contacts must be 30 minutes apart", "Another contact went out a moment ago, so this one waits."),
    "R033": ("Counted per borrower", "Limits count all of a borrower's accounts together."),
    "R034": ("Failed attempts still count", "A failed attempt counts toward the limit."),
    "R035": ("Another agent owns this borrower", "Only the owner may contact; the other agent is stopped."),
    "R036": ("Another agent owns this borrower", "Only the owner may contact; the other agent is stopped."),
    "R037": ("One owner for 24 hours", "Ownership covers all accounts and lasts 24 hours after the last contact."),
    "R038": ("One owner for 24 hours", "Ownership covers all accounts and lasts 24 hours after the last contact."),
    "R039": ("A higher-priority agent took over", "Legal outranks Negotiation, then Servicing, then Reminder; the change is logged."),
    "A12": ("A higher-priority agent took over", "The ownership change is approved and logged."),
    "R040": ("Legal case: only the Legal agent may act", "Every other agent is excluded."),
    "R041": ("Settlement in progress: only Negotiation may act", "Every other agent is excluded."),
    "R042": ("Restructure in progress: no legal action", "Legal action needs approval first."),
    "R075": ("Legal agent only after 90 days", "Or when a legal flag is set."),
    "D12-matrix": ("No agent is allowed to act at this stage", "The policy table lists no agent for this event and overdue stage."),
    "R043": ("No consent to call", "Call consent is missing or withdrawn."),
    "R044": ("No consent to SMS", "SMS consent is missing or withdrawn."),
    "R045": ("WhatsApp needs clear consent", "'Unknown' is not enough for WhatsApp."),
    "R046": ("No consent to email", "Email consent is withdrawn."),
    "R047": ("Borrower opted out of this channel", "They told us to stop using it."),
    "R048": ("Consent has expired", "Treated as not given."),
    "R049": ("Consent source is unrecorded", "We cannot show where the consent came from."),
    "R050": ("On the Do-Not-Disturb list", "No calls or SMS unless the message is a transaction notice."),
    "R051": ("On the Do-Not-Disturb list", "No calls or SMS unless the message is a transaction notice."),
    "R053": ("On the Do-Not-Disturb list", "No calls or SMS unless the message is a transaction notice."),
    "R055": ("Wrong number on record", "The number is blocked for every agent."),
    "R056": ("Phone shared with another borrower", "Identity must be checked before discussing the debt."),
    "R069": ("No phone number on record", "There is no number to call or message."),
    "R070": ("No email address on record", "There is no address to write to."),
    "R072": ("WhatsApp is not used after 90 days", "Formal notices go by email."),
    "R006": ("Borrower asked for specific hours", "We only contact within the window they chose."),
    "R092": ("Agent's daily budget used up", "The channel agent reached its attempts or spend limit for today."),
    "STATUS": ("Automation is paused for this borrower", "A person must review the account first."),
}
for _r in ("R001", "R002", "R003", "R004", "R005", "R007"):
    RULES[_r] = ("Outside contact hours", "Contact is allowed only between 8 am and 7 pm.")


def label(rule_id: str, rule_row: dict | None = None) -> tuple[str, str]:
    """(headline, one-line explanation) for a rule id. Cap rules are classified from the dataset row."""
    if rule_id in RULES:
        return RULES[rule_id]
    if rule_row:
        p, ch = (rule_row.get("parameter") or ""), (rule_row.get("channel") or "ALL")
        if p == "max_contacts_per_day":
            return (("Daily contact limit reached", "The borrower already had the maximum contacts today, across all channels.")
                    if ch == "ALL" else ("Channel limit for today reached", f"Too many {ch.lower()} contacts today."))
        if p == "max_contacts_per_7d":
            return (("Weekly contact limit reached", "The borrower already had the maximum contacts in 7 days.")
                    if ch == "ALL" else ("Channel limit for the week reached", f"Too many {ch.lower()} contacts this week."))
        if rule_row.get("description"):
            return (rule_row["description"][:80], rule_row["description"])
    return ("Policy rule applied", "A policy rule stopped this action.")


def labels_for(db, rule_ids: list) -> list[dict]:
    out = []
    for rid in rule_ids or []:
        row = db.one("SELECT * FROM ds_rule WHERE rule_id=?", (rid,)) if db is not None else None
        head, why = label(rid, dict(row) if row else None)
        out.append({"id": rid, "label": head, "explain": why})
    return out


def headline(db, rule_ids: list, fallback: str = "") -> str:
    ls = labels_for(db, rule_ids)
    return ls[0]["label"] if ls else (fallback or "")


# ---------------------------------------------------------------- stations (the nodes grouped for the drawing)
STATION_OF = {"validate_event": "event", "load_borrower": "borrower", "guardrails": "safety", "route": "agent_chosen",
              "assign": "ownership", "validate_output": "result", "monitor": "recover", "recover": "recover",
              "commit": "saved", "release": "saved", "close_event": "done"}
STATIONS = [("event", "Event received"), ("borrower", "Borrower loaded"), ("safety", "Safety checks"),
            ("agent_chosen", "Agent chosen"), ("ownership", "Ownership taken"), ("agent_acts", "Agent acts"),
            ("result", "Result checked"), ("recover", "Recover"), ("saved", "State saved"), ("done", "Done"),
            ("stopped", "Stopped")]


def station_of(node: str, outcome: dict | None = None) -> str:
    if node == "close_event":
        return "done" if (outcome or {}).get("status") == "CONTACTED" else "stopped"
    return STATION_OF.get(node, "agent_acts")


def _ch(c): return CHANNEL_WORDS.get(c, c or "a channel")
def _role(r): return ROLE_WORDS.get(r, (r or "an").capitalize())


def sentence(node: str, db, st: dict, ev_ms: float | None = None) -> tuple[str, str]:
    """(plain sentence, short label) for what the supervisor did at this node. `st` is the state after the node."""
    b, g, d = st.get("borrower") or {}, st.get("guard") or {}, st.get("decision") or {}
    out, res, f, rec = st.get("outcome") or {}, st.get("result") or {}, st.get("fault"), st.get("recovery") or {}
    ids = out.get("rule_ids") or g.get("rule_ids") or d.get("rule_ids") or []
    why = headline(db, ids, out.get("reason") or g.get("reason") or d.get("reason") or "")
    status = out.get("status")
    if node == "validate_event":
        if status == "REJECTED":
            return f"Rejected: {out.get('reason')}.", "Invalid event"
        return "Checked the event is valid.", "Valid"
    if node == "load_borrower":
        n = db.one("SELECT COUNT(*) c FROM ds_account WHERE borrower_id=?", (b.get("account_id"),)) if db is not None else None
        return (f"Opened the file: {b.get('dpd', 0)} days past due, {n['c'] if n else 1} account(s).", "Loaded")
    if node == "guardrails":
        if g.get("ok"):
            return "Allowed: no holds, and the contact limits are not reached.", "Allowed"
        return (f"{'Waiting' if status == 'DEFERRED' else 'Stopped'}: {why}.", why)
    if node == "route":
        if d.get("agent"):
            fb = [_ch(c) for c in d.get("fallbacks") or []]
            s = f"Chose the {_role(d.get('role'))} agent on {_ch(d['agent'])}."
            if fb:
                s += f" {', '.join(fb)} kept as backup."
            if d.get("handoff"):
                s += f" Handoff {_role(d['handoff']['from'])} → {_role(d['handoff']['to'])}."
            return s, f"{_role(d.get('role'))} on {_ch(d['agent'])}"
        verb = "Waiting" if status == "DEFERRED" else "No agent can act"
        return (f"{verb}: {why}." + (f" Earliest {out['until'][11:16]}." if out.get("until") else ""), why)
    if node == "assign":
        if status == "BLOCKED":
            return f"Stopped: {out.get('reason')}.", "Lost the lock"
        h = d.get("handoff")
        if h:
            return f"Locked the borrower to {_ch(d.get('agent'))}. Owner: {_role(h['from'])} → {_role(h['to'])}.", "Handoff"
        return f"Locked the borrower to {_ch(d.get('agent'))} so no other agent can act.", "Locked"
    if node in ("whatsapp", "email", "voice"):
        if f:
            return f"{_ch(node)} agent {FAULT_WORDS.get(f['type'], 'had a problem')}.", "Problem"
        ms = f" in {round(ev_ms)} ms" if ev_ms is not None else ""
        return f"{_ch(node)} agent sent the message{ms}.", "Sent"
    if node == "validate_output":
        if f:
            return f"Problem found: the agent {FAULT_WORDS.get(f['type'], 'had a problem')}.", "Problem"
        return "The result is well formed; the contact is confirmed.", "Confirmed"
    if node == "monitor":
        return (f"Asked the provider whether the message went out: {PROVIDER_WORDS.get(rec.get('provider_state'), 'unknown')}. "
                f"{RECOVERY_WORDS.get(rec.get('action'), '')}.".replace(" .", "."), "Checked")
    if node == "recover":
        return f"{RECOVERY_WORDS.get(rec.get('action'), 'Recovered')}.", RECOVERY_WORDS.get(rec.get("action"), "Recovered")
    if node == "commit":
        if res.get("status") == "DONE":
            return f"Saved the contact and gave {_role(d.get('role'))} a 24-hour ownership lease.", "Saved"
        return "Held for a person: no contact was made.", "Held"
    if node == "release":
        return "Released the lock on the borrower.", "Released"
    if node == "close_event":
        w = OUTCOME_WORDS.get(status, status or "Done")
        if status == "CONTACTED":
            return f"Done: {w}.", w
        return f"Stopped: {why or w}.", why or w
    return node, node
