"""Regression tests for focused, user-requested analytics planning."""

import pandas as pd

from app.modules.analytics_execution import execute_analytics_plan
from app.modules.analytics_planner.analytics_planner import (
    _enforce_explicit_date_filter,
    _ensure_focused_request_operations,
)
from app.modules.analytics_planner.plan_validator import validate_analytical_plan
from app.schemas.analytics_plan import WorkbookAnalyticsPlan
from app.schemas.data_understanding import DatasetProfile


def _profile():
    return DatasetProfile.model_validate({
        "filename": "01_Small_Sales.xlsx",
        "total_worksheet_count": 1,
        "successful_worksheet_count": 1,
        "failed_worksheet_count": 0,
        "worksheets": {
            "Sales": {
                "worksheet_name": "Sales", "row_count": 4, "column_count": 4,
                "columns": [
                    {"column_name": "order_date", "original_name": "Order Date", "pandas_dtype": "datetime64[ns]", "inferred_type": "date", "semantic_role": "date", "non_null_count": 4, "missing_value_count": 0, "blank_string_count": 0, "missing_percentage": 0, "unique_value_count": 4, "unique_value_percentage": 100},
                    {"column_name": "revenue_inr", "original_name": "Revenue INR", "pandas_dtype": "int64", "inferred_type": "numerical", "semantic_role": "amount", "non_null_count": 4, "missing_value_count": 0, "blank_string_count": 0, "missing_percentage": 0, "unique_value_count": 4, "unique_value_percentage": 100, "numerical_statistics": {"minimum": 10, "maximum": 40, "mean": 25, "median": 25, "total": 100, "standard_deviation": 12}},
                    {"column_name": "product", "original_name": "Product", "pandas_dtype": "object", "inferred_type": "categorical", "semantic_role": "category", "non_null_count": 4, "missing_value_count": 0, "blank_string_count": 0, "missing_percentage": 0, "unique_value_count": 2, "unique_value_percentage": 50},
                    {"column_name": "region", "original_name": "Region", "pandas_dtype": "object", "inferred_type": "categorical", "semantic_role": "category", "non_null_count": 4, "missing_value_count": 0, "blank_string_count": 0, "missing_percentage": 0, "unique_value_count": 2, "unique_value_percentage": 50},
                ],
            }
        },
    })


def _plan():
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "Sales transactions.",
        "business_context": {"domain": "sales", "dataset_purpose": "Analyze sales.", "confidence": 0.8},
        "worksheet_analyses": [{"worksheet_name": "Sales", "inferred_purpose": "Sales records", "summary": "Sales data", "analysis_focus": []}],
        "filters": [{"worksheet_name": "Sales", "column": "order_date", "start_date": "2023-01-01", "end_date": "2023-12-31"}],
        "operations": [], "kpis": [], "visualizations": [], "key_questions": [],
        "limitations": ["The analysis is limited to the date range specified in the root filter (2023-01-01 to 2023-12-31)."],
    })


def test_entire_dataset_request_removes_model_invented_2023_filter():
    plan = _plan()
    _enforce_explicit_date_filter(plan, _profile(), "Show monthly revenue for the entire available dataset")
    assert plan.filters == []
    assert not any("root filter" in item.lower() for item in plan.limitations)


def test_explicit_date_range_overrides_model_invented_filter():
    plan = _plan()
    _enforce_explicit_date_filter(plan, _profile(), "Show total sales from 1 February 2025 to 28 February 2025")
    assert len(plan.filters) == 1
    assert plan.filters[0].start_date == "2025-02-01"
    assert plan.filters[0].end_date == "2025-02-28"


def test_monthly_revenue_request_gets_time_series_and_line_chart():
    profile, plan = _profile(), _plan()
    _enforce_explicit_date_filter(plan, profile, "Show how my revenue changes month by month")
    _ensure_focused_request_operations(plan, profile, "Show how my revenue changes month by month")
    validate_analytical_plan(plan, profile)
    assert any(op.operation_type == "time_series" and op.interval == "month" for op in plan.operations)
    assert any(viz.chart_type == "line" for viz in plan.visualizations)


def test_total_and_product_breakdown_get_scalar_kpi_and_bar_chart():
    profile, plan = _profile(), _plan()
    _enforce_explicit_date_filter(plan, profile, "Show total sales and a breakdown of revenue by product")
    _ensure_focused_request_operations(
        plan, profile,
        "Show total sales and a breakdown of revenue by product",
    )
    validate_analytical_plan(plan, profile)
    assert any(op.operation_type == "sum" and op.column == "revenue_inr" for op in plan.operations)
    assert any(kpi.label.lower().startswith("total") for kpi in plan.kpis)
    assert any(op.operation_type == "group_by" for op in plan.operations)
    assert any(viz.chart_type == "bar" for viz in plan.visualizations)


def test_explicit_date_filter_is_applied_to_scalar_and_grouped_results():
    profile, plan = _profile(), _plan()
    _enforce_explicit_date_filter(plan, profile, "Show total sales from 1 February 2025 to 28 February 2025 and breakdown by product")
    _ensure_focused_request_operations(
        plan, profile,
        "Show total sales from 1 February 2025 to 28 February 2025 and breakdown by product",
    )
    _enforce_explicit_date_filter(
        plan, profile,
        "Show total sales from 1 February 2025 to 28 February 2025 and breakdown by product",
    )
    validate_analytical_plan(plan, profile)
    frame = pd.DataFrame({
        "order_date": pd.to_datetime(["2025-01-10", "2025-02-01", "2025-02-28", "2025-03-02"]),
        "revenue_inr": [100, 200, 300, 400],
        "product": ["A", "A", "B", "B"],
        "region": ["East", "East", "West", "West"],
    })
    result = execute_analytics_plan({"Sales": frame}, plan, only_recommended_charts=True, include_default_rows_kpi=False)
    total = next(item["value"] for item in result["results"] if item.get("operation_type") == "sum")
    assert total == 500
    assert result["row_count"] == 2


def test_top_products_request_does_not_add_unrequested_full_breakdown():
    profile, plan = _profile(), _plan()
    _enforce_explicit_date_filter(plan, profile, "Identify the top 3 products by revenue")
    _ensure_focused_request_operations(plan, profile, "Identify the top 3 products by revenue")
    assert not any(op.operation_type == "group_by" for op in plan.operations)


def test_region_comparison_does_not_add_unrequested_overall_total_kpi():
    profile, plan = _profile(), _plan()
    request = "Compare total revenue across all regions. Identify the highest-performing and lowest-performing regions."
    _enforce_explicit_date_filter(plan, profile, request)
    _ensure_focused_request_operations(plan, profile, request)
    assert not any(op.operation_type == "sum" for op in plan.operations)
    assert not plan.kpis
    assert len(plan.visualizations) == 1
    assert plan.visualizations[0].chart_type == "bar"
