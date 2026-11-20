# MT-02 System Architecture
## Multi-Agent Journey Supervisor

**Last updated:** 2026-11-19
**Team:** CODE - CODING OUTDATED ERA
**Problem:** MT-02 — Supervisor-Orchestrated Context Management with Conflict Resolution

---

## 1. Overview

Three layers:

1. **Stub agents** — stateless workers (`reminder`, `negotiation`, `servicing`, `legal`). Each handles one borrower at a time. They know nothing about each other. Agent logic is out of scope; they can be swapped for other teams' agents through the agent registry.
2. **Supervisor** — a LangGraph `StateGraph`. It is the **only writer** of shared state. It routes events, enforces guardrails and budgets, validates agent output, executes recovery, and writes the trace.
3. **Monitor agent** — started by the supervisor. It watches stub-agent health and *requests* recovery. It never changes state itself.

**Design principle: rules for safety and speed, LLM for judgment.**

| Concern | Handled by |
|---|---|
| One owner, one contact/day, budgets, consent | Deterministic code (hard guardrails, LLM can never override) |
| Normal routing | Deterministic rules (< 100 ms) |
| Ambiguous routing, unknown/compound faults, loop diagnosis, conflict priority, NEEDS_REVIEW summaries | LLM, choosing only from a fixed menu of safe actions |

The supervisor's job is coordination; the stub agents' job is execution.

---

## 2. Data and assumptions

Provided: **D1, D2, D4, D6** (20,000 accounts), 4 stub agents, an event simulator (1 simulated day; public fault script of 2, hidden script of 5).

The previous draft used D7 (payment feed), D10 (consent) and D12 (contact caps), which are **not provided**. Until confirmed, treat them as assumptions:

| Field | Source | Default if absent |
|---|---|---|
| `dpd_bucket`, balance, legal flag | D1 | required |
| `open_commitments` (PTPs) | D6 | empty list |
| Consent per channel | not provided | assume consent = True |
| Per-borrower daily contact cap | not provided | 1 contact/day |
| Per-agent daily cap | not provided | configurable (default: unlimited, set per run) |
| Payment events | event simulator | none |

All timestamps and timeouts use the **simulated clock**, not wall time.

---

## 3. State design

### 3.1 BorrowerState (per account, persisted to SQLite after every borrower)

```python
@dataclass
class BorrowerState:
    account_id: str
    active_owner: str | None        # agent currently holding this borrower
    owner_since: datetime | None
    last_contact: datetime | None
    last_contact_channel: str | None
    open_commitments: list[PTP]     # from D6
    contacts_today: int
    contact_budget_today: int       # per-borrower cap
    agent_attempt_counts: dict      # {agent: attempts} for loop detection
    status: Literal["ACTIVE", "NEEDS_REVIEW", "QUARANTINED"]
    dpd_bucket: str                 # from D1
    legal_flag: bool
    consent_flags: dict
```

The trace is **not** stored inside this record (see section 10).

### 3.2 SupervisorSharedState (global, single writer = supervisor)

```python
@dataclass
class AgentExecutionState:
    agent_id: str
    status: Literal["IDLE","RUNNING","CRASHED","LOOPING","MALFORMED","QUARANTINED"]
    current_borrower: str | None    # written BEFORE agent starts Bx
    last_committed: str | None      # written AFTER Bx fully completes
    last_heartbeat: datetime | None # simulated clock
    fault_count: int
    contacts_today: int             # per-agent budget counter
    contact_budget_today: int | None

@dataclass
class SupervisorSharedState:
    agents: dict[str, AgentExecutionState]
    run_id: str
    run_date: date
```

### 3.3 Other persisted stores

| Store | Purpose | Notes |
|---|---|---|
| **Event bus** | Pending + held events | Persisted in SQLite (not in-memory) so queued events survive a supervisor restart |
| **Agent registry** | Which agents exist, what each handles, health, adapter | Standard adapter interface so agents can be swapped |
| **Contact log** | Append-only record of every contact attempt | Idempotency keys; the source of truth for "was this borrower already contacted?" |
| **Decision log** | Append-only record of every routing decision and fault | Local source of truth for the trace (see section 10) |

### 3.4 Single-writer rule

Only the supervisor writes `BorrowerState` and `SupervisorSharedState`. The monitor, stub agents and LLM only **read** or **request**. This prevents two components overwriting each other or relaunching the same agent twice.

---

## 4. Event flow

```
Event Simulator → Event Bus (persisted)
                      │
                      ▼
            Supervisor (LangGraph)
   consume → guardrails → route → assign (lock + contact-log intent)
        → execute agent → validate output → commit → release → check queue
                      ▲
        Monitor agent ─┘ (reports health, requests recovery)
```

| Event | Source | Supervisor action |
|---|---|---|
| `CONTACT_REQUESTED` | Simulator | Route through rules |
| `PAYMENT_RECEIVED` | Simulator | Route to Servicing, update commitments |
| `PTP_BROKEN` | D6 check | Route to Negotiation |
| `FAULT_INJECTED` | Fault script | Handled via detection, not directly |
| `AGENT_HEARTBEAT` | Stub agent | Update heartbeat, feed loop detection |

---

## 5. Routing

### 5.1 Guardrails (always first, always deterministic)

```python
def route(event, state):
    if state.status != "ACTIVE":
        return skip("borrower_needs_review_or_quarantined")
    if state.active_owner is not None:
        return queue_event(event, "active_owner_conflict")
    if same_day_contact_blocked(state):            # contacts_today >= cap, or cooldown
        return skip("daily_contact_limit")
    if agent_budget_exhausted(target_agent):       # checked again after choosing agent
        return skip("agent_budget_exhausted")
    if state.consent_flags.get(event.channel) is False:
        return skip("no_consent")
    ...
```

### 5.2 Routing rules (specific cases first, DPD rules last)

Order matters: first match wins.

1. `legal_flag` set → `legal` (compliance override)
2. `PAYMENT_RECEIVED` → `servicing`
3. `PTP_BROKEN` → `negotiation`
4. Open PTP still active → skip (`ptp_active_no_contact`)
5. DPD 90+ → `legal`
6. DPD 30–90 and a reminder already sent → `negotiation`
7. DPD SMA / 0–30 → `reminder`
8. No match → LLM fallback

The previous draft checked DPD first, so a payment on a 0–30 borrower would have gone to Reminder. This order fixes that.

### 5.3 LLM fallback (off the hot path)

The rules cover the normal path in well under 100 ms. When no rule matches:
- The event is **held** with the safe default (`HOLD_PENDING_LLM`) so routing latency is never blocked.
- The LLM receives a compact context (borrower summary, last 5 contact outcomes, available agents) and returns a structured decision.
- Confidence below 0.5 → skip with `llm_low_confidence_safe_default`.
- The LLM can only pick an agent from the registry; the guardrails in 5.1 are re-checked before assignment.

---

## 6. Ownership, conflicts and budgets

### 6.1 One owner at a time
- `assign_agent` sets `active_owner` under a transaction. A second event for the same borrower is **queued**, not dropped.
- When the owner releases, the supervisor dequeues the next held event and runs it through routing again (including the daily-contact rule).

### 6.2 Same-day contact policy
The owner lock only protects while an agent is running. To prevent two agents contacting the same borrower minutes apart:
- `contacts_today` and `last_contact` are checked on every assignment.
- Default: one contact per borrower per day (configurable).
- A queued event that would breach the limit is skipped with a logged reason, not executed.

### 6.3 Queue priority
Queued events are ordered by priority, not FIFO: `legal` > `servicing` (payment) > `negotiation` > `reminder`. When priority between two events is unclear, the LLM picks from `{run_first, hold, skip}` and the reason is logged.

### 6.4 Budgets
- **Per-borrower:** `contacts_today` vs `contact_budget_today`.
- **Per-agent:** `AgentExecutionState.contacts_today` vs `contact_budget_today`.
- Both are checked in the supervisor before assignment (`check_budget`). Exceeding either yields a skip with the reason logged.

---

## 7. Contact log and idempotency

This closes the double-contact hole in crash recovery.

1. Before an agent sends anything, the supervisor writes an **intent** entry to the contact log with an idempotency key `(run_id, account_id, event_id)`.
2. When the agent confirms the send, the supervisor marks the entry **SENT**.
3. On any retry or resume, the supervisor checks the contact log first. If the key is already SENT, the borrower is **not** contacted again; the supervisor only completes the missing state update.

The same check applies to the malformed-output retry.

---

## 8. Monitor agent

Started by the supervisor at run start. Runs a loop beside the main workflow.

### 8.1 Tools

| Tool | Does | Mutates state? |
|---|---|---|
| `check_health(agent_id)` | status, last heartbeat, stuck? | No |
| `get_progress(agent_id)` | cursor: `current_borrower`, `last_committed` | No |
| `check_contact_log(account_id)` | was this borrower already contacted? | No |
| `request_recovery(agent_id, action, reason)` | files a recovery request for the supervisor | Request only |

Allowed actions: `RESUME`, `RESTART_SKIP_CURRENT`, `REROUTE`, `QUARANTINE`.

- **RESUME** — relaunch from the in-flight borrower (no contact was sent yet).
- **RESTART_SKIP_CURRENT** — relaunch after the in-flight borrower (contact already sent).
- **REROUTE** — hand the borrower to another agent or to human review (e.g. after a loop).
- **QUARANTINE** — stop the agent, release its locks, preserve state.

### 8.2 Who decides

| Situation | Decided by |
|---|---|
| Heartbeat missing beyond threshold | Plain code |
| Crash, no contact sent for in-flight borrower | Rule → `RESUME` |
| Crash, contact already sent | Rule → `RESTART_SKIP_CURRENT` |
| Loop vs slow agent, or an unknown fault | LLM over tool outputs, chooses one of the four actions |

The monitor only reports and requests. The supervisor's conditional edge executes the request, so there is one writer and every recovery is traced.

---

## 9. Fault handling

Faults are detected in two places: the **monitor** (health: crash, loop, hang) and the **supervisor** (result validation: malformed output).

| Fault | Detected by | Recovery |
|---|---|---|
| Agent crash mid-conversation | Monitor (missing heartbeat) or exception | Check contact log, then `RESUME` or `RESTART_SKIP_CURRENT` |
| Agent loop | Monitor (attempts > threshold, no state change) | Kill agent, borrower → `NEEDS_REVIEW`, release lock, advance cursor |
| Malformed output | Supervisor (schema validation on every result) | Retry once (contact-log guarded); if still bad → `NEEDS_REVIEW`, advance |
| Two events fire at once | Supervisor (lock already held) | Queue second event, log conflict, dequeue on release |
| Supervisor restart | On boot | Reload SQLite state and persisted event bus; any agent still `RUNNING` with stale heartbeat is recovered from its cursor; orphaned `active_owner` locks are reclaimed |
| Unknown or compound fault (e.g. crash during recovery, timeout) | Either | **Catch-all:** stop the agent, release the borrower's lock, preserve state, log the fault, and let the LLM choose from `{RESUME, RESTART_SKIP_CURRENT, REROUTE, QUARANTINE}` |

The hidden script has 5 faults and only 4 types are named in the problem, so the catch-all path is required, not optional.

The LLM never contacts borrowers and cannot bypass guardrails; it only selects a recovery action from the fixed menu.

---

## 10. Tracing

**Primary tool: Langfuse**, with every trace tagged `session_id = account_id` so any account's journey can be pulled on request. LangSmith is the alternative; either integrates with LangGraph. Langfuse is recommended because it can be self-hosted, which matters for borrower data.

**Local append-only decision log (source of truth).** The acceptance criterion is "a complete trace for any account judges pick," so the trace must not depend only on an external service. Every decision is written to a local append-only table first and mirrored to Langfuse.

Each entry records:

```python
@dataclass
class TraceEntry:
    timestamp: datetime          # simulated clock
    account_id: str
    event_type: str
    event_id: str
    decision: Literal["ASSIGNED","QUEUED","SKIPPED","COMPLETED","RELEASED","FAULT","RECOVERED"]
    agent: str | None
    reason: str                  # rule name or "llm:<rationale>"
    llm_confidence: float | None
    llm_prompt_ref: str | None   # link to full prompt/response for LLM decisions
    outcome: str | None
    fault_type: str | None
```

Every routing decision, skip, queue, fault and recovery gets an entry with its reason (guardrail: "every routing decision logged with its reason"). `get_trace(account_id)` returns the ordered entries.

---

## 11. LangGraph structure

```
SupervisorGraph (StateGraph)
├── load_state            # warm cache from SQLite, start monitor
├── consume_event         # next event from persisted bus
├── guardrails_route      # guardrails + rules (LLM fallback held off hot path)
├── assign                # lock, contact-log intent, cursor write
├── execute_agent         # call stub agent
├── validate_output       # schema check on result
├── handle_fault          # execute recovery requests (from monitor or validation)
├── commit                # state + contact-log SENT + trace
├── release_owner
└── check_queue

conditional edges:
  guardrails_route → assign          (assigned)
  guardrails_route → consume_event   (skipped / queued)
  execute_agent    → validate_output (returned)
  execute_agent    → handle_fault    (exception / timeout / monitor request)
  validate_output  → commit          (valid)
  validate_output  → handle_fault    (malformed)
  handle_fault     → execute_agent   (RESUME / RESTART_SKIP_CURRENT)
  handle_fault     → commit          (REROUTE / QUARANTINE / NEEDS_REVIEW)
  commit → release_owner → check_queue → consume_event
```

---

## 12. Latency

Routing target: < 100 ms. The hot path is: in-memory state read → guardrails → rules → in-memory write. SQLite and Langfuse writes are batched or written behind so they do not block routing. The LLM is never on the routing hot path.

---

## 13. Build sequence

| Phase | Build | Validates |
|---|---|---|
| 1 | `BorrowerState`, state store (SQLite + cache), contact log, decision log | Persistence |
| 2 | Event bus (persisted) + agent registry + stub adapter | Plumbing |
| 3 | Guardrails + ordered routing rules + trace entry per decision | Core routing |
| 4 | Single borrower end to end with one stub agent | Happy path |
| 5 | Owner lock, queue, same-day policy, per-borrower and per-agent budgets | Zero conflicting contacts |
| 6 | Cursor + contact-log idempotency | Recovery precondition |
| 7 | Fault injection: crash, loop, malformed, conflict; result validation | Fault criteria |
| 8 | Monitor agent with its four tools; recovery requests | Fault detection |
| 9 | Supervisor restart recovery + catch-all fault handler | Hidden-script safety |
| 10 | Langfuse integration + `get_trace(account_id)` | Trace criterion |
| 11 | LLM fallback routing, conflict priority, fault diagnosis | Agentic layer |
| 12 | Scale to 20,000 accounts; check zero double contacts and latency | Full acceptance |

---

## 14. Acceptance criteria mapping

| Criterion | Mechanism |
|---|---|
| Zero conflicting contacts | Owner lock + persisted queue + same-day contact policy + contact-log idempotency |
| All 5 faults recovered without losing state | Cursor + contact log + monitor requests + supervisor restart recovery + catch-all handler |
| Complete trace for any account | Append-only decision log mirrored to Langfuse (`session_id = account_id`), `get_trace()` |
| Routing < 100 ms | Rules on in-memory state; LLM and I/O off the hot path |
| Survives restart of any agent | Cursor + `RESUME` / `RESTART_SKIP_CURRENT` |
| Per-borrower and per-agent budgets | `check_budget` before every assignment |
| Every decision logged with reason | `TraceEntry.reason` on every decision, including skips and queues |

---

## 15. Open assumptions to confirm

1. Consent, contact caps and payment feed are not in D1/D2/D4/D6; defaults in section 2 apply until confirmed.
2. Default one contact per borrower per day. Confirm against the real cap.
3. Langfuse (self-hosted) vs LangSmith for tracing.
4. Whether stub agents expose a heartbeat and a "contact sent" confirmation we can hook into.
