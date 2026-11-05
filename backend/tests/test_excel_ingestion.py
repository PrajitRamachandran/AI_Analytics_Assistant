import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from pathlib import Path

from openpyxl import Workbook
import pandas as pd

from app.modules.excel_ingestion import (
    ExcelIngestionError,
    ingest_excel_workbook,
)


class TestExcelWorkbookIngestion(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)

    def create_workbook(self, filename="sample.xlsx"):
        workbook = Workbook()
        workbook.active.title = "Sales"
        workbook.active.append(["Order ID", "Revenue"])
        workbook.active.append([1, 125.50])

        employees = workbook.create_sheet("Employees")
        employees.append(["Employee", "Start Date"])
        employees.append(["Asha", datetime(2024, 1, 15)])

        path = self.directory / filename
        workbook.save(path)
        workbook.close()
        return path

    def test_reads_workbook_with_multiple_worksheets(self):
        path = self.create_workbook()

        result = ingest_excel_workbook(path)

        self.assertEqual(result.total_worksheet_count, 2)
        self.assertEqual(result.successful_worksheet_count, 2)
        self.assertEqual(result.failed_worksheet_count, 0)
        self.assertEqual(list(result.worksheets), ["Sales", "Employees"])
        self.assertEqual(result.worksheets["Sales"].shape, (1, 2))
        self.assertEqual(result.worksheets["Employees"].shape, (1, 2))

    def test_reads_empty_worksheet_gracefully(self):
        workbook = Workbook()
        workbook.active.title = "Empty"
        workbook.create_sheet("Data").append(["Value"])
        workbook["Data"].append([10])
        path = self.directory / "empty_sheet.xlsx"
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)

        self.assertEqual(result.successful_worksheet_count, 2)
        self.assertEqual(result.failed_worksheet_count, 0)
        self.assertIsInstance(result.worksheets["Empty"], pd.DataFrame)
        self.assertTrue(result.worksheets["Empty"].empty)

    def test_preserves_worksheet_names(self):
        result = ingest_excel_workbook(self.create_workbook())

        self.assertEqual(result.worksheet_names, ["Sales", "Employees"])
        self.assertEqual(result.filename, "sample.xlsx")

    def test_preserves_missing_values(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Missing Values"
        sheet.append(["Name", "Amount"])
        sheet.append(["Asha", None])
        sheet.append([None, 20])
        path = self.directory / "missing.xlsx"
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        dataframe = result.worksheets["Missing Values"]

        self.assertTrue(pd.isna(dataframe.loc[0, "Amount"]))
        self.assertTrue(pd.isna(dataframe.loc[1, "Name"]))

    def test_preserves_date_values(self):
        expected_date = datetime(2024, 1, 15)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dates"
        sheet.append(["Start Date"])
        sheet.append([expected_date])
        path = self.directory / "dates.xlsx"
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        actual_date = result.worksheets["Dates"].loc[0, "Start Date"]

        self.assertEqual(pd.Timestamp(actual_date), pd.Timestamp(expected_date))

    def test_invalid_file_path_raises_file_not_found(self):
        missing_path = self.directory / "does_not_exist.xlsx"

        with self.assertRaises(FileNotFoundError):
            ingest_excel_workbook(missing_path)

    def test_unsupported_extension_raises_value_error(self):
        unsupported_path = self.directory / "workbook.csv"
        unsupported_path.write_text("a,b\n1,2", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Only .xlsx"):
            ingest_excel_workbook(unsupported_path)

    def test_sheet_error_does_not_stop_other_worksheets(self):
        path = self.create_workbook()
        original_read_excel = pd.read_excel

        def read_with_one_failure(io, sheet_name=0, **kwargs):
            if sheet_name == "Sales":
                raise ValueError("Simulated worksheet parsing failure")
            return original_read_excel(io, sheet_name=sheet_name, **kwargs)

        with patch("app.modules.excel_ingestion.pd.read_excel", side_effect=read_with_one_failure):
            result = ingest_excel_workbook(path)

        self.assertEqual(result.total_worksheet_count, 2)
        self.assertEqual(result.successful_worksheet_count, 1)
        self.assertEqual(result.failed_worksheet_count, 1)
        self.assertEqual(result.worksheet_names, ["Sales", "Employees"])
        self.assertIn("Sales", result.worksheet_errors)
        self.assertIn("Employees", result.worksheets)

    def test_unreadable_workbook_raises_ingestion_error(self):
        invalid_workbook = self.directory / "unreadable.xlsx"
        invalid_workbook.write_bytes(b"this is not an Excel workbook")

        with self.assertRaises(ExcelIngestionError):
            ingest_excel_workbook(invalid_workbook)


if __name__ == "__main__":
    unittest.main()
