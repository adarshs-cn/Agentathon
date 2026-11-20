"""LLM helper: DeepSeek only. The key is read from the DEEPSEEK_API_KEY environment
variable (SARVAM_API_KEY also works, since the model is served via Sarvam's gateway). If it is missing or a call fails, callers fall back
to deterministic rules."""
import json
import os
import re
import urllib.request

URL = "https://api.sarvam.ai/v2/chat/completions"
MODEL = "deepseekv4.1-flash-1017"

ACTION_HELP = {
    "RESUME": "Relaunch the agent on this borrower; nothing was sent yet, so it is safe to retry.",
    "RESTART_SKIP_CURRENT": "Do not contact this borrower again; finish the record from the contact log.",
    "REROUTE": "Hand the borrower to human review.",
    "QUARANTINE": "Stop the agent, keep state, take no further action on this borrower.",
}


def _key():
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("SARVAM_API_KEY")


def enabled():
    return bool(_key())


def decide_recovery(fault, agent, account_id, sent, allowed):
    """Returns (action, diagnosis) or (None, None). The action is only accepted
    if it is in the allowed menu."""
    if not enabled():
        return None, None
    menu = "\n".join(f"- {a}: {ACTION_HELP[a]}" for a in allowed)
    prompt = (
        f"A stub agent hit an unscripted fault.\n"
        f"Fault: {fault}. Agent: {agent}. Borrower: {account_id}. "
        f"Borrower already contacted before the fault: {sent}.\n\n"
        f"Choose the single safest recovery action from this menu:\n{menu}\n\n"
        f'Reply with JSON only: {{"action": "<one of the menu names>", '
        f'"diagnosis": "<two sentences for an audit trace>"}}')
    payload = {"model": MODEL, "temperature": 0.2, "max_tokens": 400,
               "reasoning_effort": "low",
               "messages": [{"role": "user", "content": prompt}]}
    try:
        req = urllib.request.Request(
            URL, data=json.dumps(payload).encode(), method="POST",
            headers={"api-subscription-key": _key(),
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        action = data.get("action")
        return (action if action in allowed else None), data.get("diagnosis")
    except Exception:
        return None, None
