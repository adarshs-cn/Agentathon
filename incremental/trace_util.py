"""Helpers that print what LangGraph does. Same for every step."""
import json
from rich.console import Console
from rich.panel import Panel

c = Console()

def pj(d):
    return json.dumps(d, indent=2, default=str)

def run_traced(graph, inp, thread_id):
    """Run the graph and print the state update every node returns."""
    cfg = {"configurable": {"thread_id": thread_id}}
    c.rule(f"RUN thread_id={thread_id}")
    c.print(Panel(pj(inp), title="INPUT state", border_style="cyan"))
    for i, chunk in enumerate(graph.stream(inp, cfg, stream_mode="updates"), 1):
        for node, update in chunk.items():
            c.print(Panel(pj(update), title=f"step {i}: node '{node}' RETURNED (partial update)",
                          border_style="green"))
    snap = graph.get_state(cfg)
    c.print(Panel(pj(snap.values), title="FINAL state (merged)", border_style="yellow"))
    return cfg

def show_saved(graph, thread_id):
    """Read state back from the checkpoint store, without running anything."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = graph.get_state(cfg)
    c.rule(f"RETRIEVE thread_id={thread_id} from the database")
    c.print(Panel(pj(snap.values), title="state loaded from checkpoint", border_style="magenta"))
    c.print(f"next node to run: {snap.next or 'none (finished)'}")
    hist = list(graph.get_state_history(cfg))
    c.print(f"checkpoints stored for this thread: {len(hist)}")
    for h in reversed(hist):
        c.print(f"  step={h.metadata.get('step')}  source={h.metadata.get('source')}  "
                f"wrote={list((h.metadata.get('writes') or {}).keys())}  next={list(h.next)}")
