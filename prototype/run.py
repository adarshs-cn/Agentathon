"""Run the prototype, print the step-by-step trace, and write graph.html."""
from rich.console import Console
from rich.table import Table

from supervisor import build
from visualize import write_html

graph, store = build()
graph.invoke({}, config={"recursion_limit": 500})

console = Console()
t = Table(title="Node-by-node execution")
for c in ("#", "node", "account", "what happened"):
    t.add_column(c, overflow="fold")
for s in store.timeline:
    t.add_row(str(s["i"]), s["node"], s["account_id"] or "-", s["note"])
console.print(t)

counts = {}
for c in store.contact_log:
    counts[c["account_id"]] = counts.get(c["account_id"], 0) + 1
console.print("\nContacts per borrower:", counts)
console.print("Double contacts:", [a for a, n in counts.items() if n > 1] or "none")
console.print("Final status:", {k: v["status"] for k, v in store.borrowers.items()})

mermaid = graph.get_graph().draw_mermaid()
open("graph.mmd", "w").write(mermaid)
write_html(mermaid, store.timeline, "graph.html")
console.print("\nWrote graph.mmd and graph.html")
