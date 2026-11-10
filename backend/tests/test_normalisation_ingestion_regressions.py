"""Regression tests for dynamic value normalization and Excel ingestion edges."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from openpyxl import Workbook

from app.modules.data_normalization import normalize_workbook
from app.modules.excel_ingestion import WorkbookIngestionResult, ingest_excel_workbook


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    ingestion = WorkbookIngestionResult(
        filename="dynamic.xlsx",
        total_worksheet_count=1,
        worksheet_names=["Data"],
        worksheets={"Data": frame},
    )
    return normalize_workbook(ingestion).worksheets["Data"]


def test_attendance_aliases_are_inferred_and_unknown_categories_preserved():
    frame = pd.DataFrame({
        "Attendance Status": ["present", "P", 1, "yes", "absent", "A", 0, "no", "WFH"]
    })
    result = _normalize(frame)
    assert result["attendance_status"].tolist() == [
        "Present", "Present", "Present", "Present",
        "Absent", "Absent", "Absent", "Absent", "WFH",
    ]


def test_attendance_column_infers_short_codes_without_full_word_anchors():
    result = _normalize(pd.DataFrame({"Attendance": ["P", "A", "WFH", "Remote"]}))
    assert result["attendance"].tolist() == ["Present", "Absent", "WFH", "Remote"]


def test_generic_status_does_not_guess_ambiguous_short_codes():
    result = _normalize(pd.DataFrame({"Status": ["P", "A", "WFH"]}))
    assert result["status"].tolist() == ["P", "A", "WFH"]


def test_explicit_present_and_absent_anchors_establish_generic_status_context():
    result = _normalize(pd.DataFrame({
        "Status": ["Present", "P", "yes", "Absent", "A", "no", "WFH"]
    }))
    assert result["status"].tolist() == [
        "Present", "Present", "Present", "Absent", "Absent", "Absent", "WFH"
    ]


def test_single_attendance_anchor_does_not_make_a_codes_unambiguous():
    result = _normalize(pd.DataFrame({"Status": ["Present", "P", "A", "WFH"]}))
    assert result["status"].tolist() == ["Present", "P", "A", "WFH"]


def test_generic_boolean_column_is_normalized_separately():
    result = _normalize(pd.DataFrame({"Is Active": ["yes", "no", "1", "0", "custom"]}))
    assert result["is_active"].tolist() == [True, False, True, False, "custom"]


def test_absence_flag_uses_inverse_binary_orientation():
    result = _normalize(pd.DataFrame({"Is Absent": ["yes", "no", 1, 0, "custom"]}))
    assert result["is_absent"].tolist() == ["Absent", "Present", "Absent", "Present", "custom"]


def test_attendance_count_remains_numeric():
    result = _normalize(pd.DataFrame({"Attendance Count": [0, 1, 2, 3]}))
    assert result["attendance_count"].tolist() == [0, 1, 2, 3]
    assert pd.api.types.is_numeric_dtype(result["attendance_count"].dtype)


def test_unrecognized_categories_are_not_title_cased_or_replaced():
    values = ["WFH", "Paid", "in review", "Tier-X", "  Custom  "]
    result = _normalize(pd.DataFrame({"Status": values}))
    assert result["status"].tolist() == values


def test_number_words_and_units_are_normalized_without_losing_unknown_values():
    result = _normalize(pd.DataFrame({
        "Resolution Hours": ["four hours", "2 hours", "45 minutes", "unknown"]
    }))
    values = result["resolution_hours"].tolist()
    assert values[:3] == [4.0, 2.0, 0.75]
    assert values[3] == "unknown"


def test_normalization_never_mutates_input_dataframe():
    frame = pd.DataFrame({"Attendance": ["p", "a", "WFH"]})
    original = frame.copy(deep=True)
    _normalize(frame)
    pd.testing.assert_frame_equal(frame, original)


def test_ingestion_uses_first_nonblank_row_and_preserves_duplicate_headers():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "headers.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append([None, None])
        sheet.append(["Value", "Value"])
        sheet.append([10, 20])
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        frame = result.worksheets["Data"]
        assert list(frame.columns) == ["Value", "Value"]
        assert frame.iloc[0].tolist() == [10, 20]


def test_ingestion_does_not_remove_duplicate_records_or_blank_values():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "records.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Name", "Amount"])
        sheet.append(["Asha", None])
        sheet.append(["Asha", None])
        sheet.append(["Bala", 20])
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        frame = result.worksheets["Data"]
        assert len(frame) == 3
        assert frame.iloc[0].equals(frame.iloc[1])
        assert pd.isna(frame.loc[0, "Amount"])


def test_ingestion_keeps_header_only_sheet_with_zero_records():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "header_only.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Name", "Amount"])
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        frame = result.worksheets["Data"]
        assert list(frame.columns) == ["Name", "Amount"]
        assert frame.empty


def test_ingestion_handles_empty_sheet_alongside_populated_sheet():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "empty_and_full.xlsx"
        workbook = Workbook()
        workbook.active.title = "Empty"
        data = workbook.create_sheet("Data")
        data.append(["Created At", "Name"])
        data.append([datetime(2026, 1, 1), "Asha"])
        workbook.save(path)
        workbook.close()

        result = ingest_excel_workbook(path)
        assert result.successful_worksheet_count == 2
        assert result.worksheets["Empty"].empty
        assert result.worksheets["Data"].loc[0, "Name"] == "Asha"
