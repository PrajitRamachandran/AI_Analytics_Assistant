"""Pydantic models for Module 3 dataset profiling results."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


InferredDataType = Literal["numerical", "categorical", "date", "text", "boolean", "other"]
SemanticRole = Literal[
    "identifier", "date", "amount", "quantity", "category",
    "measure", "text", "boolean", "unknown",
]


class ProfileModel(BaseModel):
    """Base model with predictable handling of additional metadata."""

    model_config = ConfigDict(extra="forbid")


class NumericalStatistics(ProfileModel):
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    total: Optional[float] = None
    standard_deviation: Optional[float] = None


class CategoryFrequency(ProfileModel):
    value: Any
    count: int


class CategoricalStatistics(ProfileModel):
    unique_category_count: int = 0
    most_frequent: List[CategoryFrequency] = Field(default_factory=list)


class DateStatistics(ProfileModel):
    earliest: Optional[str] = None
    latest: Optional[str] = None


class ColumnProfile(ProfileModel):
    column_name: str
    original_name: str
    pandas_dtype: str
    inferred_type: InferredDataType
    semantic_role: SemanticRole
    non_null_count: int
    missing_value_count: int
    blank_string_count: int
    missing_percentage: float
    unique_value_count: int
    unique_value_percentage: float
    sample_values: List[Any] = Field(default_factory=list)
    numerical_statistics: Optional[NumericalStatistics] = None
    categorical_statistics: Optional[CategoricalStatistics] = None
    date_statistics: Optional[DateStatistics] = None
    mixed_value_types: List[str] = Field(default_factory=list)


class WorksheetProfile(ProfileModel):
    worksheet_name: str
    row_count: int
    column_count: int
    duplicate_row_count: int = 0
    numerical_column_count: int = 0
    categorical_column_count: int = 0
    date_column_count: int = 0
    text_column_count: int = 0
    boolean_column_count: int = 0
    other_column_count: int = 0
    total_missing_value_count: int = 0
    total_blank_string_count: int = 0
    columns: List[ColumnProfile] = Field(default_factory=list)


class DatasetProfile(ProfileModel):
    filename: str
    total_worksheet_count: int
    successful_worksheet_count: int
    failed_worksheet_count: int
    worksheets: Dict[str, WorksheetProfile] = Field(default_factory=dict)
    worksheet_errors: Dict[str, str] = Field(default_factory=dict)
