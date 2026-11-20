"""The D12 policy engine: decides, for one borrower and one event, who may contact them, how,
and when, citing the rule ids that decided it (R093).

It is PURE: it reads the dataset tables and the contact log and returns a verdict; it never
writes. The graph nodes (guardrails, route) call it and record what it says.

Two steps, mirroring the two graph nodes
  guard(facts, event)  borrower-level hard stops: suppression, deceased, payment hold, open
                       promise, frequency caps, minimum gap
  plan(facts, event)   who acts and on which channel: the agent-bucket matrix, flags, ownership
                       lease and conflict priority, then per channel: eligibility, consent and
                       DND, operating window, channel caps, call gap, D13 budget and spend cap

Verdict statuses: OK | BLOCKED | SUPPRESSED | DEFERRED (not now, retry at `defer_until`).

ASSUMPTIONS (mine, flagged where they matter; everything else is read from D12/D13/D10)
  * The unit is the BORROWER, across all their accounts (R033, R037). A borrower's bucket is
    their worst account's; any legal / settlement / restructure flag applies to the borrower.
  * Only the four in-house role agents are orchestrated. External agencies (AGY001-3) are never
    chosen, but their contacts still count toward caps and ownership.
  * D12 channel 'call' is our voice agent; 'sms' and 'field_visit' have no agent, so they are
    never chosen.
  * R007 (hard, regulatory) wins over the soft 21:00 limit of WhatsApp and email: nobody is
    contacted outside 08:00-19:00.
  * Contacts already in D4 for the event's date count in full, whatever their time of day: the
    dataset is a snapshot, so they have already happened.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta


ROLES = ("reminder", "negotiation", "servicing", "legal")
# R039: legal > negotiation > agencies > servicing > reminder
ROLE_PRIORITY = {"legal": 1, "negotiation": 2, "agency": 3, "servicing": 4, "reminder": 5}
CHANNEL_AGENT = {"whatsapp": "whatsapp", "email": "email", "call": "voice"}     # D12 channel -> our agent
AGENT_CHANNEL = {v: k for k, v in CHANNEL_AGENT.items()}
PHONE_CHANNELS = ("call", "sms", "whatsapp")
# Channel order per role, among the channels D12 allows for that role in the borrower's bucket.
# ASSUMPTION (business choice): written/async first for reminders, voice first for negotiation, email for legal.
PREFERENCE = {"reminder": ("whatsapp", "email", "call"), "negotiation": ("call", "whatsapp", "email"),
              "servicing": ("whatsapp", "email", "call"), "legal": ("email", "call")}

# What each kind of event is asking for, in order of preference. Action names are D12's.
EVENT_ACTIONS = {
    "DUE_SOON": ["emi_due_reminder", "pre_due_reminder"],
    "OVERDUE": ["overdue_reminder", "ptp_capture", "settlement_offer", "restructure_offer", "legal_notice",
                "demand_notice"],
    "CONTACT_REQUESTED": ["overdue_reminder", "ptp_capture", "settlement_offer", "restructure_offer",
                          "legal_notice", "demand_notice"],
    "PTP_DUE": ["ptp_reminder"],
    "PTP_BROKEN": ["broken_ptp_followup", "ptp_capture", "settlement_offer"],
    "PAYMENT_RECEIVED": ["payment_confirmation", "statement"],
    "SERVICE_REQUEST": ["service_request", "statement"],
}
EXTRA_ACTIONS = {"servicing": ["payment_confirmation"]}          # a payment confirmation is a servicing reply
DND_OK = {"payment_confirmation", "emi_due_reminder", "ptp_reminder", "statement", "service_request"}   # R051
LEASE_EXEMPT = {"payment_confirmation", "statement", "service_request", "closure_letter"}   # reactive service replies
CONSENT_RULE = {"call": "R043", "sms": "R044", "whatsapp": "R045", "email": "R046"}
WINDOW_RULE = {"call": "R001", "field_visit": "R002", "sms": "R003", "whatsapp": "R004", "email": "R005"}


@dataclass
class Contact:
    at: datetime
    channel: str          # sms | whatsapp | email | call | field_visit
    role: str             # reminder | negotiation | servicing | legal | AGYxxx
    disposition: str = ""
    source: str = "history"


@dataclass
class Facts:
    borrower: str
    now: datetime
    today: str
    accounts: list
    person: dict
    consent: dict
    contacts: list
    ptps: list
    payments: list
    lease: tuple
    wrong_number: bool = False
    dpd: int = 0
    bucket: str = "0"
    legal: bool = False
    settlement: bool = False
    restructure: bool = False


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _norm_channel(c: str) -> str:
    c = (c or "").lower()
    return "call" if c in ("ivr", "voice") else c


def _norm_role(a: str) -> str:
    a = a or ""
    return a[:-6] if a.endswith("_agent") else ("agency" if a.startswith("AGY") else a)


def _hhmm(s: str):
    m = re.fullmatch(r"(\d\d):(\d\d)-(\d\d):(\d\d)", (s or "").strip())
    return (int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])) if m else None


def _verdict(status="OK", rule_ids=None, reason="", rule="NONE", defer_until=None, **extra) -> dict:
    return {"status": status, "ok": status == "OK", "rule": rule, "rule_ids": list(rule_ids or []),
            "reason": reason, "defer_until": defer_until, **extra}


class D12Policy:
    def __init__(self, db, contacts, borrowers, registry, policy=None):
        self.db, self.contact_log, self.borrowers, self.registry, self.pol = db, contacts, borrowers, registry, policy
        self.reload()

    # ------------------------------------------------------------------ policy as data
    def reload(self) -> None:
        q = self.db.query
        self.matrix = {(r["agent"], r["bucket"]): dict(r) for r in q("SELECT * FROM ds_matrix")}
        self.rules = {r["rule_id"]: dict(r) for r in q("SELECT * FROM ds_rule WHERE status='active'")}
        self.capacity = {(r["agent"], r["channel"]): dict(r) for r in q("SELECT * FROM ds_capacity")}
        self.day_caps, self.week_caps, self.gaps, self.windows = [], [], {}, {}
        for r in self.rules.values():
            if r["category"] == "frequency_cap" and r["parameter"] in ("max_contacts_per_day", "max_contacts_per_7d"):
                row = (r["bucket"], r["channel"], int(r["value"]), r["rule_id"])
                (self.day_caps if r["parameter"] == "max_contacts_per_day" else self.week_caps).append(row)
            elif r["category"] == "frequency_cap" and r["parameter"].startswith("min_gap"):
                self.gaps[r["channel"]] = (int(r["value"]), r["rule_id"], r["severity"])
            elif r["category"] == "calling_hours" and r["parameter"] == "allowed_window" and _hhmm(r["value"]):
                self.windows[r["channel"]] = _hhmm(r["value"])
        # R007 (hard, regulatory): never outside the hard window, whatever the channel's softer limit says
        self.hard_window = self.windows.get("call", (8 * 60, 19 * 60))

    def describe(self, rule_id: str) -> str:
        r = self.rules.get(rule_id)
        return f"{rule_id} ({r['description'][:90].rstrip()})" if r else rule_id

    def _cap(self, table, bucket, channel):
        best, ids = None, []
        for b, c, v, rid in table:
            if b in ("ALL", bucket) and c in ("ALL", channel):
                if best is None or v < best:
                    best, ids = v, [rid]
                elif v == best:
                    ids.append(rid)
        return best, ids

    # ------------------------------------------------------------------ facts
    def facts(self, borrower: str, now: datetime) -> Facts:
        today = now.date().isoformat()
        since = (now.date() - timedelta(days=6)).isoformat()
        q = self.db.query
        accounts = [dict(r) for r in q("SELECT * FROM ds_account WHERE borrower_id=?", (borrower,))]
        person = dict(self.db.one("SELECT * FROM ds_person WHERE borrower_id=?", (borrower,)) or {})
        consent = dict(self.db.one("SELECT * FROM ds_consent WHERE borrower_id=?", (borrower,)) or {})
        contacts = [Contact(_dt(r["at"]), _norm_channel(r["channel"]), _norm_role(r["agent"]), r["disposition"] or "")
                    for r in q("SELECT at, agent, channel, disposition FROM ds_history WHERE borrower_id=? "
                               "AND substr(at,1,10) BETWEEN ? AND ?", (borrower, since, today))]
        for r in self.contact_log.recent(borrower, since, today):
            contacts.append(Contact(_dt(r["at"]) if r["at"] else now, _norm_channel(r["channel"]),
                                    _norm_role(r["role"] or r["purpose"]), "", "ours"))
        ptps = [dict(r) for r in q("SELECT * FROM ds_ptp WHERE borrower_id=?", (borrower,))]
        payments = [dict(r) for r in q("SELECT * FROM ds_payment WHERE borrower_id=? AND at >= ?",
                                       (borrower, (now - timedelta(days=3)).isoformat()))]
        f = Facts(borrower, now, today, accounts, person, consent, contacts, ptps, payments,
                  self.borrowers.get_lease(borrower))
        f.wrong_number = self.db.one("SELECT 1 FROM ds_history WHERE borrower_id=? AND disposition='wrong_number' "
                                     "LIMIT 1", (borrower,)) is not None
        if accounts:
            worst = max(accounts, key=lambda a: a["dpd"])
            f.dpd, f.bucket = worst["dpd"], worst["bucket"]
            f.legal = any(a["legal_flag"] for a in accounts)
            f.settlement = any(a["settlement_flag"] for a in accounts)
            f.restructure = any(a["restructure_flag"] for a in accounts)
        return f

    def _count(self, f: Facts, channel: str | None, since_date: str) -> int:
        return sum(1 for c in f.contacts if c.at.date().isoformat() >= since_date
                   and (channel is None or c.channel == channel))

    def current_owner(self, f: Facts):
        """(role, until) of whoever holds the ownership lease now: our own lease, or whoever made the
        latest contact in the last 24 hours (R038). Contacts later today count: the snapshot has happened."""
        best = (None, None)
        owner, until = f.lease
        if owner and until and _dt(until) > f.now:
            best = (owner, _dt(until))
        for c in f.contacts:
            u = c.at + timedelta(hours=24)
            if u > f.now and (best[1] is None or u > best[1]):
                best = (c.role, u)
        return best

    # ------------------------------------------------------------------ step 1: borrower-level guard
    def guard(self, f: Facts, event: dict) -> dict:
        now, today, et = f.now, f.today, event["type"]
        sup = (f.consent.get("suppression_reason") or "none")
        sup_from = (f.consent.get("suppression_from") or "")
        sup_active = sup != "none" and (not sup_from or sup_from[:10] <= today)

        if f.person.get("deceased") or (sup_active and sup == "deceased"):
            return _verdict("BLOCKED", ["R058"], "borrower is deceased: every outbound channel is blocked; "
                            "route to the legal-heir desk only", "SUPPRESSION")
        if sup_active and sup == "customer_request":
            return _verdict("BLOCKED", ["R059"], "customer asked us to stop: all channels blocked", "SUPPRESSION")
        if sup_active and sup == "complaint":
            hold_to = (_dt(sup_from[:10]) + timedelta(days=30)).date().isoformat() if sup_from else None
            if hold_to is None or today <= hold_to:
                return _verdict("BLOCKED", ["R060"], f"open complaint: recovery contact frozen until {hold_to} "
                                "(30-day grievance SLA)", "SUPPRESSION")

        if et != "PAYMENT_RECEIVED":              # the confirmation of a payment is the one contact allowed (R051)
            for p in f.payments:
                if p["status"] == "success" and not p["reversal"] and _dt(p["at"]) + timedelta(hours=48) > now:
                    return _verdict("BLOCKED", ["R066"], f"payment received {p['at']}: no contact for 48 hours "
                                    "pending reconciliation", "PAYMENT_HOLD")

        tomorrow = (now.date() + timedelta(days=1)).isoformat()
        open_ptps = [p for p in f.ptps if p["status"] == "open" and p["promised_date"] >= today]
        # R062 holds RECOVERY contact. A service reply is not recovery: confirming the very payment that
        # keeps a promise must still go out, so those events are not held.
        if open_ptps and et not in ("PAYMENT_RECEIVED", "SERVICE_REQUEST"):
            due_tomorrow = any(p["promised_date"] == tomorrow for p in open_ptps)
            if not (et == "PTP_DUE" and due_tomorrow):          # R063: the one reminder the day before
                p = min(open_ptps, key=lambda x: x["promised_date"])
                return _verdict("BLOCKED", ["R062"], f"open promise to pay due {p['promised_date']}: no recovery "
                                "contact until the day after", "OPEN_PTP")

        day_cap, day_ids = self._cap(self.day_caps, f.bucket, "ALL")
        used = self._count(f, None, today)
        if day_cap is not None and used >= day_cap:
            return _verdict("BLOCKED", day_ids + ["R033", "R034"], f"{used} contacts today, daily limit is {day_cap} "
                            "for this borrower across all channels and accounts (failed attempts count)", "DAILY_CAP")
        week_cap, week_ids = self._cap(self.week_caps, f.bucket, "ALL")
        used7 = self._count(f, None, (now.date() - timedelta(days=6)).isoformat())
        if week_cap is not None and used7 >= week_cap:
            return _verdict("BLOCKED", week_ids + ["R033"], f"{used7} contacts in 7 days, limit is {week_cap}",
                            "WEEKLY_CAP")

        gap, gid, _sev = self.gaps.get("ALL", (0, "R022", "soft"))
        past = [c.at for c in f.contacts if c.at <= now]
        if gap and past and now - max(past) < timedelta(minutes=gap):
            until = max(past) + timedelta(minutes=gap)
            return _verdict("DEFERRED", [gid], f"another contact {int((now - max(past)).total_seconds() // 60)} min "
                            f"ago; wait until {until.isoformat()}", "MIN_GAP", until.isoformat())
        return _verdict("OK", [], f"contacts today {used}/{day_cap}, last 7 days {used7}/{week_cap}, no hold or "
                        "suppression", "NONE")

    # ------------------------------------------------------------------ step 2: who, and on which channel
    def candidates(self, f: Facts, event: dict):
        et = event["type"]
        wanted = EVENT_ACTIONS.get(et, EVENT_ACTIONS["OVERDUE"])
        found, excluded = [], []
        ptp_owner = None
        if et == "PTP_DUE":
            due = [p for p in f.ptps if p["status"] == "open"
                   and p["promised_date"] == (f.now.date() + timedelta(days=1)).isoformat()]
            ptp_owner = _norm_role(due[0]["captured_by"]) if due else None
        for role in ROLES:
            row = self.matrix.get((f"{role}_agent", f.bucket))
            if role == "legal" and f.legal and (row is None or not row["allowed"] or not row["contact"]):
                row = self.matrix.get(("legal_agent", "90+"))            # "also allowed at any bucket when legal_flag=1"
            if row is None or not row["allowed"] or not row["contact"]:
                excluded.append({"role": role, "rule_ids": ["D12-matrix"],
                                 "why": f"{role}_agent may not contact bucket {f.bucket}"})
                continue
            if f.legal and role != "legal":
                excluded.append({"role": role, "rule_ids": ["R040"], "why": "legal flag: only the legal agent may contact"})
                continue
            if f.settlement and role not in ("negotiation",) and not (role == "legal" and f.legal):
                excluded.append({"role": role, "rule_ids": ["R041"], "why": "settlement flag: only negotiation may contact"})
                continue
            if f.restructure and role == "legal":
                excluded.append({"role": role, "rule_ids": ["R042"], "why": "restructure flag: legal action needs approval"})
                continue
            if role == "legal" and f.dpd < 91 and not f.legal:
                excluded.append({"role": role, "rule_ids": ["R075"], "why": "legal agent only at 90+ days or with the legal flag"})
                continue
            if et == "PTP_DUE":
                if role != ptp_owner:
                    excluded.append({"role": role, "rule_ids": ["R063"], "why": "only the agent that owns the promise sends its reminder"})
                    continue
                action = "ptp_reminder"
            else:
                have = row["actions"].split("|") + EXTRA_ACTIONS.get(role, [])
                match = [a for a in wanted if a in have]
                if not match:
                    excluded.append({"role": role, "rule_ids": ["D12-matrix"], "why": f"{role}_agent has no action for {et}"})
                    continue
                action = match[0]
            found.append({"role": role, "action": action, "rank": row["rank"], "channels": row["channels"].split("|")})
        if et == "PTP_BROKEN":                       # R064: ownership moves to negotiation
            for c in found:
                if c["role"] == "negotiation":
                    c["rank"] = 0
                    c["rule_ids"] = ["R064"]
        found.sort(key=lambda c: (c["rank"], ROLE_PRIORITY[c["role"]]))
        return found, excluded

    def _window_for(self, f: Facts, channel: str):
        start, end = self.hard_window
        req = _hhmm(f.consent.get("requested_window") or "")
        used_req = False
        if req:
            start, end, used_req = max(start, req[0]), min(end, req[1]), True
        return start, end, used_req

    def eval_channel(self, f: Facts, role: str, action: str, channel: str) -> dict:
        def blocked(ids, why):
            return {"channel": channel, "status": "BLOCKED", "rule_ids": ids, "reason": why}

        agent = CHANNEL_AGENT.get(channel)
        if agent is None:
            return blocked([], f"no {channel} agent is integrated")
        if agent not in self.registry:
            return blocked([], f"the {agent} agent is not registered")
        c, p, today = f.consent, f.person, f.today
        # eligibility
        if channel in PHONE_CHANNELS and not p.get("has_phone"):
            return blocked(["R069"], "no phone number on record")
        if channel == "email" and not p.get("has_email"):
            return blocked(["R070"], "no email on record")
        if channel == "whatsapp" and f.bucket == "90+":
            return blocked(["R072"], "WhatsApp is not used for 90+ accounts")
        if channel in PHONE_CHANNELS and p.get("shared_phone"):
            return blocked(["R056"], "phone shared with another borrower: verify identity before any debt discussion")
        if channel in PHONE_CHANNELS and f.wrong_number:
            return blocked(["R055"], "a wrong-number disposition quarantines this number for all agents")
        sup, sup_from = c.get("suppression_reason") or "none", c.get("suppression_from") or ""
        if sup == "dispute" and (not sup_from or sup_from[:10] <= today) and channel in ("call", "sms", "whatsapp"):
            return blocked(["R061"], "disputed debt: collection contact paused on this channel")
        # consent
        st = c.get(f"consent_{channel}") or "unknown"
        optout = c.get(f"optout_{channel}") or ""
        expiry = c.get("consent_expiry") or ""
        expired = bool(expiry) and expiry[:10] < today
        warnings = []
        if optout and optout[:10] <= today:
            return blocked(["R047"], f"borrower opted out of {channel} on {optout[:10]}")
        if st in ("denied", "revoked"):
            return blocked([CONSENT_RULE[channel]], f"{channel} consent is {st}")
        if st == "not_applicable":
            return blocked(["R069" if channel != "email" else "R070"], f"{channel} not applicable for this borrower")
        if channel == "whatsapp":
            if st != "granted":
                return blocked(["R045"], f"WhatsApp needs explicit granted consent; it is {st}")
            if expired:
                return blocked(["R048"], f"WhatsApp consent expired on {expiry[:10]} (treated as unknown)")
            if not (c.get("consent_source") or ""):
                return blocked(["R049"], "WhatsApp consent has no recorded source: unverifiable")
        else:
            if st == "unknown":
                warnings.append(f"{channel} consent unknown (allowed with a warning, {CONSENT_RULE[channel]})")
            if expired:
                warnings.append(f"consent expired on {expiry[:10]} (R048 warning)")
            if channel == "email" and not (c.get("consent_source") or ""):
                warnings.append("email consent has no source (R049 warning)")
        if channel in ("call", "sms") and (c.get("dnd_status") or "none") in ("fully_blocked", "partially_blocked"):
            eff = c.get("dnd_effective_from") or ""
            if (not eff or eff[:10] <= today) and action not in DND_OK:
                return blocked(["R050", "R051", "R053"], f"DND-registered ({c['dnd_status']}): no {channel} "
                               f"unless the purpose is transactional; '{action}' is not")
        # operating window (R007 hard, plus the borrower's own requested window R006)
        start, end, used_req = self._window_for(f, channel)
        t = f.now.hour * 60 + f.now.minute
        if not (start <= t < end):
            nxt = f.now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
            if t >= end:
                nxt += timedelta(days=1)
            ids = [WINDOW_RULE.get(channel, "R001"), "R007"] + (["R006"] if used_req else [])
            return {"channel": channel, "status": "DEFERRED", "rule_ids": ids, "defer_until": nxt.isoformat(),
                    "reason": f"outside the allowed contact window {start // 60:02d}:{start % 60:02d}-"
                              f"{end // 60:02d}:{end % 60:02d}; earliest {nxt.isoformat()}"}
        # per-channel frequency caps
        cap, ids = self._cap(self.day_caps, f.bucket, channel)
        used = self._count(f, channel, today)
        if cap is not None and used >= cap:
            return blocked(ids, f"{used} {channel} contacts today, limit {cap}")
        cap7, ids7 = self._cap(self.week_caps, f.bucket, channel)
        used7 = self._count(f, channel, (f.now.date() - timedelta(days=6)).isoformat())
        if cap7 is not None and used7 >= cap7:
            return blocked(ids7, f"{used7} {channel} contacts in 7 days, limit {cap7}")
        if channel == "call" and "call" in self.gaps:
            gap, gid, _ = self.gaps["call"]
            past = [x.at for x in f.contacts if x.channel == "call" and x.at <= f.now]
            if past and f.now - max(past) < timedelta(minutes=gap):
                until = max(past) + timedelta(minutes=gap)
                return {"channel": channel, "status": "DEFERRED", "rule_ids": [gid], "defer_until": until.isoformat(),
                        "reason": f"last call under {gap} min ago; earliest {until.isoformat()}"}
        # D13: this agent's budget on this channel
        res = self.capacity.get((f"{role}_agent", channel))
        if res is None:
            return blocked(["R092"], f"D13 has no resource for {role}_agent on {channel}")
        if f.bucket not in res["buckets"].split("|") and not (role == "legal" and f.legal):
            return blocked(["R092"], f"D13: {role}_agent on {channel} is not allowed for bucket {f.bucket}")
        raw = ("call", "ivr") if channel == "call" else (channel, channel)
        todays = self.db.one("SELECT COUNT(*) n FROM ds_history WHERE agent=? AND channel IN (?,?) "
                             "AND substr(at,1,10)=?", (f"{role}_agent", raw[0], raw[1], today))["n"]
        todays += self.db.one("SELECT COUNT(*) n FROM contact_log WHERE role=? AND channel=? AND date=? "
                              "AND status IN ('ATTEMPTING','SENT')", (role, CHANNEL_AGENT[channel], today))["n"]
        if todays >= res["daily_budget"]:
            return blocked(["R092"], f"D13 daily attempt budget used up ({todays}/{res['daily_budget']})")
        if res["spend_cap"] and (todays + 1) * res["cost"] > res["spend_cap"]:
            return blocked(["R092"], f"D13 daily spend cap of Rs {res['spend_cap']:.0f} would be exceeded")
        return {"channel": channel, "agent": agent, "status": "OK", "rule_ids": [], "warnings": warnings,
                "reason": f"consent {st}, inside window, {used}/{cap} today, budget {todays}/{res['daily_budget']}"}

    def plan(self, f: Facts, event: dict) -> dict:
        cands, excluded = self.candidates(f, event)
        considered, defers = [], []
        owner, until = self.current_owner(f)
        for cand in cands:
            role, action = cand["role"], cand["action"]
            handoff = None
            if owner and role != owner and action not in LEASE_EXEMPT:
                if ROLE_PRIORITY[role] < ROLE_PRIORITY[_norm_role(owner)]:
                    handoff = {"from": owner, "to": role, "rule_ids": ["R039", "A12"],
                               "why": f"{role} outranks {owner}, who holds the ownership lease until {until.isoformat()}"}
                else:
                    considered.append({"role": role, "action": action, "status": "BLOCKED", "rule_ids": ["R035", "R036"],
                                       "reason": f"{owner} is the active owner until {until.isoformat()}; contact by "
                                                 f"non-owner {role} is blocked"})
                    continue                      # the owner (or a higher-priority role) may still act: look further
            # From here the role is settled: if it has no usable channel the event is not handed to a
            # different role with a different intent.
            order = [c for c in PREFERENCE.get(role, ()) if c in cand["channels"]]
            results = [self.eval_channel(f, role, action, ch) for ch in order]
            ok = [r for r in results if r["status"] == "OK"]
            considered.append({"role": role, "action": action, "rank": cand["rank"], "channels": results,
                               "handoff": handoff})
            extra_ids = set(cand.get("rule_ids", [])) | set(handoff["rule_ids"] if handoff else [])
            if ok:
                return {"status": "OK", "role": role, "action": action,
                        "channel_agents": [CHANNEL_AGENT[r["channel"]] for r in ok],
                        "handoff": handoff, "considered": considered, "excluded": excluded,
                        "warnings": [w for r in ok for w in r.get("warnings", [])],
                        "rule_ids": sorted({x for r in results for x in r["rule_ids"]} | extra_ids)}
            defers += [r for r in results if r["status"] == "DEFERRED"]
            break
        if defers:
            first = min(defers, key=lambda r: r["defer_until"])
            return {"status": "DEFERRED", "defer_until": first["defer_until"], "rule_ids": first["rule_ids"],
                    "reason": first["reason"], "considered": considered, "excluded": excluded}
        ids = sorted({x for c in considered for r in (c.get("channels") or [c]) for x in r.get("rule_ids", [])}
                     | {x for e in excluded for x in e["rule_ids"]
                        if not considered or x != "D12-matrix"})   # the matrix is cited only when it is the whole reason
        why = "; ".join(
            [f"{c['role']}: " + ("; ".join(f"{r['channel']} {r['reason']}" for r in c["channels"]) if "channels" in c else c["reason"])
             for c in considered] + [f"{e['role']} excluded: {e['why']}" for e in excluded if not considered])
        return {"status": "SUPPRESSED", "rule_ids": ids, "reason": why or "no eligible agent",
                "considered": considered, "excluded": excluded}

    # ------------------------------------------------------------------ convenience: the whole verdict, no side effects
    def evaluate(self, borrower: str, event: dict) -> dict:
        f = self.facts(borrower, _dt(event["time"]))
        g = self.guard(f, event)
        if g["status"] != "OK":
            return {"guard": g, "plan": None, "final": g["status"]}
        p = self.plan(f, event)
        return {"guard": g, "plan": p, "final": p["status"]}
