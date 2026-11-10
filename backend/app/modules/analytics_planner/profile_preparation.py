
"""
Module 4: Dataset Profile Preparation.

Prepares the Module 3 DatasetProfile for consumption by the
local Ollama LLM.

Responsibilities:
- Convert the Pydantic dataset profile into a compact JSON-compatible
  representation.
- Preserve worksheet and column metadata.
- Preserve data types and inferred semantic roles.
- Preserve numerical and date statistics.
- Exclude potentially sensitive raw sample values by default.
- Optionally include categorical frequency values.
- Estimate input size before sending it to the LLM.
- Reject oversized profiles instead of silently dropping columns.

This module does not modify the original DatasetProfile.
It does not perform analytical calculations.
"""

from __future__ import annotations

import json

from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.data_understanding import (
    DatasetProfile,
    WorksheetProfile,
)
from app.modules.analytics_planner.worksheet_classifier import classify_worksheet


# ============================================================
# DEFAULT CONFIGURATION
# ============================================================

# Keep the profile comfortably within the 8K-token V1 context budget after
# accounting for the system prompt, message framing, JSON schema, and
# generated output.  The Ollama client validates the total token budget
# independently, so this limit is a profiling-layer safety net.
DEFAULT_MAX_PROFILE_CHARS = 12000

DEFAULT_MAX_SAMPLE_VALUES = 3

DEFAULT_MAX_CATEGORY_VALUES = 5

# Approximate character-to-token conversion.
# This is a rough budgeting heuristic, not an exact tokenizer.
CHARS_PER_ESTIMATED_TOKEN = 3.2


# ============================================================
# CUSTOM ERROR
# ============================================================

class ProfilePreparationError(ValueError):
    """Raised when a dataset profile cannot be prepared safely."""


# ============================================================
# PROFILE PREPARATION
# ============================================================

class DatasetProfilePreparer:
    """
    Converts Module 3 DatasetProfile into a compact LLM input.

    The preparer preserves all profiled worksheets and columns.
    It reduces optional descriptive information before considering
    the profile too large to send to the LLM.
    """

    def __init__(
        self,
        max_profile_chars: int = DEFAULT_MAX_PROFILE_CHARS,
        max_sample_values: int = DEFAULT_MAX_SAMPLE_VALUES,
        max_category_values: int = DEFAULT_MAX_CATEGORY_VALUES,
        include_sample_values: bool = False,
        include_category_values: bool = False,
    ) -> None:

        if max_profile_chars < 1000:
            raise ValueError(
                "max_profile_chars must be at least 1000."
            )

        if max_sample_values < 0:
            raise ValueError(
                "max_sample_values cannot be negative."
            )

        if max_category_values < 0:
            raise ValueError(
                "max_category_values cannot be negative."
            )

        self.max_profile_chars = max_profile_chars
        self.max_sample_values = max_sample_values
        self.max_category_values = max_category_values

        self.include_sample_values = include_sample_values
        self.include_category_values = include_category_values

    # ========================================================
    # PUBLIC METHOD
    # ========================================================

    def prepare(
        self,
        dataset_profile: DatasetProfile,
    ) -> dict[str, Any]:
        """
        Prepare a DatasetProfile for LLM consumption.

        Returns a JSON-compatible dictionary containing:

        - profile: Compact workbook profile.
        - preparation_metadata: Input-size estimates and warnings.

        Raises:
            TypeError:
                If the input is not a DatasetProfile.

            ProfilePreparationError:
                If the profile exceeds the configured size limit
                even after optional information is reduced.
        """

        if not isinstance(dataset_profile, DatasetProfile):
            raise TypeError(
                "dataset_profile must be a DatasetProfile instance."
            )
        if not dataset_profile.worksheets:
            raise ProfilePreparationError(
                "The dataset profile contains no successfully profiled worksheets."
            )

        warnings: list[str] = []

        prepared_profile = self._build_profile(
            dataset_profile=dataset_profile,
            include_samples=self.include_sample_values,
            category_limit=self.max_category_values,
        )

        profile_json = self._serialize(prepared_profile)

        # First reduction: remove optional raw sample values.
        if (
            len(profile_json) > self.max_profile_chars
            and self.include_sample_values
        ):

            prepared_profile = self._build_profile(
                dataset_profile=dataset_profile,
                include_samples=False,
                category_limit=self.max_category_values,
            )

            profile_json = self._serialize(prepared_profile)

            warnings.append(
                "Sample values were excluded to reduce profile size."
            )

        # Second reduction: reduce optional category frequencies.
        if len(profile_json) > self.max_profile_chars:

            prepared_profile = self._build_profile(
                dataset_profile=dataset_profile,
                include_samples=False,
                category_limit=0,
            )

            profile_json = self._serialize(prepared_profile)

            warnings.append(
                "Categorical frequency values were excluded "
                "to reduce profile size."
            )

        # Third reduction: compact column metadata by stripping
        # numerical/date statistics from low-priority columns (those
        # already profiled as identifiers or with few non-null values).
        if len(profile_json) > self.max_profile_chars:

            prepared_profile = self._compact_columns(prepared_profile)
            profile_json = self._serialize(prepared_profile)

            warnings.append(
                "Column statistics were compacted to reduce profile size."
            )

        # Never silently drop worksheets or columns.
        if len(profile_json) > self.max_profile_chars:

            raise ProfilePreparationError(
                "The prepared dataset profile exceeds the configured "
                f"limit of {self.max_profile_chars:,} characters. "
                f"Current size: {len(profile_json):,} characters. "
                "The workbook contains too much profiling metadata "
                "for the current LLM input budget. Consider increasing "
                "the profile limit, reducing the number of columns, "
                "or implementing hierarchical planning."
            )

        estimated_tokens = (
            len(profile_json) + CHARS_PER_ESTIMATED_TOKEN - 1
        ) // CHARS_PER_ESTIMATED_TOKEN

        if dataset_profile.failed_worksheet_count > 0:

            warnings.append(
                f"{dataset_profile.failed_worksheet_count} worksheet(s) "
                "could not be profiled and are excluded from analytical "
                "planning."
            )

        if dataset_profile.successful_worksheet_count == 0:

            raise ProfilePreparationError(
                "The dataset profile contains no successfully "
                "profiled worksheets."
            )

        return {
            "profile": prepared_profile,
            "preparation_metadata": {
                "filename": dataset_profile.filename,
                "worksheet_count": (
                    dataset_profile.successful_worksheet_count
                ),
                "total_column_count": sum(
                    worksheet.column_count
                    for worksheet in dataset_profile.worksheets.values()
                ),
                "profile_characters": len(profile_json),
                "estimated_profile_tokens": estimated_tokens,
                "max_profile_characters": self.max_profile_chars,
                "sample_values_included": (
                    self.include_sample_values
                    and "Sample values were excluded to reduce profile size."
                    not in warnings
                ),
                "category_values_included": (
                    self.include_category_values
                    and "Categorical frequency values were excluded "
                    "to reduce profile size."
                    not in warnings
                ),
                "warnings": warnings,
            },
        }

    # ========================================================
    # BUILD PROFILE
    # ========================================================

    def _build_profile(
        self,
        dataset_profile: DatasetProfile,
        include_samples: bool,
        category_limit: int,
    ) -> dict[str, Any]:
        """Build the compact workbook profile."""

        worksheets = {}

        for worksheet_name, worksheet in dataset_profile.worksheets.items():

            worksheets[worksheet_name] = self._prepare_worksheet(
                worksheet=worksheet,
                include_samples=include_samples,
                category_limit=category_limit,
            )

        return {
            "filename": dataset_profile.filename,
            "total_worksheet_count": dataset_profile.total_worksheet_count,
            "successful_worksheet_count": (
                dataset_profile.successful_worksheet_count
            ),
            "failed_worksheet_count": (
                dataset_profile.failed_worksheet_count
            ),
            "worksheets": worksheets,
            "worksheet_errors": dict(
                dataset_profile.worksheet_errors
            ),
        }

    # ========================================================
    # WORKSHEET PREPARATION
    # ========================================================

    def _prepare_worksheet(
        self,
        worksheet: WorksheetProfile,
        include_samples: bool,
        category_limit: int,
    ) -> dict[str, Any]:
        """Prepare one worksheet without losing its column definitions."""

        columns = [
            self._prepare_column(
                column=column,
                include_samples=include_samples,
                category_limit=category_limit,
            )
            for column in worksheet.columns
        ]

        classification = classify_worksheet(worksheet.worksheet_name, worksheet)

        return {
            "worksheet_name": worksheet.worksheet_name,
            "worksheet_role": classification["role"],
            "row_count": worksheet.row_count,
            "column_count": worksheet.column_count,
            "duplicate_row_count": worksheet.duplicate_row_count,
            "total_missing_value_count": worksheet.total_missing_value_count,
            "columns": columns,
        }

    # ========================================================
    # COLUMN PREPARATION
    # ========================================================

    def _prepare_column(
        self,
        column: Any,
        include_samples: bool,
        category_limit: int,
    ) -> dict[str, Any]:
        """Prepare one column profile."""

        prepared = {
            "column_name": column.column_name,
            "inferred_type": column.inferred_type,
            "semantic_role": column.semantic_role,
            "non_null_count": column.non_null_count,
            "missing_value_count": column.missing_value_count,
            "unique_value_count": column.unique_value_count,
            "mixed_value_types": column.mixed_value_types,
        }

        # Numerical statistics are useful for interpreting measures.
        if column.numerical_statistics is not None:

            stats = column.numerical_statistics.model_dump(
                mode="json", exclude_none=True
            )
            compact_stats = {
                key: stats[key] for key in ("min", "max", "mean", "median")
                if key in stats
            }
            if compact_stats:
                prepared["numerical_statistics"] = compact_stats

        # Date ranges provide useful context for time-series planning.
        if column.date_statistics is not None:

            stats = column.date_statistics.model_dump(
                mode="json", exclude_none=True
            )
            compact_stats = {
                key: stats[key]
                for key in ("min_date", "max_date", "valid_count")
                if key in stats
            }
            if compact_stats:
                prepared["date_statistics"] = compact_stats

        # Include categorical frequencies only when explicitly enabled.
        if column.categorical_statistics is not None:

            categorical = {
                "unique_category_count": (
                    column.categorical_statistics.unique_category_count
                ),
            }

            if category_limit > 0 and self.include_category_values:
                frequent = column.categorical_statistics.most_frequent[:category_limit]
                categorical["most_frequent"] = [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in frequent
                ]

            prepared["categorical_statistics"] = categorical

        # Raw sample values are disabled by default because they may
        # contain personal or confidential information.
        if include_samples and self.max_sample_values > 0:

            prepared["sample_values"] = [
                self._safe_value(value)
                for value in column.sample_values[
                    :self.max_sample_values
                ]
            ]

        return prepared

    # ========================================================
    # SAFE VALUE CONVERSION
    # ========================================================

    @staticmethod
    def _safe_value(value: Any) -> Any:
        """Convert values into safe JSON-compatible representations."""

        if isinstance(value, BaseModel):

            return value.model_dump(
                mode="json",
                exclude_none=True,
            )

        if value is None or isinstance(
            value,
            (str, int, float, bool),
        ):

            return value

        return str(value)

    # ========================================================
    # COLUMN COMPACTION
    # ========================================================

    @staticmethod
    def _compact_columns(profile: dict[str, Any]) -> dict[str, Any]:
        """Strip optional statistics from columns to reduce size.

        Removes numerical_statistics, date_statistics, and
        categorical_statistics from all columns while preserving
        the core column identity (name, type, role, counts).
        This keeps every column visible to the LLM for planning
        without exceeding the input budget.
        """

        compacted = dict(profile)
        compacted_worksheets = {}

        for ws_name, ws_data in profile.get("worksheets", {}).items():
            ws_copy = dict(ws_data)
            compacted_cols = []
            for col in ws_data.get("columns", []):
                compact_col = {
                    key: col[key]
                    for key in (
                        "column_name",
                        "inferred_type",
                        "semantic_role",
                        "non_null_count",
                        "missing_value_count",
                        "unique_value_count",
                        "mixed_value_types",
                    )
                    if key in col
                }
                compacted_cols.append(compact_col)
            ws_copy["columns"] = compacted_cols
            compacted_worksheets[ws_name] = ws_copy

        compacted["worksheets"] = compacted_worksheets
        return compacted

    # ========================================================
    # SERIALIZATION
    # ========================================================

    @staticmethod
    def _serialize(profile: dict[str, Any]) -> str:
        """Serialize the prepared profile deterministically."""

        try:

            return json.dumps(
                profile,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )

        except (TypeError, ValueError) as exc:

            raise ProfilePreparationError(
                f"Unable to serialize the prepared dataset profile: {exc}"
            ) from exc


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def prepare_dataset_profile(
    dataset_profile: DatasetProfile,
    max_profile_chars: int = DEFAULT_MAX_PROFILE_CHARS,
    include_sample_values: bool = False,
    include_category_values: bool = False,
) -> dict[str, Any]:
    """
    Convenience function for preparing a Module 3 DatasetProfile.

    Example:

        prepared = prepare_dataset_profile(dataset_profile)

        profile = prepared["profile"]

        metadata = prepared["preparation_metadata"]
    """

    preparer = DatasetProfilePreparer(
        max_profile_chars=max_profile_chars,
        include_sample_values=include_sample_values,
        include_category_values=include_category_values,
    )

    return preparer.prepare(dataset_profile)
