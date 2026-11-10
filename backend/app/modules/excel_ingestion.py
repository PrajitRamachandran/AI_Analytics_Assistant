"""Read Excel workbooks into independent worksheet DataFrames.

This module performs ingestion only. It does not normalize cell values, drop
rows, remove duplicates, or modify the source workbook. For each worksheet,
it identifies the first non-blank row as the header and preserves the remaining
records as read by Pandas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd

SUPPORTED_EXTENSIONS = (".xlsx", ".xlsm")


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
        result = pd.isna(value)
        return bool(result) if not hasattr(result, "__len__") else False
    except (TypeError, ValueError):
        return False


def _first_non_blank_row(dataframe: pd.DataFrame) -> int | None:
    """Find the first row containing at least one non-blank cell.

    The row index is positional. Returning ``None`` means the worksheet has no
    usable cell values and should be represented as an empty DataFrame.
    """
    for position, row in enumerate(dataframe.itertuples(index=False, name=None)):
        if any(not _is_blank(value) for value in row):
            return position
    return None


def _read_worksheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Read a worksheet once, then separate its first non-blank row as header.

    Reading with ``header=None`` preserves duplicate and blank header cells for
    the normalisation module to handle consistently. It also avoids reading
    each worksheet twice merely to probe for the header row.
    """
    raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
    if raw.empty and len(raw.columns) == 0:
        return pd.DataFrame()

    header_position = _first_non_blank_row(raw)
    if header_position is None:
        return pd.DataFrame()

    headers = raw.iloc[header_position].tolist()
    records = raw.iloc[header_position + 1 :].copy(deep=True)
    records.columns = headers
    records = records.reset_index(drop=True)
    return records


def ingest_excel_workbook(
    file_path: Union[str, Path],
) -> WorkbookIngestionResult:
    """Read every worksheet of an ``.xlsx``/``.xlsm`` workbook independently.

    Each worksheet is read in its own exception boundary. A parsing failure in
    one worksheet is recorded without preventing other worksheets from being
    ingested. The first non-blank row becomes the header. Blank header cells,
    duplicate header names, missing values, duplicate records and cell values
    are preserved for later modules to interpret.

    The source workbook is opened read-only and is never modified.

    Args:
        file_path: Path to the uploaded workbook.

    Returns:
        A WorkbookIngestionResult containing successful DataFrames and any
        worksheet-specific errors.

    Raises:
        FileNotFoundError: If the supplied path does not exist or is not a file.
        ValueError: If the file extension is not supported.
        ExcelIngestionError: If the workbook cannot be opened or has no sheets.
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
        # Let Pandas select the workbook engine from the supported extension.
        with pd.ExcelFile(path) as workbook:
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
                        f"Unable to read worksheet '{sheet_name}': "
                        f"{type(exc).__name__}: {exc}"
                    )
    except ExcelIngestionError:
        raise
    except Exception as exc:
        raise ExcelIngestionError(
            f"Unable to open or parse Excel workbook '{path.name}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return WorkbookIngestionResult(
        filename=path.name,
        total_worksheet_count=len(sheet_names),
        worksheet_names=list(sheet_names),
        worksheets=worksheets,
        worksheet_errors=worksheet_errors,
    )
