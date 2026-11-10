from pathlib import Path
from types import SimpleNamespace
import importlib.machinery
import importlib.util
import sys
import types

import pandas as pd
import pytest

if "psycopg" not in sys.modules:
    try:
        missing_psycopg = importlib.util.find_spec("psycopg") is None
    except ValueError:
        missing_psycopg = True
    if missing_psycopg:
        psycopg_stub = types.ModuleType("psycopg")
        psycopg_stub.__spec__ = importlib.machinery.ModuleSpec("psycopg", loader=None)
        sys.modules["psycopg"] = psycopg_stub

from app.api import analytics as analytics_api
from app.schemas.analytics_plan import WorkbookAnalyticsPlan
from app.schemas.data_understanding import DatasetProfile


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.fake_cursor = FakeCursor(row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.fake_cursor


def _profile():
    return DatasetProfile.model_validate({
        "filename": "workbook.xlsx",
        "total_worksheet_count": 1,
        "successful_worksheet_count": 1,
        "failed_worksheet_count": 0,
        "worksheets": {
            "Sales": {
                "worksheet_name": "Sales",
                "row_count": 3,
                "column_count": 2,
                "columns": [
                    {
                        "column_name": "region", "original_name": "Region",
                        "pandas_dtype": "object", "inferred_type": "categorical",
                        "semantic_role": "category", "non_null_count": 3,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 2,
                        "unique_value_percentage": 66.7,
                    },
                    {
                        "column_name": "revenue", "original_name": "Revenue",
                        "pandas_dtype": "int64", "inferred_type": "numerical",
                        "semantic_role": "amount", "non_null_count": 3,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 3,
                        "unique_value_percentage": 100,
                    },
                ],
            }
        },
        "worksheet_errors": {},
    })


def _plan():
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "Sales records grouped by region.",
        "business_context": {
            "domain": "sales", "dataset_purpose": "Summarize sales.",
            "confidence": 0.6,
        },
        "worksheet_analyses": [{
            "worksheet_name": "Sales", "inferred_purpose": "Sales records",
            "summary": "Contains region and revenue.", "analysis_focus": ["Revenue by region"],
        }],
        "operations": [{
            "id": "revenue_by_region", "operation_type": "group_by",
            "worksheet_name": "Sales", "title": "Revenue by region",
            "description": "Sum revenue by region.",
            "group_by_columns": ["region"],
            "aggregations": [{
                "alias": "total_revenue", "function": "sum", "column": "revenue",
            }],
        }],
        "kpis": [], "visualizations": [], "key_questions": [], "limitations": [],
    })


def test_analytics_endpoint_returns_plan_execution_and_chart_data(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    dataset_dir = upload_root / "dataset-1"
    dataset_dir.mkdir(parents=True)
    workbook_path = dataset_dir / "workbook.xlsx"
    workbook_path.write_bytes(b"placeholder")

    connection = FakeConnection(("sales.xlsx", str(workbook_path), "processed"))
    monkeypatch.setattr(analytics_api, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(analytics_api, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        analytics_api, "process_workbook",
        lambda path: SimpleNamespace(
            cleaning=SimpleNamespace(worksheets={
                "Sales": pd.DataFrame({
                    "region": ["North", "South", "North"],
                    "revenue": [100, 50, 25],
                })
            })
        ),
    )
    monkeypatch.setattr(analytics_api, "profile_dataset", lambda cleaning: _profile())

    class FakePlanner:
        def generate_plan(self, profile):
            assert profile.filename == "sales.xlsx"
            return _plan()

    monkeypatch.setattr(analytics_api, "AnalyticsPlanner", FakePlanner)

    result = analytics_api.generate_dataset_analytics("dataset-1")
    assert result["execution_status"] == "success"
    assert result["filename"] == "sales.xlsx"
    assert result["results"][0]["records"] == [
        {"region": "North", "total_revenue": 125},
        {"region": "South", "total_revenue": 50},
    ]
    assert result["charts"][0]["data"]


def test_analytics_endpoint_rejects_unprocessed_dataset(monkeypatch):
    monkeypatch.setattr(
        analytics_api, "get_db_connection",
        lambda: FakeConnection(("sales.xlsx", "/unused/workbook.xlsx", "uploaded")),
    )
    with pytest.raises(analytics_api.HTTPException) as error:
        analytics_api.generate_dataset_analytics("dataset-1")
    assert error.value.status_code == 409


def test_analytics_route_is_registered_in_fastapi_application():
    from app.main import app

    paths = {
        route.path for route in app.routes if hasattr(route, 'path')
    }
    for route in app.routes:
        if hasattr(route, 'original_router'):
            paths.update(sub.path for sub in route.original_router.routes if hasattr(sub, 'path'))
    assert "/api/datasets/{dataset_id}/analytics" in paths


def test_analytics_endpoint_returns_gateway_timeout_for_slow_ollama(tmp_path, monkeypatch):
    from app.modules.analytics_planner.analytics_planner import AnalyticsPlanningTimeoutError

    upload_root = tmp_path / "uploads"
    dataset_dir = upload_root / "dataset-timeout"
    dataset_dir.mkdir(parents=True)
    workbook_path = dataset_dir / "workbook.xlsx"
    workbook_path.write_bytes(b"placeholder")

    monkeypatch.setattr(analytics_api, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(
        analytics_api,
        "get_db_connection",
        lambda: FakeConnection(("sales.xlsx", str(workbook_path), "processed")),
    )
    monkeypatch.setattr(
        analytics_api,
        "process_workbook",
        lambda path: SimpleNamespace(
            cleaning=SimpleNamespace(worksheets={"Sales": pd.DataFrame({"revenue": [1]})})
        ),
    )
    monkeypatch.setattr(analytics_api, "profile_dataset", lambda cleaning: _profile())

    class SlowPlanner:
        def generate_plan(self, profile):
            raise AnalyticsPlanningTimeoutError("Ollama inference timed out.")

    monkeypatch.setattr(analytics_api, "AnalyticsPlanner", SlowPlanner)

    with pytest.raises(analytics_api.HTTPException) as error:
        analytics_api.generate_dataset_analytics("dataset-timeout")
    assert error.value.status_code == 504
    assert "timed out" in error.value.detail.lower()


def test_analytics_endpoint_excludes_reference_sheet_from_analyzed_row_count(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    dataset_dir = upload_root / "dataset-reference"
    dataset_dir.mkdir(parents=True)
    workbook_path = dataset_dir / "workbook.xlsx"
    workbook_path.write_bytes(b"placeholder")

    monkeypatch.setattr(analytics_api, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(
        analytics_api,
        "get_db_connection",
        lambda: FakeConnection(("sales.xlsx", str(workbook_path), "processed")),
    )
    monkeypatch.setattr(
        analytics_api,
        "process_workbook",
        lambda path: SimpleNamespace(
            cleaning=SimpleNamespace(worksheets={
                "Sales": pd.DataFrame({"region": ["North", "South", "North"], "revenue": [100, 50, 25]}),
                "Test Guide": pd.DataFrame({"column": ["revenue"], "issue": ["mixed values"]}),
            })
        ),
    )

    profile_data = _profile().model_dump(mode="python")
    profile_data["total_worksheet_count"] = 2
    profile_data["successful_worksheet_count"] = 2
    profile_data["worksheets"]["Test Guide"] = {
        "worksheet_name": "Test Guide", "row_count": 1, "column_count": 2,
        "columns": [
            {
                "column_name": "column", "original_name": "Column",
                "pandas_dtype": "object", "inferred_type": "categorical",
                "semantic_role": "category", "non_null_count": 1,
                "missing_value_count": 0, "blank_string_count": 0,
                "missing_percentage": 0, "unique_value_count": 1,
                "unique_value_percentage": 100,
            },
            {
                "column_name": "issue", "original_name": "Issue",
                "pandas_dtype": "object", "inferred_type": "text",
                "semantic_role": "text", "non_null_count": 1,
                "missing_value_count": 0, "blank_string_count": 0,
                "missing_percentage": 0, "unique_value_count": 1,
                "unique_value_percentage": 100,
            },
        ],
    }
    monkeypatch.setattr(
        analytics_api,
        "profile_dataset",
        lambda cleaning: DatasetProfile.model_validate(profile_data),
    )

    class FakePlanner:
        def generate_plan(self, profile):
            return _plan()

    monkeypatch.setattr(analytics_api, "AnalyticsPlanner", FakePlanner)
    result = analytics_api.generate_dataset_analytics("dataset-reference")

    assert result["row_count"] == 3
    assert result["worksheet_count"] == 1
    assert result["kpis"][0]["value"] == 3
