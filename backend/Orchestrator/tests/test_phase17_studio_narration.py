"""Phase 17: Workflow Studio. The graph shape comes from the compiled LangGraph; every node streams a trace-pad text
(LLM for five nodes, rule check for the rest) while it is shown as working; the text is saved for hover; the LLM sees
derived facts only; a failing LLM falls back to the rule check."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.ui.app import create_dashboard_app
from orchestrator.ui.narrator import LLM_NODES, Narrator, iter_sse, llm_facts, prompt_for, rule_lines
from orchestrator.ui.state import DemoState

REAL = Path(__file__).resolve().parent.parent / "data" / "portfolio" / "Multi_Agent_Supervisor_Dataset"
real = pytest.mark.skipif(not REAL.exists(), reason="portfolio dataset not present")


class FakeLLM:
    def __init__(self, fail=False):
        self.prompts, self.fail = [], fail

    def stream(self, prompt, timeout=8.0):
        self.prompts.append(prompt)
        if self.fail:
            raise TimeoutError("no answer")
        yield "think", "weighing the facts... "
        for w in ["- The ", "rules ", "decided ", "this."]:
            yield "say", w


@pytest.fixture(scope="module")
def studio(tmp_path_factory):
    st = DemoState(tmp_path_factory.mktemp("studio"), REAL, mode="scenario")
    llm = FakeLLM()
    st.narrator = Narrator(llm=llm, word_delay_s=0)
    return st, llm, TestClient(create_dashboard_app(st))


@real
def test_graph_is_the_compiled_langgraph(studio):
    st, _, c = studio
    g = c.get("/api/graph").json()
    compiled = st.sup.graph.get_graph()
    assert {n["id"] for n in g["nodes"]} == set(compiled.nodes)
    assert {(e["from"], e["to"]) for e in g["edges"]} == {(e.source, e.target) for e in compiled.edges}
    assert len(g["edges"]) == 25 and sum(e["conditional"] for e in g["edges"]) == 16
    assert {n["id"] for n in g["nodes"] if n["llm"]} == set(LLM_NODES)
    assert g["narrator"] == "llm"


@real
def test_every_node_streams_its_trace_while_working_and_it_is_saved(studio):
    st, llm, c = studio
    q = st.runs.subscribe()
    st.runs.start("demo-13", pace_ms=0, wait=True)                   # a fault + recovery path: most nodes visited
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    st.runs.unsubscribe(q)
    steps = c.get("/api/scenario/demo-13/steps").json()["steps"]
    assert steps and all(s["trace"] and s["trace"]["text"] for s in steps)
    for s in steps:
        assert s["trace"]["source"] == ("llm" if s["node"] in LLM_NODES else "rules"), s["node"]
    nodes = {s["node"] for s in steps}
    assert {"monitor", "recover"} <= nodes
    # order: for each seq, start -> trace pieces -> end
    for s in steps:
        idx = [i for i, (n, p) in enumerate(msgs) if p.get("seq") == s["seq"] and n in ("step", "trace")]
        kinds = [msgs[i][0] if msgs[i][0] == "trace" else msgs[i][1]["phase"] for i in idx]
        assert kinds[0] == "start" and kinds[-1] == "end" and "trace" in kinds[1:-1], (s["node"], kinds)
    # a step's trace is complete before the next step starts (the UI waits for the stream to finish)
    last_trace = {}
    for i, (n, p) in enumerate(msgs):
        if n == "trace":
            last_trace[p["seq"]] = i
    for i, (n, p) in enumerate(msgs):
        if n == "step" and p["phase"] == "start" and p["seq"] - 1 in last_trace:
            assert last_trace[p["seq"] - 1] < i
    starts = {p["node"]: p["llm"] for n, p in msgs if n == "step" and p["phase"] == "start"}
    assert starts["route"] is True and starts["guardrails"] is False


@real
def test_the_llm_sees_no_identifiers(studio):
    st, llm, c = studio
    for n in (1, 2, 3, 8, 9, 10, 11, 12, 14, 15):
        try:
            st.runs.start(f"demo-{n:02d}", pace_ms=0, wait=True)
        except Exception:  # noqa: BLE001 - some are locked until their pair ran; irrelevant here
            pass
    assert llm.prompts
    ids = set()
    for r in st.reader.query("SELECT p.customer_id, p.name_masked, p.phone_masked, a.account_id FROM demo_event d "
                             "JOIN customer p ON p.customer_id=d.customer_id JOIN account a ON a.customer_id=d.customer_id"):
        ids |= {r["customer_id"], r["name_masked"], r["phone_masked"], r["account_id"]}
    for p in llm.prompts:
        assert not any(i and i in p for i in ids)
        assert not re.search(r"BRW\d+|ACC\d+|XXXXXX\d+|\*\*\*", p)


def test_rule_lines_and_prompt_are_built_from_state_alone():
    st = {"event": {"type": "OVERDUE", "time": "2026-10-31T10:00:00", "account_id": "BRW00001"},
          "borrower": {"account_id": "BRW00001", "dpd": 12, "channels": ["whatsapp"], "commitments": [], "status": "ACTIVE",
                       "owner": None, "legal_flag": False},
          "guard": {"ok": True}, "decision": {"role": "reminder", "agent": "whatsapp", "fallbacks": ["email"], "rule_ids": ["R001"]}}
    for node in ("validate_event", "load_customer", "guardrails", "route", "assign", "whatsapp", "validate_output",
                 "commit", "release", "close_event"):
        lines = rule_lines(node, None, st)
        assert len(lines) >= 2 and lines[-1].startswith("=> "), node
    f = llm_facts("route", None, st)
    assert "BRW00001" not in json.dumps(f) and "WhatsApp" in f["decision"] and "Reminder" in f["decision"]
    p = prompt_for("route", f)
    assert "ALREADY decided" in p and "AT MOST 2 short sentences" in p and "35 words" in p


def test_a_failing_llm_falls_back_to_the_rule_check():
    st = {"event": {"type": "OVERDUE", "time": "2026-10-31T10:00:00"}, "borrower": {"dpd": 3, "channels": []},
          "decision": {"role": "reminder", "agent": "whatsapp"}}
    got = []
    t = Narrator(llm=FakeLLM(fail=True), word_delay_s=0).narrate("route", None, st, lambda k, x: got.append(x))
    assert t["source"] == "rules-fallback" and "rule check" in t["text"] and "".join(got).strip()
    t2 = Narrator(llm=None, word_delay_s=0).narrate("route", None, st, lambda k, x: None)
    assert t2["source"] == "rules"


def test_stream_parser_splits_thinking_from_answer():
    lines = [b'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}', b"",
             b'data: {"choices":[{"delta":{"content":"Yes."}}]}', b"data: [DONE]", b'data: {"choices":[{"delta":{"content":"x"}}]}']
    assert list(iter_sse(lines)) == [("think", "hmm"), ("say", "Yes.")]


class ChattyLLM:
    def stream(self, prompt, timeout=8.0):
        for w in ["The ", "rules ", "chose ", "WhatsApp. ", "It is ", "reachable [R004]. ", "Also a third ", "sentence. ", "And a fourth."]:
            yield "say", w


def test_the_answer_is_cut_to_two_sentences():
    got = []
    t = Narrator(llm=ChattyLLM(), word_delay_s=0).narrate("route", None, {"event": {}, "borrower": {}, "decision": {}},
                                                             lambda k, x: got.append(x))
    assert t["text"] == "The rules chose WhatsApp. It is reachable [R004]."
    assert "".join(got).strip() == t["text"]


def test_words_are_paced_for_reading():
    import time as _t
    n = Narrator(llm=None, word_delay_s=0.01)
    t0 = _t.time()
    t = n.narrate("release", None, {"event": {}}, lambda k, x: None)
    words = len(t["text"].split())
    assert _t.time() - t0 >= words * 0.01 * 0.8


@real
def test_the_live_monitor_never_calls_the_llm(tmp_path):
    live = DemoState(tmp_path / "live", REAL, mode="live", faults="none", autostart=False)
    demo = DemoState(tmp_path / "demo", REAL, mode="scenario")
    spy = FakeLLM()
    demo.narrator = Narrator(llm=spy, word_delay_s=0)
    create_dashboard_app(live, demo)
    live.sup.ctx.db.execute("UPDATE monitor_pool SET next_due=0")
    from datetime import datetime
    r = live.monitor.tick(datetime.now().replace(hour=10, minute=0))
    assert r["processed"] == 15 and spy.prompts == [] and live.narrator is None
