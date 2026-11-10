import pandas as pd

from app.modules.analytics_execution import execute_analytics_plan, execute_operation
from app.schemas.analytics_plan import WorkbookAnalyticsPlan


def _plan(operations, visualizations=None):
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "A sales worksheet with dates, regions and revenue.",
        "business_context": {
            "domain": "sales",
            "dataset_purpose": "Summarize sales records.",
            "confidence": 0.6,
        },
        "worksheet_analyses": [{
            "worksheet_name": "Sales",
            "inferred_purpose": "Sales transactions",
            "summary": "Contains dates, regions and revenue values.",
            "analysis_focus": ["Revenue by region", "Monthly revenue"],
        }],
        "operations": operations,
        "kpis": [],
        "visualizations": visualizations or [],
        "key_questions": [],
        "limitations": [],
    })


def test_group_by_executes_real_sum_and_returns_chart_ready_records():
    frame = pd.DataFrame({
        "region": ["North", "South", "North", "South"],
        "revenue": [100, 80, 50, 70],
    })
    plan = _plan([{
        "id": "region_revenue",
        "operation_type": "group_by",
        "worksheet_name": "Sales",
        "title": "Revenue by region",
        "description": "Sum revenue by region.",
        "group_by_columns": ["region"],
        "aggregations": [{
            "alias": "total_revenue",
            "function": "sum",
            "column": "revenue",
        }],
    }])
    output = execute_analytics_plan({"Sales": frame}, plan)
    records = output["results"][0]["records"]
    assert {row["region"]: row["total_revenue"] for row in records} == {
        "North": 150, "South": 150
    }
    assert output["charts"][0]["data"]
    assert output["kpis"][0]["value"] == 4


def test_time_series_monthly_uses_month_buckets_not_raw_dates():
    frame = pd.DataFrame({
        "order_date": pd.to_datetime([
            "2025-01-02", "2025-01-29", "2025-02-03", "2025-02-27"
        ]),
        "revenue": [10, 20, 30, 40],
    })
    plan = _plan([{
        "id": "monthly_revenue",
        "operation_type": "time_series",
        "worksheet_name": "Sales",
        "title": "Monthly revenue trend",
        "description": "Sum revenue by calendar month.",
        "date_column": "order_date",
        "interval": "month",
        "metric": {
            "alias": "monthly_revenue",
            "function": "sum",
            "column": "revenue",
        },
        "group_by_columns": [],
    }], [{
        "id": "monthly_chart",
        "operation_id": "monthly_revenue",
        "chart_type": "line",
        "title": "Monthly revenue",
        "description": "Revenue aggregated by month.",
        "priority": "high",
    }])
    output = execute_analytics_plan({"Sales": frame}, plan)
    records = output["results"][0]["records"]
    assert records == [
        {"period": "2025-01", "monthly_revenue": 30},
        {"period": "2025-02", "monthly_revenue": 70},
    ]
    assert output["charts"][0]["chart_type"] == "line"
    assert [point["value"] for point in output["charts"][0]["data"]] == [30.0, 70.0]


def test_scalar_operation_calculates_kpi_deterministically():
    frame = pd.DataFrame({"revenue": [10, 20, None]})
    plan = _plan([{
        "id": "revenue_sum",
        "operation_type": "sum",
        "worksheet_name": "Sales",
        "title": "Total revenue",
        "description": "Sum revenue.",
        "result_name": "total_revenue",
        "column": "revenue",
    }])
    output = execute_analytics_plan({"Sales": frame}, plan)
    assert output["results"][0]["value"] == 30
    assert output["kpis"][-1]["value"] == 30


def test_monthly_intent_must_use_time_series_not_raw_date_grouping():
    import pytest
    from app.modules.analytics_planner.plan_validator import (
        AnalyticalPlanValidationError,
        validate_analytical_plan,
    )
    from app.schemas.data_understanding import DatasetProfile

    profile = DatasetProfile.model_validate({
        "filename": "sales.xlsx",
        "total_worksheet_count": 1,
        "successful_worksheet_count": 1,
        "failed_worksheet_count": 0,
        "worksheets": {
            "Sales": {
                "worksheet_name": "Sales", "row_count": 2, "column_count": 2,
                "columns": [
                    {
                        "column_name": "order_date", "original_name": "Order Date",
                        "pandas_dtype": "datetime64[ns]", "inferred_type": "date",
                        "semantic_role": "date", "non_null_count": 2,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 2,
                        "unique_value_percentage": 100,
                    },
                    {
                        "column_name": "revenue", "original_name": "Revenue",
                        "pandas_dtype": "int64", "inferred_type": "numerical",
                        "semantic_role": "amount", "non_null_count": 2,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 2,
                        "unique_value_percentage": 100,
                    },
                ],
            }
        },
    })
    plan = _plan([{
        "id": "monthly_revenue", "operation_type": "group_by",
        "worksheet_name": "Sales", "title": "Monthly revenue",
        "description": "Group revenue by month.",
        "group_by_columns": ["order_date"],
        "aggregations": [{
            "alias": "total_revenue", "function": "sum", "column": "revenue",
        }],
    }])
    with pytest.raises(AnalyticalPlanValidationError, match="time_series"):
        validate_analytical_plan(plan, profile)


def test_top_n_and_percentage_of_total_are_calculated_from_rows():
    frame = pd.DataFrame({
        "category": ["A", "A", "B", "C"],
        "revenue": [60, 40, 50, 50],
    })
    top_plan = _plan([{
        "id": "top_category", "operation_type": "top_n",
        "worksheet_name": "Sales", "title": "Top category",
        "description": "Rank categories by revenue.",
        "group_by_column": "category",
        "metric": {"alias": "revenue_sum", "function": "sum", "column": "revenue"},
        "limit": 2,
    }])
    top_result = execute_analytics_plan({"Sales": frame}, top_plan)
    assert top_result["results"][0]["records"] == [
        {"category": "A", "revenue_sum": 100},
        {"category": "B", "revenue_sum": 50},
    ]

    percentage_plan = _plan([{
        "id": "category_share", "operation_type": "percentage_of_total",
        "worksheet_name": "Sales", "title": "Revenue share",
        "description": "Calculate category share of revenue.",
        "category_column": "category",
        "value_column": "revenue",
        "result_name": "share_percent",
    }])
    percentage_result = execute_analytics_plan({"Sales": frame}, percentage_plan)
    shares = {
        row["category"]: row["share_percent"]
        for row in percentage_result["results"][0]["records"]
    }
    assert shares == {"A": 50.0, "B": 25.0, "C": 25.0}


def test_numeric_aggregations_coerce_numeric_text_and_ignore_infinity():
    frame = pd.DataFrame({
        "region": ["North", "South", "North", "South"],
        "revenue": ["10", "20", "inf", "30"],
    })
    plan = _plan([{
        "id": "revenue_by_region",
        "operation_type": "group_by",
        "worksheet_name": "Sales",
        "title": "Revenue by region",
        "description": "Sum valid numeric revenue by region.",
        "group_by_columns": ["region"],
        "aggregations": [{
            "alias": "total_revenue",
            "function": "sum",
            "column": "revenue",
        }],
    }])

    output = execute_analytics_plan({"Sales": frame}, plan)
    values = {row["region"]: row["total_revenue"] for row in output["results"][0]["records"]}
    assert values == {"North": 10, "South": 50}


def test_time_series_handles_mixed_timezone_date_values():
    frame = pd.DataFrame({
        "order_date": [
            "2025-01-02T09:00:00+05:30",
            "2025-01-20T10:00:00-04:00",
            "2025-02-03T12:00:00Z",
        ],
        "revenue": [10, 20, 30],
    })
    plan = _plan([{
        "id": "monthly_revenue",
        "operation_type": "time_series",
        "worksheet_name": "Sales",
        "title": "Monthly revenue",
        "description": "Sum revenue by month.",
        "date_column": "order_date",
        "interval": "month",
        "metric": {
            "alias": "monthly_revenue",
            "function": "sum",
            "column": "revenue",
        },
        "group_by_columns": [],
    }])

    output = execute_analytics_plan({"Sales": frame}, plan)
    assert output["results"][0]["records"] == [
        {"period": "2025-01", "monthly_revenue": 30},
        {"period": "2025-02", "monthly_revenue": 30},
    ]


def test_plan_can_validly_contain_no_operations_for_non_analytical_workbook():
    plan = _plan([])
    output = execute_analytics_plan({"Sales": pd.DataFrame({"notes": ["a", "b"]})}, plan)
    assert output["results"] == []
    assert output["charts"] == []
    assert output["kpis"][0]["value"] == 2
