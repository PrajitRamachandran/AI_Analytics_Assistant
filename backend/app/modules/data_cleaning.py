"""Conservative data cleaning and quality reporting for normalized workbooks.

Only fully empty rows and columns are removed by default. Missing values are
reported, not imputed. Duplicate rows are reported and are retained unless
the caller explicitly enables duplicate removal.

A column is only considered empty when the worksheet contains at least one
non-empty row; a header-only (or all-blank) worksheet keeps its schema.
Duplicates are evaluated on non-empty rows across non-empty columns, and row
positions in reports are zero-based positions within the data rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.modules.data_normalization import (
    ColumnNameMapping,
    ColumnTypeInfo,
    NormalizationResult,
)


@dataclass(frozen=True)
class CleaningConfig:
    """Controls the limited, auditable transformations performed by cleaning."""

    remove_empty_rows: bool = True
    remove_empty_columns: bool = True
    remove_duplicate_rows: bool = False


@dataclass(frozen=True)
class ColumnQualityReport:
    """Data quality observations for one column before cleaning."""

    column_name: str
    pandas_dtype: str
    missing_value_count: int
    blank_string_count: int
    missing_percentage: float
    mixed_value_types: List[str] = field(default_factory=list)
    whitespace_padded_string_count: int = 0


@dataclass
class WorksheetQualityReport:
    """Before/after quality and cleaning audit for one worksheet."""

    worksheet_name: str
    original_row_count: int
    original_column_count: int
    cleaned_row_count: int
    cleaned_column_count: int
    empty_row_positions: List[int] = field(default_factory=list)
    empty_column_names: List[str] = field(default_factory=list)
    duplicate_row_count: int = 0
    removed_empty_row_count: int = 0
    removed_empty_column_count: int = 0
    removed_duplicate_row_count: int = 0
    column_quality: List[ColumnQualityReport] = field(default_factory=list)


@dataclass
class CleaningResult:
    """Cleaned worksheet copies, quality reports, and worksheet errors."""

    filename: str
    total_worksheet_count: int
    worksheet_names: List[str] = field(default_factory=list)
    worksheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    quality_reports: Dict[str, WorksheetQualityReport] = field(default_factory=dict)
    column_mappings: Dict[str, List[ColumnNameMapping]] = field(default_factory=dict)
    column_types: Dict[str, List[ColumnTypeInfo]] = field(default_factory=dict)
    worksheet_errors: Dict[str, str] = field(default_factory=dict)

    @property
    def successful_worksheet_count(self) -> int:
        """Number of worksheets successfully cleaned, including empty sheets."""
        return len(self.worksheets)

    @property
    def failed_worksheet_count(self) -> int:
        """Number of worksheets that failed ingestion, normalization, or cleaning."""
        return len(self.worksheet_errors)


def _can_hold_strings(series: pd.Series) -> bool:
    """Return whether a column may contain Python strings."""
    dtype = series.dtype
    return bool(ptypes.is_object_dtype(dtype) or ptypes.is_string_dtype(dtype))


def _string_flags(
    series: pd.Series,
    predicate: Callable[[str], bool],
) -> np.ndarray:
    """Return a boolean array marking string cells that satisfy ``predicate``."""
    if not _can_hold_strings(series):
        return np.zeros(len(series), dtype=bool)
    return np.fromiter(
        (isinstance(value, str) and predicate(value) for value in series.tolist()),
        dtype=bool,
        count=len(series),
    )


def _blank_string_flags(series: pd.Series) -> np.ndarray:
    """Mark whitespace-only (or zero-length) string cells."""
    return _string_flags(series, lambda value: not value.strip())


def _empty_cell_mask(dataframe: pd.DataFrame) -> np.ndarray:
    """Mark null and whitespace-only string cells as empty without changing them.

    Returns a boolean array of shape ``(rows, columns)`` indexed by position.
    """
    row_count, column_count = dataframe.shape
    mask = np.zeros((row_count, column_count), dtype=bool)
    for position in range(column_count):
        series = dataframe.iloc[:, position]
        mask[:, position] = series.isna().to_numpy(dtype=bool) | _blank_string_flags(
            series
        )
    return mask


def _column_quality_report(
    series: pd.Series,
    column_name: str,
) -> ColumnQualityReport:
    """Build conservative missingness and mixed-Python-type metadata.

    Blank strings count as missing and are excluded from the mixed-type check.
    """
    row_count = len(series)

    null_flags = series.isna().to_numpy(dtype=bool)
    blank_flags = _blank_string_flags(series)

    missing_count = int(null_flags.sum())
    blank_string_count = int(blank_flags.sum())
    total_missing = missing_count + blank_string_count
    missing_percentage = (
        round((total_missing / row_count) * 100, 2) if row_count else 0.0
    )

    value_types: List[str] = []
    if ptypes.is_object_dtype(series.dtype):
        present = series.to_numpy(dtype=object)[~(null_flags | blank_flags)]
        observed = sorted({type(value).__name__ for value in present})
        value_types = observed if len(observed) > 1 else []

    whitespace_padded_count = int(
        _string_flags(series, lambda value: value != value.strip()).sum()
    )

    return ColumnQualityReport(
        column_name=str(column_name),
        pandas_dtype=str(series.dtype),
        missing_value_count=missing_count,
        blank_string_count=blank_string_count,
        missing_percentage=missing_percentage,
        mixed_value_types=value_types,
        whitespace_padded_string_count=whitespace_padded_count,
    )


def _clean_worksheet(
    worksheet_name: str,
    source_df: pd.DataFrame,
    config: CleaningConfig,
) -> tuple[pd.DataFrame, WorksheetQualityReport]:
    """Audit and clean a single worksheet copy."""
    dataframe = source_df.copy(deep=True)
    row_count, column_count = dataframe.shape

    # Quality analysis is performed before any row/column removal.
    column_quality = [
        _column_quality_report(dataframe.iloc[:, position], str(name))
        for position, name in enumerate(dataframe.columns)
    ]

    empty_mask = _empty_cell_mask(dataframe)

    if column_count:
        empty_row_flags = empty_mask.all(axis=1)
    else:
        empty_row_flags = np.zeros(row_count, dtype=bool)

    # Without any populated record there is no evidence a column is empty;
    # retain the schema for downstream analysis.
    has_records = bool(row_count) and not bool(empty_row_flags.all())
    if has_records:
        empty_column_flags = empty_mask.all(axis=0)
    else:
        empty_column_flags = np.zeros(column_count, dtype=bool)

    # Duplicates are counted among non-empty rows over non-empty columns.
    duplicate_flags = np.zeros(row_count, dtype=bool)
    candidate_rows = np.flatnonzero(~empty_row_flags)
    informative_columns = np.flatnonzero(~empty_column_flags)
    if candidate_rows.size and informative_columns.size:
        subset = dataframe.iloc[candidate_rows, informative_columns]
        duplicate_flags[candidate_rows] = subset.duplicated(keep="first").to_numpy(
            dtype=bool
        )

    keep_rows = np.ones(row_count, dtype=bool)
    if config.remove_empty_rows:
        keep_rows &= ~empty_row_flags
    if config.remove_duplicate_rows:
        keep_rows &= ~duplicate_flags

    keep_columns = np.ones(column_count, dtype=bool)
    if config.remove_empty_columns:
        keep_columns &= ~empty_column_flags

    cleaned = (
        dataframe.iloc[np.flatnonzero(keep_rows), np.flatnonzero(keep_columns)]
        .reset_index(drop=True)
        .copy()
    )

    empty_row_positions = [int(position) for position in np.flatnonzero(empty_row_flags)]
    empty_column_names = [
        str(dataframe.columns[position])
        for position in np.flatnonzero(empty_column_flags)
    ]
    duplicate_row_count = int(duplicate_flags.sum())

    report = WorksheetQualityReport(
        worksheet_name=worksheet_name,
        original_row_count=row_count,
        original_column_count=column_count,
        cleaned_row_count=len(cleaned),
        cleaned_column_count=len(cleaned.columns),
        empty_row_positions=empty_row_positions,
        empty_column_names=empty_column_names,
        duplicate_row_count=duplicate_row_count,
        removed_empty_row_count=(
            len(empty_row_positions) if config.remove_empty_rows else 0
        ),
        removed_empty_column_count=(
            len(empty_column_names) if config.remove_empty_columns else 0
        ),
        removed_duplicate_row_count=(
            duplicate_row_count if config.remove_duplicate_rows else 0
        ),
        column_quality=column_quality,
    )
    return cleaned, report


def clean_workbook(
    normalization_result: NormalizationResult,
    config: Optional[CleaningConfig] = None,
) -> CleaningResult:
    """Create cleaned worksheet copies and produce a data quality audit.

    Fully empty rows and columns are removed by default. Null and whitespace-
    only cells in partially populated rows/columns are reported but retained.
    Duplicate rows are counted and retained by default.

    All quality metrics are calculated against the normalized input before
    transformations. Original input DataFrames are never modified, and cleaned
    DataFrames have a fresh zero-based index.

    Args:
        normalization_result: Output from ``normalize_workbook``.
        config: Optional switches for safe, explicit cleaning operations.

    Returns:
        CleaningResult containing cleaned DataFrames, per-sheet reports,
        carried-forward column metadata, and worksheet-specific errors.
    """
    if not isinstance(normalization_result, NormalizationResult):
        raise TypeError(
            "normalization_result must be a NormalizationResult instance."
        )

    cleaning_config = config or CleaningConfig()

    cleaned_worksheets: Dict[str, pd.DataFrame] = {}
    quality_reports: Dict[str, WorksheetQualityReport] = {}
    column_mappings: Dict[str, List[ColumnNameMapping]] = {}
    column_types: Dict[str, List[ColumnTypeInfo]] = {}
    worksheet_errors = dict(normalization_result.worksheet_errors)

    for worksheet_name, source_df in normalization_result.worksheets.items():
        try:
            cleaned, report = _clean_worksheet(
                worksheet_name, source_df, cleaning_config
            )

            # Carry column mappings/type metadata only for columns that remain.
            remaining_columns = set(cleaned.columns)
            kept_mappings = [
                mapping
                for mapping in normalization_result.column_mappings.get(
                    worksheet_name, []
                )
                if mapping.normalized_name in remaining_columns
            ]
            kept_types = [
                type_info
                for type_info in normalization_result.column_types.get(
                    worksheet_name, []
                )
                if type_info.normalized_name in remaining_columns
            ]

            cleaned_worksheets[worksheet_name] = cleaned
            quality_reports[worksheet_name] = report
            column_mappings[worksheet_name] = kept_mappings
            column_types[worksheet_name] = kept_types

        except Exception as exc:
            worksheet_errors[worksheet_name] = (
                f"Unable to clean worksheet '{worksheet_name}': {exc}"
            )

    return CleaningResult(
        filename=normalization_result.filename,
        total_worksheet_count=normalization_result.total_worksheet_count,
        worksheet_names=list(normalization_result.worksheet_names),
        worksheets=cleaned_worksheets,
        quality_reports=quality_reports,
        column_mappings=column_mappings,
        column_types=column_types,
        worksheet_errors=worksheet_errors,
    )