"""Integration tests for the Module 2 workbook processing pipeline."""

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.modules.workbook_processing import process_workbook


class TestWorkbookProcessingPipeline(unittest.TestCase):
    def _create_workbook(self, path: Path):
        workbook = Workbook()
        sales = workbook.active
        sales.title = "Sales Data"
        sales.append(["Order ID", "Revenue", "Unused"])
        sales.append([1, 100, None])
        sales.append([2, None, None])
        sales.append([2, None, None])
        sales.append([None, None, None])

        employees = workbook.create_sheet("Employees")
        employees.append(["Employee Name", "Department"])
        employees.append(["Alex", "Sales"])
        employees.append(["Sam", "HR"])

        workbook.save(path)
        workbook.close()

    def test_pipeline_runs_all_three_stages_for_multiple_sheets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "pipeline.xlsx"
            self._create_workbook(file_path)

            result = process_workbook(file_path)

            self.assertEqual(result.ingestion.successful_worksheet_count, 2)
            self.assertEqual(result.normalization.successful_worksheet_count, 2)
            self.assertEqual(result.cleaning.successful_worksheet_count, 2)
            self.assertEqual(
                list(result.cleaning.worksheets),
                ["Sales Data", "Employees"],
            )

    def test_pipeline_removes_only_fully_empty_rows_and_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "pipeline.xlsx"
            self._create_workbook(file_path)

            result = process_workbook(file_path)
            sales = result.cleaning.worksheets["Sales Data"]

            self.assertEqual(list(sales.columns), ["order_id", "revenue"])
            # The row with Order ID 2 and a missing Revenue remains: it is
            # not completely empty. The repeated row is reported, not removed.
            self.assertEqual(len(sales), 3)
            report = result.cleaning.quality_reports["Sales Data"]
            self.assertEqual(report.duplicate_row_count, 1)
            self.assertEqual(report.removed_duplicate_row_count, 0)

    def test_pipeline_preserves_original_workbook_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "pipeline.xlsx"
            self._create_workbook(file_path)
            original_bytes = file_path.read_bytes()

            process_workbook(file_path)

            self.assertEqual(file_path.read_bytes(), original_bytes)

    def test_pipeline_carries_worksheet_names_and_metadata_forward(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "pipeline.xlsx"
            self._create_workbook(file_path)

            result = process_workbook(file_path)

            self.assertEqual(
                result.cleaning.worksheet_names,
                ["Sales Data", "Employees"],
            )
            self.assertIn("order_id", result.cleaning.worksheets["Sales Data"].columns)
            self.assertEqual(
                result.cleaning.column_mappings["Sales Data"][0].original_name,
                "Order ID",
            )

    def test_pipeline_rejects_missing_workbook_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.xlsx"
            with self.assertRaises(FileNotFoundError):
                process_workbook(missing_path)


if __name__ == "__main__":
    unittest.main()
