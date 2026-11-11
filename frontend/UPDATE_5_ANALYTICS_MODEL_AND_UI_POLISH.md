# Update 5 — Analytics model selection and UI polish

## Changes
- Moved model discovery and selection from Settings into the Analytics workflow page.
- Preserved the existing `GET /api/models` and `PUT /api/models/selection` API contracts and `{ provider, model }` payload.
- Added active-model context, refresh, saving feedback, connection warning and error states.
- Kept Settings focused on appearance and accessibility preferences.
- Refined analytics model card, chart/KPI surfaces, workflow history hover/focus states and responsive layout.
- Added reduced-motion handling for the new interaction polish.

## Validation
- Existing Node test suite should be run with `node --test`.
- Vite production build and live backend integration require the project's installed dependencies and running backend; they are not claimed as verified here.
