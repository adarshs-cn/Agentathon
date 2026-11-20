"""Narrator: the streamed "trace pad" text for every node of a Workflow Studio run.

Decisions are ALWAYS made by the rules. The narrator only explains them, after the node has run:

  * five nodes (validate_event, route, assign, monitor, recover) are explained by the LLM, which is given the derived
    facts and the decision the rules already made, and asked to reason about why it follows. Its hidden reasoning
    ("think") and its answer ("say") are both streamed.
  * every other node streams its real rule check, line by line, built from the node's own state.
  * if the LLM is unavailable, slow to start, or fails before saying anything, the node falls back to its rule check.

Privacy: the LLM sees only derived facts (event type, time of day, days past due, channels, rule ids and their text,
roles, fault type). Never a borrower id, account id, name, phone, email or message body. `llm_facts` is the only
thing sent, and a test asserts it holds no identifier.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Iterator, Optional

from orchestrator.ui import reasons

LLM_NODES = ("validate_event", "route", "assign", "monitor", "recover")
CHANNEL_NODES = ("whatsapp", "email", "voice")

NODE_WORDS = {
    "validate_event": ("Validate event", "Checks the incoming event is complete and known"),
    "load_borrower": ("Load borrower", "Opens the borrower's file"),
    "guardrails": ("Guardrails", "Borrower-level safety checks (D12)"),
    "route": ("Route", "Chooses the role and channel from the D12 matrix"),
    "assign": ("Assign", "Takes the ownership lock for the chosen agent"),
    "whatsapp": ("WhatsApp agent", "Channel agent (stub: nothing is really sent)"),
    "email": ("Email agent", "Channel agent (stub: nothing is really sent)"),
    "voice": ("Voice agent", "Channel agent (stub: nothing is really sent)"),
    "validate_output": ("Validate output", "Checks the agent's reply"),
    "monitor": ("Monitor", "Diagnoses a fault with the provider"),
    "recover": ("Recover", "Chooses the safe recovery"),
    "commit": ("Commit", "Saves the contact and the ownership lease"),
    "release": ("Release", "Releases the lock"),
    "close_event": ("Close event", "Records the final outcome"),
    "__start__": ("Start", "An event arrives"),
    "__end__": ("End", "The run is finished"),
}

Emit = Callable[[str, str], None]          # (kind: "think" | "say", text)


# ---------------------------------------------------------------------------- facts
def _ch(c):
    return reasons.CHANNEL_WORDS.get(c, c or "none")


def _role(r):
    return reasons.ROLE_WORDS.get(r, (r or "none").capitalize())


def _rule_texts(ids) -> list[str]:
    out = []
    for rid in ids or []:
        h, d = reasons.label(rid, None)
        out.append(f"{rid}: {h}" + (f" - {d}" if d else ""))
    return out


def llm_facts(node: str, db, st: dict) -> dict:
    """The only data the LLM receives: a small set of derived facts for THIS step, and the decision. No identifiers."""
    ev, b, g, d = st.get("event") or {}, st.get("borrower") or {}, st.get("guard") or {}, st.get("decision") or {}
    out, f, rec = st.get("outcome") or {}, st.get("fault") or {}, st.get("recovery") or {}
    event = f"{reasons.EVENT_WORDS.get(ev.get('type'), ev.get('type'))} at {(ev.get('time') or '')[11:16]}"
    if node == "validate_event":
        rejected = out.get("status") == "REJECTED"
        return {"event": event,
                "checks": "id, type, borrower and time are present; the type is one the supervisor handles; the borrower exists",
                "decision": f"rejected: {out.get('reason')}" if rejected else "accepted; the borrower's previous run state is cleared"}
    if node == "route":
        facts = {"event": event, "days_past_due": b.get("dpd"), "legal_flag": bool(b.get("legal_flag")),
                 "open_promises_to_pay": len(b.get("commitments") or []),
                 "reachable_on": [_ch(c) for c in b.get("channels") or []]}
        if d.get("agent"):
            facts["decision"] = (f"{_role(d.get('role'))} agent, on {_ch(d.get('agent'))}"
                                 + (f"; backups: {', '.join(_ch(c) for c in d.get('fallbacks') or [])}" if d.get("fallbacks") else "")
                                 + (f"; ownership moves from {_role(d['handoff']['from'])} to {_role(d['handoff']['to'])}"
                                    if d.get("handoff") else ""))
        else:
            facts["decision"] = f"no agent may act now ({(out.get('status') or '').lower()}): {out.get('reason') or d.get('reason')}"
        blocked = []
        for c in d.get("considered") or []:
            for x in c.get("channels") or []:
                if x.get("status") != "OK" and x.get("rule_ids"):
                    blocked.append(f"{_role(c.get('role'))} on {_ch(x.get('channel'))}: {', '.join(x['rule_ids'])}")
        if blocked:
            facts["options_ruled_out"] = blocked[:4]
        facts["rules"] = _rule_texts(d.get("rule_ids") or out.get("rule_ids"))[:4]
        return facts
    if node == "assign":
        if out.get("status") == "BLOCKED":
            return {"decision": "lock not taken: another agent took this borrower first", "rule": "one owner at a time (R035-R038)"}
        facts = {"decision": f"ownership lock taken for the {_role(d.get('role'))} agent on {_ch(d.get('agent'))}",
                 "rule": "only one agent may contact a borrower at a time (R035-R038)"}
        if d.get("handoff"):
            facts["ownership_change"] = f"{_role(d['handoff']['from'])} to {_role(d['handoff']['to'])} (higher priority role)"
        return facts
    fault = (f"the {_ch(d.get('agent'))} agent {reasons.FAULT_WORDS.get(f.get('type') or '', 'had a problem')}"
             if f else f"the {_ch(d.get('agent'))} agent had a fault")
    provider = reasons.PROVIDER_WORDS.get(rec.get("provider_state"), "unknown")
    if node == "monitor":
        return {"what_went_wrong": fault, "attempt": st.get("attempt"), "provider_confirms_the_message": provider,
                "recommended_recovery": reasons.RECOVERY_WORDS.get(rec.get("action"), rec.get("action")),
                "recommended_by": "the LLM advisor" if rec.get("advisor") == "llm" else "the recovery rules"}
    if node == "recover":
        effect = {"RESUME": "the same agent is called again; nothing had been sent, so no duplicate is possible",
                  "RESTART_SKIP_CURRENT": "the contact is recorded as made and the agent is not called again, so the borrower "
                                          "gets exactly one message",
                  "REROUTE_CHANNEL": f"the borrower is handed to the next channel ({_ch(d.get('agent'))})",
                  "ESCALATE": "no channel is left, so a person takes over",
                  "QUARANTINE": "the outcome cannot be verified, so automation stops and a person takes over"}
        return {"action_applied": reasons.RECOVERY_WORDS.get(rec.get("action"), rec.get("action")),
                "effect": effect.get(rec.get("action"), "the run continues safely"),
                "because_provider_says_the_message": provider}
    return {"event": event}


STEP_FOCUS = {
    "validate_event": "whether the incoming event can be processed",
    "route": "which agent and channel act, or why none may",
    "assign": "who now owns the borrower",
    "monitor": "what went wrong with the agent and what the provider confirmed about the message",
    "recover": "the recovery applied and what it means for the borrower",
}


def prompt_for(node: str, facts: dict) -> str:
    name, _ = NODE_WORDS.get(node, (node, ""))
    return (
        f"You explain one step ('{name}') of a debt-collection supervisor to a collections manager.\n"
        f"Focus: {STEP_FOCUS.get(node, 'what this step decided')}.\n"
        "The rules have ALREADY decided; the decision is in FACTS. Do not change it, do not speculate, do not add anything "
        "that is not in FACTS.\n"
        "Answer in AT MOST 2 short sentences, 35 words in total. Sentence 1: what was decided. Sentence 2: the single most "
        "important reason, with its rule id in brackets if one is given. Plain English, no lists, no preamble, no markdown.\n\n"
        f"FACTS: {json.dumps(facts, ensure_ascii=False, default=str)}")


def two_sentences(text: str) -> tuple[str, bool]:
    """The text up to the end of its second sentence, and whether it was cut."""
    count = 0
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1] in " \n\"'") and not text[max(0, i - 2):i + 1].lower().endswith(("e.g", "i.e")):
            count += 1
            if count == 2:
                return text[:i + 1], i + 1 < len(text.rstrip())
    return text, False


# ---------------------------------------------------------------------------- rule traces
def rule_lines(node: str, db, st: dict, ms: float | None = None) -> list[str]:
    ev, b, g, d = st.get("event") or {}, st.get("borrower") or {}, st.get("guard") or {}, st.get("decision") or {}
    out, f, rec, res = st.get("outcome") or {}, st.get("fault"), st.get("recovery") or {}, st.get("result") or {}
    did, _ = reasons.sentence(node, db, st, ms)
    ids = out.get("rule_ids") or g.get("rule_ids") or d.get("rule_ids") or []
    L: list[str] = []
    if node == "validate_event":
        L += [f"Reading the incoming event: {reasons.EVENT_WORDS.get(ev.get('type'), ev.get('type'))} at {(ev.get('time') or '')[11:16]}.",
              "Required fields present (id, type, borrower, time)... " + ("no" if out.get("status") == "REJECTED" else "yes"),
              "Event type is one the supervisor handles... yes", "Borrower exists in the portfolio... yes"]
    elif node == "load_borrower":
        L += ["Opening the borrower's file...",
              f"Days past due: {b.get('dpd', 0)}", f"Legal flag: {'set' if b.get('legal_flag') else 'not set'}",
              f"Reachable on: {', '.join(_ch(c) for c in b.get('channels') or []) or 'no channel'}",
              f"Open promises to pay: {len(b.get('commitments') or [])}",
              f"Current owner: {_role(b.get('owner')) if b.get('owner') else 'nobody'}",
              f"Automation status: {b.get('status')}"]
    elif node == "guardrails":
        L += ["Running the borrower-level safety checks (D12)...",
              "Deceased, stop requests, complaints, disputes... ", "Payment in the last 48 hours, open promise to pay...",
              "Daily and weekly contact limits, minimum gap between contacts..."]
        L += (["All clear: nothing stops a contact."] if g.get("ok") else
              [f"Stop: {reasons.headline(db, ids, g.get('reason') or '')}" + (f" [{', '.join(ids)}]" if ids else "")])
    elif node == "route":
        L.append("Looking up the D12 role x overdue-stage matrix...")
        for c in (d.get("considered") or [])[:5]:
            if c.get("channels"):
                parts = [f"{_ch(x.get('channel'))} {'ok' if x.get('status') == 'OK' else 'no' + (' [' + ', '.join(x.get('rule_ids') or []) + ']' if x.get('rule_ids') else '')}"
                         for x in c["channels"]]
                L.append(f"{_role(c.get('role'))}: " + "; ".join(parts))
            else:
                L.append(f"{_role(c.get('role'))}: {c.get('status') or 'not allowed'}"
                         + (f" [{', '.join(c.get('rule_ids') or [])}]" if c.get("rule_ids") else ""))
    elif node == "assign":
        L += ["Asking for the ownership lock on this borrower...",
              "Only one agent may contact a borrower at a time [R035-R038]."]
    elif node in CHANNEL_NODES:
        L += [f"Calling the {_ch(node)} agent (a stub: nothing is really sent)...", f"Attempt {st.get('attempt') or 1}."]
        if f:
            L.append(f"The agent {reasons.FAULT_WORDS.get(f.get('type'), 'had a problem')}: {f.get('detail') or f.get('type')}.")
        elif res:
            L.append(f"Reply: status {res.get('status')}, outcome {res.get('outcome')}" + (f" in {round(ms)} ms." if ms is not None else "."))
    elif node == "validate_output":
        L.append("Checking the reply has the borrower, a status and an outcome...")
        L.append(f"Fault found: {f.get('type')}." if f else "Reply is well formed; the contact is marked SENT.")
    elif node == "monitor":
        L += ["Asking the provider whether the message actually went out...",
              f"Provider says: {reasons.PROVIDER_WORDS.get(rec.get('provider_state'), rec.get('provider_state'))}.",
              f"Decision: {reasons.RECOVERY_WORDS.get(rec.get('action'), rec.get('action'))}."]
    elif node == "recover":
        L.append(f"Applying the recovery: {reasons.RECOVERY_WORDS.get(rec.get('action'), rec.get('action'))}.")
    elif node == "commit":
        L += ["Writing the contact to the log...", "Granting a 24-hour ownership lease to the role that made contact [R038]."
              if res.get("status") == "DONE" else "No contact was made: holding for a person."]
    elif node == "release":
        L.append("Releasing the lock so the next event can be handled...")
    elif node == "close_event":
        L.append(f"Closing the event. Outcome: {reasons.OUTCOME_WORDS.get(out.get('status'), out.get('status'))}.")
        if ids:
            L.append("Rules cited: " + ", ".join(ids) + ".")
    L.append(f"=> {did}")
    return L


# ---------------------------------------------------------------------------- the narrator
class Narrator:
    """Streams one node's trace. `word_delay_s` paces every word on screen (rule text, and the LLM's answer, which the
    model sends in bursts, is re-paced word by word so it reads smoothly)."""

    def __init__(self, llm=None, word_delay_s: float = 0.06, first_token_timeout_s: float = 8.0):
        self.llm = llm                        # an object with .stream(prompt) -> iterator of (kind, text); None = rules only
        self.word_delay_s = word_delay_s
        self.first_token_timeout_s = first_token_timeout_s

    def uses_llm(self, node: str) -> bool:
        return self.llm is not None and node in LLM_NODES

    def _type(self, text: str, emit: Emit, kind: str = "say", delay: float | None = None) -> None:
        delay = self.word_delay_s if delay is None else delay
        for piece in re.findall(r"\S+\s*|\s+", text):
            emit(kind, piece)
            if delay:
                time.sleep(delay)

    def _rules(self, node, db, st, ms, emit, delay) -> str:
        lines = rule_lines(node, db, st, ms)
        for i, line in enumerate(lines):
            self._type(line + ("\n" if i < len(lines) - 1 else ""), emit, delay=delay)
        return "\n".join(lines)

    def narrate(self, node: str, db, st: dict, emit: Emit, ms: float | None = None, word_delay_s: float | None = None) -> dict:
        """Stream the trace through `emit` and return what was streamed: {source, think, text}."""
        delay = self.word_delay_s if word_delay_s is None else word_delay_s
        if not self.uses_llm(node):
            return {"source": "rules", "think": "", "text": self._rules(node, db, st, ms, emit, delay)}
        think, say = [], ""
        shown = 0
        try:
            for kind, piece in self.llm.stream(prompt_for(node, llm_facts(node, db, st)), self.first_token_timeout_s):
                if kind != "say":
                    think.append(piece)
                    emit("think", piece)              # the reasoning meter: not re-paced, it is only counted on screen
                    continue
                say += piece
                capped, cut = two_sentences(say.lstrip())
                if cut:
                    ready = capped
                else:                                 # only whole words go on screen while the model is still talking
                    k = capped.rfind(" ")
                    ready = capped[:k + 1] if k >= 0 else ""
                if len(ready) > shown:
                    self._type(ready[shown:], emit, delay=delay)
                    shown = len(ready)
                if cut:
                    break                             # never more than two sentences on screen
        except Exception:  # noqa: BLE001 - narration must never break a run
            pass
        final, _ = two_sentences(say.lstrip())
        if len(final) > shown:                        # the last word(s) the model sent
            self._type(final[shown:], emit, delay=delay)
        text = final.strip()
        if text:
            return {"source": "llm", "think": "".join(think), "text": text}
        emit("say", "(model unavailable, showing the rule check)\n")
        return {"source": "rules-fallback", "think": "".join(think),
                "text": "(model unavailable, showing the rule check)\n" + self._rules(node, db, st, ms, emit, delay)}


def build_narrator(advisor=None, mode: Optional[str] = None) -> Narrator:
    """LLM narration when a key is configured (and MT02_NARRATOR is not 'rules'), else rules only."""
    import os
    mode = (mode or os.environ.get("MT02_NARRATOR") or "llm").lower()
    llm = advisor if (advisor is not None and mode != "rules" and hasattr(advisor, "stream")) else None
    return Narrator(llm=llm)


def iter_sse(lines: Iterator[bytes]) -> Iterator[tuple[str, str]]:
    """Parse an OpenAI-style streaming response into (kind, text) pieces."""
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
        except ValueError:
            continue
        if delta.get("reasoning_content"):
            yield "think", delta["reasoning_content"]
        if delta.get("content"):
            yield "say", delta["content"]
