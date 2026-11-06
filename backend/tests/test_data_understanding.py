"""Tests for the Module 3 deterministic data understanding engine."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from app.modules.data_cleaning import clean_workbook
from app.modules.data_normalization import normalize_workbook
from app.modules.excel_ingestion import WorkbookIngestionResult
from app.modules import data_understanding
from app.modules.data_understanding import profile_dataset
from app.schemas.data_understanding import DatasetProfile


def _cleaning_result(worksheets):
    ingestion = WorkbookIngestionResult(
        filename="sample.xlsx",
        total_worksheet_count=len(worksheets),
        worksheet_names=list(worksheets),
        worksheets=worksheets,
    )
    return clean_workbook(normalize_workbook(ingestion))


def _sheet(result, name):
    return result.worksheets[name]


def test_numerical_column_profile():
    result = _cleaning_result({"Sales": pd.DataFrame({"Revenue": [10, 20, 30, None], "Region": ["A", "B", "C", "D"]})})
    col = _sheet(profile_dataset(result), "Sales").columns[0]
    assert col.inferred_type == "numerical"
    assert col.semantic_role == "amount"
    assert col.numerical_statistics.minimum == 10
    assert col.numerical_statistics.maximum == 30
    assert col.numerical_statistics.mean == 20
    assert col.numerical_statistics.median == 20
    assert col.numerical_statistics.total == 60
    assert col.missing_value_count == 1


def test_categorical_column_profile():
    result = _cleaning_result({"Data": pd.DataFrame({"Region": ["East", "West", "East", "North"]})})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert col.inferred_type == "categorical"
    assert col.semantic_role == "category"
    assert col.categorical_statistics.unique_category_count == 3
    assert col.categorical_statistics.most_frequent[0].value == "East"
    assert col.categorical_statistics.most_frequent[0].count == 2


def test_date_column_profile():
    result = _cleaning_result({"Data": pd.DataFrame({"Order Date": pd.to_datetime(["2025-01-02", "2025-03-04"])})})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert col.inferred_type == "date"
    assert col.semantic_role == "date"
    assert col.date_statistics.earliest.startswith("2025-01-02")
    assert col.date_statistics.latest.startswith("2025-03-04")


def test_text_column_profile():
    values = [f"Long description number {i}" for i in range(30)]
    result = _cleaning_result({"Data": pd.DataFrame({"Description": values})})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert col.inferred_type == "text"
    assert col.semantic_role == "text"
    assert len(col.sample_values) == 5


def test_identifier_detection_precedes_numeric_role():
    result = _cleaning_result({"Data": pd.DataFrame({"Customer ID": [101, 102, 103]})})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert col.inferred_type == "numerical"
    assert col.semantic_role == "identifier"


def test_missing_and_blank_string_statistics_are_separate():
    result = _cleaning_result({"Data": pd.DataFrame({"Comment": ["hello", "", "   ", None, "world"], "Keep": [1, 2, 3, 4, 5]})})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert col.missing_value_count == 1
    assert col.blank_string_count == 2
    assert col.missing_percentage == 60.0


def test_duplicate_count_comes_from_module2_quality_report():
    result = _cleaning_result({"Data": pd.DataFrame({"value": [1, 1, 2, 2, 2]})})
    profile = _sheet(profile_dataset(result), "Data")
    assert profile.duplicate_row_count == 3


def test_multiple_worksheets_profile_independently():
    result = _cleaning_result({
        "One": pd.DataFrame({"a": [1, 2]}),
        "Two": pd.DataFrame({"b": ["x", "y"]}),
    })
    profile = profile_dataset(result)
    assert set(profile.worksheets) == {"One", "Two"}
    assert profile.successful_worksheet_count == 2


def test_empty_worksheet_is_supported():
    result = _cleaning_result({"Empty": pd.DataFrame()})
    profile = _sheet(profile_dataset(result), "Empty")
    assert profile.row_count == 0
    assert profile.column_count == 0
    assert profile.columns == []


def test_empty_column_is_retained_when_no_records_exist():
    result = _cleaning_result({"Empty": pd.DataFrame({"empty_col": pd.Series(dtype="object")})})
    profile = _sheet(profile_dataset(result), "Empty")
    assert profile.column_count == 1
    assert profile.columns[0].inferred_type == "other"


def test_mixed_data_types_are_reported_without_crashing():
    frame = pd.DataFrame({"mixed": pd.Series([1, "two", 3.5], dtype=object)})
    result = _cleaning_result({"Data": frame})
    col = _sheet(profile_dataset(result), "Data").columns[0]
    assert set(col.mixed_value_types) == {"int", "str", "float"}


def test_profile_is_json_serializable():
    result = _cleaning_result({"Data": pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01"]),
        "value": [np.int64(5)],
    })})
    profile = profile_dataset(result)
    encoded = profile.model_dump(mode="json")
    assert encoded["filename"] == "sample.xlsx"
    assert encoded["worksheets"]["Data"]["columns"][0]["sample_values"]


def test_original_cleaned_dataframe_is_not_modified():
    result = _cleaning_result({"Data": pd.DataFrame({"amount": [10, 20, None], "group": ["A", "B", "A"]})})
    before = result.worksheets["Data"].copy(deep=True)
    profile_dataset(result)
    pd.testing.assert_frame_equal(result.worksheets["Data"], before)


def test_failure_in_one_worksheet_does_not_block_others(monkeypatch):
    result = _cleaning_result({
        "Good": pd.DataFrame({"value": [1, 2]}),
        "Bad": pd.DataFrame({"value": [3, 4]}),
    })
    original = data_understanding.profile_worksheet

    def fail_bad(name, dataframe, cleaning_result):
        if name == "Bad":
            raise RuntimeError("synthetic failure")
        return original(name, dataframe, cleaning_result)

    monkeypatch.setattr(data_understanding, "profile_worksheet", fail_bad)
    profile = profile_dataset(result)
    assert "Good" in profile.worksheets
    assert "Bad" not in profile.worksheets
    assert "synthetic failure" in profile.worksheet_errors["Bad"]
