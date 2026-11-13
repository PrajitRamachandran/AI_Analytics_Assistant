# Focused analytics request fixes

This backend update keeps the existing Module 4 architecture. It does not add a separate NLP service.

## Correctness fixes

- A user-specified date range is parsed and applied as an inclusive worksheet-level filter before deterministic execution.
- If the user does not specify a date range, model-generated date filters are removed. Requests such as "entire available dataset" therefore use all available rows; the LLM cannot silently invent a year such as 2023.
- Monthly, daily, weekly, quarterly, and yearly trend requests are repaired to use the existing `time_series` operation with an explicit interval. If the model omits the operation, a narrow profile-grounded operation is added when exactly one suitable date column and a matching numerical measure are available.
- Explicitly requested scalar totals receive a deterministic scalar `sum` operation and linked KPI when a suitable numerical measure is available.
- Explicit category breakdowns/comparisons receive one grouped operation and one relevant chart when the requested dimension and measure can be mapped unambiguously. Ordinary top-N requests do not also receive an unrequested full-category breakdown.
- Category breakdowns default to bar charts. Pie/donut charts are reserved for explicit share/proportion/composition requests.
- All calculations remain in the Pandas/NumPy execution layer. The LLM only proposes the plan.

## Regression tests

Added `tests/test_focused_request_repairs.py` for:

- Removing invented 2023 filters when no range is requested.
- Replacing model filters with the user's explicit February 2025 range.
- Ensuring monthly revenue requests create a monthly time-series operation and line chart.
- Ensuring total-sales plus product-breakdown requests create a scalar KPI and a bar chart.
- Ensuring date filters affect scalar and grouped calculations.
- Preventing a top-products request from creating an unrelated full product breakdown.
- Preventing a regional comparison from adding an unrequested overall-total KPI.

## Test status in the packaging environment

Focused analytics tests pass. Six existing Processing/Understanding API tests still fail in this packaging environment because its imported `psycopg` module has no `connect` attribute. These failures are outside the analytics planner/executor changes and should be re-run in the project's normal virtual environment with the declared `psycopg` dependency installed correctly.

## Installation

Replace the existing backend source with this `backend/` directory. Preserve the local `.env` file and do not overwrite local database or model configuration. Restart FastAPI after replacement.
