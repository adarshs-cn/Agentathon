# 10. Handoff context: what has been built, end to end

Written for another model (or person) picking this project up cold. It says what the project is, how it is built, what was
decided and why, how to run and test it, and what is still open. Where this file and an older doc disagree, **this file is
newer**; documents 01-09 hold the original plans and some of them (for example the navigation in 03 and 07) are superseded.

Date of this snapshot: 2026-11-20. Branch `main`, remote `adarshs-cn/Agentathon` (public). Last feature commit: "Live monitor,
separate demo database, notification panel".

---

## 1. The project in one paragraph

**MT-02 "Multi-agent journey supervisor"** for a collections business (CreditNirvana). A **supervisor** decides, for each event on
a borrower (payment due soon, overdue, broken promise, payment received, ...), whether to contact them, through which channel
agent (WhatsApp / email / voice) and under which role (reminder, negotiation, servicing, legal), and it keeps the borrower safe
from conflicting contacts. It is a **LangGraph** state machine over a **D12 policy engine** (rules R001..R066+), with fault
recovery, SQLite persistence and a React dashboard. The channel agents are **stubs**: nothing is ever really sent.
All data is synthetic and masked.

Original brief: `problem_statement.md`, `architecture.md`, `documentation/01-brief-and-principles.md`.
Owner's working style (see memory file): plain language, small verified steps, no black boxes, always check against the real
dataset, ask before destructive or outward-facing actions.

## 2. Repository layout

```
Supervisor-Agent-Orchestration/
  README.md                      how to run, how it works (kept current)
  architecture.md, problem_statement.md, *_explained.html, prototype/, incremental/   original design material
  documentation/                 01..09 plans, 10 = this file
  run_demo.sh                    starts API (:8001) and UI (:5173); Ctrl+C stops both
  backend/Orchestrator/
    orchestrator/                the supervisor + dashboard API (see section 4)
    scripts/serve_ui.py          starts the dashboard API
    tests/                       phase 0 .. 16 (about 320 tests, all passing; 1 skipped)
    data/portfolio/Multi_Agent_Supervisor_Dataset/   the synthetic dataset (d1..d13 CSVs) -- git-ignored except snapshots
    data/live, data/demo, data/ui  SQLite databases written at run time (git-ignored)
  frontend/                      React 18 + Vite + MUI v5 dashboard
    e2e/overview.mjs, live.mjs, notify.mjs   headless-Chrome end-to-end tests
```

## 3. The supervisor (backend core)

* **Graph** (`orchestrator/graph.py`, nodes in `orchestrator/nodes/`): `validate_event -> load_borrower -> guardrails -> route -> assign
  (take the ownership lock) -> channel agent (whatsapp | email | voice) -> validate_output -> commit -> close_event`, with a
  fault branch `monitor -> recover` (and an early "Stopped" exit when guardrails/route refuse).
* **State**: `GraphState` (per event) vs `BorrowerState` (per borrower, table `borrower_state`). LangGraph checkpointer is
  `SqliteSaver`, `thread_id = borrower`, so a crashed run resumes.
* **Policy engine** `orchestrator/policy/d12.py` (`D12Policy`): `guard()` (borrower-level stops: deceased, DND, suppression, payment
  in last 48 h, ...) and `plan()` (role, channels, operating window, caps, call gap, budget). Every refusal carries rule ids.
  Hard contact window = **08:00-19:00 (R007)**; `engine.hard_window` is in minutes. Ownership: 24 h lease (R038) after a contact.
* **Idempotency**: `contact_log` key `borrower|event_id`; a message is never sent twice. Provider `lookup` and `sent_message`.
* **Recovery** (`nodes/recovery.py`): faults CRASH, TIMEOUT, MALFORMED, NO_PROGRESS -> actions RESUME (retry), RESTART_SKIP_CURRENT
  (message already went out, do not resend), REROUTE_CHANNEL, ESCALATE, QUARANTINE. Rules decide; an optional LLM advisor
  (`orchestrator/llm/deepseek.py`) only picks among safe options for unscripted faults. Fault injection: `agents/fault_injector.py`
  with a script keyed `(borrower, call_number)`; kinds used: `CRASH_AFTER_SEND`, `LOOP`, `CRASH`, ...
* **Messages** (`agents/messages.py`): templates, Indian rupee grouping, masked demo contact (env `MT02_DEMO_PHONE/EMAIL/NAME`,
  `MT02_SHOW_FULL_PHONE`). Stored on `contact_log.message_json` so the phone preview can show exactly what the agent "sent".
* **Supervisor API** (`supervisor.py`): `process_next(until)` (queue order), `process_event(event_id)` (one chosen event),
  `recover_on_start()`, `publish()`. `_record_run()` writes one `journey_run` row per finished **real** event (skips events that
  exist in `demo_event`); it also captures any fault and recovery from `decision_log`.
* `Context.node_listeners` lets the dashboard watch every node start/end (used by the live walkthrough animation).

## 4. Dashboard backend (`orchestrator/ui/`)

| File | Job |
|---|---|
| `state.py` | `DemoState(data_dir, dataset_dir, events, seed, faults, advisor, mode, autostart)`. Modes: **`live`** (real monitored side), **`scenario`** (the 15-event walkthrough), **`day`** (old simulated day on a clock). Builds or reopens the SQLite DB, a read-only reader connection, background audit thread. `_reopen()` keeps saved data across restarts for live/scenario. |
| `monitor.py` | `LiveMonitor` + `setup_pool()`; see section 6. |
| `scenario.py` | the 15 walkthrough events (`SPECS`), picks real borrowers from the dataset, stages their data, publishes events `demo-01..15`. |
| `run.py` | `RunManager`: runs ONE demo event live and streams node start/end as SSE; stores `run_step` rows for hover/Replay. |
| `reasons.py` | plain-language layer: station map, sentences, outcome/event/channel/role words. |
| `demo_views.py` | walkthrough list; tile drawers (`drilldown`) -- demo rows or, for live, `real_rows()` (events not starting `demo-`). |
| `journeys.py` | Journey Runs rows (filters, pinning of highlighted runs), notification list, mark-as-seen, alert wording, new-fault feed. |
| `views.py`, `accounts.py`, `events.py`, `runner.py` | overview numbers, decisions, trace, accounts grid and search, UI event feed, sim clock. |
| `app.py` | `create_dashboard_app(state, demo=None)`. `state` = real side; `demo` = walkthrough (defaults to `state` for single-DB setups/tests). |

**Endpoints (all under `/api`)**: `overview`, `stream` (SSE: `counters`, `event`, `run_start`/`step`/`run_end`, `notify`, `reset`),
`monitor` (GET) + `monitor/{pause|resume}` (POST), `journeys`, `notifications` (GET) + `notifications/seen` (POST, body
`{event_ids: [...]}` or empty = all), `scenario` (list), `scenario/{id}/run?pace_ms=`, `scenario/{id}/steps`, `scenario/reset`,
`overview/drilldown/{tile}` (conflicts, faults, latency, borrowers, contacts, blocked), `accounts`, `accounts/filter-options`,
`accounts/search`, `borrowers/{id}/state`, `borrowers/{id}/trace`, `decisions`, `rules`, plus legacy `agents`, `faults`,
`ownership`, `budgets`, `simulation[/action]`.

## 5. Two databases, on purpose

* **Real side** (`data/live/orchestrator.db`, `mode="live"`): dataset tables `ds_*` (20,000 accounts, 17,000 borrowers), the
  supervisor's tables (`event_queue`, `decision_log`, `contact_log`, `borrower_state`, `borrower_profile`), `journey_run`,
  `monitor_pool`, plus LangGraph checkpoints in `checkpoints.db` beside it. Tiles, Journey Runs, notifications, Accounts,
  Decision Log all read this.
* **Demo side** (`data/demo/`, `mode="scenario"`): the same schema plus `demo_event`, `demo_setup`, `run_step`. Only the Overview
  "Workflow walkthrough" uses it. "Reset demo" rebuilds only this database. **A demo run can never change a real number.**
  (Tests prove it: `test_walkthrough_runs_never_change_the_real_numbers`.)
* `serve_ui` default `--mode live` starts both; `--mode day` / `--mode scenario` start the old single-database setups.
  First start loads the dataset twice (slow); later starts reopen. `data/ui` from older versions is no longer used.
* `Database` (`stores/db.py`): one SQLite connection with an RLock, WAL mode, a read-only second connection for the dashboard,
  in-place migration for old `contact_log` and `journey_run` shapes (`_upgrade_journey_run`).

## 6. The live monitor (continuous supervision)

* A **background thread that runs whenever the server runs**, not tied to a login. (Decision taken with the owner: always-on worker,
  compliance window enforced per contact, not login-based.)
* **Pool**: 15 borrowers chosen once and saved (`monitor_pool`): single-account, reachable, not suppressed; 5 due-soon and 10
  overdue (1-60 DPD). Deterministic by seed.
* **Each tick** (every `MT02_MONITOR_TICK_S`, default 3 s): if not paused and inside the window -> append an event (`DUE_SOON` for
  0 DPD, else `OVERDUE`, id `live-<ms>-<borrower>`) for every pool borrower whose `next_due` has passed and who has no pending
  event, then run `process_next(until=now)` until the queue is empty. Outside the window it does nothing; waiting events are
  processed when the window opens. `next_due` advances by `MT02_MONITOR_EVERY_MIN` (default 30 min); on a fresh pool the first 15
  events are 20 s apart so the demo shows life immediately. Next-due times are saved, so a restart never repeats an event.
* **Window**: the policy's hard window (08:00-19:00); override `MT02_MONITOR_WINDOW=08:00-17:00`. Uses the server's local clock.
* **Faults**: on a freshly built live DB with `--faults` not `none`, two faults are scripted on pool borrowers 3 and 7
  (`CRASH_AFTER_SEND`, `LOOP`) so recoveries and alerts can be seen. Not persisted across restarts (by design: demo input).
* `status()` powers the header pill: state `monitoring | outside_window | paused`, label, window, pool size, handled, waiting,
  next event, when it opens.
* **Events are generated by this schedule. A real event feed does not exist yet** (see open items).

## 7. Notifications and Journey Runs

* `journey_run` row per finished real run: borrower, event type/time, outcome, channel, role, owner after, rule ids, summary,
  **fault, fault_agent, recovery_action, recovery_reason, notify_seen** (0 only when a fault happened and nobody has read it),
  duration, attempts. Demo events are never recorded.
* The stream emits `notify` when a new faulty run appears. The UI shows an **alert at the top**:
  `Alert Supervisor Agent - {Agent}/{Fault} happened and recovering` with **Mark as read** and **Ignore**.
  *Ignore* closes it but leaves it unread. *Mark as read* calls `POST /api/notifications/seen`.
* **Bell** (header): badge = unread count; click opens a **panel** (does not navigate) listing unread alerts with **Mark as read**,
  **View run** (opens Journey Runs with the run highlighted and pinned to the top) and **Mark all as read**. Empty panel text:
  "You are all caught up." Read state is stored in the DB (survives reload and restart).

## 8. Frontend (`frontend/src`)

* **Navigation** (`layout/AppLayout.jsx`): *Journey Supervisor* -> Overview (title "Live Journey", placeholder name in
  `config/labels.js`, still the owner's choice), Journey Runs (`/runs`), Decision Log (`/decisions`); *Loan Management* -> Accounts
  (`/accounts`). Borrower Trace still exists at `/trace` (reached from rows and alerts). Removed screens (Budgets, Ownership,
  Faults & Recovery, Agents) are deleted from the tree but remain in git history. Header: monitor pill (+ pause/resume),
  bell, avatar. Removed on request: "Judge demo build..." text and the "MT-02 SUPERVISOR" sidebar label.
* **Overview** (`pages/Overview.jsx`): six hero tiles (real numbers only; each opens an in-place drawer, `TileDrawer`), then the
  **Workflow walkthrough**: event picker (15 demo events), Run / Replay / Reset demo, Normal/Slow pace, SVG workflow graph
  (`components/workflow/*`, 11 stations, edges light per hop, hover card = exactly 3 facts: borrower, owner (Null for fresh),
  what the supervisor did and why), phone preview of the message, step log. Strictly existing theme tokens (`theme/muiTheme.js`).
* **State**: `context/SimContext.jsx` holds one SSE connection (overview counters, run events bus, notifications, toast).
  `hooks/useScenario.js`, `hooks/useRun.js`; pure logic in `components/workflow/{layout,logic}.js`.
* Gotcha: the installed MUI X DataGrid passes `(params)` to `valueGetter/valueFormatter`; use `renderCell` for custom cell text.
* `VITE_API_BASE_URL` selects the API (default `http://localhost:8001`); backend CORS allows only 5173/4173 unless `MT02_CORS` is set.

## 9. How to run

```bash
./run_demo.sh                                        # API :8001 + UI :5173
# or
cd backend/Orchestrator && .venv/bin/python -m scripts.serve_ui     # live monitor + demo walkthrough
cd frontend && npm run dev
```
`serve_ui` flags: `--mode live|scenario|day`, `--faults none|public|hidden`, `--port`, `--data-dir` (live/demo dirs are siblings
named `live` and `demo` under that folder's parent), `--events` (day mode). Secrets live in `backend/Orchestrator/.env`
(git-ignored; `.env.example` is blank). An earlier API key was exposed in chat and should be rotated.

## 10. Tests

* Backend: `cd backend/Orchestrator && .venv/bin/python -m pytest -q` (use `python -m pytest`, not `pytest`). Phases 0-13 = the
  supervisor, policy, dataset, API; **14** walkthrough; **15** journey runs, notifications, table upgrade, alert wording;
  **16** live monitor (pool, window, pause, restart, demo isolation, scripted faults). Many tests need the dataset under
  `data/portfolio/...` and skip without it.
* Browser (real headless Chrome via CDP, no Playwright): `frontend/e2e/overview.mjs` (walkthrough graph; honours `E2E_API`,
  `E2E_UI`), `live.mjs` (monitor runs on its own; demo run never leaks), `notify.mjs` (alert, Ignore, Mark as read, panel,
  reload). The latter two expect a throwaway server pair, see `frontend/README.md`:
  API `:8002` (`MT02_CORS=http://127.0.0.1:5175 python -m scripts.serve_ui --port 8002 --faults public --data-dir /tmp/mt02/ui`),
  UI `:5175` (`VITE_API_BASE_URL=http://localhost:8002 npx vite --port 5175`).
* Lint: `cd frontend && npx eslint src e2e` (clean). Build: `npx vite build`.

## 11. Decisions the owner made (do not re-litigate)

1. Walkthrough messages are **preview only**; nothing is really sent.
2. Keep Accounts as the single customer screen; separate "Borrower master" screen was dropped; Journey Runs added instead.
3. Demo runs are for explaining the workings only: not saved as runs, not counted in tiles, "Reset demo" touches only the demo.
4. Supervision runs on its own, inside the compliance window, on a pool of 15 real borrowers; runs and checkpoints persist and
   come back after a reboot.
5. Alerts: one-line "Alert Supervisor Agent - {Agent}/{fault} happened and recovering", with Mark as read / Ignore; the bell shows the
   unread count and a panel; read items disappear.
6. Journey Supervisor module = Overview + Journey Runs + Decision Log; Loan Management module = Accounts.
7. Overview name ("Live Journey") is a placeholder; owner will choose (one-line edit in `config/labels.js`).

## 12. Known limits and open items

* **No real event feed.** The monitor generates events by schedule. Next step: `POST /api/events` for external systems (publish via
  `Supervisor.publish`) and, if wanted, event types beyond DUE_SOON/OVERDUE (PAYMENT_RECEIVED, PTP_BROKEN, ...).
* **Day mode rebuilds on every start** (simulation); only live/scenario modes reopen saved data.
* Monitor uses the server's local clock and the real date; dataset history ends 2026-10-31 so "today" has no prior contacts.
* Live-side `faults_scheduled` and drawers are per-process: scripted faults are not re-created after a restart.
* Old screens (Borrower Trace page, `SimClockMini`, `/api/agents|faults|ownership|budgets`) still exist in code/API though not in
  the sidebar; remove only after the owner confirms.
* Not built: borrower drawer, real message delivery (owner will supply agent details), LLM advisor is optional/off without key.
* GitHub repo is public; `data/snapshot/` holds SQLite snapshots/raw copies pushed on request from the *old* single-database layout,
  now stale. Refresh them after running the new version if still wanted.
* Process/ops gotchas: the repo's `git remote` URL embeds a personal access token (rotate it; use a credential helper). `pkill -f`
  can match the calling shell; kill by port (`kill $(lsof -ti :8001)`). The user's own backend is usually pid-owned by
  `run_demo.sh`; ask before stopping it.

## 13. Fast orientation for a new model

1. Read `README.md` (run + how it works), then this file.
2. Read `orchestrator/graph.py`, `nodes/*.py`, `policy/d12.py` for the supervisor; `ui/state.py`, `ui/monitor.py`, `ui/app.py` for the server.
3. Read `frontend/src/pages/Overview.jsx`, `context/SimContext.jsx`, `components/NotificationBell.jsx` for the UI.
4. Run the backend tests, then `e2e/live.mjs` against a throwaway server pair before changing anything.
5. Match the owner's style: plain words, small verified steps, test against the real dataset, say plainly what was and was not verified.
