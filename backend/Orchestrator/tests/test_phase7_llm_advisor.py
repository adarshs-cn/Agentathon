"""PHASE 7 integration test: the LLM advisor inside the monitor's catch-all branch.
No network is used except in the opt-in live test (RUN_LIVE_LLM=1 with a key set)."""
import io
import json
import os

import pytest

from orchestrator.agents.fault_injector import FaultInjector
from orchestrator.llm import deepseek
from orchestrator.llm.deepseek import DeepSeekAdvisor, build_advisor
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS
from orchestrator.supervisor import Supervisor
from tests.helpers import make_event

ALLOWED = ["RESUME", "REROUTE_CHANNEL", "QUARANTINE"]
FAULT = {"type": "TIMEOUT", "detail": "whatsapp agent never answered"}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(content=None, raises=None, capture=None):
    def opener(req, timeout=None):
        if capture is not None:
            capture.append({"headers": dict(req.header_items()), "body": json.loads(req.data), "timeout": timeout})
        if raises:
            raise raises
        return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
    return opener


def advisor(**kw):
    return DeepSeekAdvisor("test-key", opener=fake_opener(**kw))


# ------------------------------------------------------------------ the advisor on its own
def test_valid_choice_is_returned_with_its_diagnosis():
    a = advisor(content='Sure. {"action": "REROUTE_CHANNEL", "diagnosis": "Provider is slow."}')
    assert a.advise(FAULT, "whatsapp", "B1", ALLOWED) == ("REROUTE_CHANNEL", "Provider is slow.")


@pytest.mark.parametrize("content", [
    '{"action": "SEND_ANYWAY", "diagnosis": "x"}',      # not on the menu
    '{"action": "ESCALATE", "diagnosis": "x"}',         # a real action, but not on THIS menu
    "I think you should retry.",                          # no JSON at all
    '{"action": ',                                        # broken JSON
    "",
])
def test_anything_outside_the_menu_or_unparseable_is_declined(content):
    assert advisor(content=content).advise(FAULT, "whatsapp", "B1", ALLOWED)[0] is None


@pytest.mark.parametrize("exc", [TimeoutError("slow"), OSError("network down"), ValueError("bad")])
def test_network_failure_is_swallowed(exc):
    assert advisor(raises=exc).advise(FAULT, "whatsapp", "B1", ALLOWED) == (None, None)


def test_the_prompt_lists_only_the_allowed_actions_and_leaks_no_borrower_identifier():
    seen = []
    a = DeepSeekAdvisor("secret-key-123", opener=fake_opener(content='{"action":"RESUME"}', capture=seen))
    a.advise(FAULT, "whatsapp", "ACCOUNT-98765", ["RESUME", "QUARANTINE"])
    prompt = seen[0]["body"]["messages"][0]["content"]
    assert "RESUME" in prompt and "QUARANTINE" in prompt and "REROUTE_CHANNEL" not in prompt and "ESCALATE" not in prompt
    assert "ACCOUNT-98765" not in prompt                                         # no borrower identifier leaves the system
    assert "secret-key-123" not in prompt                                        # the key goes in a header only
    assert seen[0]["headers"]["Api-subscription-key"] == "secret-key-123"
    assert seen[0]["body"]["model"] == deepseek.MODEL and seen[0]["timeout"] == 10.0
    # regression: 400 tokens let hidden reasoning eat the whole budget and truncate the JSON answer
    assert seen[0]["body"]["max_tokens"] >= 1500


def test_build_advisor_needs_a_key_in_the_environment(monkeypatch):
    monkeypatch.setattr(deepseek, "load_env", lambda *a, **k: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert build_advisor() is None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert isinstance(build_advisor(), DeepSeekAdvisor)


def test_the_key_is_never_written_anywhere_in_the_project():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    assigned = re.compile(r"(DEEPSEEK|SARVAM)_API_KEY\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{8,}")
    hits = [str(p) for p in root.rglob("*") if p.is_file() and ".venv" not in p.parts
            and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts and p.name != ".env"
            and p.suffix in {".py", ".md", ".txt", ".example", ".ini", ".json", ".yml", ".yaml", ".sh"}
            and assigned.search(p.read_text(errors="ignore"))]
    assert hits == []
    assert (root / ".env.example").read_text().strip().endswith("DEEPSEEK_API_KEY=")   # the template holds no value


# ------------------------------------------------------------------ inside the supervisor
def supervisor_with(adv, script):
    sup = Supervisor(injector=FaultInjector(script), advisor=adv)
    sup.seed_borrowers(SAMPLE_BORROWERS)
    return sup


def test_an_unscripted_timeout_is_resolved_by_the_llm_when_it_chooses_resume():
    sup = supervisor_with(advisor(content='{"action": "RESUME", "diagnosis": "Transient timeout."}'), {("B1", 1): "TIMEOUT"})
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    assert sup.ctx.bus.get("e1")["outcome"] == "CONTACTED" and sup.ctx.contacts.sent_total() == 1
    m = next(r for r in sup.ctx.decisions.for_event("e1") if r["node"] == "monitor")
    assert m["data"]["advisor"] == "llm" and "Transient timeout." in m["text"]


def test_the_llm_cannot_authorise_a_second_contact():
    """After a crash-after-send the provider says SENT; the advisor must not even be asked."""
    class Tripwire:
        def advise(self, *a, **k):
            raise AssertionError("advisor must not be consulted when a message may have gone out")
    sup = supervisor_with(Tripwire(), {("B1", 1): "CRASH_AFTER_SEND"})
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    assert sup.ctx.contacts.sent_total() == 1 and sup.ctx.bus.get("e1")["outcome"] == "CONTACTED"


def test_when_the_llm_is_down_the_borrower_is_quarantined_not_lost():
    sup = supervisor_with(advisor(raises=OSError("down")), {("B1", 1): "TIMEOUT"})
    sup.publish(make_event("e1", account_id="B1"))
    sup.run_until_empty()
    b = sup.ctx.borrowers.load("B1")
    assert sup.ctx.bus.get("e1")["outcome"] == "ESCALATED" and b["status"] == "QUARANTINED" and b["owner"] is None


# ------------------------------------------------------------------ opt-in live call
deepseek.load_env()          # the key normally lives in the git-ignored .env, not the shell


@pytest.mark.skipif(not (os.environ.get("RUN_LIVE_LLM") == "1"
                         and (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("SARVAM_API_KEY"))),
                    reason="live LLM test: set RUN_LIVE_LLM=1 and DEEPSEEK_API_KEY")
def test_live_deepseek_answers_from_the_menu():
    adv = build_advisor()
    action, note = adv.advise(FAULT, "whatsapp", "x", ALLOWED)
    assert action in ALLOWED and note
