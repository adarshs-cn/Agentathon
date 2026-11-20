"""The contract between the supervisor and a channel agent (email, whatsapp, voice).

The other teams own the real agents. To plug one in, write a thin adapter that subclasses
`ChannelAgent` and implements two methods:

  execute(request)  perform the contact. Return a dict with at least
                    {"customer_id", "status": "DONE", "outcome": "CONTACTED"}.
                    May raise (crash) or hang (timeout) or return garbage; the supervisor
                    is built to survive all of that.
  lookup(key)       "did a contact with this idempotency key go out?"
                    -> "SENT" | "NOT_SENT" | "UNKNOWN".
                    This is how the supervisor resolves a crash it cannot otherwise
                    interpret, without ever risking a second message.

ASSUMPTION: the real agents can accept an idempotency key and answer a status lookup
(or the adapter can emulate that from the provider's message API). If they cannot, a
crash with an unconfirmed send must be treated as UNKNOWN, and the supervisor will
quarantine the borrower rather than risk a double contact.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


class AgentCrash(Exception):
    """The agent died while handling a request."""


class AgentTimeout(Exception):
    """The agent did not answer in time."""


@dataclass(frozen=True)
class ContactRequest:
    customer_id: str
    purpose: str            # reminder | negotiation | servicing | legal
    template: str           # which pre-drafted template the agent should use
    idempotency_key: str    # '<customer>|<event>' ('<customer>|<date>' in simple mode); the agent/provider must dedupe on it
    event_id: str
    time: str
    role: str = ""          # the role agent acting (dataset mode): reminder | negotiation | servicing | legal
    action: str = ""        # D12 action, e.g. ptp_capture (dataset mode)
    context: tuple = ()     # (key, value) pairs a message may use: masked name, EMI, dues... never raw personal data
    account_id: str = ""    # the loan this contact is about (the event's account)

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("account_id"):
            d.pop("account_id", None)
        if not d.get("context"):
            d.pop("context", None)          # keep the logged request unchanged when no message text is built
        else:
            d["context"] = {k: v for k, v in d["context"] if k in ("emi", "dues", "dpd", "amount")}   # no contact details in the trace
        return d


class ChannelAgent(ABC):
    name: str = ""

    @abstractmethod
    def execute(self, request: ContactRequest) -> dict: ...

    @abstractmethod
    def lookup(self, idempotency_key: str) -> str: ...

    def sent_message(self, idempotency_key: str):
        """The message that went out under this key, if the provider can say (used after a crash). Optional."""
        return None

    def template_for(self, purpose: str) -> str:
        return f"{self.name}/{purpose}_v1"
