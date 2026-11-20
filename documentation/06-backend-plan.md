# 06. Backend plan

Everything is **additive** where possible. The supervisor graph, policy engine, recovery and audit are not touched; the
285 existing tests must keep passing at every step.

## 1. Scenario mode (replaces the day clock as the default)

* New mode switch `MT02_MODE=scenario` (default) or `day` (today's behaviour, kept behind the flag until you say delete it).
* `orchestrator/ui/scenario.py`: a deterministic **builder** that, for each of the 15 rows in 04, runs a selection query
  against the loaded dataset, applies the row's small **setup** (for example, a Reminder contact yesterday evening for event 4,
  an open promise for 5 and 8), publishes **one event** to the bus, and records the row in a new table:

  ```sql
  demo_event(seq, key, label, event_id, borrower_id, event_type, depends_on, note)
  demo_setup(seq, table_name, row_key)        -- every row the setup inserted, so it is listed and removable
  ```
* The 15 events are published but **not processed**. Nothing runs until the user presses Run (no clock thread in this mode).
* Fault scripts for events 13 and 14 are built by the same builder and loaded into the existing `FaultInjector`.
* `POST /api/scenario/reset` rebuilds the database and the 15 events (the existing `DemoState.build()` path).
* If a selection query matches no borrower the builder **raises**; it never silently substitutes.

## 2. Execute one event on demand

| Piece | Change |
|---|---|
| `EventQueue.claim(event_id)` | Atomically move a specific `PENDING` event to `IN_PROGRESS` (respecting the one-lane-per-borrower rule). |
| `Supervisor.process_event(event_id)` | Claim by id, run the graph through the existing `_execute`, mark done, run `_after` (deferral). Reuses all current recovery and restart behaviour. |
| Dependency | Event 12 needs 11 done. Running 12 earlier returns **409** with a one-line reason. |
| One at a time | A run lock; a second Run while one is active returns **409**. |
| Idempotence | Running an event that is already done returns its stored steps (nothing re-executes); the UI calls this **Replay**. |

## 3. Live node streaming (what drives the animation)

The animation must follow the **real** execution, so the backend announces each node as it happens.

* `Context.instrument()` already wraps every node. It gains `node_listeners`: callables invoked as
  `listener(phase, node, info)` with `phase` = `start` or `end`.
* **Pacing for ad-hoc runs.** On `start`, if the run has `pace_ms > 0`, the wrapper sleeps `pace_ms` *before* running the node, so
  the screen shows each station active for a human-readable moment and the state really changes one step at a time.
  Tests run with `pace_ms=0`. The default is 650 ms; the UI exposes Slow (1000) and Normal (650).
* **Stations.** A static map `node -> station` (see 03) groups the 15 nodes into the 8 to 10 drawn stations. Several nodes may
  share a station (for example `monitor` and `recover` are the Recover station).
* **Stored steps (so Replay and hover are exact).** A listener also writes one row per node to a new table:

  ```sql
  run_step(event_id, seq, node, station, started_at, ms,
           owner_before, owner_after, did TEXT, label TEXT, rule_ids TEXT, data TEXT)
  ```
  `did` is the plain sentence (05), `label` the headline reason, `data` the technical detail for the expandable log.
* **SSE.** The existing `/api/stream` gains three event names (existing ones are unchanged):

  | Event | Payload |
  |---|---|
  | `run_start` | `{run_id, event_id, borrower_id, pace_ms}` |
  | `step` | `{run_id, seq, node, station, phase: "start"\|"end", did?, label?, owner_before?, owner_after?, ms?}` |
  | `run_end` | `{run_id, event_id, outcome, outcome_label, summary, message?}` |

  `start` lets the screen zoom the node *before* it executes; `end` carries the sentence that goes in the hover.
* **Owner at each step.** Computed with the engine's existing `current_owner` plus the in-flight lock: before the run, after
  `assign` (lock holder), after `commit` (the lease). Stored on the step, so fact 2 of the hover is a lookup, not a guess.

## 4. The message the borrower receives

Today the stub agents return only a provider reference. They will now return the message they "sent".

* `orchestrator/agents/messages.py`: templates keyed by `(action, channel)` for the actions in the scenario
  (`emi_due_reminder`, `overdue_reminder`, `ptp_capture`, `ptp_reminder`, `broken_ptp_followup`, `payment_confirmation`,
  `legal_notice`). WhatsApp: a short text. Email: subject plus body. Voice: the IVR script. Placeholders: first name (masked),
  amount (EMI or dues), due date, a clearly fake pay link, lender name, and a standard opt-out and grievance footer.
* `ContactRequest` gains a `context` dict (masked name, EMI, dues, due date, DPD) built by the execution node from `ds_account`
  and `ds_person`. Only already-masked or non-personal values go in.
* Stub agents render the template and return `{"message": {"channel", "to", "subject", "body"}}`.
* `contact_log` gains `message_text` and `to_masked`, written when the contact is confirmed SENT. The step's `data` and the
  `run_end` event carry the message so the phone view shows it immediately and Replay shows it later.
* **The "To" field** is the configured demo contact (see 09): `MT02_DEMO_PHONE`, optionally `MT02_DEMO_EMAIL`, set outside the code.
  It is masked in the database and the API (`XXXXXX1234`) unless `MT02_SHOW_FULL_PHONE=1` is set on the demo machine.
* **Real delivery is a separate, later phase** (08, P5): a `ChannelAgent` adapter that calls your teammates' services. The
  execution path already supports it (`execute` and `lookup`); nothing in this plan blocks it, and nothing real is sent
  before then.

## 5. Plain-language layer

`orchestrator/ui/reasons.py` holds the catalogue and sentence builders from 05. **Every** API that returns a reason returns
both `rule_ids` and `reason_plain` (and `labels`), additively, so nothing existing breaks. A test fails if the engine can
emit any rule id that has no label.

## 6. Endpoints (new or changed)

| Endpoint | Purpose |
|---|---|
| `GET /api/scenario` | The 15 events: label, type in words, borrower, status, outcome in words, availability and why not. Also the masked demo contact. |
| `POST /api/scenario/{event_id}/run?pace_ms=650` | Start an ad-hoc run (returns `run_id`); progress arrives on the stream. |
| `GET /api/scenario/{event_id}/steps` | The stored steps, with owners, sentences and the message. Used for hover, Replay, and the event log. |
| `POST /api/scenario/reset` | Rebuild the 15 events and the data. |
| `GET /api/overview/drilldown/{tile}` | Plain-English rows behind each tile (`contacts`, `blocked`, `faults`, `borrowers`, `audit`, `latency`). |
| `/api/overview`, `/api/decisions`, `/api/accounts…`, `/api/borrowers/{id}/…` | Same shapes, plus `reason_plain` and friendly type and outcome words. `sim_clock` is returned only in `day` mode. |

## 7. Tests (added; the existing 285 stay green)

| Test | Proves |
|---|---|
| Scenario builder | Every one of the 15 criteria finds a borrower; same borrowers on every build; setup rows are recorded. |
| Each event, parametrised | Event *n* ends exactly as the table in 04 says (outcome, agent, channel, owner change, fault recovery). |
| Dependency and lock | 12 before 11 is 409; two simultaneous runs, the second is 409; replay does not execute twice. |
| Node streaming | `start` precedes `end` for every node, in graph order, with the right station; fault path includes the Recover station. |
| Stored steps | One row per node; owner before and after are consistent; `did` is non-empty for every step. |
| Messages | Each action and channel renders a non-empty message with an amount and no unfilled placeholder; no real name, phone or email leaks (extends the existing privacy test). |
| Reasons | No rule id the engine can emit lacks a label; no reason string on any API response contains a bare code as its only text. |
| Drilldowns | Each tile's rows match the database counts shown on the tile. |
| Regression | Full existing suite, unchanged. |

## 8. Risks and how they are handled

* **Pacing inside the graph run.** The sleep happens in the node wrapper, only for ad-hoc runs, under the run lock; restart
  recovery and tests are unaffected because pacing defaults to 0 outside the UI.
* **Stream reliability.** If the stream drops mid-run, the screen falls back to `GET …/steps` and shows the finished run.
* **SQLite concurrency.** Writes stay on the supervisor connection; the API keeps using the read-only connection.
* **Demo data realism.** Setup rows are minimal, flagged, and listed, so anyone can see exactly what was staged.
