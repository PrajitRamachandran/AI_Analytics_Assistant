"""Unit tests for the workbook data normalisation module."""

import unittest

import pandas as pd

from app.modules.excel_ingestion import WorkbookIngestionResult
from app.modules.data_normalization import normalize_workbook


def make_ingestion_result(worksheets, worksheet_names=None, worksheet_errors=None):
    names = worksheet_names or list(worksheets.keys())
    return WorkbookIngestionResult(
        filename="test_workbook.xlsx",
        total_worksheet_count=len(names),
        worksheet_names=names,
        worksheets=worksheets,
        worksheet_errors=worksheet_errors or {},
    )


class TestDataNormalization(unittest.TestCase):
    def test_standard_column_names_are_converted_to_snake_case(self):
        df = pd.DataFrame([[1, "A", 2]], columns=[
            "Order ID", "Customer Name", "Total Revenue"
        ])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["order_id", "customer_name", "total_revenue"],
        )

    def test_leading_and_trailing_whitespace_is_removed(self):
        df = pd.DataFrame([[1, "A"]], columns=["  Order Date  ", " Region "])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["order_date", "region"],
        )

    def test_special_characters_are_handled_consistently(self):
        df = pd.DataFrame([[1, 2]], columns=["Order-Date", "Revenue ($)"])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["order_date", "revenue"],
        )

    def test_empty_column_names_receive_position_based_names(self):
        df = pd.DataFrame([[1, 2, 3]], columns=["", "  ", None])
        result = normalize_workbook(make_ingestion_result({"Sheet1": df}))
        self.assertEqual(
            list(result.worksheets["Sheet1"].columns),
            ["column_1", "column_2", "column_3"],
        )

    def test_duplicate_original_column_names_receive_unique_suffixes(self):
        df = pd.DataFrame([[10, 20, 30]], columns=["Revenue", "Revenue", "Revenue"])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["revenue", "revenue_2", "revenue_3"],
        )

    def test_names_that_collide_after_normalization_are_unique(self):
        df = pd.DataFrame([[1, 2, 3]], columns=["Order ID", "Order-ID", "order_id"])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        self.assertEqual(
            list(result.worksheets["Sales"].columns),
            ["order_id", "order_id_2", "order_id_3"],
        )

    def test_normalization_does_not_change_numerical_values(self):
        df = pd.DataFrame({"Total Revenue ($)": [100.5, 250.0]})
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        pd.testing.assert_series_equal(
            result.worksheets["Sales"]["total_revenue"],
            df["Total Revenue ($)"],
            check_names=False,
        )

    def test_normalization_preserves_datetime_values_and_dtype(self):
        dates = pd.to_datetime(["2026-01-01", "2026-02-01"])
        df = pd.DataFrame({"Order Date": dates})
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        normalized = result.worksheets["Sales"]["order_date"]
        pd.testing.assert_series_equal(normalized, df["Order Date"], check_names=False)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(normalized.dtype))
        self.assertEqual(result.column_types["Sales"][0].data_category, "datetime")

    def test_missing_values_are_preserved(self):
        df = pd.DataFrame({"Sales Amount": [10.0, None, 30.0]})
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        normalized = result.worksheets["Sales"]["sales_amount"]
        self.assertTrue(pd.isna(normalized.iloc[1]))
        self.assertEqual(normalized.iloc[0], 10.0)
        self.assertEqual(normalized.iloc[2], 30.0)

    def test_original_dataframe_is_not_modified(self):
        df = pd.DataFrame([[1, "A"]], columns=["Order ID", "Customer Name"])
        original_copy = df.copy(deep=True)
        normalize_workbook(make_ingestion_result({"Sales": df}))
        pd.testing.assert_frame_equal(df, original_copy)

    def test_empty_worksheet_is_normalized_successfully(self):
        df = pd.DataFrame()
        result = normalize_workbook(make_ingestion_result({"Empty": df}))
        self.assertIn("Empty", result.worksheets)
        self.assertEqual(result.successful_worksheet_count, 1)
        self.assertEqual(result.failed_worksheet_count, 0)
        self.assertEqual(result.worksheets["Empty"].shape, (0, 0))

    def test_multiple_worksheets_are_processed_independently(self):
        sales = pd.DataFrame({"Order ID": [1]})
        employees = pd.DataFrame({"Employee Name": ["Alex"]})
        result = normalize_workbook(
            make_ingestion_result({"Sales": sales, "Employees": employees})
        )
        self.assertEqual(result.successful_worksheet_count, 2)
        self.assertEqual(list(result.worksheets["Sales"].columns), ["order_id"])
        self.assertEqual(
            list(result.worksheets["Employees"].columns), ["employee_name"]
        )

    def test_worksheet_names_are_preserved(self):
        df = pd.DataFrame({"Order ID": [1]})
        result = normalize_workbook(
            make_ingestion_result({"Sales Data": df}, ["Sales Data"])
        )
        self.assertEqual(result.worksheet_names, ["Sales Data"])
        self.assertIn("Sales Data", result.worksheets)

    def test_original_to_normalized_mapping_retains_column_positions(self):
        df = pd.DataFrame([[1, 2]], columns=["Revenue", "Revenue"])
        result = normalize_workbook(make_ingestion_result({"Sales": df}))
        mappings = result.column_mappings["Sales"]
        self.assertEqual(len(mappings), 2)
        self.assertEqual(
            [(m.position, m.original_name, m.normalized_name) for m in mappings],
            [(0, "Revenue", "revenue"), (1, "Revenue", "revenue_2")],
        )

    def test_existing_ingestion_errors_are_preserved(self):
        df = pd.DataFrame({"Order ID": [1]})
        errors = {"Broken": "Unable to read worksheet 'Broken'."}
        result = normalize_workbook(
            make_ingestion_result(
                {"Sales": df},
                worksheet_names=["Sales", "Broken"],
                worksheet_errors=errors,
            )
        )
        self.assertEqual(result.worksheet_errors, errors)
        self.assertEqual(result.total_worksheet_count, 2)
        self.assertEqual(result.failed_worksheet_count, 1)

    def test_one_worksheet_normalization_failure_does_not_stop_others(self):
        class BrokenFrame:
            def copy(self, deep=True):
                raise RuntimeError("simulated copy failure")

        good_df = pd.DataFrame({"Order ID": [1]})
        ingestion = make_ingestion_result(
            {"Broken": BrokenFrame(), "Sales": good_df},
            worksheet_names=["Broken", "Sales"],
        )
        result = normalize_workbook(ingestion)
        self.assertIn("Sales", result.worksheets)
        self.assertNotIn("Broken", result.worksheets)
        self.assertIn("Broken", result.worksheet_errors)
        self.assertIn("simulated copy failure", result.worksheet_errors["Broken"])
        self.assertEqual(result.successful_worksheet_count, 1)
        self.assertEqual(result.failed_worksheet_count, 1)

    def test_dtype_metadata_identifies_numeric_boolean_and_categorical(self):
        df = pd.DataFrame({
            "Units Sold": pd.Series([1, 2], dtype="int64"),
            "Is Active": pd.Series([True, False], dtype="bool"),
            "Segment": pd.Series(["A", "B"], dtype="category"),
        })
        result = normalize_workbook(make_ingestion_result({"Data": df}))
        categories = [item.data_category for item in result.column_types["Data"]]
        self.assertEqual(categories, ["numeric", "boolean", "categorical"])

    def test_non_ingestion_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            normalize_workbook({"Sales": pd.DataFrame({"A": [1]})})


if __name__ == "__main__":
    unittest.main()
