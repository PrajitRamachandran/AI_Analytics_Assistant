"""Normalize worksheet column labels and collect lightweight dtype metadata.

This module deliberately changes column labels only. Cell values, missing
values, row order, and worksheet contents are preserved in copied DataFrames.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List

import pandas as pd
from pandas.api import types as ptypes

from app.modules.excel_ingestion import WorkbookIngestionResult


@dataclass(frozen=True)
class ColumnNameMapping:
    """Maps one original column position and label to its normalized label."""

    position: int
    original_name: Any
    normalized_name: str


@dataclass(frozen=True)
class ColumnTypeInfo:
    """Describes a column's Pandas dtype and broad data category."""

    position: int
    original_name: Any
    normalized_name: str
    pandas_dtype: str
    data_category: str


@dataclass
class NormalizationResult:
    """Contains normalized worksheet copies and their metadata."""

    filename: str
    total_worksheet_count: int
    worksheet_names: List[str] = field(default_factory=list)
    worksheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    column_mappings: Dict[str, List[ColumnNameMapping]] = field(default_factory=dict)
    column_types: Dict[str, List[ColumnTypeInfo]] = field(default_factory=dict)
    worksheet_errors: Dict[str, str] = field(default_factory=dict)

    @property
    def successful_worksheet_count(self) -> int:
        """Number of worksheets successfully normalized, including empty sheets."""
        return len(self.worksheets)

    @property
    def failed_worksheet_count(self) -> int:
        """Number of worksheets with ingestion or normalization errors."""
        return len(self.worksheet_errors)


def _is_empty_header(value: Any) -> bool:
    """Return whether a header is genuinely empty or whitespace-only."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _base_column_name(original_name: Any, position: int) -> str:
    """Convert a header to a lowercase ASCII snake_case base name."""
    if _is_empty_header(original_name):
        return f"column_{position + 1}"

    text = str(original_name).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")

    if not text:
        return f"column_{position + 1}"

    if text[0].isdigit():
        text = f"column_{text}"

    return text


def _make_unique_name(base_name: str, used_names: set[str]) -> str:
    """Append a numeric suffix until the name is unique within the worksheet."""
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name

    suffix = 2
    while f"{base_name}_{suffix}" in used_names:
        suffix += 1

    unique_name = f"{base_name}_{suffix}"
    used_names.add(unique_name)
    return unique_name


def _classify_dtype(series: pd.Series) -> str:
    """Map a Pandas dtype to a conservative, broad data category."""
    dtype = series.dtype

    if ptypes.is_bool_dtype(dtype):
        return "boolean"
    if ptypes.is_datetime64_any_dtype(dtype):
        return "datetime"
    if ptypes.is_numeric_dtype(dtype):
        return "numeric"
    if isinstance(dtype, pd.CategoricalDtype):
        return "categorical"
    if ptypes.is_string_dtype(dtype) or ptypes.is_object_dtype(dtype):
        return "text/object"

    return "other"


def normalize_workbook(
    ingestion_result: WorkbookIngestionResult,
) -> NormalizationResult:
    """Normalize column labels on copied worksheet DataFrames.

    The input WorkbookIngestionResult and its DataFrames are never modified.
    Existing ingestion errors are carried forward. A failure on one worksheet
    is recorded without preventing other worksheets from being normalized.

    Args:
        ingestion_result: Result produced by ``ingest_excel_workbook``.

    Returns:
        A NormalizationResult with copied DataFrames, column mappings, dtype
        metadata, and worksheet-specific errors.
    """
    if not isinstance(ingestion_result, WorkbookIngestionResult):
        raise TypeError(
            "ingestion_result must be a WorkbookIngestionResult instance."
        )

    normalized_worksheets: Dict[str, pd.DataFrame] = {}
    column_mappings: Dict[str, List[ColumnNameMapping]] = {}
    column_types: Dict[str, List[ColumnTypeInfo]] = {}
    worksheet_errors = dict(ingestion_result.worksheet_errors)

    for worksheet_name, original_df in ingestion_result.worksheets.items():
        try:
            normalized_df = original_df.copy(deep=True)
            used_names: set[str] = set()
            mappings: List[ColumnNameMapping] = []
            type_details: List[ColumnTypeInfo] = []
            normalized_names: List[str] = []

            for position, original_name in enumerate(original_df.columns):
                base_name = _base_column_name(original_name, position)
                normalized_name = _make_unique_name(base_name, used_names)
                normalized_names.append(normalized_name)

                mappings.append(
                    ColumnNameMapping(
                        position=position,
                        original_name=original_name,
                        normalized_name=normalized_name,
                    )
                )

                original_series = original_df.iloc[:, position]
                type_details.append(
                    ColumnTypeInfo(
                        position=position,
                        original_name=original_name,
                        normalized_name=normalized_name,
                        pandas_dtype=str(original_series.dtype),
                        data_category=_classify_dtype(original_series),
                    )
                )

            normalized_df.columns = normalized_names
            normalized_worksheets[worksheet_name] = normalized_df
            column_mappings[worksheet_name] = mappings
            column_types[worksheet_name] = type_details

        except Exception as exc:
            worksheet_errors[worksheet_name] = (
                f"Unable to normalize worksheet '{worksheet_name}': {exc}"
            )

    return NormalizationResult(
        filename=ingestion_result.filename,
        total_worksheet_count=ingestion_result.total_worksheet_count,
        worksheet_names=list(ingestion_result.worksheet_names),
        worksheets=normalized_worksheets,
        column_mappings=column_mappings,
        column_types=column_types,
        worksheet_errors=worksheet_errors,
    )
