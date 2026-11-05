"""Read Excel workbooks into independent worksheet DataFrames.

This module performs ingestion only. Cell values, blanks, duplicate rows and
header text are left as Pandas reads them; the only structural decision made
here is locating the header row when a worksheet begins with fully blank rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd

SUPPORTED_EXTENSIONS = (".xlsx", ".xlsm")
_HEADER_PROBE_ROWS = 200


@dataclass
class WorkbookIngestionResult:
    """Result returned after attempting to ingest an Excel workbook."""

    filename: str
    total_worksheet_count: int
    worksheet_names: List[str] = field(default_factory=list)
    worksheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    worksheet_errors: Dict[str, str] = field(default_factory=dict)

    @property
    def successful_worksheet_count(self) -> int:
        """Number of worksheets successfully read, including empty sheets."""
        return len(self.worksheets)

    @property
    def failed_worksheet_count(self) -> int:
        """Number of worksheets that could not be read."""
        return len(self.worksheet_errors)


class ExcelIngestionError(Exception):
    """Raised when a workbook cannot be opened for ingestion."""


def _is_blank(value: Any) -> bool:
    """Return whether a raw cell value is null or a whitespace-only string."""
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _detect_header_row(workbook: pd.ExcelFile, sheet_name: str) -> int:
    """Return the zero-based index of the first row containing any value."""
    probe = workbook.parse(
        sheet_name=sheet_name,
        header=None,
        nrows=_HEADER_PROBE_ROWS,
    )
    for position, row in enumerate(probe.itertuples(index=False, name=None)):
        if not all(_is_blank(value) for value in row):
            return position
    return 0


def _read_worksheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Read one worksheet, skipping fully blank rows above the header."""
    header_row = _detect_header_row(workbook, sheet_name)
    return workbook.parse(sheet_name=sheet_name, header=header_row)


def ingest_excel_workbook(
    file_path: Union[str, Path],
) -> WorkbookIngestionResult:
    """Read every worksheet of an ``.xlsx``/``.xlsm`` workbook into a DataFrame.

    Each worksheet is read independently so a worksheet-level parsing error
    does not prevent the remaining worksheets from being ingested. The first
    non-blank row of each worksheet is used as its header. Formula cells are
    read as the values cached by the application that last saved the file.

    The source workbook is opened read-only and is never modified.

    Args:
        file_path: Path to the uploaded workbook.

    Returns:
        A WorkbookIngestionResult containing successfully read DataFrames and
        any worksheet-specific errors.

    Raises:
        FileNotFoundError: If the supplied path does not exist or is not a file.
        ValueError: If the file extension is not supported.
        ExcelIngestionError: If the workbook cannot be opened or contains no
            worksheets.
    """
    path = Path(file_path).expanduser()

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "Unsupported file extension. Only .xlsx and .xlsm files are supported."
        )

    if not path.exists():
        raise FileNotFoundError(f"Excel workbook not found: {path}")

    if not path.is_file():
        raise FileNotFoundError(f"Excel workbook path is not a file: {path}")

    worksheets: Dict[str, pd.DataFrame] = {}
    worksheet_errors: Dict[str, str] = {}

    try:
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            sheet_names = [str(name) for name in workbook.sheet_names]

            if not sheet_names:
                raise ExcelIngestionError(
                    f"The Excel workbook contains no worksheets: {path.name}"
                )

            for sheet_name in sheet_names:
                try:
                    worksheets[sheet_name] = _read_worksheet(workbook, sheet_name)
                except Exception as exc:
                    worksheet_errors[sheet_name] = (
                        f"Unable to read worksheet '{sheet_name}': {exc}"
                    )

    except ExcelIngestionError:
        raise
    except Exception as exc:
        raise ExcelIngestionError(
            f"Unable to open or parse Excel workbook '{path.name}': {exc}"
        ) from exc

    return WorkbookIngestionResult(
        filename=path.name,
        total_worksheet_count=len(sheet_names),
        worksheet_names=list(sheet_names),
        worksheets=worksheets,
        worksheet_errors=worksheet_errors,
    )
