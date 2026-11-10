
"""
Module 4: Analytical Plan Validator.

Validates an AI-generated workbook analytical plan against
the actual DatasetProfile produced by Module 3.

Responsibilities:
- Validate worksheet references.
- Validate column references.
- Validate operation-specific data types.
- Validate aggregation compatibility.
- Validate grouping columns.
- Validate time-series configurations.
- Validate KPI and visualization references.
- Reject unsupported or incompatible analytical requests.

This module never executes analytical calculations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.analytics_plan import (
    AverageOperation,
    BottomNOperation,
    ComparisonOperation,
    CountOperation,
    DistinctCountOperation,
    GroupByOperation,
    MaxOperation,
    MetricAggregation,
    MinOperation,
    PercentageOfTotalOperation,
    ScalarOperation,
    SumOperation,
    TimeSeriesOperation,
    TopNOperation,
    WorkbookAnalyticsPlan,
)

from app.schemas.data_understanding import DatasetProfile
from app.modules.analytics_planner.worksheet_classifier import classify_worksheet


# ============================================================
# CUSTOM VALIDATION ERROR
# ============================================================

class AnalyticalPlanValidationError(ValueError):
    """Raised when an analytical plan is incompatible with a dataset."""


# ============================================================
# SUPPORTED DATA TYPES
# ============================================================

NUMERICAL_TYPES = {"numerical"}

GROUPABLE_TYPES = {
    "categorical",
    "date",
    "boolean",
}

ORDERABLE_TYPES = {
    "numerical",
    "date",
}


# ============================================================
# MAIN VALIDATOR
# ============================================================

class AnalyticalPlanValidator:
    """
    Validates WorkbookAnalyticsPlan against DatasetProfile.

    Validation is deterministic and independent of the LLM.
    """

    def __init__(
        self,
        dataset_profile: DatasetProfile,
    ) -> None:

        if not isinstance(dataset_profile, DatasetProfile):
            raise TypeError(
                "dataset_profile must be a DatasetProfile instance."
            )

        self.dataset_profile = dataset_profile

        self.worksheets = dataset_profile.worksheets

    # ========================================================
    # PUBLIC VALIDATION METHOD
    # ========================================================

    def validate(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> WorkbookAnalyticsPlan:
        """
        Validate an analytical plan against the actual dataset.

        Returns:
            The same validated WorkbookAnalyticsPlan.

        Raises:
            AnalyticalPlanValidationError:
                If any worksheet, column, operation or data type
                is invalid.
        """

        if not isinstance(plan, WorkbookAnalyticsPlan):
            raise TypeError(
                "plan must be a WorkbookAnalyticsPlan instance."
            )

        # Keep deterministic validation aligned with the deliberately small
        # V1 planning contract in the prompt. Schema maxima are safety bounds,
        # not permission for the model to flood the downstream executor.
        if len(plan.operations) > 12:
            raise AnalyticalPlanValidationError(
                "V1 plans may contain at most 12 analytical operations."
            )
        if len(plan.visualizations) > 12:
            raise AnalyticalPlanValidationError(
                "V1 plans may contain at most 12 visualizations."
            )
        if len(plan.key_questions) > 2:
            raise AnalyticalPlanValidationError(
                "V1 plans may contain at most 2 key questions."
            )

        self._validate_worksheet_analyses(plan)
        self._validate_unsupported_currency_claims(plan)
        self._validate_key_questions(plan)

        # Reject duplicate analytical intent even when the model changes IDs,
        # titles, or descriptions to make duplicate operations look different.
        signatures: set[str] = set()
        for operation in plan.operations:
            self._validate_operation(operation)
            payload = operation.model_dump(mode="json")
            for cosmetic_field in ("id", "title", "description"):
                payload.pop(cosmetic_field, None)
            signature = json.dumps(
                payload, sort_keys=True, ensure_ascii=False
            )
            if signature in signatures:
                raise AnalyticalPlanValidationError(
                    "The plan contains duplicate analytical operations."
                )
            signatures.add(signature)

        self._validate_kpis(plan)

        self._validate_visualizations(plan)

        return plan

    # ========================================================
    # FREE-TEXT GROUNDING GUARDS
    # ========================================================

    def _validate_unsupported_currency_claims(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> None:
        """Reject currency formatting when the profile has no unit metadata."""

        # DatasetProfile currently has no currency/unit field. A currency
        # marker would therefore be an unsupported assumption, even if the
        # underlying numeric values are correctly copied from statistics.
        currency_marker = re.compile(
            r"[₹$€£¥]|\b(?:USD|INR|EUR|GBP|JPY|CAD|AUD)\b",
            re.IGNORECASE,
        )
        narrative_fields = [
            plan.workbook_summary,
            plan.business_context.domain,
            plan.business_context.dataset_purpose,
            *plan.key_questions,
            *plan.limitations,
        ]
        for worksheet in plan.worksheet_analyses:
            narrative_fields.extend([
                worksheet.inferred_purpose,
                worksheet.summary,
                *worksheet.analysis_focus,
            ])
        for operation in plan.operations:
            narrative_fields.extend([operation.title, operation.description])
        for kpi in plan.kpis:
            narrative_fields.extend([kpi.label, kpi.description])
            if kpi.format_hint == "currency":
                raise AnalyticalPlanValidationError(
                    f"KPI '{kpi.id}' requests currency formatting, but the "
                    "dataset profile contains no explicit currency metadata."
                )
        for visualization in plan.visualizations:
            narrative_fields.extend([visualization.title, visualization.description])

        for text in narrative_fields:
            if currency_marker.search(text):
                raise AnalyticalPlanValidationError(
                    "The plan contains an unsupported currency marker, but the dataset "
                    "profile provides no explicit currency/unit metadata."
                )

    def _validate_key_questions(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> None:
        """Keep questions within the analytical capabilities of V1."""

        unsupported = re.compile(r"\bcorrelat(?:e|es|ed|ion|ions)\b", re.IGNORECASE)
        for question in plan.key_questions:
            if unsupported.search(question):
                raise AnalyticalPlanValidationError(
                    "Correlation questions are unsupported by the V1 "
                    "analytical operation schema."
                )

    # ========================================================
    # WORKSHEET VALIDATION
    # ========================================================

    def _get_worksheet(self, worksheet_name: str):
        """Retrieve a successfully profiled worksheet."""

        worksheet = self.worksheets.get(worksheet_name)

        if worksheet is None:
            raise AnalyticalPlanValidationError(
                f"Unknown or unavailable worksheet: '{worksheet_name}'."
            )

        return worksheet

    def _validate_worksheet_analyses(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> None:
        """Ensure every analysed worksheet exists in Module 3."""

        supplied = [item.worksheet_name for item in plan.worksheet_analyses]
        expected = set(self.worksheets)
        supplied_set = set(supplied)

        for analysis in plan.worksheet_analyses:
            self._get_worksheet(analysis.worksheet_name)

        if supplied_set != expected:
            missing = sorted(expected - supplied_set)
            extra = sorted(supplied_set - expected)
            details = []
            if missing:
                details.append(f"missing worksheets: {missing}")
            if extra:
                details.append(f"unknown worksheets: {extra}")
            raise AnalyticalPlanValidationError(
                "Worksheet analyses must cover every successfully profiled "
                "worksheet exactly once (" + "; ".join(details) + ")."
            )

    # ========================================================
    # COLUMN VALIDATION
    # ========================================================

    def _get_column(
        self,
        worksheet_name: str,
        column_name: str,
    ):
        """
        Retrieve a column profile using its normalized name.

        Original Excel column names are not accepted as substitutes.
        Module 2's normalized names are the execution identifiers.
        """

        worksheet = self._get_worksheet(worksheet_name)

        column = next(
            (
                item
                for item in worksheet.columns
                if item.column_name == column_name
            ),
            None,
        )

        if column is None:
            raise AnalyticalPlanValidationError(
                f"Column '{column_name}' does not exist in "
                f"worksheet '{worksheet_name}'."
            )

        return column

    def _validate_column_type(
        self,
        worksheet_name: str,
        column_name: str,
        allowed_types: set[str],
        operation_name: str,
    ):
        """Validate that a column has a compatible inferred type."""

        column = self._get_column(
            worksheet_name,
            column_name,
        )

        if column.inferred_type not in allowed_types:

            allowed = ", ".join(sorted(allowed_types))

            raise AnalyticalPlanValidationError(
                f"Operation '{operation_name}' cannot use column "
                f"'{column_name}' from worksheet '{worksheet_name}'. "
                f"Detected type: '{column.inferred_type}'. "
                f"Expected one of: {allowed}."
            )

        if column.semantic_role == "identifier" and operation_name in {
            "group_by", "top_n", "bottom_n", "time_series",
            "percentage_of_total", "comparison",
        }:
            raise AnalyticalPlanValidationError(
                f"Operation '{operation_name}' cannot use identifier column "
                f"'{column_name}' as a grouping/category dimension."
            )

        return column

    # ========================================================
    # AGGREGATION VALIDATION
    # ========================================================

    def _validate_aggregation(
        self,
        worksheet_name: str,
        aggregation: MetricAggregation,
        operation_name: str,
    ) -> None:
        """
        Validate an aggregation's column and inferred data type.

        Supported rules:

        sum / average:
            Numerical columns only.

        min / max:
            Numerical or date columns.

        count:
            Any column, or no column for record count.

        distinct_count:
            Any column.
        """

        function = aggregation.function
        column_name = aggregation.column

        # Record count does not require a column.
        if function == "count" and column_name is None:
            return

        # Other cases require an existing column.
        if column_name is None:
            raise AnalyticalPlanValidationError(
                f"Aggregation '{function}' requires a column."
            )

        if function in {"sum", "average"}:

            allowed_types = NUMERICAL_TYPES

        elif function in {"min", "max"}:

            allowed_types = ORDERABLE_TYPES

        elif function in {"count", "distinct_count"}:

            allowed_types = {
                "numerical",
                "categorical",
                "date",
                "text",
                "boolean",
                "other",
            }

        else:

            raise AnalyticalPlanValidationError(
                f"Unsupported aggregation function: '{function}'."
            )

        column_profile = self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=column_name,
            allowed_types=allowed_types,
            operation_name=operation_name,
        )
        if function in {"sum", "average", "min", "max"} and column_profile.semantic_role == "identifier":
            raise AnalyticalPlanValidationError(
                f"Aggregation '{function}' cannot use identifier column "
                f"'{column_name}'."
            )

    # ========================================================
    # SCALAR OPERATION VALIDATION
    # ========================================================

    def _validate_scalar_operation(
        self,
        operation: ScalarOperation,
    ) -> None:

        operation_type = operation.operation_type

        if isinstance(operation, SumOperation):

            allowed_types = NUMERICAL_TYPES

        elif isinstance(operation, AverageOperation):

            allowed_types = NUMERICAL_TYPES

        elif isinstance(operation, MinOperation):

            allowed_types = ORDERABLE_TYPES

        elif isinstance(operation, MaxOperation):

            allowed_types = ORDERABLE_TYPES

        elif isinstance(operation, DistinctCountOperation):

            allowed_types = {
                "numerical",
                "categorical",
                "date",
                "text",
                "boolean",
                "other",
            }

        elif isinstance(operation, CountOperation):

            if operation.column is not None:

                self._get_column(
                    operation.worksheet_name,
                    operation.column,
                )

            return

        else:

            raise AnalyticalPlanValidationError(
                f"Unsupported scalar operation: '{operation_type}'."
            )

        column_profile = self._validate_column_type(
            worksheet_name=operation.worksheet_name,
            column_name=operation.column,
            allowed_types=allowed_types,
            operation_name=operation_type,
        )
        if operation_type in {"sum", "average", "min", "max"} and column_profile.semantic_role == "identifier":
            raise AnalyticalPlanValidationError(
                f"Operation '{operation_type}' cannot use identifier column "
                f"'{operation.column}'."
            )

    # ========================================================
    # GROUP BY VALIDATION
    # ========================================================

    def _validate_group_by(
        self,
        operation: GroupByOperation,
    ) -> None:

        worksheet_name = operation.worksheet_name

        # Validate grouping columns.
        for column_name in operation.group_by_columns:

            column_profile = self._validate_column_type(
                worksheet_name=worksheet_name,
                column_name=column_name,
                allowed_types=GROUPABLE_TYPES,
                operation_name="group_by",
            )
            if column_profile.inferred_type == "date":
                raise AnalyticalPlanValidationError(
                    f"Date column '{column_name}' cannot be grouped as raw "
                    "dates. Use a time_series operation with an explicit interval."
                )

        # Validate all aggregations.
        for aggregation in operation.aggregations:

            self._validate_aggregation(
                worksheet_name=worksheet_name,
                aggregation=aggregation,
                operation_name="group_by",
            )

    # ========================================================
    # TOP N / BOTTOM N VALIDATION
    # ========================================================

    def _validate_ranking_operation(
        self,
        operation: TopNOperation | BottomNOperation,
    ) -> None:

        worksheet_name = operation.worksheet_name

        self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=operation.group_by_column,
            allowed_types=GROUPABLE_TYPES,
            operation_name=operation.operation_type,
        )

        self._validate_aggregation(
            worksheet_name=worksheet_name,
            aggregation=operation.metric,
            operation_name=operation.operation_type,
        )

    # ========================================================
    # TIME SERIES VALIDATION
    # ========================================================

    def _validate_time_series(
        self,
        operation: TimeSeriesOperation,
    ) -> None:

        worksheet_name = operation.worksheet_name

        # Date column must actually be identified as a date.
        self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=operation.date_column,
            allowed_types={"date"},
            operation_name="time_series",
        )

        # Validate optional category groupings.
        for column_name in operation.group_by_columns:

            self._validate_column_type(
                worksheet_name=worksheet_name,
                column_name=column_name,
                allowed_types=GROUPABLE_TYPES - {"date"},
                operation_name="time_series",
            )

        # Validate the metric.
        self._validate_aggregation(
            worksheet_name=worksheet_name,
            aggregation=operation.metric,
            operation_name="time_series",
        )

    # ========================================================
    # PERCENTAGE OF TOTAL VALIDATION
    # ========================================================

    def _validate_percentage(
        self,
        operation: PercentageOfTotalOperation,
    ) -> None:

        worksheet_name = operation.worksheet_name

        self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=operation.category_column,
            allowed_types=GROUPABLE_TYPES,
            operation_name="percentage_of_total",
        )

        self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=operation.value_column,
            allowed_types=NUMERICAL_TYPES,
            operation_name="percentage_of_total",
        )

    # ========================================================
    # COMPARISON VALIDATION
    # ========================================================

    def _validate_comparison(
        self,
        operation: ComparisonOperation,
    ) -> None:

        worksheet_name = operation.worksheet_name

        self._validate_column_type(
            worksheet_name=worksheet_name,
            column_name=operation.category_column,
            allowed_types={"categorical", "boolean"},
            operation_name="comparison",
        )

        self._validate_aggregation(
            worksheet_name=worksheet_name,
            aggregation=operation.metric,
            operation_name="comparison",
        )

        category_column = self._get_column(
            worksheet_name,
            operation.category_column,
        )

        # Reject comparison values whose basic Python types
        # are incompatible with the profiled column.
        expected_type = category_column.inferred_type

        values = (
            operation.baseline_value,
            operation.comparison_value,
        )

        # Module 3 retains only the most frequent categories. Membership can
        # be asserted only when that list is known to cover every category.
        categorical = category_column.categorical_statistics
        if (
            categorical is not None
            and categorical.unique_category_count == len(categorical.most_frequent)
        ):
            observed = [item.value for item in categorical.most_frequent]
            for value in values:
                if value not in observed:
                    raise AnalyticalPlanValidationError(
                        f"Comparison value {value!r} was not observed in "
                        f"column '{operation.category_column}'."
                    )

        for value in values:

            if expected_type == "boolean" and not isinstance(value, bool):
                raise AnalyticalPlanValidationError(
                    f"Comparison values for boolean column "
                    f"'{operation.category_column}' must be booleans."
                )

            if expected_type == "categorical" and not isinstance(
                value, (str, int, float, bool)
            ):
                raise AnalyticalPlanValidationError(
                    f"Invalid comparison value for "
                    f"'{operation.category_column}'."
                )

    # ========================================================
    # OPERATION DISPATCH
    # ========================================================

    def _validate_operation(
        self,
        operation: Any,
    ) -> None:
        """Route each operation to its specific validation logic."""

        # Validate worksheet existence and ensure documentation/reference
        # sheets are never silently treated as transactional data.
        worksheet = self._get_worksheet(operation.worksheet_name)
        classification = classify_worksheet(operation.worksheet_name, worksheet)
        if classification["role"] != "analytical":
            raise AnalyticalPlanValidationError(
                f"Operation '{operation.id}' targets worksheet "
                f"'{operation.worksheet_name}', classified as "
                f"'{classification['role']}': {classification['reason']}"
            )

        if isinstance(operation, ScalarOperation):

            self._validate_scalar_operation(operation)

        elif isinstance(operation, GroupByOperation):

            self._validate_group_by(operation)

        elif isinstance(operation, (TopNOperation, BottomNOperation)):

            self._validate_ranking_operation(operation)

        elif isinstance(operation, TimeSeriesOperation):

            self._validate_time_series(operation)

        elif isinstance(operation, PercentageOfTotalOperation):

            self._validate_percentage(operation)

        elif isinstance(operation, ComparisonOperation):

            self._validate_comparison(operation)

        else:

            raise AnalyticalPlanValidationError(
                f"Unsupported analytical operation: "
                f"{type(operation).__name__}."
            )

    # ========================================================
    # KPI VALIDATION
    # ========================================================

    def _validate_kpis(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> None:
        """Ensure KPI references point to valid operations."""

        operations = {
            operation.id: operation
            for operation in plan.operations
        }

        for kpi in plan.kpis:

            operation = operations.get(kpi.operation_id)

            if operation is None:
                raise AnalyticalPlanValidationError(
                    f"KPI '{kpi.id}' references an unknown operation."
                )

            if operation.operation_type not in {
                "sum",
                "average",
                "count",
                "min",
                "max",
                "distinct_count",
            }:
                raise AnalyticalPlanValidationError(
                    f"KPI '{kpi.id}' must reference a scalar operation."
                )

    # ========================================================
    # VISUALIZATION VALIDATION
    # ========================================================

    def _validate_visualizations(
        self,
        plan: WorkbookAnalyticsPlan,
    ) -> None:
        """
        Ensure charts reference operations with compatible output.

        Supported chart compatibility:

        bar:
            Group-by, ranking, percentage, comparison.

        line / area:
            Time series.

        pie / donut:
            Percentage-of-total or group-by.

        table:
            Any non-scalar operation.

        scatter:
            Rejected in V1 because no dedicated scatter-data
            operation exists in the current analytical contract.
        """

        operations = {
            operation.id: operation
            for operation in plan.operations
        }

        # A chart recommendation is identified by its operation and chart
        # type. Repeating the same pair would render the same data twice.
        # Keep at most two genuinely different views per operation.
        seen_chart_signatures: set[tuple[str, str]] = set()
        chart_types_by_operation: dict[str, set[str]] = {}

        for visualization in plan.visualizations:
            signature = (visualization.operation_id, visualization.chart_type)
            if signature in seen_chart_signatures:
                raise AnalyticalPlanValidationError(
                    f"Duplicate '{visualization.chart_type}' visualization "
                    f"for operation '{visualization.operation_id}'."
                )
            seen_chart_signatures.add(signature)

            selected_types = chart_types_by_operation.setdefault(
                visualization.operation_id, set()
            )
            selected_types.add(visualization.chart_type)
            if len(selected_types) > 2:
                raise AnalyticalPlanValidationError(
                    f"Operation '{visualization.operation_id}' has more than "
                    "two visualization recommendations."
                )
            if {"pie", "donut"}.issubset(selected_types):
                raise AnalyticalPlanValidationError(
                    f"Operation '{visualization.operation_id}' cannot have "
                    "both pie and donut recommendations; they communicate "
                    "the same part-to-whole view."
                )
            if {"line", "area"}.issubset(selected_types):
                raise AnalyticalPlanValidationError(
                    f"Operation '{visualization.operation_id}' cannot have "
                    "both line and area recommendations for the same series."
                )

            operation = operations.get(
                visualization.operation_id
            )

            if operation is None:
                raise AnalyticalPlanValidationError(
                    f"Visualization '{visualization.id}' "
                    f"references an unknown operation."
                )

            chart_type = visualization.chart_type
            operation_type = operation.operation_type

            if chart_type == "scatter":

                raise AnalyticalPlanValidationError(
                    "Scatter charts are not supported in V1 because "
                    "the current operation contract does not define "
                    "a dedicated scatter-data operation."
                )

            if chart_type in {"line", "area"}:

                if operation_type != "time_series":

                    raise AnalyticalPlanValidationError(
                        f"Chart '{visualization.id}' of type "
                        f"'{chart_type}' requires a time_series operation."
                    )

            elif chart_type in {"pie", "donut"}:

                if operation_type not in {
                    "group_by",
                    "percentage_of_total",
                }:

                    raise AnalyticalPlanValidationError(
                        f"Chart '{visualization.id}' of type "
                        f"'{chart_type}' requires a group_by or "
                        f"percentage_of_total operation."
                    )

            elif chart_type == "bar":

                if operation_type not in {
                    "group_by",
                    "top_n",
                    "bottom_n",
                    "percentage_of_total",
                    "comparison",
                }:

                    raise AnalyticalPlanValidationError(
                        f"Bar chart '{visualization.id}' "
                        f"references an incompatible operation."
                    )

            elif chart_type == "table":

                if operation_type in {
                    "sum",
                    "average",
                    "count",
                    "min",
                    "max",
                    "distinct_count",
                }:

                    raise AnalyticalPlanValidationError(
                        f"Table '{visualization.id}' cannot reference "
                        f"a scalar-only operation."
                    )


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def validate_analytical_plan(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
) -> WorkbookAnalyticsPlan:
    """
    Convenience function for validating an analytical plan.

    Usage:

        validated_plan = validate_analytical_plan(
            plan,
            dataset_profile,
        )
    """

    validator = AnalyticalPlanValidator(
        dataset_profile=dataset_profile,
    )

    return validator.validate(plan)
