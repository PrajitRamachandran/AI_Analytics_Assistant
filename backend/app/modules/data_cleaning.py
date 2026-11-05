"""Conservative data cleaning and quality reporting for normalized workbooks.

Only fully empty rows and columns are removed by default. Missing values are
reported, not imputed. Duplicate rows are reported and are retained unless
the caller explicitly enables duplicate removal.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd

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


def _empty_cell_mask(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Mark null and whitespace-only string cells as empty without changing them."""
    null_mask = dataframe.isna()
    blank_string_mask = dataframe.apply(
        lambda column: column.map(
            lambda value: isinstance(value, str) and not value.strip()
        )
    )
    return null_mask | blank_string_mask


def _column_quality_report(
    dataframe: pd.DataFrame,
    column_name: str,
) -> ColumnQualityReport:
    """Build conservative missingness and mixed-Python-type metadata."""
    series = dataframe[column_name]
    row_count = len(series)

    missing_count = int(series.isna().sum())
    blank_string_count = int(
        series.map(lambda value: isinstance(value, str) and not value.strip()).sum()
    )
    total_missing = missing_count + blank_string_count
    missing_percentage = (
        round((total_missing / row_count) * 100, 2) if row_count else 0.0
    )

    non_null_values = series[~series.isna()]
    value_types = sorted({type(value).__name__ for value in non_null_values.tolist()})

    whitespace_padded_count = int(
        series.map(
            lambda value: isinstance(value, str) and value != value.strip()
        ).sum()
    )

    return ColumnQualityReport(
        column_name=str(column_name),
        pandas_dtype=str(series.dtype),
        missing_value_count=missing_count,
        blank_string_count=blank_string_count,
        missing_percentage=missing_percentage,
        mixed_value_types=value_types if len(value_types) > 1 else [],
        whitespace_padded_string_count=whitespace_padded_count,
    )


def clean_workbook(
    normalization_result: NormalizationResult,
    config: CleaningConfig | None = None,
) -> CleaningResult:
    """Create cleaned worksheet copies and produce a data quality audit.

    Fully empty rows and columns are removed by default. Null and whitespace-
    only cells in partially populated rows/columns are reported but retained.
    Duplicate rows are counted and retained by default.

    All quality metrics are calculated against the normalized input before
    transformations. Original input DataFrames are never modified.

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
            dataframe = source_df.copy(deep=True)
            original_row_count, original_column_count = dataframe.shape

            # Quality analysis is performed before any row/column removal.
            column_quality = [
                _column_quality_report(dataframe, str(column_name))
                for column_name in dataframe.columns
            ]

            empty_mask = _empty_cell_mask(dataframe)

            if original_column_count:
                empty_row_mask = empty_mask.all(axis=1)
                empty_row_positions = [
                    position
                    for position, is_empty in enumerate(empty_row_mask.tolist())
                    if is_empty
                ]
            else:
                empty_row_mask = pd.Series(False, index=dataframe.index)
                empty_row_positions = []

            if original_row_count and original_column_count:
                empty_column_mask = empty_mask.all(axis=0)
                empty_column_names = [
                    str(name)
                    for name, is_empty in zip(
                        dataframe.columns, empty_column_mask.tolist()
                    )
                    if is_empty
                ]
            else:
                # With no records, there is no evidence that a header-only
                # column is empty; retain the schema for downstream analysis.
                empty_column_mask = pd.Series(
                    False, index=dataframe.columns, dtype=bool
                )
                empty_column_names = []

            # Ignore fully empty rows when counting duplicate business records.
            non_empty_rows = dataframe.loc[~empty_row_mask]
            duplicate_mask = non_empty_rows.duplicated(keep="first")
            duplicate_row_count = int(duplicate_mask.sum())

            if cleaning_config.remove_empty_rows:
                dataframe = dataframe.loc[~empty_row_mask].copy()

            if cleaning_config.remove_empty_columns and original_row_count:
                keep_columns = ~empty_column_mask
                dataframe = dataframe.loc[:, keep_columns].copy()

            removed_duplicate_count = 0
            if cleaning_config.remove_duplicate_rows and not dataframe.empty:
                before_deduplication = len(dataframe)

                if cleaning_config.remove_empty_rows:
                    dataframe = dataframe.drop_duplicates(keep="first").copy()
                else:
                    # Keep fully empty rows even when duplicate removal is enabled.
                    post_clean_empty_mask = _empty_cell_mask(dataframe)
                    if dataframe.shape[1]:
                        fully_empty_rows = post_clean_empty_mask.all(axis=1).tolist()
                    else:
                        fully_empty_rows = [False] * len(dataframe)

                    non_empty_positions = [
                        position
                        for position, is_empty in enumerate(fully_empty_rows)
                        if not is_empty
                    ]
                    non_empty_frame = dataframe.iloc[non_empty_positions]
                    duplicate_positions = {
                        position
                        for position, is_duplicate in zip(
                            non_empty_positions,
                            non_empty_frame.duplicated(keep="first").tolist(),
                        )
                        if is_duplicate
                    }
                    keep_positions = [
                        position
                        for position in range(len(dataframe))
                        if position not in duplicate_positions
                    ]
                    dataframe = dataframe.iloc[keep_positions].copy()

                removed_duplicate_count = before_deduplication - len(dataframe)

            # Carry column mappings/type metadata only for columns that remain.
            remaining_columns = set(dataframe.columns)
            source_mappings = normalization_result.column_mappings.get(
                worksheet_name, []
            )
            source_types = normalization_result.column_types.get(
                worksheet_name, []
            )

            kept_mappings = [
                mapping
                for mapping in source_mappings
                if mapping.normalized_name in remaining_columns
            ]
            kept_types = [
                type_info
                for type_info in source_types
                if type_info.normalized_name in remaining_columns
            ]

            cleaned_worksheets[worksheet_name] = dataframe
            column_mappings[worksheet_name] = kept_mappings
            column_types[worksheet_name] = kept_types

            quality_reports[worksheet_name] = WorksheetQualityReport(
                worksheet_name=worksheet_name,
                original_row_count=original_row_count,
                original_column_count=original_column_count,
                cleaned_row_count=len(dataframe),
                cleaned_column_count=len(dataframe.columns),
                empty_row_positions=empty_row_positions,
                empty_column_names=empty_column_names,
                duplicate_row_count=duplicate_row_count,
                removed_empty_row_count=(
                    len(empty_row_positions)
                    if cleaning_config.remove_empty_rows
                    else 0
                ),
                removed_empty_column_count=(
                    len(empty_column_names)
                    if cleaning_config.remove_empty_columns and original_row_count
                    else 0
                ),
                removed_duplicate_row_count=removed_duplicate_count,
                column_quality=column_quality,
            )

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
