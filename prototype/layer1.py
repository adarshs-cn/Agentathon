"""Layer 1: route an event to ONE agent and log why. Nothing else."""

# 1. Borrower data (in production this comes from D1/D2/D4/D6)
BORROWERS = {
    "B1": {"dpd": 5,  "legal_flag": False},
    "B2": {"dpd": 45, "legal_flag": False},
    "B3": {"dpd": 95, "legal_flag": True},
}

# 2. Stub agents: each just says what it would do
def reminder(acc):    return f"reminder sent to {acc}"
def negotiation(acc): return f"negotiation offer sent to {acc}"
def legal(acc):       return f"legal notice sent to {acc}"

AGENTS = {"reminder": reminder, "negotiation": negotiation, "legal": legal}

# 3. The routing rules: first match wins. Returns (agent, reason)
def route(b):
    if b["legal_flag"]:
        return "legal", "legal flag is set"
    if b["dpd"] > 30:
        return "negotiation", f"DPD {b['dpd']} is above 30"
    return "reminder", f"DPD {b['dpd']} is 30 or below"

# 4. The supervisor loop: event -> look up -> route -> call -> log why
decision_log = []

def handle(event):
    acc = event["account_id"]
    borrower = BORROWERS[acc]
    agent, reason = route(borrower)
    result = AGENTS[agent](acc)
    decision_log.append({"account": acc, "event": event["type"],
                         "agent": agent, "reason": reason, "result": result})

for e in [{"type": "DUE_SOON", "account_id": a} for a in BORROWERS]:
    handle(e)

for row in decision_log:
    print(row)
