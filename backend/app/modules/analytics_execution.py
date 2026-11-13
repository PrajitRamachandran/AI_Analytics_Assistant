"""Deterministic execution of validated Module 4 analytical plans.

The LLM proposes operations only. All calculations in this module are performed
against the cleaned Pandas DataFrames produced by Module 2.
"""
from __future__ import annotations

from typing import Any
import math

import numpy as np
import pandas as pd

from app.schemas.analytics_plan import (
    AverageOperation, BottomNOperation, ComparisonOperation, CountOperation,
    DistinctCountOperation, GroupByOperation, MaxOperation, MinOperation,
    PercentageOfTotalOperation, ScalarOperation, SumOperation,
    TimeSeriesOperation, TopNOperation, WorkbookAnalyticsPlan,
    ScatterOperation, HistogramOperation,
)


class AnalyticsExecutionError(ValueError):
    """Raised when a validated analytical operation cannot be executed."""


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _aggregate(series: pd.Series, function: str) -> Any:
    """Apply a supported aggregation while preventing string concatenation/Inf."""
    values = series.dropna()
    if function in {"sum", "average"}:
        values = pd.to_numeric(values, errors="coerce")
        values = values[np.isfinite(values.astype(float, copy=False))]
    elif function in {"min", "max"} and pd.api.types.is_numeric_dtype(values.dtype):
        numeric = pd.to_numeric(values, errors="coerce")
        values = numeric[np.isfinite(numeric.astype(float, copy=False))]

    if function == "sum":
        return values.sum() if len(values) else 0
    if function == "average":
        return values.mean() if len(values) else None
    if function == "count":
        return int(series.count())
    if function == "min":
        return values.min() if len(values) else None
    if function == "max":
        return values.max() if len(values) else None
    if function == "distinct_count":
        return int(values.nunique())
    raise AnalyticsExecutionError(f"Unsupported aggregation: {function}")


def _group_aggregate(
    frame: pd.DataFrame,
    group_columns: list[str],
    function: str,
    column: str | None,
    alias: str,
) -> pd.DataFrame:
    grouped = frame.groupby(group_columns, dropna=False, observed=True)
    if function == "count" and column is None:
        result = grouped.size().rename(alias)
    else:
        if column is None:
            raise AnalyticsExecutionError(
                f"Aggregation '{function}' requires a source column."
            )
        if function in {"sum", "average"}:
            frame = frame.copy()
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            finite = np.isfinite(frame[column].astype(float, copy=False))
            frame.loc[~finite, column] = np.nan
            grouped = frame.groupby(group_columns, dropna=False, observed=True)
        aggregate_name = (
            "mean" if function == "average" else
            "nunique" if function == "distinct_count" else function
        )
        result = grouped[column].agg(aggregate_name).rename(alias)
    return result.reset_index()


def _execute_scalar(frame: pd.DataFrame, operation: ScalarOperation) -> dict:
    if isinstance(operation, CountOperation):
        value = len(frame) if operation.column is None else int(frame[operation.column].count())
    elif isinstance(operation, SumOperation):
        value = _aggregate(frame[operation.column], "sum")
    elif isinstance(operation, AverageOperation):
        value = _aggregate(frame[operation.column], "average")
    elif isinstance(operation, MinOperation):
        value = _aggregate(frame[operation.column], "min")
    elif isinstance(operation, MaxOperation):
        value = _aggregate(frame[operation.column], "max")
    elif isinstance(operation, DistinctCountOperation):
        value = _aggregate(frame[operation.column], "distinct_count")
    else:
        raise AnalyticsExecutionError(
            f"Unsupported scalar operation: {operation.operation_type}"
        )
    return {
        "operation_id": operation.id,
        "title": operation.title,
        "operation_type": operation.operation_type,
        "worksheet_name": operation.worksheet_name,
        "result_name": operation.result_name,
        "value": _json_value(value),
        "row_count": int(len(frame)),
    }


def _execute_group_by(frame: pd.DataFrame, operation: GroupByOperation) -> list[dict]:
    result: pd.DataFrame | None = None
    for aggregation in operation.aggregations:
        part = _group_aggregate(
            frame, operation.group_by_columns, aggregation.function,
            aggregation.column, aggregation.alias,
        )
        if result is None:
            result = part
        else:
            result = result.merge(part, on=operation.group_by_columns, how="outer")
    if result is None:
        return []
    return [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in result.to_dict(orient="records")
    ]


def _execute_time_series(frame: pd.DataFrame, operation: TimeSeriesOperation) -> list[dict]:
    working = frame.copy()
    dates = pd.to_datetime(
        working[operation.date_column], errors="coerce", format="mixed", utc=True,
    ).dt.tz_convert(None)
    valid_dates = dates.notna()
    working = working.loc[valid_dates].copy()
    working["_analytics_period"] = dates.loc[valid_dates].dt.to_period({
        "day": "D", "week": "W-SUN", "month": "M",
        "quarter": "Q", "year": "Y",
    }[operation.interval]).astype(str)
    group_columns = ["_analytics_period", *operation.group_by_columns]
    result = _group_aggregate(
        working, group_columns, operation.metric.function,
        operation.metric.column, operation.metric.alias,
    ).rename(columns={"_analytics_period": "period"})
    result = result.sort_values("period")
    return [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in result.to_dict(orient="records")
    ]


def _execute_ranking(
    frame: pd.DataFrame,
    operation: TopNOperation | BottomNOperation,
) -> list[dict]:
    result = _group_aggregate(
        frame, [operation.group_by_column], operation.metric.function,
        operation.metric.column, operation.metric.alias,
    )
    result = result.sort_values(
        operation.metric.alias,
        ascending=isinstance(operation, BottomNOperation),
        na_position="last",
    ).head(operation.limit)
    return [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in result.to_dict(orient="records")
    ]


def _execute_percentage(frame: pd.DataFrame, operation: PercentageOfTotalOperation) -> list[dict]:
    values = pd.to_numeric(frame[operation.value_column], errors="coerce")
    values = values.where(np.isfinite(values.astype(float, copy=False)))
    working = frame.assign(_analytics_value=values)
    grouped = working.groupby(
        operation.category_column, dropna=False, observed=True,
    )["_analytics_value"].sum(min_count=1)
    total = grouped.sum(min_count=1)
    percentages = grouped * np.nan if total is None or pd.isna(total) or total == 0 else grouped / total * 100
    result = pd.DataFrame({
        operation.category_column: grouped.index,
        operation.result_name: percentages.values,
    })
    return [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in result.to_dict(orient="records")
    ]


def _execute_comparison(frame: pd.DataFrame, operation: ComparisonOperation) -> list[dict]:
    rows = []
    for label, category_value in (
        ("baseline", operation.baseline_value),
        ("comparison", operation.comparison_value),
    ):
        subset = frame.loc[frame[operation.category_column] == category_value]
        metric = operation.metric
        value = (
            len(subset) if metric.function == "count" and metric.column is None
            else _aggregate(subset[metric.column], metric.function)
        )
        rows.append({
            operation.category_column: _json_value(category_value),
            "comparison_group": label,
            metric.alias: _json_value(value),
        })
    return rows


def _execute_histogram(frame: pd.DataFrame, operation: HistogramOperation) -> list[dict]:
    values = pd.to_numeric(frame[operation.column], errors="coerce")
    values = values[np.isfinite(values.astype(float, copy=False))].dropna()
    if values.empty:
        return []
    counts, edges = np.histogram(values.to_numpy(dtype=float), bins=operation.bins)
    return [
        {
            "bin": f"{edges[index]:g} – {edges[index + 1]:g}",
            "count": int(counts[index]),
            "bin_start": float(edges[index]),
            "bin_end": float(edges[index + 1]),
        }
        for index in range(len(counts))
    ]


def _execute_scatter(frame: pd.DataFrame, operation: ScatterOperation) -> list[dict]:
    x_values = pd.to_numeric(frame[operation.x_column], errors="coerce")
    y_values = pd.to_numeric(frame[operation.y_column], errors="coerce")
    working = pd.DataFrame({"x": x_values, "y": y_values}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(working) > operation.sample_limit:
        # Deterministic evenly spaced sampling avoids random dashboard changes.
        indexes = np.linspace(0, len(working) - 1, operation.sample_limit, dtype=int)
        working = working.iloc[indexes]
    return [
        {"x": float(row.x), "y": float(row.y)}
        for row in working.itertuples(index=False)
    ]


def execute_operation(worksheets: dict[str, pd.DataFrame], operation: Any) -> dict:
    """Execute one validated operation and return JSON-safe records."""
    frame = worksheets.get(operation.worksheet_name)
    if frame is None:
        raise AnalyticsExecutionError(
            f"Worksheet '{operation.worksheet_name}' is unavailable for execution."
        )
    if isinstance(operation, ScalarOperation):
        return _execute_scalar(frame, operation)
    if isinstance(operation, GroupByOperation):
        records = _execute_group_by(frame, operation)
    elif isinstance(operation, TimeSeriesOperation):
        records = _execute_time_series(frame, operation)
    elif isinstance(operation, (TopNOperation, BottomNOperation)):
        records = _execute_ranking(frame, operation)
    elif isinstance(operation, PercentageOfTotalOperation):
        records = _execute_percentage(frame, operation)
    elif isinstance(operation, ComparisonOperation):
        records = _execute_comparison(frame, operation)
    elif isinstance(operation, HistogramOperation):
        records = _execute_histogram(frame, operation)
    elif isinstance(operation, ScatterOperation):
        records = _execute_scatter(frame, operation)
    else:
        raise AnalyticsExecutionError(f"Unsupported operation type: {operation.operation_type}")
    return {
        "operation_id": operation.id,
        "title": operation.title,
        "operation_type": operation.operation_type,
        "worksheet_name": operation.worksheet_name,
        "row_count": int(len(frame)),
        "records": records,
    }


def _chart_axes(operation: Any, aggregation_index: int = 0) -> tuple[str, str, str] | None:
    """Return x key, y key, and a safe default chart type for an operation."""
    if isinstance(operation, TimeSeriesOperation):
        return "period", operation.metric.alias, "line"
    if isinstance(operation, HistogramOperation):
        return "bin", "count", "histogram"
    if isinstance(operation, ScatterOperation):
        return "x", "y", "scatter"
    if isinstance(operation, GroupByOperation):
        if aggregation_index >= len(operation.aggregations):
            return None
        return operation.group_by_columns[0], operation.aggregations[aggregation_index].alias, "bar"
    if isinstance(operation, (TopNOperation, BottomNOperation)):
        return operation.group_by_column, operation.metric.alias, "bar"
    if isinstance(operation, PercentageOfTotalOperation):
        return operation.category_column, operation.result_name, "bar"
    if isinstance(operation, ComparisonOperation):
        return operation.category_column, operation.metric.alias, "bar"
    return None


def _chart_label(row: dict, x_key: str, operation: Any) -> str:
    """Preserve all grouping dimensions in a readable chart category label."""
    if isinstance(operation, GroupByOperation) and len(operation.group_by_columns) > 1:
        values = [row.get(column) for column in operation.group_by_columns]
    elif isinstance(operation, TimeSeriesOperation) and operation.group_by_columns:
        values = [row.get("period"), *(row.get(c) for c in operation.group_by_columns)]
    else:
        values = [row.get(x_key)]
    return " · ".join("Unknown" if value is None else str(value) for value in values)


def _build_insight(points: list[dict], chart_type: str) -> str:
    """Create a brief factual observation from calculated chart points."""
    if not points:
        return "No finite numeric values were available for this visualization."
    highest = max(points, key=lambda point: point["value"])
    lowest = min(points, key=lambda point: point["value"])
    if len(points) == 1:
        return f"{highest['label']} is the only available category, with a value of {highest['value']:g}."
    if chart_type in {"pie", "donut"}:
        total = sum(point["value"] for point in points)
        share = (highest["value"] / total * 100) if total > 0 else None
        if share is not None and math.isfinite(share):
            return f"{highest['label']} contributes the largest share ({share:.1f}%) of the displayed total."
    return (
        f"{highest['label']} has the highest value ({highest['value']:g}); "
        f"{lowest['label']} has the lowest ({lowest['value']:g})."
    )


def _chart_from_result(
    operation: Any,
    result: dict,
    recommendation: Any | None = None,
    aggregation_index: int = 0,
) -> dict | None:
    if "records" not in result or not result["records"]:
        return None
    axes = _chart_axes(operation, aggregation_index)
    if axes is None:
        return None
    x_key, y_key, default_type = axes
    records = result["records"]
    if isinstance(operation, ScatterOperation):
        scatter_data = [
            {"x": row.get("x"), "y": row.get("y")}
            for row in records
            if isinstance(row.get("x"), (int, float))
            and isinstance(row.get("y"), (int, float))
            and math.isfinite(float(row["x"]))
            and math.isfinite(float(row["y"]))
        ]
        if not scatter_data:
            return None
        chart_id = recommendation.id if recommendation else f"auto_{operation.id}"
        return {
            "id": chart_id,
            "operation_id": operation.id,
            "title": recommendation.title if recommendation else operation.title,
            "chart_type": "scatter",
            "description": recommendation.description if recommendation else operation.description,
            "insight": "Each point represents one paired observation. No correlation or causal conclusion is inferred.",
            "priority": recommendation.priority if recommendation else "medium",
            "worksheet_name": operation.worksheet_name,
            "x_label": operation.x_column,
            "y_label": operation.y_column,
            "scatter_data": scatter_data,
            "data": [],
            "table_columns": [operation.x_column, operation.y_column],
            "table_data": [
                {operation.x_column: point["x"], operation.y_column: point["y"]}
                for point in scatter_data[:100]
            ],
            "table_truncated": len(scatter_data) > 100,
        }

    points = []
    for row in records:
        value = row.get(y_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            points.append({"label": _chart_label(row, x_key, operation), "value": float(value)})
    if not points:
        return None

    requested_type = recommendation.chart_type if recommendation else default_type
    chart_type = requested_type
    # Pie/donut charts cannot represent negative values or a zero total.
    # Fall back to a bar chart rather than rendering a misleading composition.
    if chart_type in {"pie", "donut"} and (
        len(points) < 2 or any(point["value"] < 0 for point in points)
        or sum(point["value"] for point in points) <= 0
    ):
        chart_type = "bar"
    if chart_type in {"line", "area"} and len(points) < 2:
        return None
    if chart_type not in {"bar", "line", "area", "pie", "donut", "table", "histogram"}:
        chart_type = default_type

    if default_type == "bar":
        points.sort(key=lambda point: point["value"], reverse=True)

    table_columns = list(records[0].keys())
    table_data = records[:100]
    chart_id = recommendation.id if recommendation else (
        f"auto_{operation.id}_{aggregation_index + 1}"
    )
    title = recommendation.title if recommendation else operation.title
    description = recommendation.description if recommendation else operation.description
    if chart_type != requested_type:
        description = (
            f"{description} A bar chart is used because the calculated values "
            "are not suitable for a part-to-whole chart."
        )

    return {
        "id": chart_id,
        "operation_id": operation.id,
        "title": title,
        "chart_type": chart_type,
        "description": description,
        "insight": _build_insight(points, chart_type),
        "priority": recommendation.priority if recommendation else "medium",
        "worksheet_name": operation.worksheet_name,
        "x_label": x_key,
        "y_label": y_key,
        "data": points[:30],
        "table_columns": table_columns,
        "table_data": table_data,
        "table_truncated": len(records) > len(table_data),
    }


def _apply_plan_filters(
    worksheets: dict[str, pd.DataFrame],
    filters: list[Any],
) -> dict[str, pd.DataFrame]:
    """Apply validated inclusive date filters before any analytical operation."""
    filtered = {name: frame.copy() for name, frame in worksheets.items()}
    for item in filters:
        frame = filtered.get(item.worksheet_name)
        if frame is None:
            raise AnalyticsExecutionError(
                f"Worksheet '{item.worksheet_name}' is unavailable for filtering."
            )
        dates = pd.to_datetime(
            frame[item.column], errors="coerce", format="mixed", utc=True,
        )
        start = pd.Timestamp(item.start_date, tz="UTC")
        end_exclusive = pd.Timestamp(item.end_date, tz="UTC") + pd.Timedelta(days=1)
        mask = dates.ge(start) & dates.lt(end_exclusive)
        filtered[item.worksheet_name] = frame.loc[mask].copy()
    return filtered


def execute_analytics_plan(
    worksheets: dict[str, pd.DataFrame],
    plan: WorkbookAnalyticsPlan,
    *,
    only_recommended_charts: bool = False,
    include_default_rows_kpi: bool = True,
) -> dict:
    """Execute a validated plan and materialize its compatible chart recommendations."""
    execution_worksheets = _apply_plan_filters(worksheets, plan.filters)
    results = []
    result_by_id = {}
    for operation in plan.operations:
        result = execute_operation(execution_worksheets, operation)
        results.append(result)
        result_by_id[operation.id] = result

    recommendations: dict[str, list[Any]] = {}
    for item in plan.visualizations:
        recommendations.setdefault(item.operation_id, []).append(item)

    charts = []
    for operation in plan.operations:
        if operation.id not in result_by_id or "records" not in result_by_id[operation.id]:
            continue
        aggregation_count = len(operation.aggregations) if isinstance(operation, GroupByOperation) else 1
        operation_recommendations = recommendations.get(operation.id, [])
        # A recommendation maps to the first metric. Additional group-by metrics
        # still receive a default bar chart, ensuring no executed metric is hidden.
        for aggregation_index in range(aggregation_count):
            matching_recommendations = operation_recommendations if aggregation_index == 0 else []
            if matching_recommendations:
                for recommendation in matching_recommendations:
                    chart = _chart_from_result(
                        operation, result_by_id[operation.id], recommendation,
                        aggregation_index=aggregation_index,
                    )
                    if chart:
                        charts.append(chart)
            elif not only_recommended_charts:
                chart = _chart_from_result(
                    operation, result_by_id[operation.id], None,
                    aggregation_index=aggregation_index,
                )
                if chart:
                    charts.append(chart)

    kpis = []
    if include_default_rows_kpi:
        kpis.append({
            "id": "rows_analyzed",
            "label": "Rows analyzed",
            "value": sum(len(frame) for frame in execution_worksheets.values()),
            "format_hint": "integer",
        })
    operations_by_id = {operation.id: operation for operation in plan.operations}
    for result in results:
        if "value" in result:
            operation = operations_by_id.get(result["operation_id"])
            label = result.get("title", result.get("result_name", "Metric"))
            label_text = str(label).lower()
            # A scalar max/min is a row-level extreme. Never present it as a
            # highest/lowest-performing region, product, or other category.
            category_extreme = (
                isinstance(operation, (MaxOperation, MinOperation))
                and any(token in label_text for token in (
                    "highest performing", "lowest performing",
                    "top performing", "bottom performing",
                    "best performing", "worst performing",
                ))
            )
            if category_extreme:
                wants_high = isinstance(operation, MaxOperation) or any(
                    token in label_text for token in ("highest", "top performing", "best performing")
                )
                candidates = []
                for grouped_operation in plan.operations:
                    if not isinstance(grouped_operation, GroupByOperation):
                        continue
                    if grouped_operation.worksheet_name != operation.worksheet_name:
                        continue
                    for aggregation in grouped_operation.aggregations:
                        if aggregation.column != operation.column or aggregation.function != "sum":
                            continue
                        for group_column in grouped_operation.group_by_columns:
                            if group_column.lower().replace("_", " ") in label_text:
                                grouped_result = result_by_id.get(grouped_operation.id, {})
                                for row in grouped_result.get("records", []):
                                    value = row.get(aggregation.alias)
                                    category = row.get(group_column)
                                    if isinstance(value, (int, float)) and category is not None:
                                        candidates.append((value, category))
                if candidates:
                    extreme_value, category = (
                        max(candidates, key=lambda item: item[0])
                        if wants_high else min(candidates, key=lambda item: item[0])
                    )
                    kpis.append({
                        "id": f"operation_{result['operation_id']}",
                        "label": f"{label} ({category})",
                        "value": extreme_value,
                        "format_hint": "number",
                    })
                # If there is no matching grouped aggregation, omit the
                # misleading row-level extreme rather than displaying it.
                continue
            kpis.append({
                "id": f"operation_{result['operation_id']}",
                "label": label,
                "value": result["value"],
                "format_hint": "number",
            })

    return {
        "plan": plan.model_dump(mode="json"),
        "results": results,
        "kpis": kpis,
        "charts": charts,
        "worksheet_count": len(execution_worksheets),
        "row_count": sum(len(frame) for frame in execution_worksheets.values()),
        "filters_applied": [item.model_dump(mode="json") for item in plan.filters],
    }
