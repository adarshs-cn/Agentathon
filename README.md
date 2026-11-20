# MT-02 Multi-agent journey supervisor

```
backend/Orchestrator/   the supervisor (LangGraph + SQLite) and the dashboard API   -> http://localhost:8001
frontend/               the React dashboard (Vite + MUI)                              -> http://localhost:5173
```

## Run it

One command (starts both, Ctrl+C stops both):

```bash
./run_demo.sh
```

or in two terminals:

```bash
cd backend/Orchestrator && .venv/bin/python -m scripts.serve_ui --events 700      # API + simulated day, paused
cd frontend && npm run dev                                                          # then open http://localhost:5173
```

Press **play** (top right, or on Overview). Speeds 1x / 60x / 300x / 900x are simulated seconds per real second, so at
900x a working day takes about a minute. Press **/** anywhere to jump to a borrower. **Reset day** rebuilds the day.

## Where the data comes from

Everything on screen is read from the SQLite database the supervisor writes (`backend/Orchestrator/data/ui/orchestrator.db`),
through a second read-only connection. Nothing is mocked: the same LangGraph runs, the same rows are written.

| Page | What it shows | Tables |
|---|---|---|
| Overview | acceptance scorecard, headline numbers, why contacts were stopped, the day by hour, live feed | `event_queue`, `decision_log`, `contact_log` |
| Accounts | all 20,000 accounts, server-side filter / sort / paging, live owner and last contact | `ds_account`, `ds_person`, `contact_log`, `ds_history` |
| Borrower Trace | one borrower: standing now (caps, holds, consent), "what would happen now", every event step by step | `ds_*`, `decision_log`, `event_queue` |
| Faults & Recovery | every fault, what the provider said, how it was recovered, the fault script | `decision_log`, `contact_log` |
| Agents | channel-agent health, D12 role x bucket matrix | `decision_log`, `ds_matrix` |
| Ownership | leases, handoffs, simultaneous requests, non-owner contacts stopped | `borrower_state`, `decision_log`, `event_queue` |
| Budgets | D13 attempt budgets and spend per agent and channel, contacts per borrower today | `ds_capacity`, `ds_history`, `contact_log` |
| Decision Log | every decision with its reason and the D12 rule ids; filters live in the URL | `event_queue`, `decision_log` |

API reference: see the docstring at the top of `backend/Orchestrator/orchestrator/ui/app.py`.

## Things to know

* **Personal data.** Names and phone numbers are stored only masked (`D*** S***`, `XXXXXX4842`); emails and addresses are not stored.
  All data is synthetic. A test asserts that no real name, phone or email from the source files ever leaves the API.
* **Time.** Times are simulated wall-clock times sent as ISO strings ending in `Z`, so the browser shows exactly what the supervisor saw.
* **Total O/S and Installment Overdue** are not in the source data (D1); they are left empty and hidden rather than invented.
* **Account status** is derived from D1 flags: legal, restructured, settled (settlement flag), overdue (DPD > 0), current.
* The channel agents are stubs: nothing is ever sent.

## Tests

```bash
cd backend/Orchestrator && .venv/bin/python -m pytest        # ~280 tests (use `python -m pytest`: the venv's `pytest` launcher breaks if the folder is moved)
cd frontend && npm run lint && npm run build
```
