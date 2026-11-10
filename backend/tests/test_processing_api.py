"""Tests for the Module 2 processing API response helpers and endpoint."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys
import types

# The API tests mock database access. Provide an import stub only when the
# optional local psycopg driver is absent in the test runner environment.
if importlib.util.find_spec("psycopg") is None:
    sys.modules["psycopg"] = types.ModuleType("psycopg")

import numpy as np
import pandas as pd
from openpyxl import Workbook

from app.api import processing as processing_api


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


class TestProcessingAPI(unittest.TestCase):
    def _create_workbook(self, path: Path):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales"
        sheet.append(["Order ID", "Revenue", "Unused"])
        sheet.append([1, 100, None])
        sheet.append([2, 200, None])
        workbook.save(path)
        workbook.close()

    def test_json_safe_value_converts_pandas_and_numpy_values(self):
        self.assertEqual(
            processing_api._json_safe_value(pd.Timestamp("2026-01-02")),
            "2026-01-02T00:00:00",
        )
        self.assertIsNone(processing_api._json_safe_value(float("nan")))
        self.assertEqual(processing_api._json_safe_value(np.int64(7)), 7)

    def test_worksheet_response_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "sample.xlsx"
            self._create_workbook(file_path)
            result = processing_api.process_workbook(file_path)
            payload = processing_api._build_worksheet_response(result, "Sales")
            encoded = json.dumps(payload)
            self.assertIn('"worksheet_name": "Sales"', encoded)
            self.assertEqual(payload["row_count"], 2)
            self.assertEqual(payload["column_count"], 2)
            self.assertEqual(payload["quality"]["removed_empty_column_count"], 1)
            self.assertIn("total_missing_value_count", payload["quality"])
            self.assertIn("total_whitespace_padded_string_count", payload["quality"])
            self.assertIn("whitespace_padded_string_count", payload["columns"][0])
            self.assertIn("normalization", payload["columns"][0])

    def test_processing_endpoint_processes_dataset_and_updates_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            upload_root = Path(temp_dir)
            dataset_dir = upload_root / "dataset-123"
            dataset_dir.mkdir()
            workbook_path = dataset_dir / "workbook.xlsx"
            self._create_workbook(workbook_path)

            select_connection = FakeConnection(
                ("sample.xlsx", str(workbook_path.resolve()))
            )
            update_connection = FakeConnection()

            with (
                patch.object(processing_api, "UPLOAD_DIR", upload_root),
                patch.object(
                    processing_api,
                    "get_db_connection",
                    side_effect=[select_connection, update_connection],
                ),
            ):
                response = processing_api.process_dataset("dataset-123")

            self.assertEqual(response["status"], "success")
            self.assertEqual(response["processing"]["successful_worksheet_count"], 1)
            self.assertIn("normalized_cell_count", response["processing"])
            self.assertIn("unparseable_cell_count", response["processing"])
            self.assertIn("Sales", response["worksheets"])
            self.assertEqual(len(update_connection.fake_cursor.executed), 1)
            self.assertIn(
                "UPDATE datasets",
                update_connection.fake_cursor.executed[0][0],
            )

    def test_processing_endpoint_returns_404_for_unknown_dataset(self):
        connection = FakeConnection(dataset_row=None)
        with patch.object(
            processing_api,
            "get_db_connection",
            return_value=connection,
        ):
            with self.assertRaises(processing_api.HTTPException) as context:
                processing_api.process_dataset("missing-id")
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
