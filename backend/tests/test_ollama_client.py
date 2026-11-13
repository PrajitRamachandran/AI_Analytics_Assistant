"""Regression tests for conservative Ollama plan payload normalization."""

from app.modules.analytics_planner.ollama_client import _normalize_plan_payload


def test_discards_placeholder_date_filters_without_rejecting_entire_plan():
    payload = {
        "filters": [
            {"worksheet_name": "Sales", "column": "Order Date",
             "start_date": "N/A", "end_date": "N/A"},
            {"worksheet_name": "Sales", "column": "Order Date",
             "start_date": "2026-01-01", "end_date": "2026-12-31"},
        ]
    }

    result = _normalize_plan_payload(payload)

    assert result["filters"] == [payload["filters"][1]]


def test_discards_scatter_with_identical_axes_and_its_visualization():
    payload = {
        "operations": [
            {"id": "bad_scatter", "operation_type": "scatter",
             "x_column": "revenue", "y_column": "revenue"},
            {"id": "good_scatter", "operation_type": "scatter",
             "x_column": "units", "y_column": "revenue"},
        ],
        "visualizations": [
            {"id": "viz_bad", "operation_id": "bad_scatter"},
            {"id": "viz_good", "operation_id": "good_scatter"},
        ],
    }

    result = _normalize_plan_payload(payload)

    assert [op["id"] for op in result["operations"]] == ["good_scatter"]
    assert [viz["id"] for viz in result["visualizations"]] == ["viz_good"]


def test_leaves_non_dict_payload_unchanged():
    assert _normalize_plan_payload([]) == []
