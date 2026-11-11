# Update 4 — Model selection and persistent workflow history

## Delivered
- Restored the existing model selector in **Settings → Analytics language model**. It uses the established `GET /api/models` and `PUT /api/models/selection` contracts and the original `{ provider, model }` payload.
- Added IndexedDB persistence for processing, understanding/profile, and analytics response payloads, keyed by dataset ID.
- Rehydrates saved workflow payloads when the app reloads, so detailed result views remain available across refreshes and browser restarts.
- Added a dataset-scoped Workflow history panel showing completion state and last-saved timestamps, with direct navigation to each stage.
- Clears locally persisted workflow payloads when a dataset is deleted.
- Added responsive styling for the model controls and workflow history cards.

## Persistence behaviour
The backend remains the source of truth for uploaded dataset records and stage status. Detailed response payloads are cached in browser IndexedDB because the supplied frontend/backend contract documents POST routes for generating results but no GET routes for retrieving those full result payloads. No backend endpoints or payload schemas were invented. Clearing browser site data will clear this local result cache.

## Validation
- `node --test`: 12/12 passed.
- Vite build could not be run because dependencies are not installed in this environment (`vite: not found`).
- Browser/backend integration was not available here; verify model discovery/selection and a full process → profile → analytics run locally.
