"""DeepSeek recovery advisor, served through Sarvam's gateway.

The key is read from the DEEPSEEK_API_KEY environment variable (SARVAM_API_KEY also works),
optionally loaded from a git-ignored .env file. It is never written to a file or logged.

What the model sees: the fault type, the channel agent's name, and a menu. It does NOT see
the borrower's account id or any borrower data: it does not need them to choose a recovery
action, and borrower identifiers should not leave our systems.

Failure is always safe: any error, timeout, malformed answer or out-of-menu choice returns
(None, None) and the monitor quarantines the borrower instead.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable, Optional

from orchestrator.config import load_env

URL = "https://api.sarvam.ai/v2/chat/completions"
MODEL = "deepseekv4.1-flash-1017"
MAX_TOKENS = 2000

ACTION_HELP = {
    "RESUME": "Call the same channel agent again. Safe: the provider confirmed nothing was sent.",
    "REROUTE_CHANNEL": "Hand the borrower to the next channel agent. Safe: nothing was sent.",
    "ESCALATE": "No channel is left to try: send the borrower to human review.",
    "QUARANTINE": "Stop automation for this borrower and keep all state for a human.",
}


class DeepSeekAdvisor:
    def __init__(self, api_key: str, url: str = URL, model: str = MODEL, timeout: float = 10.0,
                 opener: Callable = urllib.request.urlopen):
        self._key, self.url, self.model, self.timeout, self._open = api_key, url, model, timeout, opener

    def build_prompt(self, fault: dict, agent: str, allowed: list[str]) -> str:
        menu = "\n".join(f"- {a}: {ACTION_HELP.get(a, '')}" for a in allowed)
        return (
            "A channel agent used by a collections supervisor hit a fault that no rule covers.\n"
            f"Fault type: {fault.get('type')}. Detail: {fault.get('detail')}. Channel agent: {agent}.\n"
            "The provider confirmed that NO message was sent.\n\n"
            f"Choose the single safest recovery action from this menu:\n{menu}\n\n"
            'Reply with JSON only: {"action": "<one of the menu names>", '
            '"diagnosis": "<two sentences for an audit trace>"}')

    def advise(self, fault: dict, agent: str, customer_id: str, allowed: list[str]):
        # max_tokens covers the model's hidden reasoning AND its answer. At 400 the reasoning
        # alone used it all about half the time (finish_reason=length, empty or cut-off JSON).
        payload = {"model": self.model, "temperature": 0.2, "max_tokens": MAX_TOKENS,
                   "reasoning_effort": "low",
                   "messages": [{"role": "user", "content": self.build_prompt(fault, agent, allowed)}]}
        try:
            req = urllib.request.Request(
                self.url, data=json.dumps(payload).encode(), method="POST",
                headers={"api-subscription-key": self._key, "Content-Type": "application/json"})
            with self._open(req, timeout=self.timeout) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            action = data.get("action")
            note = str(data.get("diagnosis") or "").strip() or None
            return (action if action in allowed else None), note
        except Exception:  # noqa: BLE001 - the advisor must never be able to break recovery
            return None, None


    def stream(self, prompt: str, timeout: float = 8.0, max_tokens: int = MAX_TOKENS):
        """Stream a narration: yields ("think", text) for the model's reasoning and ("say", text) for its answer.
        Used only by the Workflow Studio narrator, which explains decisions the rules already made. The budget covers the
        hidden reasoning too: at 700 tokens the answer was cut off on the larger nodes (monitor), so it uses MAX_TOKENS."""
        from orchestrator.ui.narrator import iter_sse
        payload = {"model": self.model, "temperature": 0.3, "max_tokens": max_tokens, "reasoning_effort": "low",
                   "stream": True, "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), method="POST",
            headers={"api-subscription-key": self._key, "Content-Type": "application/json"})
        with self._open(req, timeout=timeout) as r:
            yield from iter_sse(r)


def build_advisor() -> Optional[DeepSeekAdvisor]:
    """An advisor if a key is configured, else None (the monitor then uses rules only)."""
    load_env()
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("SARVAM_API_KEY")
    return DeepSeekAdvisor(key) if key else None
