"""Deterministic fallback analytics planning grounded in Module 3 profiles.

The fallback creates a bounded set of useful operations across eligible sheets.
It never calculates values; Module 5 remains the only calculation engine.
"""
from __future__ import annotations

import re
from typing import Optional

from app.modules.analytics_planner.worksheet_classifier import classify_worksheet
from app.schemas.analytics_plan import (
    AverageOperation, CountOperation, GroupByOperation, HistogramOperation,
    KPIRecommendation, MetricAggregation, ScatterOperation, TimeSeriesOperation,
    VisualizationRecommendation,
    WorkbookAnalyticsPlan,
)
from app.schemas.data_understanding import DatasetProfile, WorksheetProfile

_MAX_OPERATIONS = 12
_DIMENSION_PREFERENCE = re.compile(
    r"attendance|status|department|region|category|type|priority|agent|"
    r"channel|segment|active|group|issue",
    re.IGNORECASE,
)
_METRIC_PREFERENCE = re.compile(
    r"duration|hours?|quantity|units?|amount|revenue|sales|value|total|"
    r"score|count|cost|profit|expense|resolved|assigned",
    re.IGNORECASE,
)
_METRIC_AVOID = re.compile(r"completion|rate|percentage|ratio|phone|postal", re.IGNORECASE)
_DIMENSION_AVOID = re.compile(r"(^|_)(id|uuid|email|phone|address|date|time|notes?|comment|description)(_|$)", re.IGNORECASE)


def _analytical_worksheets(profile: DatasetProfile) -> list[WorksheetProfile]:
    return [
        sheet for name, sheet in profile.worksheets.items()
        if classify_worksheet(name, sheet)["role"] == "analytical"
    ]


def _metrics(sheet: WorksheetProfile) -> list[str]:
    candidates = []
    for col in sheet.columns:
        if (col.inferred_type != "numerical" or col.semantic_role == "identifier"
                or col.non_null_count < 2 or col.numerical_statistics is None
                or col.numerical_statistics.mean is None):
            continue
        score = 3 if _METRIC_PREFERENCE.search(col.column_name) else 0
        if re.search(r"duration|resolution_time|work_hours", col.column_name, re.I):
            score += 4
        if col.missing_percentage > 50:
            score -= 2
        if _METRIC_AVOID.search(col.column_name):
            score -= 5
        candidates.append((score, col.column_name))
    return [name for _, name in sorted(candidates, key=lambda x: (-x[0], x[1]))]


def _dimensions(sheet: WorksheetProfile) -> list[str]:
    candidates = []
    for col in sheet.columns:
        if col.inferred_type not in {"categorical", "boolean", "text"}:
            continue
        unique = int(col.unique_value_count or 0)
        non_null = int(col.non_null_count or 0)
        if unique < 2 or unique > 15 or non_null < 2:
            continue
        if _DIMENSION_AVOID.search(col.column_name):
            continue
        if unique / max(non_null, 1) > .95 and not re.search(
            r"agent|employee|representative|owner", col.column_name, re.I
        ):
            continue
        score = 3 if _DIMENSION_PREFERENCE.search(col.column_name) else 0
        # A low-cardinality name field is often a valid dimension (e.g. agent).
        if re.search(r"(^|_)name($|_)", col.column_name, re.I) and unique <= 10:
            score += 2
        if col.semantic_role == "identifier" and not re.search(
            r"(^|_)name($|_)", col.column_name, re.I
        ):
            continue
        candidates.append((score, col.column_name))
    return [name for _, name in sorted(candidates, key=lambda x: (-x[0], x[1]))]


def _date_column(sheet: WorksheetProfile) -> Optional[str]:
    dates = [
        col.column_name for col in sheet.columns
        if col.inferred_type == "date" and col.non_null_count >= 2
    ]
    return dates[0] if dates else None


def build_deterministic_fallback_plan(
    dataset_profile: DatasetProfile,
    generated_plan: WorkbookAnalyticsPlan,
) -> Optional[WorkbookAnalyticsPlan]:
    """Build a multi-chart plan when the LLM produces no executable operations."""
    sheets = _analytical_worksheets(dataset_profile)
    if not sheets:
        return None

    operations, kpis, visualizations = [], [], []
    used_ids = set()

    def add_visualization(op_id: str, title: str, chart_type: str, description: str):
        visualizations.append(VisualizationRecommendation(
            id=f"viz_{op_id}", operation_id=op_id, chart_type=chart_type,
            title=title, description=description, priority="high",
        ))

    for sheet in sheets:
        if len(operations) >= _MAX_OPERATIONS:
            break
        metrics = _metrics(sheet)
        dimensions = _dimensions(sheet)
        date_col = _date_column(sheet)
        metric = metrics[0] if metrics else None

        # Each dimension gets a record-count chart; when a valid measure exists,
        # include its average in the same deterministic grouped result.
        for dimension in dimensions[:3]:
            if len(operations) >= _MAX_OPERATIONS:
                break
            op_id = f"fallback_{len(operations)+1}_{re.sub(r'[^a-zA-Z0-9]+','_',sheet.worksheet_name).strip('_').lower()[:18]}"
            aggregations = [MetricAggregation(alias="record_count", function="count", column=None)]
            if metric:
                aggregations.append(MetricAggregation(
                    alias="average_metric", function="average", column=metric,
                ))
            operations.append(GroupByOperation(
                id=op_id, operation_type="group_by", worksheet_name=sheet.worksheet_name,
                title=f"Analysis by {dimension.replace('_',' ').title()}",
                description=f"Record distribution and available measure by {dimension}.",
                group_by_columns=[dimension], aggregations=aggregations,
            ))
            add_visualization(op_id, f"Records by {dimension.replace('_',' ').title()}",
                              "bar", f"Observed record distribution by {dimension}.")

        # Date-based trends use a valid measure where available, otherwise count rows.
        if date_col and len(operations) < _MAX_OPERATIONS:
            op_id = f"fallback_trend_{len(operations)+1}"
            operations.append(TimeSeriesOperation(
                id=op_id, operation_type="time_series", worksheet_name=sheet.worksheet_name,
                title=f"Trend by {date_col.replace('_',' ').title()}",
                description="Time-based trend calculated from valid dates in the worksheet.",
                date_column=date_col, interval="month",
                metric=MetricAggregation(
                    alias="average_metric" if metric else "record_count",
                    function="average" if metric else "count",
                    column=metric,
                ),
            ))
            add_visualization(op_id, f"Trend over time — {sheet.worksheet_name}",
                              "line", "Monthly trend based on valid worksheet dates.")

        # Distribution view: a histogram answers a different question from a
        # category aggregation and is useful even when the LLM omits it.
        if metric and len(operations) < _MAX_OPERATIONS:
            op_id = f"fallback_distribution_{len(operations)+1}"
            operations.append(HistogramOperation(
                id=op_id, operation_type="histogram",
                worksheet_name=sheet.worksheet_name,
                title=f"Distribution of {metric.replace('_', ' ').title()}",
                description=f"Frequency distribution of observed {metric.replace('_', ' ')} values.",
                column=metric, bins=10,
            ))
            add_visualization(
                op_id, f"{metric.replace('_', ' ').title()} Distribution",
                "histogram", f"Frequency distribution of {metric.replace('_', ' ')} values.",
            )

        # Exploratory numeric-pair view. This shows paired observations only;
        # it does not assert correlation or causation.
        numeric_metrics = metrics[:2]
        if len(numeric_metrics) == 2 and len(operations) < _MAX_OPERATIONS:
            op_id = f"fallback_scatter_{len(operations)+1}"
            operations.append(ScatterOperation(
                id=op_id, operation_type="scatter",
                worksheet_name=sheet.worksheet_name,
                title=f"{numeric_metrics[0]} vs {numeric_metrics[1]}",
                description="Exploratory view of paired numeric observations; no relationship is inferred.",
                x_column=numeric_metrics[0], y_column=numeric_metrics[1],
                sample_limit=1000,
            ))
            add_visualization(
                op_id, f"{numeric_metrics[0]} vs {numeric_metrics[1]}",
                "scatter", "Paired numeric observations without correlation or causal claims.",
            )

        # One scalar KPI per worksheet when a numeric measure is available.
        if metric and len(operations) < _MAX_OPERATIONS:
            op_id = f"fallback_kpi_{len(operations)+1}"
            col = next(c for c in sheet.columns if c.column_name == metric)
            operations.append(AverageOperation(
                id=op_id, operation_type="average", worksheet_name=sheet.worksheet_name,
                title=f"Average {col.original_name}", description="Average of valid numeric values.",
                result_name="average_value", column=metric,
            ))
            kpis.append(KPIRecommendation(
                id=f"kpi_{len(kpis)+1}", operation_id=op_id,
                label=f"Average {col.original_name}",
                description="Mean calculated from valid numeric values.",
                format_hint="decimal", priority="medium",
            ))

    if not operations:
        sheet = sheets[0]
        op_id = "fallback_record_count"
        operations.append(CountOperation(
            id=op_id, operation_type="count", worksheet_name=sheet.worksheet_name,
            title="Records analyzed", description="Number of rows in this worksheet.",
            result_name="record_count", column=None,
        ))
        kpis.append(KPIRecommendation(
            id="record_count", operation_id=op_id, label="Records analyzed",
            description="Number of worksheet records.", format_hint="integer", priority="high",
        ))

    limitations = list(generated_plan.limitations)
    limitations.append(
        "The LLM returned no executable operations; a deterministic fallback plan "
        "fallback was generated from eligible worksheet profiles."
    )
    return WorkbookAnalyticsPlan(
        plan_version=generated_plan.plan_version,
        workbook_summary=generated_plan.workbook_summary,
        business_context=generated_plan.business_context,
        worksheet_analyses=generated_plan.worksheet_analyses,
        operations=operations[:_MAX_OPERATIONS],
        kpis=kpis[:4],
        visualizations=visualizations[:12],
        key_questions=generated_plan.key_questions[:2],
        limitations=limitations[:15],
    )
