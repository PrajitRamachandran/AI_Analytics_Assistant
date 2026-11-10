
"""Temporary end-to-end inference test for Module 4."""

import json

from app.schemas.data_understanding import DatasetProfile
from app.modules.analytics_planner.analytics_planner import AnalyticsPlanner


def create_sample_profile() -> DatasetProfile:
    """Create a realistic in-memory sales dataset profile."""

    profile_data = {
        "filename": "sample_sales.xlsx",
        "total_worksheet_count": 1,
        "successful_worksheet_count": 1,
        "failed_worksheet_count": 0,
        "worksheet_errors": {},
        "worksheets": {
            "Sales": {
                "worksheet_name": "Sales",
                "row_count": 120,
                "column_count": 5,
                "duplicate_row_count": 0,
                "numerical_column_count": 2,
                "categorical_column_count": 2,
                "date_column_count": 1,
                "text_column_count": 0,
                "boolean_column_count": 0,
                "other_column_count": 0,
                "total_missing_value_count": 0,
                "total_blank_string_count": 0,
                "columns": [
                    {
                        "column_name": "Order_Date",
                        "original_name": "Order Date",
                        "pandas_dtype": "datetime64[ns]",
                        "inferred_type": "date",
                        "semantic_role": "date",
                        "non_null_count": 120,
                        "missing_value_count": 0,
                        "blank_string_count": 0,
                        "missing_percentage": 0,
                        "unique_value_count": 90,
                        "unique_value_percentage": 75,
                        "date_statistics": {
                            "earliest": "2025-01-01",
                            "latest": "2025-03-31",
                        },
                    },
                    {
                        "column_name": "Region",
                        "original_name": "Region",
                        "pandas_dtype": "object",
                        "inferred_type": "categorical",
                        "semantic_role": "category",
                        "non_null_count": 120,
                        "missing_value_count": 0,
                        "blank_string_count": 0,
                        "missing_percentage": 0,
                        "unique_value_count": 4,
                        "unique_value_percentage": 3.33,
                        "categorical_statistics": {
                            "unique_category_count": 4,
                            "most_frequent": [
                                {"value": "North", "count": 35},
                                {"value": "South", "count": 32},
                                {"value": "East", "count": 28},
                                {"value": "West", "count": 25},
                            ],
                        },
                    },
                    {
                        "column_name": "Product_Category",
                        "original_name": "Product Category",
                        "pandas_dtype": "object",
                        "inferred_type": "categorical",
                        "semantic_role": "category",
                        "non_null_count": 120,
                        "missing_value_count": 0,
                        "blank_string_count": 0,
                        "missing_percentage": 0,
                        "unique_value_count": 4,
                        "unique_value_percentage": 3.33,
                        "categorical_statistics": {
                            "unique_category_count": 4,
                            "most_frequent": [
                                {"value": "Electronics", "count": 40},
                                {"value": "Furniture", "count": 30},
                                {"value": "Clothing", "count": 28},
                                {"value": "Accessories", "count": 22},
                            ],
                        },
                    },
                    {
                        "column_name": "Revenue",
                        "original_name": "Revenue",
                        "pandas_dtype": "float64",
                        "inferred_type": "numerical",
                        "semantic_role": "amount",
                        "non_null_count": 120,
                        "missing_value_count": 0,
                        "blank_string_count": 0,
                        "missing_percentage": 0,
                        "unique_value_count": 115,
                        "unique_value_percentage": 95.83,
                        "numerical_statistics": {
                            "minimum": 250,
                            "maximum": 15000,
                            "mean": 4250,
                            "median": 3800,
                            "total": 510000,
                            "standard_deviation": 2200,
                        },
                    },
                    {
                        "column_name": "Quantity",
                        "original_name": "Quantity",
                        "pandas_dtype": "int64",
                        "inferred_type": "numerical",
                        "semantic_role": "quantity",
                        "non_null_count": 120,
                        "missing_value_count": 0,
                        "blank_string_count": 0,
                        "missing_percentage": 0,
                        "unique_value_count": 15,
                        "unique_value_percentage": 12.5,
                        "numerical_statistics": {
                            "minimum": 1,
                            "maximum": 20,
                            "mean": 6.5,
                            "median": 6,
                            "total": 780,
                            "standard_deviation": 3.2,
                        },
                    },
                ],
            }
        },
    }

    return DatasetProfile.model_validate(profile_data)


def main() -> None:
    print("=" * 60)
    print("MODULE 4 - REAL QWEN INFERENCE TEST")
    print("=" * 60)

    profile = create_sample_profile()

    print("\n[1/3] Sample DatasetProfile created successfully.")

    planner = AnalyticsPlanner()

    print("[2/3] Sending profile to Ollama...")
    print("Model: qwen3.5:4b")
    print("Please wait. Local inference may take some time.\n")

    plan = planner.generate_plan(profile)

    print("[3/3] Analytics plan generated and validated!")
    print("\n" + "=" * 60)
    print("GENERATED ANALYTICS PLAN")
    print("=" * 60)

    print(
        json.dumps(
            plan.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n" + "=" * 60)
    print("INFERENCE TEST: SUCCESS")
    print("=" * 60)


if __name__ == "__main__":
    main()
