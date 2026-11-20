"""Stub channel agents standing in for the real email / WhatsApp / voice (IVR) agents.

They deliver nothing for real: "delivery" means writing the idempotency key into an
in-memory outbox that plays the role of the provider. That outbox is also what `lookup`
reads, exactly like asking a real provider "did message <key> go out?".

To integrate a teammate's real agent, write a ChannelAgent adapter (see agents/base.py)
and register it instead of the stub; nothing else in the supervisor changes.
"""
from __future__ import annotations

from orchestrator.agents.base import AgentCrash, AgentTimeout, ChannelAgent, ContactRequest
from orchestrator.agents.fault_injector import FaultInjector


class StubChannelAgent(ChannelAgent):
    def __init__(self, name: str, injector: FaultInjector | None = None):
        self.name = name
        self.injector = injector
        self.outbox: dict[str, str] = {}      # idempotency key -> provider message ref
        self.sent_text: dict[str, dict] = {}  # idempotency key -> the message text that went out
        self.calls = 0
        self.lookup_available = True          # set False to simulate a provider that cannot answer

    def execute(self, req: ContactRequest) -> dict:
        self.calls += 1
        fault = self.injector.next_fault(req.customer_id) if self.injector else None
        if fault == "CRASH_BEFORE_SEND":
            raise AgentCrash(f"{self.name} agent died before sending")
        if fault == "TIMEOUT":
            raise AgentTimeout(f"{self.name} agent never answered")
        if fault == "MALFORMED":
            return {"oops": "garbage"}
        if fault == "LOOP":
            return {"customer_id": req.customer_id, "status": "IN_PROGRESS"}
        ref = self._deliver(req)
        if req.context:
            from orchestrator.agents.messages import render
            self.sent_text.setdefault(req.idempotency_key, render(req.action or req.purpose, self.name, dict(req.context)))
        if fault == "CRASH_AFTER_SEND":
            raise AgentCrash(f"{self.name} agent died after sending")
        out = {"customer_id": req.customer_id, "status": "DONE", "outcome": "CONTACTED",
               "channel": self.name, "provider_ref": ref, "template": req.template}
        if req.idempotency_key in self.sent_text:         # the text a real agent would have sent
            out["message"] = self.sent_text[req.idempotency_key]
        return out

    def _deliver(self, req: ContactRequest) -> str:
        # Providers dedupe on the idempotency key: a repeated call returns the same message.
        if req.idempotency_key not in self.outbox:
            self.outbox[req.idempotency_key] = f"{self.name}-{len(self.outbox) + 1:06d}"
        return self.outbox[req.idempotency_key]

    def sent_message(self, idempotency_key: str):
        return self.sent_text.get(idempotency_key)

    def lookup(self, idempotency_key: str) -> str:
        if not self.lookup_available:
            return "UNKNOWN"
        return "SENT" if idempotency_key in self.outbox else "NOT_SENT"


class WhatsAppAgent(StubChannelAgent):
    def __init__(self, injector=None):
        super().__init__("whatsapp", injector)

    def template_for(self, purpose: str) -> str:
        return f"wa_template/{purpose}_v1"


class EmailAgent(StubChannelAgent):
    def __init__(self, injector=None):
        super().__init__("email", injector)

    def template_for(self, purpose: str) -> str:
        return f"email_template/{purpose}_v1"


class VoiceAgent(StubChannelAgent):
    """The IVR voicebot: places a call that plays a pre-drafted script."""
    def __init__(self, injector=None):
        super().__init__("voice", injector)

    def template_for(self, purpose: str) -> str:
        return f"ivr_script/{purpose}_v1"


def default_agents(injector: FaultInjector | None = None) -> list[StubChannelAgent]:
    """One shared injector so call numbers count per borrower across all channels."""
    return [WhatsAppAgent(injector), EmailAgent(injector), VoiceAgent(injector)]
