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

    node e2e/overview.mjs <screenshot-dir> 1440 900

It runs events 1, 8 and 13 through the graph, checks the stations activate in graph order and each edge lights, the hover shows
exactly three facts, the phone shows the message, tiles open in place, Replay, the locked second request, reduced motion and Reset.
