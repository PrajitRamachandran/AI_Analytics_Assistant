"""Read Excel workbooks into independent worksheet DataFrames.

This module intentionally performs ingestion only. It does not clean,
normalise, or otherwise modify worksheet data.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Union

import pandas as pd


@dataclass
class WorkbookIngestionResult:
    """Result returned after attempting to ingest an Excel workbook."""

    filename: str
    total_worksheet_count: int
    worksheet_names: list[str] = field(default_factory=list)
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


def ingest_excel_workbook(
    file_path: Union[str, Path],
) -> WorkbookIngestionResult:
    """Read every worksheet in an ``.xlsx`` workbook into a DataFrame.

    Each worksheet is read independently so a worksheet-level parsing error
    does not prevent the remaining worksheets from being ingested.

    The source workbook is opened read-only by Pandas and is never modified.
    Missing values, blank cells, duplicate rows, headers, and column names are
    left as Pandas reads them; no cleaning or normalisation is performed.

    Args:
        file_path: Path to the uploaded ``.xlsx`` workbook.

    Returns:
        A WorkbookIngestionResult containing successfully read DataFrames and
        any worksheet-specific errors.

    Raises:
        FileNotFoundError: If the supplied path does not exist or is not a file.
        ValueError: If the file does not have an ``.xlsx`` extension.
        ExcelIngestionError: If the workbook cannot be opened or has no
            readable workbook structure.
    """

    path = Path(file_path).expanduser()

    if path.suffix.lower() != ".xlsx":
        raise ValueError("Unsupported file extension. Only .xlsx files are supported.")

    if not path.exists():
        raise FileNotFoundError(f"Excel workbook not found: {path}")

    if not path.is_file():
        raise FileNotFoundError(f"Excel workbook path is not a file: {path}")

    try:
        # Opening once discovers worksheet names and validates workbook access.
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            sheet_names = workbook.sheet_names

            if not sheet_names:
                raise ExcelIngestionError(
                    f"The Excel workbook contains no worksheets: {path.name}"
                )

            worksheets: Dict[str, pd.DataFrame] = {}
            worksheet_errors: Dict[str, str] = {}

            for sheet_name in sheet_names:
                try:
                    worksheets[sheet_name] = pd.read_excel(
                        workbook,
                        sheet_name=sheet_name,
                        engine="openpyxl",
                    )
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
