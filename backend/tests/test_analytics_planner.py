"""Deterministic tests for Module 4 grounding and provider boundaries."""

import json

import pytest

from app.modules.analytics_planner.analytics_planner import AnalyticsPlanner
from app.modules.analytics_planner.errors import PlanSchemaValidationError
from app.modules.analytics_planner.plan_validator import (
    AnalyticalPlanValidationError,
    validate_analytical_plan,
)
from app.modules.analytics_planner.prompt_builder import AnalyticsPromptBuilder
from app.modules.analytics_planner.profile_preparation import DatasetProfilePreparer
from app.modules.analytics_planner.ollama_client import OllamaClient, OllamaResponseError
from app.schemas.analytics_plan import WorkbookAnalyticsPlan
from app.schemas.data_understanding import DatasetProfile


def make_profile() -> DatasetProfile:
    return DatasetProfile.model_validate({
        "filename": "sales.xlsx",
        "total_worksheet_count": 2,
        "successful_worksheet_count": 2,
        "failed_worksheet_count": 0,
        "worksheet_errors": {},
        "worksheets": {
            "Sales": {
                "worksheet_name": "Sales", "row_count": 3, "column_count": 2,
                "columns": [
                    {
                        "column_name": "order_id", "original_name": "Order ID",
                        "pandas_dtype": "int64", "inferred_type": "numerical",
                        "semantic_role": "identifier", "non_null_count": 3,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 3,
                        "unique_value_percentage": 100,
                    },
                    {
                        "column_name": "revenue", "original_name": "Revenue",
                        "pandas_dtype": "float64", "inferred_type": "numerical",
                        "semantic_role": "amount", "non_null_count": 3,
                        "missing_value_count": 0, "blank_string_count": 0,
                        "missing_percentage": 0, "unique_value_count": 3,
                        "unique_value_percentage": 100,
                        "numerical_statistics": {
                            "minimum": 10, "maximum": 30, "mean": 20,
                            "median": 20, "total": 60,
                            "standard_deviation": 10,
                        },
                    },
                ],
            },
            "Notes": {
                "worksheet_name": "Notes", "row_count": 2, "column_count": 1,
                "columns": [{
                    "column_name": "comment", "original_name": "Comment",
                    "pandas_dtype": "object", "inferred_type": "text",
                    "semantic_role": "text", "non_null_count": 2,
                    "missing_value_count": 0, "blank_string_count": 0,
                    "missing_percentage": 0, "unique_value_count": 2,
                    "unique_value_percentage": 100,
                }],
            },
        },
    })


def make_plan(*, worksheets=None, operations=None) -> WorkbookAnalyticsPlan:
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "A workbook containing sales and notes data.",
        "business_context": {
            "domain": "sales", "dataset_purpose": "Summarize recorded sales.",
            "confidence": 0.7,
        },
        "worksheet_analyses": worksheets if worksheets is not None else [
            {"worksheet_name": "Sales", "inferred_purpose": "Sales records",
             "summary": "Contains order identifiers and revenue values.",
             "analysis_focus": ["Revenue totals"]},
            {"worksheet_name": "Notes", "inferred_purpose": "Text notes",
             "summary": "Contains free-text comments.",
             "analysis_focus": []},
        ],
        "operations": operations if operations is not None else [{
            "id": "total_revenue", "operation_type": "sum",
            "worksheet_name": "Sales", "title": "Total revenue",
            "description": "Sum recorded revenue values.",
            "result_name": "total_revenue", "column": "revenue",
        }],
        "kpis": [], "visualizations": [],
        "key_questions": [], "limitations": [],
    })


def test_prompt_uses_preparation_metadata_and_normalized_column_contract():
    profile = make_profile()
    prepared = DatasetProfilePreparer().prepare(profile)
    messages = AnalyticsPromptBuilder().build_messages(prepared)
    system, user = messages
    assert "normalized execution identifier" in system["content"]
    assert "original_name is display metadata only" in system["content"]
    assert "PROFILE PREPARATION METADATA" in user["content"]
    assert "total" in user["content"]
    assert "sample_values_included" in user["content"]


def test_validator_requires_every_successfully_profiled_worksheet_once():
    profile = make_profile()
    plan = make_plan(worksheets=[{
        "worksheet_name": "Sales", "inferred_purpose": "Sales records",
        "summary": "Contains order identifiers and revenue values.",
        "analysis_focus": [],
    }])
    with pytest.raises(AnalyticalPlanValidationError, match="cover every"):
        validate_analytical_plan(plan, profile)


def test_validator_rejects_numeric_identifier_as_measure():
    profile = make_profile()
    plan = make_plan(operations=[{
        "id": "sum_ids", "operation_type": "sum",
        "worksheet_name": "Sales", "title": "Sum IDs",
        "description": "Sum identifier values.",
        "result_name": "sum_ids", "column": "order_id",
    }])
    with pytest.raises(AnalyticalPlanValidationError, match="identifier"):
        validate_analytical_plan(plan, profile)


def test_validator_rejects_duplicate_operations_with_different_ids_and_copy():
    profile = make_profile()
    base_op = {
        "operation_type": "sum", "worksheet_name": "Sales",
        "title": "Revenue total", "description": "Sum revenue.",
        "result_name": "revenue_total", "column": "revenue",
    }
    plan = make_plan(operations=[
        {"id": "sum_a", **base_op},
        {"id": "sum_b", **{**base_op, "title": "Overall revenue", "description": "Total revenue."}},
    ])
    with pytest.raises(AnalyticalPlanValidationError, match="duplicate analytical"):
        validate_analytical_plan(plan, profile)


def test_validator_accepts_grounded_plan():
    plan = make_plan()
    assert validate_analytical_plan(plan, make_profile()) is plan


def test_provider_neutral_injection_does_not_require_ollama_client():
    class FakeGenerator:
        def generate_plan(self, messages):
            assert len(messages) == 2
            return make_plan()

    planner = AnalyticsPlanner(plan_generator=FakeGenerator())
    result = planner.generate_plan(make_profile())
    assert isinstance(result, WorkbookAnalyticsPlan)
    assert result.operations[0].column == "revenue"


def test_profile_preparation_never_drops_columns_or_worksheets():
    profile = make_profile()
    prepared = DatasetProfilePreparer().prepare(profile)["profile"]
    assert set(prepared["worksheets"]) == {"Sales", "Notes"}
    assert [c["column_name"] for c in prepared["worksheets"]["Sales"]["columns"]] == [
        "order_id", "revenue"
    ]


def test_validator_rejects_unobserved_comparison_value_when_profile_is_complete():
    profile_data = make_profile().model_dump(mode="python")
    sales = profile_data["worksheets"]["Sales"]
    sales["columns"].append({
        "column_name": "region", "original_name": "Region",
        "pandas_dtype": "object", "inferred_type": "categorical",
        "semantic_role": "category", "non_null_count": 3,
        "missing_value_count": 0, "blank_string_count": 0,
        "missing_percentage": 0, "unique_value_count": 2,
        "unique_value_percentage": 66.7,
        "categorical_statistics": {
            "unique_category_count": 2,
            "most_frequent": [
                {"value": "North", "count": 2},
                {"value": "South", "count": 1},
            ],
        },
    })
    sales["column_count"] = 3
    sales["categorical_column_count"] = 1
    profile = DatasetProfile.model_validate(profile_data)
    plan = make_plan(operations=[{
        "id": "region_compare", "operation_type": "comparison",
        "worksheet_name": "Sales", "title": "Compare regions",
        "description": "Compare observed regional revenue.",
        "category_column": "region", "baseline_value": "North",
        "comparison_value": "West",
        "metric": {"alias": "revenue_sum", "function": "sum", "column": "revenue"},
    }])
    with pytest.raises(AnalyticalPlanValidationError, match="not observed"):
        validate_analytical_plan(plan, profile)


def test_ollama_client_rejects_truncated_generation(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "done": False,
                "done_reason": "length",
                "message": {"content": "{}"},
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.modules.analytics_planner.ollama_client.httpx.Client", FakeClient)
    client = OllamaClient()
    with pytest.raises(OllamaResponseError, match="(token limit|too large|context)"):
        client.generate_plan([{"role": "user", "content": "make a plan"}])


def test_validator_enforces_v1_recommendation_limits():
    profile = make_profile()
    op1 = {
        "id": "sum_a", "operation_type": "sum", "worksheet_name": "Sales",
        "title": "Revenue total", "description": "Sum revenue.",
        "result_name": "revenue_total", "column": "revenue",
    }
    op2 = {
        "id": "sum_b", "operation_type": "sum", "worksheet_name": "Sales",
        "title": "Revenue maximum", "description": "Maximum revenue.",
        "result_name": "revenue_max", "column": "revenue",
    }
    # Use distinct operation types/semantics so duplicate detection is not
    # the reason this is rejected.
    op2["operation_type"] = "max"
    plan = make_plan(operations=[op1, op2])
    plan.key_questions = ["Question one?", "Question two?", "Question three?"]
    with pytest.raises(AnalyticalPlanValidationError, match="at most 2 key questions"):
        validate_analytical_plan(plan, profile)


def test_provider_specific_failure_is_wrapped_by_provider_neutral_planner():
    from app.modules.analytics_planner.analytics_planner import AnalyticsPlanningError

    class BrokenGenerator:
        def generate_plan(self, messages):
            raise RuntimeError("provider-specific transport failure")

    planner = AnalyticsPlanner(plan_generator=BrokenGenerator())
    with pytest.raises(AnalyticsPlanningError, match="configured language-model provider"):
        planner.generate_plan(make_profile())


def test_prompt_uses_real_newlines_and_explicitly_forbids_invented_units():
    prepared = DatasetProfilePreparer().prepare(make_profile())
    messages = AnalyticsPromptBuilder().build_messages(prepared)
    user_prompt = messages[1]["content"]
    system_prompt = messages[0]["content"]

    assert "\n" in user_prompt  # Real line breaks are present.
    assert "\\n" not in user_prompt  # No literal backslash-n sequences.
    assert "NEVER add" in system_prompt
    assert "currency symbols/codes" in system_prompt
    assert "Correlation analysis is not supported" in system_prompt
    assert 'inferred_type' not in system_prompt or 'column_name' in system_prompt
    assert "NEVER use a numerical, date, identifier" in system_prompt


def test_validator_rejects_currency_symbol_without_unit_metadata():
    plan = make_plan()
    plan.worksheet_analyses[0].summary = "Revenue is recorded in $ values."
    with pytest.raises(AnalyticalPlanValidationError, match="currency marker"):
        validate_analytical_plan(plan, make_profile())


def test_validator_rejects_currency_kpi_format_without_unit_metadata():
    payload = make_plan().model_dump(mode="python")
    payload["kpis"] = [{
        "id": "revenue_kpi", "operation_id": "total_revenue",
        "label": "Revenue", "description": "Total revenue",
        "format_hint": "currency",
    }]
    plan = WorkbookAnalyticsPlan.model_validate(payload)
    with pytest.raises(AnalyticalPlanValidationError, match="currency formatting"):
        validate_analytical_plan(plan, make_profile())


def test_validator_rejects_unsupported_correlation_question():
    plan = make_plan()
    plan.key_questions = ["Does revenue correlate with order ID?"]
    with pytest.raises(AnalyticalPlanValidationError, match="Correlation questions"):
        validate_analytical_plan(plan, make_profile())


def test_ollama_defaults_match_the_verified_tuned_configuration():
    client = OllamaClient()
    assert client.timeout_seconds == 600
    assert client.context_length == 16384
    assert client.max_output_tokens == 2048
    assert client.temperature == 0.1


def test_validator_rejects_currency_code_without_unit_metadata():
    plan = make_plan()
    plan.worksheet_analyses[0].summary = "Revenue values are reported in USD."
    with pytest.raises(AnalyticalPlanValidationError, match="currency marker"):
        validate_analytical_plan(plan, make_profile())


def test_planner_retries_once_after_dataset_validation_failure():
    invalid = make_plan()
    invalid.worksheet_analyses[0].summary = "Revenue is reported in $ values."
    valid = make_plan()

    class CorrectingGenerator:
        def __init__(self):
            self.calls = []

        def generate_plan(self, messages):
            self.calls.append(messages)
            return invalid if len(self.calls) == 1 else valid

    generator = CorrectingGenerator()
    planner = AnalyticsPlanner(plan_generator=generator)
    result = planner.generate_plan(make_profile())

    assert result is valid
    assert len(generator.calls) == 2
    assert "Validation error" in generator.calls[1][-1]["content"]
    assert "categorical or boolean" in generator.calls[1][-1]["content"]
    # The repair request reuses the original profile but omits the bulky
    # previous assistant JSON to conserve the local model context window.
    assert len(generator.calls[1]) == 3
    assert all(message["role"] != "assistant" for message in generator.calls[1])


def test_planner_does_not_retry_more_than_once():
    invalid = make_plan()
    invalid.worksheet_analyses[0].summary = "Revenue is reported in $ values."

    class AlwaysInvalidGenerator:
        def __init__(self):
            self.calls = 0

        def generate_plan(self, messages):
            self.calls += 1
            return invalid

    generator = AlwaysInvalidGenerator()
    planner = AnalyticsPlanner(plan_generator=generator)
    with pytest.raises(AnalyticalPlanValidationError, match="currency marker"):
        planner.generate_plan(make_profile())
    assert generator.calls == 2


def test_comparison_schema_rejects_null_category_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_plan(operations=[{
            "id": "compare_regions",
            "operation_type": "comparison",
            "worksheet_name": "Sales",
            "title": "Compare regions",
            "description": "Compare two observed regions.",
            "category_column": "region",
            "baseline_value": None,
            "comparison_value": "North",
            "metric": {
                "alias": "revenue_sum",
                "function": "sum",
                "column": "revenue",
            },
        }])


def test_planner_retries_once_after_provider_neutral_schema_validation_error():
    valid = make_plan()
    invalid_output = '{"operations":[{"operation_type":"comparison"}]}'
    schema_errors = [{
        "type": "value_error",
        "loc": ["operations", 0, "comparison"],
        "msg": "baseline_value must be a non-null scalar value.",
    }]

    class CorrectingGenerator:
        def __init__(self):
            self.calls = []

        def generate_plan(self, messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise PlanSchemaValidationError(
                    "Invalid plan schema",
                    generated_output=invalid_output,
                    validation_errors=schema_errors,
                )
            return valid

    generator = CorrectingGenerator()
    result = AnalyticsPlanner(plan_generator=generator).generate_plan(make_profile())

    assert result is valid
    assert len(generator.calls) == 2
    retry_messages = generator.calls[1]
    assert retry_messages[-2] == {
        "role": "assistant",
        "content": invalid_output,
    }
    assert "baseline_value" in retry_messages[-1]["content"]
    assert "Do not use null" in retry_messages[-1]["content"]


def test_planner_does_not_retry_schema_validation_more_than_once():
    error = PlanSchemaValidationError(
        "Invalid plan schema",
        generated_output='{"invalid": true}',
        validation_errors=[{"loc": ["operations"], "msg": "invalid"}],
    )

    class AlwaysInvalidGenerator:
        def __init__(self):
            self.calls = 0

        def generate_plan(self, messages):
            self.calls += 1
            raise error

    from app.modules.analytics_planner.analytics_planner import AnalyticsPlanningError

    generator = AlwaysInvalidGenerator()
    with pytest.raises(AnalyticsPlanningError, match="still failed schema validation"):
        AnalyticsPlanner(plan_generator=generator).generate_plan(make_profile())
    assert generator.calls == 2


def test_ollama_client_rejects_prompt_that_cannot_fit_context_before_network_call(monkeypatch):
    client = OllamaClient(context_length=128, max_output_tokens=64)

    def unexpected_network_call(*args, **kwargs):
        raise AssertionError("Network must not be called for an oversized prompt.")

    monkeypatch.setattr("app.modules.analytics_planner.ollama_client.httpx.Client", unexpected_network_call)
    with pytest.raises(OllamaResponseError, match="too large"):
        client.generate_plan([{"role": "user", "content": "x" * 500}])


def test_empty_llm_plan_gets_deterministic_fallback_for_analytical_profile():
    profile = make_profile()
    empty_plan = make_plan(operations=[])
    empty_plan.kpis = []
    empty_plan.visualizations = []

    class EmptyPlanGenerator:
        def generate_plan(self, messages):
            return empty_plan

    result = AnalyticsPlanner(plan_generator=EmptyPlanGenerator()).generate_plan(profile)
    assert result.operations
    assert any(operation.operation_type == "average" for operation in result.operations)
    assert result.kpis
    # This fixture has no categorical dimension, so no chart is forced.
    assert result.visualizations == []
    assert any("fallback plan" in item.lower() for item in result.limitations)


def test_reference_worksheet_is_classified_and_never_used_for_fallback_operations():
    profile_data = make_profile().model_dump(mode="python")
    profile_data["worksheets"]["Test Guide"] = {
        "worksheet_name": "Test Guide", "row_count": 2, "column_count": 2,
        "columns": [
            {
                "column_name": "column", "original_name": "Column",
                "pandas_dtype": "object", "inferred_type": "categorical",
                "semantic_role": "category", "non_null_count": 2,
                "missing_value_count": 0, "blank_string_count": 0,
                "missing_percentage": 0, "unique_value_count": 2,
                "unique_value_percentage": 100,
            },
            {
                "column_name": "variation_issues",
                "original_name": "Intentionally introduced variations / issues",
                "pandas_dtype": "object", "inferred_type": "text",
                "semantic_role": "text", "non_null_count": 2,
                "missing_value_count": 0, "blank_string_count": 0,
                "missing_percentage": 0, "unique_value_count": 2,
                "unique_value_percentage": 100,
            },
        ],
    }
    profile_data["total_worksheet_count"] = 3
    profile_data["successful_worksheet_count"] = 3
    profile = DatasetProfile.model_validate(profile_data)

    from app.modules.analytics_planner.deterministic_plan import build_deterministic_fallback_plan
    from app.modules.analytics_planner.worksheet_classifier import classify_worksheet

    assert classify_worksheet("Test Guide", profile.worksheets["Test Guide"])["role"] == "reference"
    fallback = build_deterministic_fallback_plan(profile, make_plan(operations=[]))
    assert fallback is not None
    assert all(operation.worksheet_name != "Test Guide" for operation in fallback.operations)


def test_fallback_creates_grouped_chart_when_profile_has_safe_dimension():
    profile_data = make_profile().model_dump(mode="python")
    sales = profile_data["worksheets"]["Sales"]
    sales["columns"].append({
        "column_name": "region", "original_name": "Region",
        "pandas_dtype": "object", "inferred_type": "categorical",
        "semantic_role": "category", "non_null_count": 3,
        "missing_value_count": 0, "blank_string_count": 0,
        "missing_percentage": 0, "unique_value_count": 2,
        "unique_value_percentage": 66.7,
        "categorical_statistics": {
            "unique_category_count": 2,
            "most_frequent": [
                {"value": "North", "count": 2},
                {"value": "South", "count": 1},
            ],
        },
    })
    sales["column_count"] = 3
    sales["categorical_column_count"] = 1
    profile = DatasetProfile.model_validate(profile_data)
    empty_plan = make_plan(operations=[])

    class EmptyPlanGenerator:
        def generate_plan(self, messages):
            return empty_plan

    result = AnalyticsPlanner(plan_generator=EmptyPlanGenerator()).generate_plan(profile)
    grouped = next(operation for operation in result.operations if operation.operation_type == "group_by")
    assert grouped.group_by_columns == ["region"]
    assert result.visualizations[0].operation_id == grouped.id
    assert result.visualizations[0].chart_type == "bar"


def test_prepared_profile_exposes_worksheet_role_without_dropping_reference_sheet():
    prepared = DatasetProfilePreparer().prepare(make_profile())["profile"]
    assert prepared["worksheets"]["Sales"]["worksheet_role"] == "analytical"
    assert prepared["worksheets"]["Notes"]["worksheet_role"] == "insufficient"
    assert set(prepared["worksheets"]) == {"Sales", "Notes"}
