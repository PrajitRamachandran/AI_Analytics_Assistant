
"""
Pydantic schemas for Module 4: AI Analytics Planner.

Defines the workbook-level analytical plan and the strictly supported
operations that Module 5 will eventually execute.

The LLM proposes operations. These schemas validate their structure.
Dataset-specific validation will be performed separately against the
actual Module 3 DatasetProfile.
"""

from __future__ import annotations

import math
import re

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat,
    StrictInt, StrictStr, model_validator,
)


# ============================================================
# BASE CONFIGURATION
# ============================================================

class AnalyticsPlanModel(BaseModel):
    """Base model enforcing strict schema validation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


# ============================================================
# ENUMERATIONS / SUPPORTED OPERATIONS
# ============================================================

AggregationFunction = Literal[
    "sum",
    "average",
    "count",
    "min",
    "max",
    "distinct_count",
]

TimeInterval = Literal[
    "day",
    "week",
    "month",
    "quarter",
    "year",
]

ChartType = Literal[
    "bar",
    "line",
    "area",
    "pie",
    "donut",
    "scatter",
    "table",
]

Priority = Literal[
    "high",
    "medium",
    "low",
]


# ============================================================
# SHARED METRIC AGGREGATION
# ============================================================

class MetricAggregation(AnalyticsPlanModel):
    """
    Defines an aggregation to be executed by Module 5.

    For count:
        column=None means count records.
        column=<name> means count non-null values.

    All other aggregation functions require a column.
    """

    alias: str = Field(
        min_length=1,
        max_length=80,
        description="Unique name for the resulting metric.",
    )

    function: AggregationFunction

    column: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Column used for the aggregation.",
    )

    @model_validator(mode="after")
    def validate_column_requirement(self):
        if self.function != "count" and self.column is None:
            raise ValueError(
                f"Column is required for '{self.function}' aggregation."
            )

        return self


# ============================================================
# COMMON ANALYTICAL OPERATION FIELDS
# ============================================================

class BaseAnalyticalOperation(AnalyticsPlanModel):
    """Fields shared by all analytical operations."""

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
    )

    worksheet_name: str = Field(
        min_length=1,
        max_length=255,
    )

    title: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str = Field(
        min_length=1,
        max_length=500,
    )


class ScalarOperation(BaseAnalyticalOperation):
    """Base class for operations producing a single scalar result."""

    result_name: str = Field(
        min_length=1,
        max_length=80,
    )


# ============================================================
# 1. SUM
# ============================================================

class SumOperation(ScalarOperation):

    operation_type: Literal["sum"]

    column: str = Field(min_length=1)


# ============================================================
# 2. AVERAGE
# ============================================================

class AverageOperation(ScalarOperation):

    operation_type: Literal["average"]

    column: str = Field(min_length=1)


# ============================================================
# 3. COUNT
# ============================================================

class CountOperation(ScalarOperation):
    """
    Count records or non-null values in a specified column.

    If column is None, count all worksheet records.
    """

    operation_type: Literal["count"]

    column: Optional[str] = Field(
        default=None,
        min_length=1,
    )


# ============================================================
# 4. MINIMUM
# ============================================================

class MinOperation(ScalarOperation):

    operation_type: Literal["min"]

    column: str = Field(min_length=1)


# ============================================================
# 5. MAXIMUM
# ============================================================

class MaxOperation(ScalarOperation):

    operation_type: Literal["max"]

    column: str = Field(min_length=1)


# ============================================================
# 6. DISTINCT COUNT
# ============================================================

class DistinctCountOperation(ScalarOperation):

    operation_type: Literal["distinct_count"]

    column: str = Field(min_length=1)


# ============================================================
# 7. GROUP BY
# ============================================================

class GroupByOperation(BaseAnalyticalOperation):
    """
    Groups records by one or more categorical columns
    and calculates one or more aggregations.
    """

    operation_type: Literal["group_by"]

    group_by_columns: list[str] = Field(
        min_length=1,
        max_length=3,
    )

    aggregations: list[MetricAggregation] = Field(
        min_length=1,
        max_length=10,
    )

    @model_validator(mode="after")
    def validate_grouping_configuration(self):

        if len(set(self.group_by_columns)) != len(self.group_by_columns):
            raise ValueError(
                "Duplicate columns are not allowed in group_by_columns."
            )

        aliases = [item.alias for item in self.aggregations]

        if len(set(aliases)) != len(aliases):
            raise ValueError(
                "Aggregation aliases must be unique within an operation."
            )

        return self


# ============================================================
# 8. TOP N
# ============================================================

class TopNOperation(BaseAnalyticalOperation):
    """
    Returns the highest-ranking groups based on an aggregation.

    Example:
        Top 5 products by total revenue.
    """

    operation_type: Literal["top_n"]

    group_by_column: str = Field(min_length=1)

    metric: MetricAggregation

    limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )


# ============================================================
# 9. BOTTOM N
# ============================================================

class BottomNOperation(BaseAnalyticalOperation):
    """
    Returns the lowest-ranking groups based on an aggregation.
    """

    operation_type: Literal["bottom_n"]

    group_by_column: str = Field(min_length=1)

    metric: MetricAggregation

    limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )


# ============================================================
# 10. TIME SERIES
# ============================================================

class TimeSeriesOperation(BaseAnalyticalOperation):
    """
    Performs date-based aggregation.

    Example:
        Monthly revenue trend.
    """

    operation_type: Literal["time_series"]

    date_column: str = Field(min_length=1)

    interval: TimeInterval

    metric: MetricAggregation

    group_by_columns: list[str] = Field(
        default_factory=list,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_time_series_configuration(self):

        if self.date_column in self.group_by_columns:
            raise ValueError(
                "The date column cannot also be a grouping column."
            )

        if len(set(self.group_by_columns)) != len(self.group_by_columns):
            raise ValueError(
                "Duplicate grouping columns are not allowed."
            )

        return self


# ============================================================
# 11. PERCENTAGE OF TOTAL
# ============================================================

class PercentageOfTotalOperation(BaseAnalyticalOperation):
    """
    Calculates each category's percentage contribution
    to the overall total of a numerical column.

    Example:
        Each region's percentage contribution to total revenue.
    """

    operation_type: Literal["percentage_of_total"]

    category_column: str = Field(min_length=1)

    value_column: str = Field(min_length=1)

    result_name: str = Field(
        default="percentage_of_total",
        min_length=1,
        max_length=80,
    )

    @model_validator(mode="after")
    def validate_columns(self):

        if self.category_column == self.value_column:
            raise ValueError(
                "Category and value columns must be different."
            )

        return self


# ============================================================
# 12. COMPARISON
# ============================================================

class ComparisonOperation(BaseAnalyticalOperation):
    """
    Compares an aggregated metric between two explicit categories.

    The first category is the baseline.
    The second category is compared against the baseline.

    Module 5 will calculate:
        - Baseline metric
        - Comparison metric
        - Absolute difference
        - Percentage difference relative to baseline
    """

    operation_type: Literal["comparison"]

    category_column: str = Field(min_length=1)

    # Explicit observed category values only. A nullable Any would allow
    # Ollama's constrained decoder to emit null, which is unusable for a
    # comparison and only fails later during model validation.
    baseline_value: StrictStr | StrictInt | StrictFloat | StrictBool

    comparison_value: StrictStr | StrictInt | StrictFloat | StrictBool

    metric: MetricAggregation

    @model_validator(mode="after")
    def validate_comparison_values(self):

        for name, value in (
            ("baseline_value", self.baseline_value),
            ("comparison_value", self.comparison_value),
        ):
            if value is None or not isinstance(
                value, (str, int, float, bool)
            ):
                raise ValueError(
                    f"{name} must be a non-null scalar value."
                )

            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(
                    f"{name} must be finite."
                )

        if self.baseline_value == self.comparison_value:
            raise ValueError(
                "Baseline and comparison values must be different."
            )

        return self


# ============================================================
# ANALYTICAL OPERATION UNION
# ============================================================

AnalyticalOperation = Annotated[
    Union[
        SumOperation,
        AverageOperation,
        CountOperation,
        MinOperation,
        MaxOperation,
        DistinctCountOperation,
        GroupByOperation,
        TopNOperation,
        BottomNOperation,
        TimeSeriesOperation,
        PercentageOfTotalOperation,
        ComparisonOperation,
    ],
    Field(discriminator="operation_type"),
]


# ============================================================
# WORKSHEET ANALYSIS
# ============================================================

class WorksheetAnalysis(AnalyticsPlanModel):
    """AI interpretation of an individual worksheet."""

    worksheet_name: str = Field(
        min_length=1,
        max_length=255,
    )

    inferred_purpose: str = Field(
        min_length=1,
        max_length=300,
    )

    summary: str = Field(
        min_length=1,
        max_length=1000,
    )

    analysis_focus: list[str] = Field(
        default_factory=list,
        max_length=4,
    )


# ============================================================
# WORKBOOK BUSINESS CONTEXT
# ============================================================

class BusinessContext(AnalyticsPlanModel):
    """Overall business interpretation of the workbook."""

    domain: str = Field(
        min_length=1,
        max_length=100,
        description="Likely domain, such as sales, finance, HR or inventory.",
    )

    dataset_purpose: str = Field(
        min_length=1,
        max_length=500,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )


# ============================================================
# KPI RECOMMENDATIONS
# ============================================================

class KPIRecommendation(AnalyticsPlanModel):
    """A recommended KPI linked to a scalar analytical operation."""

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
    )

    operation_id: str = Field(min_length=1)

    label: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str = Field(
        min_length=1,
        max_length=300,
    )

    format_hint: Literal[
        "number",
        "integer",
        "decimal",
        "currency",
        "percentage",
    ] = "number"

    priority: Priority = "medium"


# ============================================================
# VISUALIZATION RECOMMENDATIONS
# ============================================================

class VisualizationRecommendation(AnalyticsPlanModel):
    """
    Recommends a visualization for an existing analytical operation.

    The chart references an operation ID. It does not contain
    independently generated numerical data.
    """

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
    )

    operation_id: str = Field(min_length=1)

    chart_type: ChartType

    title: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str = Field(
        min_length=1,
        max_length=300,
    )

    priority: Priority = "medium"


# ============================================================
# KPI -> SCALAR OPERATION DERIVATION
# ============================================================

_SCALAR_OPERATION_CLASSES: dict[str, type[ScalarOperation]] = {
    "sum": SumOperation,
    "average": AverageOperation,
    "count": CountOperation,
    "min": MinOperation,
    "max": MaxOperation,
    "distinct_count": DistinctCountOperation,
}

# Maximum number of operations a plan may contain (WorkbookAnalyticsPlan).
_MAX_PLAN_OPERATIONS = 12


_FUNCTION_HINTS: dict[str, str] = {
    "avg": "average", "average": "average", "mean": "average",
    "total": "sum", "sum": "sum",
    "min": "min", "minimum": "min", "lowest": "min",
    "max": "max", "maximum": "max", "highest": "max",
    "count": "count",
    "distinct": "distinct_count", "unique": "distinct_count",
}


def _candidate_metrics(operation: Any) -> list[MetricAggregation]:
    """Return every measure a non-scalar operation reports."""
    if isinstance(operation, GroupByOperation):
        return list(operation.aggregations)

    if isinstance(
        operation, (TopNOperation, BottomNOperation, TimeSeriesOperation),
    ) or isinstance(operation, ComparisonOperation):
        return [operation.metric]

    if isinstance(operation, PercentageOfTotalOperation):
        return [MetricAggregation(
            alias=operation.result_name,
            function="sum",
            column=operation.value_column,
        )]

    return []


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _select_kpi_metric(
    candidates: list[MetricAggregation],
    kpi: "KPIRecommendation",
) -> Optional[tuple[str, Optional[str], str]]:
    """
    Choose (function, column, result_name) for a KPI from the measures of
    the operation it references, using only the KPI's own id and label.

    Returns None when the KPI text does not identify a single measure.
    """
    if not candidates:
        return None

    text = f"{kpi.id} {kpi.label}"
    squashed = _squash(text)

    # 1. A reported measure whose alias is named by the KPI wins outright.
    aliased = [c for c in candidates if _squash(c.alias) and _squash(c.alias) in squashed]
    if len({(c.function, c.column) for c in aliased}) == 1:
        c = aliased[0]
        return c.function, c.column, c.alias

    # 2. Column: a column named by the KPI, else the only column reported.
    columns = {c.column for c in candidates if c.column}
    named = {col for col in columns if _squash(col) in squashed}

    if len(named) == 1:
        column: Optional[str] = next(iter(named))
    elif not named and len(columns) == 1:
        column = next(iter(columns))
    elif not columns:
        column = None
    else:
        return None

    matching = [c for c in candidates if c.column == column]

    # 3. Function: one stated by the KPI (when it can apply), else the
    #    function of the single matching measure.
    tokens = re.findall(r"[a-z]+", text.lower())
    hinted = {_FUNCTION_HINTS[t] for t in tokens if t in _FUNCTION_HINTS}
    function: Optional[str] = None

    if len(hinted) == 1:
        hint = next(iter(hinted))
        if column is not None or hint == "count":
            function = hint

    if function is None:
        functions = {c.function for c in matching}
        if len(functions) != 1:
            return None
        function = next(iter(functions))

    for c in matching:
        if c.function == function:
            return function, column, c.alias

    return function, column, f"{function}_{column or 'records'}"[:80]


def _derive_scalar_operation(
    source: Any,
    kpi: "KPIRecommendation",
    taken_ids: set[str],
) -> Optional[ScalarOperation]:
    """
    Build the explicit scalar operation equivalent to a KPI's measure.

    The result is the chosen aggregation (function and column) applied to the
    whole worksheet, so it is computed deterministically by Module 5 like any
    other scalar operation and is still validated against the dataset profile.
    """
    selected = _select_kpi_metric(_candidate_metrics(source), kpi)

    if selected is None:
        return None

    function, column, result_name = selected

    if function != "count" and column is None:
        return None

    base = f"{kpi.id}_overall"[:56]
    operation_id = base
    suffix = 2

    while operation_id in taken_ids:
        operation_id = f"{base}_{suffix}"
        suffix += 1

    fields: dict[str, Any] = {
        "id": operation_id,
        "operation_type": function,
        "worksheet_name": source.worksheet_name,
        "title": kpi.label,
        "description": (
            f"Overall {function} across the worksheet, "
            f"derived from the measures of operation '{source.id}'."
        ),
        "result_name": result_name,
        "column": column,
    }

    return _SCALAR_OPERATION_CLASSES[function](**fields)


# ============================================================
# COMPLETE WORKBOOK-LEVEL ANALYTICAL PLAN
# ============================================================

class WorkbookAnalyticsPlan(AnalyticsPlanModel):
    """
    Complete analytical plan generated by Module 4.

    One comprehensive plan represents the entire workbook.
    Individual operations remain worksheet-specific.

    Cross-worksheet execution is not implicitly permitted.
    Any future joins require separate relationship validation.
    """

    plan_version: Literal["1.0"] = "1.0"

    workbook_summary: str = Field(
        min_length=1,
        max_length=1500,
    )

    business_context: BusinessContext

    worksheet_analyses: list[WorksheetAnalysis] = Field(
        min_length=1,
        max_length=30,
    )

    operations: list[AnalyticalOperation] = Field(
        default_factory=list,
        max_length=12,
    )

    kpis: list[KPIRecommendation] = Field(
        default_factory=list,
        max_length=4,
    )

    visualizations: list[VisualizationRecommendation] = Field(
        default_factory=list,
        max_length=12,
    )

    key_questions: list[str] = Field(
        default_factory=list,
        max_length=2,
    )

    limitations: list[str] = Field(
        default_factory=list,
        max_length=15,
    )

    def _scalar_for_kpi(
        self,
        source: Any,
        kpi: KPIRecommendation,
        scalar_ops: list[Any],
    ) -> Optional[ScalarOperation]:
        """Reuse or append the scalar operation backing a KPI measure."""
        candidate = _derive_scalar_operation(
            source, kpi, {op.id for op in self.operations},
        )

        if candidate is None:
            return None

        for existing in scalar_ops:
            if (
                existing.worksheet_name == candidate.worksheet_name
                and existing.operation_type == candidate.operation_type
                and getattr(existing, "column", None) == candidate.column
            ):
                return existing

        self.operations.append(candidate)
        scalar_ops.append(candidate)

        return candidate

    # --------------------------------------------------------
    # CROSS-REFERENCE VALIDATION
    # --------------------------------------------------------

    @model_validator(mode="after")
    def validate_plan_references(self):

        # Validate worksheet names.
        worksheet_names = [
            item.worksheet_name
            for item in self.worksheet_analyses
        ]

        if len(set(worksheet_names)) != len(worksheet_names):
            raise ValueError(
                "Worksheet names must be unique."
            )

        available_worksheets = set(worksheet_names)

        # Validate operation IDs.
        operation_ids = [
            operation.id
            for operation in self.operations
        ]

        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError(
                "Analytical operation IDs must be unique."
            )

        operations_by_id = {
            operation.id: operation
            for operation in self.operations
        }

        # Every operation must reference a worksheet
        # included in the workbook-level plan.
        for operation in self.operations:

            if operation.worksheet_name not in available_worksheets:
                raise ValueError(
                    f"Operation '{operation.id}' references unknown "
                    f"worksheet '{operation.worksheet_name}'."
                )

        # Validate KPI references.
        kpi_ids = [kpi.id for kpi in self.kpis]

        if len(set(kpi_ids)) != len(kpi_ids):
            raise ValueError(
                "KPI IDs must be unique."
            )

        scalar_operation_types = {
            "sum",
            "average",
            "count",
            "min",
            "max",
            "distinct_count",
        }

        scalar_ops = [
            op for op in self.operations
            if op.operation_type in scalar_operation_types
        ]

        for kpi in self.kpis:

            operation = operations_by_id.get(kpi.operation_id)

            if operation is None:
                by_type = [op for op in scalar_ops if op.operation_type == kpi.operation_id]
                by_result = [op for op in scalar_ops if getattr(op, "result_name", None) == kpi.operation_id]
                if len(by_type) == 1:
                    kpi.operation_id = by_type[0].id
                    operation = by_type[0]
                elif len(by_result) == 1:
                    kpi.operation_id = by_result[0].id
                    operation = by_result[0]
                elif len(scalar_ops) == 1:
                    kpi.operation_id = scalar_ops[0].id
                    operation = scalar_ops[0]
                else:
                    raise ValueError(
                        f"KPI '{kpi.id}' references an unknown "
                        f"operation '{kpi.operation_id}'."
                    )

            if operation.operation_type not in scalar_operation_types:
                # A KPI must show one number. When it points at a grouped or
                # trend result with a single unambiguous measure, link it to
                # an explicit scalar operation over that same measure instead
                # of rejecting the plan. Anything ambiguous still fails.
                derived = None

                if len(self.operations) < _MAX_PLAN_OPERATIONS:
                    derived = self._scalar_for_kpi(
                        operation, kpi, scalar_ops,
                    )

                if derived is None:
                    raise ValueError(
                        f"KPI '{kpi.id}' must reference a scalar operation."
                    )

                kpi.operation_id = derived.id

        # Validate visualization references.
        visualization_ids = [
            item.id for item in self.visualizations
        ]

        if len(set(visualization_ids)) != len(visualization_ids):
            raise ValueError(
                "Visualization IDs must be unique."
            )

        scalar_types = scalar_operation_types

        non_scalar_ops = [
            op for op in self.operations
            if op.operation_type not in scalar_types
        ]

        for visualization in self.visualizations:

            operation = operations_by_id.get(
                visualization.operation_id
            )

            if operation is None:
                by_type = [op for op in non_scalar_ops if op.operation_type == visualization.operation_id]
                if len(by_type) == 1:
                    visualization.operation_id = by_type[0].id
                    operation = by_type[0]
                elif len(non_scalar_ops) == 1:
                    visualization.operation_id = non_scalar_ops[0].id
                    operation = non_scalar_ops[0]
                else:
                    raise ValueError(
                        f"Visualization '{visualization.id}' references "
                        f"an unknown operation "
                        f"'{visualization.operation_id}'."
                    )

            if operation.operation_type in scalar_types:
                raise ValueError(
                    f"Visualization '{visualization.id}' must reference "
                    "a grouped or comparative analytical operation, "
                    "not a scalar operation."
                )

        return self
