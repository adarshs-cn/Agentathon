"""The supervisor graph.

`build_graph(ctx, checkpointer, stage)` wires the LangGraph StateGraph. `stage` lets the
graph be built up phase by phase (and tested at each phase): nodes introduced after
`stage` are left out, and any edge that would lead to one ends the run instead.

  stage 1  validate_event, load_customer, close_event
  stage 2  + guardrails, route
  stage 3  + assign, the channel agent nodes, validate_output, commit, release
  stage 4  + monitor, recover                      (the complete graph)
"""
from __future__ import annotations

from importlib import import_module

from langgraph.graph import END, START, StateGraph

from orchestrator.context import Context
from orchestrator.nodes import edges
from orchestrator.state.models import GraphState

FINAL_STAGE = 4
AGENT_STAGE = 3

# node name -> (stage introduced, module in orchestrator.nodes, factory name)
PLAIN_NODES = {
    "validate_event": (1, "intake", "make_validate_event"),
    "load_customer": (1, "intake", "make_load_customer"),
    "close_event": (1, "finish", "make_close_event"),
    "guardrails": (2, "guardrails", "make_guardrails"),
    "route": (2, "routing", "make_route"),
    "assign": (3, "execution", "make_assign"),
    "validate_output": (3, "execution", "make_validate_output"),
    "commit": (3, "finish", "make_commit"),
    "release": (3, "finish", "make_release"),
    "monitor": (4, "recovery", "make_monitor"),
    "recover": (4, "recovery", "make_recover"),
}


def build_graph(ctx: Context, checkpointer=None, stage: int = FINAL_STAGE):
    agents = ctx.registry.names()

    def node_stage(n: str) -> int:
        return AGENT_STAGE if n in agents else PLAIN_NODES[n][0]

    def present(n: str) -> bool:
        return node_stage(n) <= stage

    def target(n: str):
        return n if present(n) else END

    g = StateGraph(GraphState)

    # ---- nodes
    for name, (st, mod, fac) in PLAIN_NODES.items():
        if st <= stage:
            fn = getattr(import_module(f"orchestrator.nodes.{mod}"), fac)(ctx)
            g.add_node(name, ctx.instrument(name, fn))
    if stage >= AGENT_STAGE:
        make_agent_node = import_module("orchestrator.nodes.execution").make_agent_node
        for a in agents:
            g.add_node(a, ctx.instrument(a, make_agent_node(ctx, a)))

    # ---- edges
    def edge(src, dst):
        if present(src):
            g.add_edge(src, target(dst))

    def cond(src, fn, dests):
        if present(src):
            g.add_conditional_edges(src, fn, {d: target(d) for d in dests})

    g.add_edge(START, "validate_event")
    cond("validate_event", edges.after_validate_event, ["load_customer", "close_event"])
    edge("load_customer", "guardrails")
    cond("guardrails", edges.after_guardrails, ["route", "close_event"])
    cond("route", edges.after_route, ["assign", "close_event"])
    cond("assign", edges.after_assign, agents + ["close_event"])
    if stage >= AGENT_STAGE:
        for a in agents:
            g.add_edge(a, "validate_output")
    cond("validate_output", edges.after_validate_output, ["monitor", "commit"])
    edge("monitor", "recover")
    cond("recover", edges.after_recover, agents + ["commit"])
    edge("commit", "release")
    edge("release", "close_event")
    g.add_edge("close_event", END)
    return g.compile(checkpointer=checkpointer)
