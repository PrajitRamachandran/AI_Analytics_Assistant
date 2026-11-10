"""Tests for the Module 3 dataset-understanding API endpoint."""

import importlib.util
import importlib.machinery
import json
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook

if "psycopg" not in sys.modules:
    try:
        psycopg_missing = importlib.util.find_spec("psycopg") is None
    except ValueError:
        psycopg_missing = True
    if psycopg_missing:
        psycopg_stub = types.ModuleType("psycopg")
        psycopg_stub.__spec__ = importlib.machinery.ModuleSpec("psycopg", loader=None)
        sys.modules["psycopg"] = psycopg_stub

from app.api import understanding as understanding_api
from app.modules.data_cleaning import CleaningResult


class FakeCursor:
    def __init__(self, dataset_row=None):
        self.dataset_row = dataset_row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.dataset_row


class FakeConnection:
    def __init__(self, dataset_row=None):
        self.fake_cursor = FakeCursor(dataset_row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return self.fake_cursor


def _create_workbook(path: Path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Order ID", "Region", "Revenue", "Order Date"])
    sheet.append([101, "Chennai", 80000, "2026-01-01"])
    sheet.append([102, "Coimbatore", 2500, "2026-01-02"])
    sheet.append([103, "Chennai", 40000, "2026-01-03"])
    workbook.save(path)
    workbook.close()


def test_understanding_endpoint_returns_profile_for_processed_dataset():
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)
        dataset_dir = upload_root / "dataset-123"
        dataset_dir.mkdir()
        workbook_path = dataset_dir / "workbook.xlsx"
        _create_workbook(workbook_path)

        connection = FakeConnection(
            ("quarterly_sales.xlsx", str(workbook_path.resolve()), "processed")
        )

        with (
            patch.object(understanding_api, "UPLOAD_DIR", upload_root),
            patch.object(understanding_api, "get_db_connection", return_value=connection),
        ):
            response = understanding_api.understand_dataset("dataset-123")

        payload = response.model_dump(mode="json")
        json.dumps(payload)

        assert payload["filename"] == "quarterly_sales.xlsx"
        assert payload["total_worksheet_count"] == 1
        assert payload["successful_worksheet_count"] == 1
        assert "Sales" in payload["worksheets"]
        assert payload["worksheets"]["Sales"]["row_count"] == 3
        assert payload["worksheets"]["Sales"]["column_count"] == 4
        assert payload["worksheets"]["Sales"]["columns"]


def test_understanding_endpoint_returns_404_for_unknown_dataset():
    connection = FakeConnection(dataset_row=None)
    with patch.object(
        understanding_api,
        "get_db_connection",
        return_value=connection,
    ):
        with pytest.raises(understanding_api.HTTPException) as error:
            understanding_api.understand_dataset("missing-id")

    assert error.value.status_code == 404


def test_understanding_endpoint_requires_module2_processing_first():
    connection = FakeConnection(("sample.xlsx", "/unused/workbook.xlsx", "uploaded"))
    with patch.object(
        understanding_api,
        "get_db_connection",
        return_value=connection,
    ), patch.object(understanding_api, "process_workbook") as process_mock:
        with pytest.raises(understanding_api.HTTPException) as error:
            understanding_api.understand_dataset("dataset-123")

    assert error.value.status_code == 409
    process_mock.assert_not_called()


def test_understanding_endpoint_returns_404_when_workbook_is_missing():
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)
        dataset_dir = upload_root / "dataset-123"
        dataset_dir.mkdir()
        connection = FakeConnection(
            ("sample.xlsx", str((dataset_dir / "workbook.xlsx").resolve()), "processed")
        )

        with (
            patch.object(understanding_api, "UPLOAD_DIR", upload_root),
            patch.object(understanding_api, "get_db_connection", return_value=connection),
        ):
            with pytest.raises(understanding_api.HTTPException) as error:
                understanding_api.understand_dataset("dataset-123")

    assert error.value.status_code == 404


def test_understanding_endpoint_rejects_storage_path_outside_upload_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir) / "uploads"
        upload_root.mkdir()
        outside_path = Path(temp_dir) / "outside" / "workbook.xlsx"
        connection = FakeConnection(("sample.xlsx", str(outside_path), "processed"))

        with (
            patch.object(understanding_api, "UPLOAD_DIR", upload_root),
            patch.object(understanding_api, "get_db_connection", return_value=connection),
        ):
            with pytest.raises(understanding_api.HTTPException) as error:
                understanding_api.understand_dataset("dataset-123")

    assert error.value.status_code == 500


def test_understanding_endpoint_reports_failure_when_no_worksheets_profile():
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir)
        dataset_dir = upload_root / "dataset-123"
        dataset_dir.mkdir()
        workbook_path = dataset_dir / "workbook.xlsx"
        _create_workbook(workbook_path)
        connection = FakeConnection(
            ("sample.xlsx", str(workbook_path.resolve()), "processed")
        )

        class ProcessingResult:
            cleaning = CleaningResult(
                filename="workbook.xlsx",
                total_worksheet_count=1,
                worksheet_errors={"Sales": "synthetic worksheet failure"},
            )

        with (
            patch.object(understanding_api, "UPLOAD_DIR", upload_root),
            patch.object(understanding_api, "get_db_connection", return_value=connection),
            patch.object(understanding_api, "process_workbook", return_value=ProcessingResult()),
        ):
            with pytest.raises(understanding_api.HTTPException) as error:
                understanding_api.understand_dataset("dataset-123")

    assert error.value.status_code == 422
    assert "No worksheets could be profiled" in error.value.detail
