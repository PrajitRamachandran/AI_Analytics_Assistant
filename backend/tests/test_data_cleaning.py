"""Unit tests for conservative workbook data cleaning."""

import unittest

import pandas as pd

from app.modules.excel_ingestion import WorkbookIngestionResult
from app.modules.data_normalization import normalize_workbook
from app.modules.data_cleaning import (
    CleaningConfig,
    clean_workbook,
)


def make_normalized_result(worksheets, worksheet_names=None, worksheet_errors=None):
    names = worksheet_names or list(worksheets.keys())
    ingestion_result = WorkbookIngestionResult(
        filename="cleaning_test.xlsx",
        total_worksheet_count=len(names),
        worksheet_names=names,
        worksheets=worksheets,
        worksheet_errors=worksheet_errors or {},
    )
    return normalize_workbook(ingestion_result)


class TestDataCleaning(unittest.TestCase):
    def test_removes_fully_empty_rows_by_default(self):
        df = pd.DataFrame({
            "Order ID": [1, None, 2],
            "Revenue": [100, None, 200],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        cleaned = result.worksheets["Sales"]
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned["order_id"].tolist(), [1.0, 2.0])
        self.assertEqual(
            result.quality_reports["Sales"].empty_row_positions, [1]
        )
        self.assertEqual(
            result.quality_reports["Sales"].removed_empty_row_count, 1
        )

    def test_removes_fully_empty_columns_by_default(self):
        df = pd.DataFrame({
            "Order ID": [1, 2],
            "Unused": [None, None],
            "Revenue": [100, 200],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["order_id", "revenue"],
        )
        self.assertEqual(
            result.quality_reports["Sales"].empty_column_names, ["unused"]
        )
        self.assertEqual(
            result.quality_reports["Sales"].removed_empty_column_count, 1
        )

    def test_whitespace_only_cells_are_considered_empty_for_empty_rows(self):
        df = pd.DataFrame({
            "Order ID": [1, "   ", 2],
            "Revenue": [100, "\t", 200],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        self.assertEqual(len(result.worksheets["Sales"]), 2)
        self.assertEqual(
            result.quality_reports["Sales"].empty_row_positions, [1]
        )

    def test_partially_missing_values_are_reported_not_replaced(self):
        df = pd.DataFrame({
            "Revenue": [100.0, None, 300.0],
            "Region": ["North", "South", "West"],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        cleaned = result.worksheets["Sales"]
        self.assertEqual(len(cleaned), 3)
        self.assertTrue(pd.isna(cleaned["revenue"].iloc[1]))
        report = result.quality_reports["Sales"].column_quality[0]
        self.assertEqual(report.missing_value_count, 1)
        self.assertEqual(report.missing_percentage, 33.33)

    def test_whitespace_only_values_are_reported_as_blank_strings(self):
        df = pd.DataFrame({
            "Region": ["North", "   ", "South"],
            "Store": ["A", "B", "C"],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        report = result.quality_reports["Sales"].column_quality[0]
        self.assertEqual(report.blank_string_count, 1)
        self.assertEqual(report.missing_percentage, 33.33)
        self.assertEqual(len(result.worksheets["Sales"]), 3)

    def test_duplicate_rows_are_reported_but_retained_by_default(self):
        df = pd.DataFrame({
            "Order ID": [1, 1, 2],
            "Revenue": [100, 100, 200],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        self.assertEqual(len(result.worksheets["Sales"]), 3)
        self.assertEqual(result.quality_reports["Sales"].duplicate_row_count, 1)
        self.assertEqual(
            result.quality_reports["Sales"].removed_duplicate_row_count, 0
        )

    def test_duplicate_rows_can_be_removed_when_explicitly_enabled(self):
        df = pd.DataFrame({
            "Order ID": [1, 1, 2],
            "Revenue": [100, 100, 200],
        })
        result = clean_workbook(
            make_normalized_result({"Sales": df}),
            CleaningConfig(remove_duplicate_rows=True),
        )
        self.assertEqual(len(result.worksheets["Sales"]), 2)
        self.assertEqual(
            result.quality_reports["Sales"].removed_duplicate_row_count, 1
        )

    def test_duplicate_removal_does_not_remove_blank_rows_when_empty_row_removal_disabled(self):
        df = pd.DataFrame({
            "Order ID": [1, 1, None, None],
            "Revenue": [100, 100, None, None],
        })
        result = clean_workbook(
            make_normalized_result({"Sales": df}),
            CleaningConfig(
                remove_empty_rows=False,
                remove_empty_columns=True,
                remove_duplicate_rows=True,
            ),
        )
        cleaned = result.worksheets["Sales"]
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned.isna().all(axis=1).sum(), 2)
        self.assertEqual(
            result.quality_reports["Sales"].removed_duplicate_row_count, 1
        )

    def test_empty_row_removal_can_be_disabled(self):
        df = pd.DataFrame({"Order ID": [1, None], "Revenue": [100, None]})
        result = clean_workbook(
            make_normalized_result({"Sales": df}),
            CleaningConfig(remove_empty_rows=False),
        )
        self.assertEqual(len(result.worksheets["Sales"]), 2)
        self.assertEqual(
            result.quality_reports["Sales"].removed_empty_row_count, 0
        )

    def test_empty_column_removal_can_be_disabled(self):
        df = pd.DataFrame({"Order ID": [1, 2], "Unused": [None, None]})
        result = clean_workbook(
            make_normalized_result({"Sales": df}),
            CleaningConfig(remove_empty_columns=False),
        )
        self.assertIn("unused", result.worksheets["Sales"].columns)
        self.assertEqual(
            result.quality_reports["Sales"].removed_empty_column_count, 0
        )

    def test_duplicate_empty_rows_are_not_counted_as_duplicate_records(self):
        df = pd.DataFrame({
            "Order ID": [1, None, None],
            "Revenue": [100, None, None],
        })
        result = clean_workbook(
            make_normalized_result({"Sales": df}),
            CleaningConfig(remove_empty_rows=False),
        )
        self.assertEqual(result.quality_reports["Sales"].duplicate_row_count, 0)

    def test_mixed_python_value_types_are_flagged(self):
        df = pd.DataFrame({"Code": [100, "ABC", 200]})
        result = clean_workbook(make_normalized_result({"Data": df}))
        report = result.quality_reports["Data"].column_quality[0]
        self.assertIn("int", report.mixed_value_types)
        self.assertIn("str", report.mixed_value_types)

    def test_whitespace_padded_strings_are_reported_without_modification(self):
        df = pd.DataFrame({"Region": [" North ", "South"]})
        result = clean_workbook(make_normalized_result({"Sales": df}))
        report = result.quality_reports["Sales"].column_quality[0]
        self.assertEqual(report.whitespace_padded_string_count, 1)
        self.assertEqual(
            result.worksheets["Sales"]["region"].iloc[0], " North "
        )

    def test_original_dataframe_is_never_modified(self):
        df = pd.DataFrame({
            "Order ID": [1, None, 1],
            "Unused": [None, None, None],
        })
        original_copy = df.copy(deep=True)
        normalized = make_normalized_result({"Sales": df})
        normalized_copy = normalized.worksheets["Sales"].copy(deep=True)
        clean_workbook(normalized)
        pd.testing.assert_frame_equal(df, original_copy)
        pd.testing.assert_frame_equal(normalized.worksheets["Sales"], normalized_copy)

    def test_empty_worksheet_is_handled_gracefully(self):
        df = pd.DataFrame()
        result = clean_workbook(make_normalized_result({"Empty": df}))
        self.assertIn("Empty", result.worksheets)
        self.assertEqual(result.worksheets["Empty"].shape, (0, 0))
        self.assertEqual(result.successful_worksheet_count, 1)

    def test_header_only_worksheet_retains_its_columns(self):
        df = pd.DataFrame(columns=["Order ID", "Revenue"])
        result = clean_workbook(make_normalized_result({"Headers": df}))
        self.assertEqual(
            list(result.worksheets["Headers"].columns),
            ["order_id", "revenue"],
        )

    def test_multiple_worksheets_are_cleaned_independently(self):
        sales = pd.DataFrame({"Order ID": [1, None], "Revenue": [100, None]})
        employees = pd.DataFrame({"Employee": ["A", "B"]})
        result = clean_workbook(
            make_normalized_result({"Sales": sales, "Employees": employees})
        )
        self.assertEqual(result.successful_worksheet_count, 2)
        self.assertEqual(len(result.worksheets["Sales"]), 1)
        self.assertEqual(len(result.worksheets["Employees"]), 2)

    def test_worksheet_names_and_existing_errors_are_preserved(self):
        sales = pd.DataFrame({"Order ID": [1]})
        errors = {"Broken": "Unable to read worksheet 'Broken'."}
        normalized = make_normalized_result(
            {"Sales": sales},
            worksheet_names=["Sales", "Broken"],
            worksheet_errors=errors,
        )
        result = clean_workbook(normalized)
        self.assertEqual(result.worksheet_names, ["Sales", "Broken"])
        self.assertEqual(result.worksheet_errors, errors)
        self.assertEqual(result.total_worksheet_count, 2)
        self.assertEqual(result.failed_worksheet_count, 1)

    def test_column_mappings_and_type_metadata_follow_retained_columns(self):
        df = pd.DataFrame({"Order ID": [1, 2], "Unused": [None, None]})
        result = clean_workbook(make_normalized_result({"Sales": df}))
        self.assertEqual(
            [item.normalized_name for item in result.column_mappings["Sales"]],
            ["order_id"],
        )
        self.assertEqual(
            [item.normalized_name for item in result.column_types["Sales"]],
            ["order_id"],
        )

    def test_one_worksheet_cleaning_failure_does_not_stop_others(self):
        class BrokenFrame:
            def copy(self, deep=True):
                raise RuntimeError("simulated cleaning failure")

        good_df = pd.DataFrame({"Order ID": [1]})
        normalized = make_normalized_result({"Good": good_df})
        normalized.worksheets["Broken"] = BrokenFrame()
        normalized.worksheet_names.append("Broken")
        normalized.total_worksheet_count = 2

        result = clean_workbook(normalized)
        self.assertIn("Good", result.worksheets)
        self.assertNotIn("Broken", result.worksheets)
        self.assertIn("Broken", result.worksheet_errors)
        self.assertIn("simulated cleaning failure", result.worksheet_errors["Broken"])

    def test_non_normalization_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            clean_workbook({"Sales": pd.DataFrame({"A": [1]})})

    def test_quality_report_tracks_before_and_after_dimensions(self):
        df = pd.DataFrame({
            "Order ID": [1, None, 2],
            "Unused": [None, None, None],
        })
        result = clean_workbook(make_normalized_result({"Sales": df}))
        report = result.quality_reports["Sales"]
        self.assertEqual((report.original_row_count, report.original_column_count), (3, 2))
        self.assertEqual((report.cleaned_row_count, report.cleaned_column_count), (2, 1))


if __name__ == "__main__":
    unittest.main()
