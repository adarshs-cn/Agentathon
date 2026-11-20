"""Shared test helpers."""
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from orchestrator.config import RECURSION_LIMIT


def make_event(id="e1", type="DUE_SOON", account_id="B1", time="2026-11-20T09:00:00", **extra):
    ev = {"id": id, "type": type, "account_id": account_id, "time": time}
    ev.update(extra)
    return ev


def new_checkpointer():
    return SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))


def thread_cfg(account_id):
    return {"configurable": {"thread_id": account_id}, "recursion_limit": RECURSION_LIMIT}


def run(graph, event):
    """Run one event through the graph on its account's thread; returns the final state."""
    return graph.invoke({"event": event}, thread_cfg(event["account_id"]))
