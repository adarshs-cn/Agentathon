Multi-agent journey supervisor

Business context
Objective
Users
Scope
Why agentic
What makes it hard
Functional requirements
Non-functional requirements
Data provided
Tools the agent must call
Guardrails
Acceptance criteria
Business context
CN is moving from single bots to many agents acting on the same borrowers: reminders, negotiation, servicing, compliance. Without coordination, two agents will contact one borrower on the same day with conflicting messages, and no one can reconstruct why.

Objective
One coherent, auditable journey per borrower, however many agents are involved.

Users
Platform engineering; AI Labs; operations; auditors.

Scope
In
shared borrower state, routing, conflict resolution, budgets, fault recovery, tracing.

Out
the individual agents' logic.

Why agentic
Once several agents act on the same borrower, coordination is the product. A workflow engine handles fixed paths; the supervisor must handle crashes, loops and conflicts it was never scripted for.

What makes it hard
Injected faults: an agent crashes mid-conversation, another loops, a third returns malformed output, two fire on the same borrower at once.

Functional requirements
Hold shared state per borrower: active owner, last contact, open commitments.
Decide which agent acts next on each event.
Resolve conflicts so one agent owns a borrower at a time.
Enforce per-borrower and per-agent budgets.
Detect and recover from agent faults without losing state.
Produce a full trace for any account on request.
Non-functional requirements
Routing decision under 100 ms. Survives restart of any agent.

Data provided
Dataset	Volume	Notes
D1, D2, D4, D6	20,000 accounts	
Stub agents (MT-02 only)	4	reminder, negotiation, servicing, legal; can be swapped for other teams' agents
Event simulator	1 simulated day	public fault script of 2, hidden script of 5
Tools the agent must call
Shared state store, agent registry, event bus, contact log, tracing.

Guardrails
One active owner per borrower at a time. Every routing decision logged with its reason.

Acceptance criteria
Over the hidden simulated day: zero conflicting contacts, all 5 faults recovered without losing borrower state, and a complete trace for any account judges pick.
