# Update 2 — Upload Dataset and My Datasets

## Delivered
- Migrated the existing upload component to its dedicated `/upload` page.
- Migrated dataset history to its dedicated `/datasets` page.
- Replaced the long overview with a concise workspace summary and recent-datasets list.
- Added overview metrics derived from the existing `/api/datasets` response.
- Added upload success navigation to My Datasets.
- Added a dataset-management table with filename, size, upload date, status, open workspace, download and delete actions.
- Added a clear Upload Dataset call-to-action from My Datasets and Overview.
- Kept upload validation, progress reporting, download and delete API behaviour.
- Kept dataset list and upload state in the root App so page navigation does not discard it.
- Removed the model selector from the overview; model configuration will be migrated into Settings in the later workflow update.
- Removed processing/profile/analytics controls from the dataset library; those actions belong on their dedicated workflow pages in Update 3.

## Routes now functional
- `/` — Overview
- `/upload` — Upload Dataset
- `/datasets` — My Datasets

Dataset-scoped processing/profile/analytics routes remain reserved for Update 3.

## API contracts
No backend endpoint, request payload, or response schema was changed. Existing upload, list, download and delete API calls are reused.

## Validation
- `node --test`: 12/12 tests passed.
- Relative import scan: no missing imports.
- Build and browser smoke test remain pending because frontend dependencies are not installed in this workspace.
