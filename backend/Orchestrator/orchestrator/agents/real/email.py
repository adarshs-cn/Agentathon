"""Real Email Agent: sends an actual email via Brevo.

Unlike voicebot.py, `BrevoEmailSender` (email_sender.py, copied from the email_bot project)
is a pure transport: it delivers whatever body text it's given and does no drafting of its
own. So this adapter builds the message with our own `orchestrator.agents.messages.render()`
(the same ₹-formatted, masked-contact template the email stub already uses for preview) and
hands the rendered body to `BrevoEmailSender.send()`.

Its own allowlist/override safety guard (DEMO_OVERRIDE_EMAIL / ALLOWED_EMAILS -- never a real
dataset address by accident) is reused unchanged.

MAX_REAL_EMAILS (env MT02_MAX_REAL_EMAILS, default 10) is the same per-process volume cap
applied to the voice agent, for the same reason: a burst of many different borrowers' events
in a short window would otherwise send one real email per borrower with no ceiling.
"""
from __future__ import annotations

import os

from orchestrator.agents.base import AgentCrash, ChannelAgent, ContactRequest
from orchestrator.agents.messages import render
from orchestrator.agents.real.email_sender import BrevoEmailSender, EmailBlocked, EmailConfigError


class RealEmailAgent(ChannelAgent):
    """Sends a real email for whichever role resolves to the "email" channel."""

    def __init__(self, injector=None, sender=None):
        self.name = "email"
        self.injector = injector
        self._sender = sender or BrevoEmailSender()
        self._outbox: dict[str, str] = {}   # idempotency_key -> "SENT" | "NOT_SENT"
        self._sent_text: dict[str, str] = {}
        self._placed = 0
        self._max_emails = int(os.environ.get("MT02_MAX_REAL_EMAILS", "10"))

    def execute(self, req: ContactRequest) -> dict:
        if self._placed >= self._max_emails:
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"real-email cap reached ({self._placed}/{self._max_emails}); "
                              f"raise MT02_MAX_REAL_EMAILS to send more")
        ctx = dict(req.context)
        rendered = render(req.action or req.purpose, "email", ctx)
        to = ctx.get("to_email") or rendered.get("to") or ""
        try:
            res = self._sender.send("email", to, rendered["body"], account_id=req.account_id,
                                      idempotency_key=req.idempotency_key)
        except (EmailBlocked, EmailConfigError) as e:
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"email {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - any transport failure is a fault, not a silent drop
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"email send failed: {type(e).__name__}: {e}")
        if res.get("disposition") != "sent":
            self._outbox[req.idempotency_key] = "NOT_SENT"
            raise AgentCrash(f"email send disposition={res.get('disposition')}")
        self._outbox[req.idempotency_key] = "SENT"
        self._placed += 1
        self._sent_text[req.idempotency_key] = rendered
        # "message" must be the full {channel, to, subject, body} dict, matching the stub's
        # convention -- contacts.mark_sent() does (message or {}).get("to") on it, so passing
        # just the body string here crashes validate_output AFTER the real send already went
        # out (contact_log row stays stuck ATTEMPTING; no duplicate send on the retries that
        # follow, since they resume past the already-completed agent_node, but it's still a bug).
        return {"account_id": req.account_id, "status": "DONE", "outcome": "CONTACTED",
                "channel": "email", "provider_ref": req.idempotency_key,
                "template": req.template, "message": rendered}

    def sent_message(self, idempotency_key: str):
        return self._sent_text.get(idempotency_key)

    def lookup(self, idempotency_key: str) -> str:
        return self._outbox.get(idempotency_key, "UNKNOWN")

    def template_for(self, purpose: str) -> str:
        return f"email_template/{purpose}_v1"
