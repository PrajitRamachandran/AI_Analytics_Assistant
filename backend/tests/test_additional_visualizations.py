import pandas as pd

from app.schemas.analytics_plan import HistogramOperation, ScatterOperation
from app.modules.analytics_execution import execute_operation, _chart_from_result, execute_analytics_plan


def test_histogram_operation_builds_histogram_chart():
    frames = {"Sales": pd.DataFrame({"Revenue": [100, 200, 300, 400, 500]})}
    operation = HistogramOperation(
        id="op_histogram",
        operation_type="histogram",
        worksheet_name="Sales",
        title="Revenue distribution",
        description="Distribution of revenue values",
        column="Revenue",
        bins=3,
    )

    result = execute_operation(frames, operation)
    chart = _chart_from_result(operation, result)

    assert chart is not None
    assert chart["chart_type"] == "histogram"
    assert len(chart["data"]) == 3
    assert sum(point["value"] for point in chart["data"]) == 5


def test_scatter_operation_builds_numeric_pairs():
    frames = {
        "Sales": pd.DataFrame({
            "Quantity": [1, 2, 2, 3, 4],
            "Revenue": [100, 200, 220, 300, 400],
        })
    }
    operation = ScatterOperation(
        id="op_scatter",
        operation_type="scatter",
        worksheet_name="Sales",
        title="Quantity vs revenue",
        description="Paired quantity and revenue observations",
        x_column="Quantity",
        y_column="Revenue",
    )

    result = execute_operation(frames, operation)
    chart = _chart_from_result(operation, result)

    assert chart is not None
    assert chart["chart_type"] == "scatter"
    assert len(chart["scatter_data"]) == 5
    assert chart["scatter_data"][0] == {"x": 1.0, "y": 100.0}


def test_scatter_sampling_is_deterministic():
    frames = {
        "Sales": pd.DataFrame({
            "x": range(100),
            "y": range(100, 200),
        })
    }
    operation = ScatterOperation(
        id="op_scatter_sampled",
        operation_type="scatter",
        worksheet_name="Sales",
        title="x vs y",
        description="Paired observations",
        x_column="x",
        y_column="y",
        sample_limit=10,
    )

    first = execute_operation(frames, operation)["records"]
    second = execute_operation(frames, operation)["records"]
    assert first == second
    assert len(first) == 10


def test_row_level_max_min_are_not_mislabelled_as_category_performance_kpis():
    from app.schemas.analytics_plan import WorkbookAnalyticsPlan

    plan = WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "Regional sales summary.",
        "business_context": {
            "domain": "sales",
            "dataset_purpose": "Compare regional revenue.",
            "confidence": 0.8,
        },
        "worksheet_analyses": [{
            "worksheet_name": "Sales",
            "inferred_purpose": "Sales transactions",
            "summary": "Regional revenue records.",
            "analysis_focus": ["Revenue by region"],
        }],
        "operations": [
            {
                "id": "total_revenue",
                "operation_type": "sum",
                "worksheet_name": "Sales",
                "title": "Overall Total Revenue",
                "description": "Total revenue across all rows.",
                "result_name": "total_revenue",
                "column": "revenue",
            },
            {
                "id": "region_totals",
                "operation_type": "group_by",
                "worksheet_name": "Sales",
                "title": "Revenue by region",
                "description": "Sum revenue for each region.",
                "group_by_columns": ["region"],
                "aggregations": [{
                    "alias": "total_revenue",
                    "function": "sum",
                    "column": "revenue",
                }],
            },
            {
                "id": "max_revenue",
                "operation_type": "max",
                "worksheet_name": "Sales",
                "title": "Highest Performing Region Revenue",
                "description": "Maximum individual revenue value.",
                "result_name": "max_revenue",
                "column": "revenue",
            },
            {
                "id": "min_revenue",
                "operation_type": "min",
                "worksheet_name": "Sales",
                "title": "Lowest Performing Region Revenue",
                "description": "Minimum individual revenue value.",
                "result_name": "min_revenue",
                "column": "revenue",
            },
        ],
        "kpis": [],
        "visualizations": [],
        "key_questions": [],
        "limitations": [],
    })
    output = execute_analytics_plan({
        "Sales": pd.DataFrame({
            "region": ["East", "East", "West", "West"],
            "revenue": [260000, 235010, 1710, 80520],
        })
    }, plan)
    labels = [item["label"] for item in output["kpis"]]
    assert "Overall Total Revenue" in labels
    high = next(item for item in output["kpis"] if item["id"] == "operation_max_revenue")
    low = next(item for item in output["kpis"] if item["id"] == "operation_min_revenue")
    assert high["value"] == 495010
    assert "(East)" in high["label"]
    assert low["value"] == 82230
    assert "(West)" in low["label"]
