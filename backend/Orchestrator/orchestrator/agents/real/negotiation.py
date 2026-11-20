"""Real Negotiation Agent: places an outbound one-way voice call via Twilio.

Wraps `voicebot.handle_call` wholesale: its safety guard (only DEMO_OVERRIDE_NUMBER /
ALLOWED_NUMBERS, never a real/synthetic borrower number), idempotency, and Sarvam/fallback
script generation are untouched. This adapter only translates a `ContactRequest` into the
payload shape `handle_call` expects, and translates its result back into the shape the
supervisor requires from a ChannelAgent.
voicebot.py's own idempotency only dedupes a repeat of the SAME borrower's call; it does not
limit how many DIFFERENT borrowers get called in a burst. A fast-moving event source (e.g. the
simulated-day clock releasing many events in a short window) can otherwise place one real call
per eligible borrower with no ceiling — every one of them lands on the same DEMO_OVERRIDE_NUMBER.
MAX_REAL_CALLS (env MT02_MAX_REAL_CALLS, default 5) is a hard per-process cap: once reached,
further negotiation events fail closed (AgentCrash, no call attempted) instead of placing one.
"""
from __future__ import annotations

import os

from orchestrator.agents.base import AgentCrash, ChannelAgent, ContactRequest
from orchestrator.agents.real import voicebot


class NegotiationAgent(ChannelAgent):
    """The IVR voicebot for the negotiation role: places a real Twilio call."""

    def __init__(self, injector=None):
        self.name = "voice"
        self.injector = injector
        self._outbox: dict[str, str] = {}   # idempotency_key -> "SENT" | "NOT_SENT"
        self._sent_text: dict[str, str] = {}
        self._placed = 0
        self._max_calls = int(os.environ.get("MT02_MAX_REAL_CALLS", "5"))

    def execute(self, req: ContactRequest) -> dict:
        if self._placed >= self._max_calls:
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"real-call cap reached ({self._placed}/{self._max_calls}); "
                              f"raise MT02_MAX_REAL_CALLS to place more")
        ctx = dict(req.context)
        payload = {
            "borrower_id": req.account_id,
            "account_id": req.account_id,
            "name": ctx.get("name", "Customer"),
            "phone": ctx.get("to_phone", ""),
            "language": "en",
            "ptp_amount": ctx.get("amount", ""),
            "ptp_date": ctx.get("ptp_date", ""),
        }
        res = voicebot.handle_call("negotiation", payload, wait=False)
        if not res.get("ok"):
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"voice call {res.get('status')}: {res.get('reason')}")
        self._outbox[req.idempotency_key] = "SENT"
        if res.get("status") not in ("dry_run", "skipped_duplicate"):   # only count a real, newly-placed call
            self._placed += 1
        if res.get("script"):
            self._sent_text[req.idempotency_key] = res["script"]
        return {"account_id": req.account_id, "status": "DONE", "outcome": "CONTACTED",
                "channel": "voice", "provider_ref": res.get("call_sid") or res.get("idempotency_key"),
                "message": res.get("script")}

    def sent_message(self, idempotency_key: str):
        return self._sent_text.get(idempotency_key)

    def lookup(self, idempotency_key: str) -> str:
        return self._outbox.get(idempotency_key, "UNKNOWN")

    def template_for(self, purpose: str) -> str:
        return f"ivr_script/{purpose}_v1"
