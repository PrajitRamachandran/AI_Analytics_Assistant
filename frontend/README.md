# AI Data Analytics Assistant — Frontend

React 19 + Vite frontend for the AI Data Analytics Assistant.

## Development

```bash
npm ci
npm run dev
```

## Validation

```bash
npm test
npm run lint
npm run build
```

The built application is served by the existing FastAPI backend/deployment setup. Keep `src/services/api.js` and its endpoint contracts aligned with the backend.

## Current frontend structure

- `src/components/layout/` — application shell, sidebar, and top bar.
- `src/components/dataset/` — upload panel, dataset history, and dataset display helpers.
- `src/components/` — analytics dashboard.
- `src/context/` — persistent theme and appearance preferences.
- `src/pages/` — settings page and future workflow pages.
- `src/services/` — Axios API client.
- `src/styles/` — shared design tokens and theme variables.

## Workflow behaviour

The upload and dataset-history components are presentational modules. Upload validation, API requests, progress state, dataset lifecycle actions, and processing orchestration remain owned by `App.jsx` so that existing behaviour and backend contracts are preserved while the UI is modularised.

## Phase 2 & 3 — Data Explorer and Analytics

- `src/components/explorer/DataExplorer.jsx` owns the worksheet preview, processing audit, and column profiling presentation.
- `src/components/AnalyticsDashboard.jsx` owns the KPI and chart presentation, including client-side chart search and type filters.
- `src/components/analyticsUtils.js` contains pure chart filtering and KPI formatting helpers.
- `src/components/analyticsUtils.test.js` tests chart filtering and formatting.
- `App.jsx` remains the workflow orchestrator and passes existing API results and callbacks into the presentation components.
- Existing FastAPI endpoint contracts and `src/services/api.js` are unchanged.

Run the frontend checks from this directory:

```bash
npm ci
npm test
npm run lint
npm run build
```

## Phase 4–6

See `PHASE4_5_6_IMPLEMENTATION_NOTES.md` for the settings, appearance, accessibility, API capability audit, and QA status. Reports/chat endpoints are not exposed by the supplied frontend integration, so no guessed routes or fake feature pages were added.


## Multi-page navigation (Update 1)

The workspace now has route foundations for Overview, Upload Dataset, My Datasets, Data Processing, Data Profile, Analytics and Settings. Navigation supports direct URLs and browser Back/Forward. The workflow pages are migration placeholders at this stage; existing functional panels will be moved into them in the next updates. See `UPDATE_1_NAVIGATION_FOUNDATION.md`.


## Update 2 — Upload and dataset pages

`/upload` and `/datasets` now host the existing upload and dataset-management components independently. The overview is a compact summary with recent datasets. See `UPDATE_2_UPLOAD_AND_DATASETS.md`.
