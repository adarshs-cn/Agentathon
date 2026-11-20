# Orchestrator: the multi-agent journey supervisor (backend)

One supervisor in front of the channel agents (email, WhatsApp, voice/IVR). For every
borrower it decides which agent acts, guarantees one owner and one contact per day, survives
agent faults and its own restarts, and records why it did everything.

## Two modes

* **Simple mode** (default): the original built-in rules, one contact per borrower per day. Used by the
  phase 0-8 tests and `scripts.run_day`.
* **Dataset mode** (`sup.load_dataset(folder)`): loads the real portfolio (D1/D2/D4/D6/D7/D10 + the D12
  policy and D13 capacity) and lets the **D12 policy engine** decide, citing rule ids in every decision.
  This is the mode to use on real data. See "Dataset mode" below.

## Run it

```bash
cd Orchestrator
.venv/bin/pytest                         # 106+ tests, one file per build phase
.venv/bin/python -m scripts.run_day      # a full simulated day on 20,000 borrowers + acceptance report
.venv/bin/python -m scripts.serve        # the HTTP API at http://127.0.0.1:8000/docs
RUN_LIVE_LLM=1 DEEPSEEK_API_KEY=... .venv/bin/pytest tests/test_phase7_llm_advisor.py   # optional live LLM call
```

## Layout

```
orchestrator/
  config.py            policy knobs, channel preferences, paths          (assumptions live here)
  context.py           dependency container every node closes over
  graph.py             the LangGraph StateGraph; build_graph(ctx, checkpointer, stage=1..4)
  supervisor.py        the service: bus -> graph -> bus, restart recovery
  state/models.py      GraphState (per-event scratchpad) and BorrowerState (permanent file)
  stores/              db.py (SQLite + schema), borrowers.py, contacts.py, decisions.py
  bus/event_queue.py   the event bus: persisted, deduplicating, one lane per account
  agents/              base.py (the contract), registry.py, stubs.py, fault_injector.py, runner.py
  nodes/               intake, guardrails, routing, execution, recovery, finish, edges
  llm/                 advisor contract + DeepSeek advisor (catch-all faults only)
  simulator/           borrowers, day (events), faults (scripts), checks (acceptance criteria)
  tracing/trace.py     per-account trace + completeness check
  api/app.py           FastAPI: events in, account listing and traces out
tests/                 phase0 ... phase7, each an integration test of that phase
scripts/               run_day.py, serve.py
```

## The graph (15 nodes)

```
validate_event -> load_borrower -> guardrails -> route -> assign -> [whatsapp|email|voice]
   -> validate_output -> commit -> release -> close_event
                     \-> monitor -> recover -> (back to the agent | commit)
early exits (invalid / blocked / suppressed / lock lost) go straight to close_event
```

`build_graph(..., stage=N)` builds it up phase by phase: 1 intake, 2 + guardrails/routing,
3 + execution/commit, 4 + recovery. The tests for each phase run the real graph at that stage.

## Two kinds of state

| | GraphState | BorrowerState |
|---|---|---|
| What | scratchpad for ONE event | the borrower's permanent file |
| Where | LangGraph checkpoint (`thread_id = account_id`) | our `borrower_profile` + `borrower_state` tables |
| Written by | every node (partial updates) | only assign, commit, release, recover |

## The safety design in one paragraph

Every contact is recorded in `contact_log` **before** the agent is called, under the key
`<account>|<date>` (so a second contact on the same day cannot even be inserted), and marked
SENT only after the agent's answer validates. If anything dies in between, the row is left
ATTEMPTING, and the monitor asks the agent's provider (`lookup`) whether that message went out:
SENT -> never call again; NOT_SENT -> retry or reroute is safe; UNKNOWN -> quarantine. The
LLM is consulted only for faults no rule covers, only when nothing was sent, and can only pick
from a menu the rules built.

## Plugging in a teammate's real agent

Subclass `ChannelAgent` (`agents/base.py`) with two methods, then register it instead of the stub:

```python
class EmailAgentAdapter(ChannelAgent):
    name = "email"
    def execute(self, request: ContactRequest) -> dict: ...   # {"account_id","status":"DONE","outcome":"CONTACTED",...}
    def lookup(self, idempotency_key: str) -> str: ...        # "SENT" | "NOT_SENT" | "UNKNOWN"
```

## Assumptions to confirm (all are one-line changes)

* **Real agent contract.** The agents must accept the idempotency key and answer a status
  lookup. If they cannot, every crash is UNKNOWN and the borrower is quarantined (safe, but
  conservative).
* **Business policy** (`config.py`): 1 contact per borrower per day across all channels;
  DPD thresholds 30 and 90; channel preference per purpose; an open promise to pay
  suppresses contact; a legal flag outranks everything.
* **Data.** Borrower facts come from a stand-in `borrower_profile` table (synthetic, 20,000
  accounts). The real D1/D2/D4/D6 adapter replaces `BorrowerStore.seed`/`load`. Channel
  availability and consent flags are assumed present; they are not in the data we were given.
* **Unscripted faults** (e.g. a timeout) quarantine the borrower unless the LLM advisor is on.
* **Bus** is a SQLite table; swap `bus/event_queue.py` for SQS/Kafka behind the same three methods.
* **Single worker.** One driver processes events in order; the one-lane-per-account rule is
  already enforced for adding workers. The owner lock is already an atomic compare-and-set.
* **Tracing** is the local `decision_log`. A Langfuse mirror can be added as one more sink.

## Dataset mode (the real portfolio)

```bash
.venv/bin/python -m scripts.dataset check                         # load it; baseline of D4 before a supervisor
.venv/bin/python -m scripts.dataset run --events 40 --narrate     # a small day, every decision printed live
.venv/bin/python -m scripts.dataset run --events 800              # a bigger day + acceptance report
.venv/bin/python -m scripts.trace --find blocked --data-dir data/dataset_run
.venv/bin/python -m scripts.trace BRW01234 --data-dir data/dataset_run
```

Put the CSVs in `data/portfolio/Multi_Agent_Supervisor_Dataset/` (git-ignored). "Today" in the dataset is
2026-10-31. Nothing is ever sent (the channel agents are stubs); names, phones and emails are never stored.

What the engine (`orchestrator/policy/d12.py`) does, per borrower (R033, R037), citing the rule ids:

| Step | Rules |
|---|---|
| Suppression: deceased, customer request, complaint (30 days), dispute | R058-R061 |
| Payment hold 48 h (ended by a reversal); open promise hold; the one reminder the day before | R066, R067, R062, R063 |
| Frequency: per day/7 days, global + channel + bucket (minimum applies), failed attempts count, minimum gap | R009-R034 |
| Who acts: agent x bucket matrix, flags (legal/settlement/restructure), legal >= 91 days, broken promise -> negotiation | D12 matrix, R040-R042, R075, R064 |
| Ownership: 24 h lease, higher priority takes over with a logged handoff, non-owner blocked | R035-R039, A12 |
| Channel: phone/email on record, consent and opt-out, DND, shared phone, wrong number, hours, requested window | R043-R056, R069-R072, R001-R007 |
| Budget: D13 daily attempts and spend per agent and channel | R092 |

Verdicts: OK, BLOCKED, SUPPRESSED, or DEFERRED (re-published for when it may proceed). `simulator/audit.py` is an
**independent** re-check of every contact sent; it is also pointed at the historical D4 contacts, where it finds the
planted violations, so "zero violations" on a supervised day means something.

### Assumptions to confirm (all in `policy/d12.py` or the loader)

* **R007 beats the soft 21:00 limit.** Nobody is contacted outside 08:00-19:00, on any channel.
* **Unit = borrower**; their bucket is their worst account's; a legal/settlement/restructure flag on any account applies.
* **Only the four in-house roles are orchestrated**; external agencies (AGY001-3) are never chosen, but their contacts
  count toward caps and ownership. `sms` and `field_visit` have no agent, so are never chosen.
* **Channel preference per role** (`PREFERENCE`), the event -> action mapping (`EVENT_ACTIONS`), and what counts as a
  service reply exempt from the lease and the promise hold (`LEASE_EXEMPT`).
* **WhatsApp consent with no recorded source** is treated as unverifiable (blocked); email only warns (R049).
* Contacts already in D4 for the event's date count in full whatever their time: the data is a snapshot.
* D4 keeps only the last 14 days (plus any wrong-number disposition, kept permanently).

## Dashboard API (port 8001)

The React app in `../../frontend` talks to this. Start it with `.venv/bin/python -m scripts.serve_ui` (paused at the start of the
simulated day; press play in the UI). The code is in `orchestrator/ui/`:

| File | Job |
|---|---|
| `runner.py` | the simulation clock thread: releases each event when its time arrives, at 1x / 60x / 300x / 900x |
| `state.py` | builds the day (dataset, events, fault script), the read-only DB connection, the background audit; rebuilds on reset |
| `events.py` | turns decision-log rows into the eight event types the UI draws |
| `accounts.py` | the accounts grid (server-side filter/sort/paging), search, one borrower's state and "what would happen now" |
| `views.py` | overview numbers, faults, agents, ownership, budgets, decisions, rules, a borrower's trace |
| `app.py` | the FastAPI routes under `/api` and the `/api/stream` server-sent events |

Note: if `.venv/bin/pytest` says "required file not found" after the folder was moved, use `.venv/bin/python -m pytest`.
