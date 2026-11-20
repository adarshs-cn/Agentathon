"""STEP 1: a graph with ONE node + a checkpointer.

The node loads a borrower's data into the shared state.
"""
import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
from trace_util import run_traced, show_saved

# ---- fake borrower table (production: D1, D2, D4, D6) ----
BORROWER_DB = {
    "B1": {"dpd": 5,  "legal_flag": False, "last_contact": None},
    "B2": {"dpd": 45, "legal_flag": False, "last_contact": None},
}

# ---- the shared state: this dict is what flows through the graph ----
class State(TypedDict, total=False):
    event: dict       # what just happened (input)
    borrower: dict    # filled by load_borrower

# ---- node 1 ----
def load_borrower(state: State) -> dict:
    acc = state["event"]["account_id"]
    return {"borrower": {"account_id": acc, **BORROWER_DB[acc]}}

def build(checkpointer):
    g = StateGraph(State)
    g.add_node("load_borrower", load_borrower)
    g.add_edge(START, "load_borrower")
    g.add_edge("load_borrower", END)
    return g.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    DB = "journey.db"
    if os.path.exists(DB): os.remove(DB)

    saver = SqliteSaver(sqlite3.connect(DB, check_same_thread=False))
    graph = build(saver)
    run_traced(graph, {"event": {"type": "DUE_SOON", "account_id": "B1"}}, thread_id="B1")

    # simulate a restart: brand-new graph object, same database file
    saver2 = SqliteSaver(sqlite3.connect(DB, check_same_thread=False))
    graph2 = build(saver2)
    show_saved(graph2, "B1")
