"""Deterministic, non-mutating profiling for processed Excel worksheets.

The engine consumes the CleaningResult produced by Module 2. It does not
clean, normalise, persist, or otherwise modify the supplied DataFrames.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.modules.data_cleaning import CleaningResult
from app.schemas.data_understanding import (
    CategoryFrequency,
    CategoricalStatistics,
    ColumnProfile,
    DatasetProfile,
    DateStatistics,
    NumericalStatistics,
    WorksheetProfile,
)

_ID_NAME = re.compile(r"(^|_)(id|uuid|guid|code|key|number|no|ref|reference)(_|$)", re.I)
_DATE_NAME = re.compile(r"date|time|timestamp|dob|birth|created|updated", re.I)
_AMOUNT_NAME = re.compile(r"amount|revenue|sales|price|cost|fee|salary|wage|profit|expense|income|total", re.I)
_QUANTITY_NAME = re.compile(r"quantity|qty|units|count|volume|stock|hours|duration", re.I)
_CATEGORY_NAME = re.compile(r"category|type|status|region|department|gender|product|country|city|class", re.I)
_TEXT_NAME = re.compile(r"description|comment|remarks?|message|notes?|address|narrative", re.I)


def _is_blank_string(value: Any) -> bool:
    return isinstance(value, str) and not value.strip()


def _safe_scalar(value: Any) -> Any:
    """Convert a scalar into a JSON-compatible value without losing meaning."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date, np.datetime64)):
        try:
            return pd.Timestamp(value).isoformat()
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, np.generic):
        value = value.item()
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _metadata_for_column(cleaning_result: CleaningResult, sheet: str, name: str):
    mapping = next(
        (item for item in cleaning_result.column_mappings.get(sheet, [])
         if item.normalized_name == name),
        None,
    )
    type_info = next(
        (item for item in cleaning_result.column_types.get(sheet, [])
         if item.normalized_name == name),
        None,
    )
    return mapping, type_info


def _infer_data_type(series: pd.Series, semantic_type: str = "") -> str:
    """Infer broad analytical type, preferring Module 2's semantic metadata."""
    semantic = (semantic_type or "").strip().lower()
    if semantic in {"boolean", "bool"} or ptypes.is_bool_dtype(series.dtype):
        return "boolean"
    if semantic in {"date", "datetime", "timestamp", "time"} or ptypes.is_datetime64_any_dtype(series.dtype):
        return "date"
    if semantic in {"numeric", "number", "integer", "floating", "decimal", "currency", "percentage"}:
        return "numerical"
    if ptypes.is_numeric_dtype(series.dtype) and not ptypes.is_bool_dtype(series.dtype):
        return "numerical"
    if semantic in {"categorical", "category", "attendance", "gender", "status"}:
        return "categorical"
    if isinstance(series.dtype, pd.CategoricalDtype):
        return "categorical"
    if ptypes.is_string_dtype(series.dtype) or ptypes.is_object_dtype(series.dtype):
        non_missing = series[series.notna()]
        if len(non_missing) == 0:
            return "other"
        # Low-cardinality object columns are generally useful as categories.
        unique_count = int(non_missing.nunique(dropna=True))
        ratio = unique_count / max(len(non_missing), 1)
        return "categorical" if unique_count <= 20 or ratio <= 0.20 else "text"
    return "other"


def _infer_semantic_role(name: str, inferred_type: str, semantic_type: str = "") -> str:
    """Infer likely business role using names first and Module 2 metadata second."""
    normalized = name.lower()
    semantic = (semantic_type or "").lower()

    # Identifier is deliberately checked before numerical/date semantics.
    if _ID_NAME.search(normalized) or normalized in {"id", "index", "serial"}:
        return "identifier"
    if inferred_type == "date" or _DATE_NAME.search(normalized) or semantic in {"date", "datetime"}:
        return "date"
    if inferred_type == "boolean" or semantic == "boolean":
        return "boolean"
    if _QUANTITY_NAME.search(normalized):
        return "quantity"
    if _AMOUNT_NAME.search(normalized):
        return "amount"
    if inferred_type == "categorical" or _CATEGORY_NAME.search(normalized):
        return "category"
    if inferred_type == "numerical":
        return "measure"
    if _TEXT_NAME.search(normalized) or inferred_type == "text":
        return "text"
    return "unknown"


def _mixed_python_types(series: pd.Series) -> List[str]:
    observed = {
        type(value).__name__
        for value in series.tolist()
        if not pd.isna(value) and not _is_blank_string(value)
    }
    return sorted(observed) if len(observed) > 1 else []


def _column_profile(
    dataframe: pd.DataFrame,
    worksheet_name: str,
    column_name: str,
    cleaning_result: CleaningResult,
) -> ColumnProfile:
    series = dataframe[column_name]
    mapping, type_info = _metadata_for_column(cleaning_result, worksheet_name, column_name)
    original_name = str(mapping.original_name) if mapping else column_name
    semantic_type = type_info.semantic_type if type_info else ""
    inferred_type = _infer_data_type(series, semantic_type)
    role = _infer_semantic_role(column_name, inferred_type, semantic_type)

    null_count = int(series.isna().sum())
    blank_count = int(sum(_is_blank_string(value) for value in series.tolist()))
    missing_count = null_count + blank_count
    row_count = len(series)
    non_null_count = row_count - missing_count
    missing_percentage = round((missing_count / row_count) * 100, 2) if row_count else 0.0

    present = series[~series.isna()]
    present = present[~present.map(_is_blank_string)]
    try:
        unique_count = int(present.nunique(dropna=True))
    except TypeError:
        unique_count = int(present.map(lambda value: repr(value)).nunique())
    unique_percentage = round((unique_count / non_null_count) * 100, 2) if non_null_count else 0.0
    samples = [_safe_scalar(value) for value in present.head(5).tolist()]

    numerical_stats = None
    categorical_stats = None
    date_stats = None

    if inferred_type == "numerical" and role != "identifier":
        numeric = pd.to_numeric(present, errors="coerce")
        numeric = numeric[np.isfinite(numeric.astype(float))]
        if len(numeric):
            numerical_stats = NumericalStatistics(
                minimum=_safe_float(numeric.min()),
                maximum=_safe_float(numeric.max()),
                mean=_safe_float(numeric.mean()),
                median=_safe_float(numeric.median()),
                total=_safe_float(numeric.sum()),
                standard_deviation=_safe_float(numeric.std()),
            )
        else:
            numerical_stats = NumericalStatistics()
    elif inferred_type == "categorical":
        try:
            counts = present.value_counts(dropna=True).head(5)
            frequent = [
                CategoryFrequency(value=_safe_scalar(value), count=int(count))
                for value, count in counts.items()
            ]
        except TypeError:
            counts = present.map(lambda value: repr(value)).value_counts().head(5)
            frequent = [
                CategoryFrequency(value=str(value), count=int(count))
                for value, count in counts.items()
            ]
        categorical_stats = CategoricalStatistics(
            unique_category_count=unique_count,
            most_frequent=frequent,
        )
    elif inferred_type == "date":
        # UTC normalization avoids comparison failures for mixed timezone offsets.
        parsed = pd.to_datetime(present, errors="coerce", utc=True).dropna()
        if len(parsed):
            parsed = parsed.dt.tz_convert(None)
        date_stats = DateStatistics(
            earliest=parsed.min().isoformat() if len(parsed) else None,
            latest=parsed.max().isoformat() if len(parsed) else None,
        )

    return ColumnProfile(
        column_name=column_name,
        original_name=original_name,
        pandas_dtype=str(series.dtype),
        inferred_type=inferred_type,
        semantic_role=role,
        non_null_count=non_null_count,
        missing_value_count=null_count,
        blank_string_count=blank_count,
        missing_percentage=missing_percentage,
        unique_value_count=unique_count,
        unique_value_percentage=unique_percentage,
        sample_values=samples,
        numerical_statistics=numerical_stats,
        categorical_statistics=categorical_stats,
        date_statistics=date_stats,
        mixed_value_types=_mixed_python_types(series),
    )


def profile_worksheet(
    worksheet_name: str,
    dataframe: pd.DataFrame,
    cleaning_result: CleaningResult,
) -> WorksheetProfile:
    """Profile one already-cleaned worksheet without modifying its DataFrame."""
    columns = [
        _column_profile(dataframe, worksheet_name, str(name), cleaning_result)
        for name in dataframe.columns
    ]
    quality = cleaning_result.quality_reports.get(worksheet_name)
    duplicate_count = int(quality.duplicate_row_count) if quality else int(dataframe.duplicated().sum())

    counts = {
        kind: sum(column.inferred_type == kind for column in columns)
        for kind in ("numerical", "categorical", "date", "text", "boolean", "other")
    }
    return WorksheetProfile(
        worksheet_name=worksheet_name,
        row_count=int(dataframe.shape[0]),
        column_count=int(dataframe.shape[1]),
        duplicate_row_count=duplicate_count,
        numerical_column_count=counts["numerical"],
        categorical_column_count=counts["categorical"],
        date_column_count=counts["date"],
        text_column_count=counts["text"],
        boolean_column_count=counts["boolean"],
        other_column_count=counts["other"],
        total_missing_value_count=sum(c.missing_value_count for c in columns),
        total_blank_string_count=sum(c.blank_string_count for c in columns),
        columns=columns,
    )


def profile_dataset(cleaning_result: CleaningResult) -> DatasetProfile:
    """Create a structured profile for every successfully cleaned worksheet.

    Worksheet failures are isolated: a failure profiling one worksheet is
    recorded in ``worksheet_errors`` while other worksheets are still profiled.
    """
    if not isinstance(cleaning_result, CleaningResult):
        raise TypeError("cleaning_result must be a CleaningResult instance.")

    profiles = {}
    errors = dict(cleaning_result.worksheet_errors)
    for worksheet_name, dataframe in cleaning_result.worksheets.items():
        try:
            profiles[worksheet_name] = profile_worksheet(
                worksheet_name, dataframe, cleaning_result
            )
        except Exception as exc:
            errors[worksheet_name] = (
                f"Unable to profile worksheet '{worksheet_name}': "
                f"{type(exc).__name__}: {exc}"
            )

    return DatasetProfile(
        filename=cleaning_result.filename,
        total_worksheet_count=cleaning_result.total_worksheet_count,
        successful_worksheet_count=len(profiles),
        failed_worksheet_count=len(errors),
        worksheets=profiles,
        worksheet_errors=errors,
    )
