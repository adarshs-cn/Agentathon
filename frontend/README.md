# MT-02 Supervisor: dashboard

React 18 + Vite + MUI v5 (+ MUI X DataGrid, Recharts). Talks to the dashboard API in `backend/Orchestrator`
(default `http://localhost:8001`; override with `VITE_API_BASE_URL`).

```bash
npm install
npm run dev      # http://localhost:5173  (start the API first, or use ../run_demo.sh)
npm run lint
npm run build
```

## The theme (do not drift from it)

All colours, shadows and radii come from `src/theme/muiTheme.js` (`tokens`) and `src/index.css`. Conventions used by every page:

* **Cards**: `components/Section.jsx`: white `Paper`, radius 10, `cardShadow`, grouped-grey header strip with a divider, 14px / 600 title.
* **Status is never colour alone**: `StatusChip` and `OutcomeChip` always pair an icon with a label.
* **IDs in monospace** (`MonoId`), **numbers in tabular figures** (`.tabular-nums`).
* **Tiles** use `StatTile`; **tables** use the DataGrid style from `components/gridStyles.js` or `components/SimpleTable.jsx`.
* **Rule ids** are `RuleChip`s: hover explains the D12 rule, click filters the Decision Log.
* Text sizes follow the 12px scale in the theme; do not introduce new fonts or colours.

## Structure

```
src/api/client.js          every API call in one place
src/context/SimContext.jsx one live connection (SSE) for the whole app: overview, sim clock, feed
src/hooks/useApi.js        fetch + live refresh whenever the simulation produced new decisions
src/hooks/useRules.js      the D12 rule book, fetched once
src/layout/AppLayout.jsx   navigation rail, header (sim clock, borrower search), fault toasts
src/pages/*                one file per page
src/components/*           shared, themed building blocks
```


## End-to-end test (real Chrome, real clicks)

With the API (`:8001`) and the UI (`:5173`) running (`../run_demo.sh`):

    node e2e/overview.mjs <screenshot-dir> 1440 900      # the walkthrough graph (needs :8001 + :5173)
    node e2e/live.mjs <dir> 1440 900                     # live monitor + demo isolation (API :8002, UI :5175)
    node e2e/notify.mjs <dir> 1440 900                   # alerts, bell panel, mark as read (API :8002, UI :5175)

`live.mjs` and `notify.mjs` expect a throwaway pair of servers on other ports so they never touch your data:

    cd ../backend/Orchestrator && MT02_CORS=http://127.0.0.1:5175 .venv/bin/python -m scripts.serve_ui --port 8002 --faults public --data-dir /tmp/mt02/ui
    VITE_API_BASE_URL=http://localhost:8002 npx vite --host 127.0.0.1 --port 5175

(`overview.mjs` also honours `E2E_API` / `E2E_UI`.) `overview.mjs` runs events 1, 8 and 13 through the graph, checks the stations activate in graph order and each edge lights, the hover shows
exactly three facts, the phone shows the message, tiles open in place, Replay, the locked second request, reduced motion and Reset.
