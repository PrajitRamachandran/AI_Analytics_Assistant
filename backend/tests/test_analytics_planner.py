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


def _fail_validation_times(monkeypatch, failures):
    """Make the planner's dataset validation fail ``failures`` times."""
    from app.modules.analytics_planner import analytics_planner as planner_module

    real = planner_module.validate_analytical_plan
    state = {"calls": 0}

    def flaky(plan, profile):
        state["calls"] += 1
        if failures is None or state["calls"] <= failures:
            raise AnalyticalPlanValidationError(
                "Column 'region' must be a categorical or boolean column."
            )
        return real(plan, profile)

    monkeypatch.setattr(planner_module, "validate_analytical_plan", flaky)
    return state


def test_planner_retries_once_after_dataset_validation_failure(monkeypatch):
    valid = make_plan()
    _fail_validation_times(monkeypatch, failures=1)

    class CorrectingGenerator:
        def __init__(self):
            self.calls = []

        def generate_plan(self, messages):
            self.calls.append(messages)
            return valid

    generator = CorrectingGenerator()
    planner = AnalyticsPlanner(plan_generator=generator)
    result = planner.generate_plan(make_profile())

    assert result.operations[0].id == "total_revenue"
    assert len(generator.calls) == 2
    assert "Validation error" in generator.calls[1][-1]["content"]
    assert "categorical or boolean" in generator.calls[1][-1]["content"]
    # The repair request reuses the original profile but omits the bulky
    # previous assistant JSON to conserve the local model context window.
    assert len(generator.calls[1]) == 3
    assert all(message["role"] != "assistant" for message in generator.calls[1])


def test_planner_does_not_retry_more_than_once(monkeypatch):
    # Validation fails every time, including for the deterministic salvage
    # plan, so the original error must still surface after exactly one retry.
    from app.modules.analytics_planner import plan_sanitizer

    _fail_validation_times(monkeypatch, failures=None)
    monkeypatch.setattr(
        plan_sanitizer, "validate_analytical_plan",
        lambda plan, profile: (_ for _ in ()).throw(
            AnalyticalPlanValidationError("still invalid")
        ),
    )

    class AlwaysInvalidGenerator:
        def __init__(self):
            self.calls = 0

        def generate_plan(self, messages):
            self.calls += 1
            return make_plan()

    generator = AlwaysInvalidGenerator()
    planner = AnalyticsPlanner(plan_generator=generator)
    with pytest.raises(AnalyticalPlanValidationError, match="categorical or boolean"):
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

    assert result.operations[0].id == "total_revenue"
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
    # A numeric-only worksheet still supports a distribution chart.
    assert any(item.chart_type == "histogram" for item in result.visualizations)
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
    # Record counts over two categories are a part-to-whole view.
    assert result.visualizations[0].chart_type == "pie"


def test_prepared_profile_exposes_worksheet_role_without_dropping_reference_sheet():
    prepared = DatasetProfilePreparer().prepare(make_profile())["profile"]
    assert prepared["worksheets"]["Sales"]["worksheet_role"] == "analytical"
    assert prepared["worksheets"]["Notes"]["worksheet_role"] == "insufficient"
    assert set(prepared["worksheets"]) == {"Sales", "Notes"}


# ---------------------------------------------------------------------------
# KPI -> scalar operation linkage
# ---------------------------------------------------------------------------

def _kpi_plan_payload(operations, kpis):
    payload = make_plan().model_dump(mode="json")
    payload["operations"] = operations
    payload["kpis"] = kpis
    return payload


def _group_by_revenue(op_id="op_1", aggregations=None):
    return {
        "id": op_id, "operation_type": "group_by", "worksheet_name": "Sales",
        "title": "Revenue by region", "description": "Revenue per region.",
        "group_by_columns": ["region"],
        "aggregations": aggregations or [
            {"alias": "total_revenue", "function": "sum", "column": "revenue"},
        ],
    }


def _kpi(kpi_id="kpi1", operation_id="op_1"):
    return {
        "id": kpi_id, "operation_id": operation_id, "label": "Total revenue",
        "description": "Sum of revenue.", "format_hint": "number",
        "priority": "high",
    }


def _profile_with_region() -> DatasetProfile:
    data = make_profile().model_dump(mode="json")
    sales = data["worksheets"]["Sales"]
    sales["columns"].append({
        "column_name": "region", "original_name": "Region",
        "pandas_dtype": "object", "inferred_type": "categorical",
        "semantic_role": "category", "non_null_count": 3,
        "missing_value_count": 0, "blank_string_count": 0,
        "missing_percentage": 0, "unique_value_count": 2,
        "unique_value_percentage": 66.7,
    })
    sales["column_count"] = len(sales["columns"])
    return DatasetProfile.model_validate(data)


def test_kpi_on_single_metric_group_by_gets_explicit_scalar_operation():
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload([_group_by_revenue()], [_kpi()])
    )

    assert [op.operation_type for op in plan.operations] == ["group_by", "sum"]
    derived = plan.operations[1]
    assert plan.kpis[0].operation_id == derived.id == "kpi1_overall"
    assert (derived.worksheet_name, derived.column) == ("Sales", "revenue")
    assert derived.result_name == "total_revenue"

    # The repaired plan is itself a valid plan (round-trips and passes the
    # dataset validator), so downstream execution sees an ordinary scalar KPI.
    WorkbookAnalyticsPlan.model_validate(plan.model_dump(mode="json"))
    validate_analytical_plan(plan, _profile_with_region())


def test_kpi_reuses_equivalent_existing_scalar_operation():
    existing = {
        "id": "total_revenue", "operation_type": "sum",
        "worksheet_name": "Sales", "title": "Total revenue",
        "description": "Sum revenue.", "result_name": "total_revenue",
        "column": "revenue",
    }
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload([_group_by_revenue(), existing], [_kpi()])
    )

    assert len(plan.operations) == 2
    assert plan.kpis[0].operation_id == "total_revenue"


def test_two_kpis_on_same_metric_share_one_derived_operation():
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload(
            [_group_by_revenue()], [_kpi("kpi1"), _kpi("kpi2")],
        )
    )

    assert len(plan.operations) == 2
    assert plan.kpis[0].operation_id == plan.kpis[1].operation_id
    validate_analytical_plan(plan, _profile_with_region())


def test_kpi_on_time_series_uses_its_metric():
    series = {
        "id": "trend", "operation_type": "time_series",
        "worksheet_name": "Sales", "title": "Trend", "description": "Trend.",
        "date_column": "order_date", "interval": "month",
        "metric": {"alias": "avg_revenue", "function": "average",
                   "column": "revenue"},
    }
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload([series], [_kpi(operation_id="trend")])
    )

    # The KPI label ("Total revenue") names the function, so it wins over the
    # chart's own average metric; the column is the one the chart reports.
    derived = plan.operations[-1]
    assert derived.operation_type == "sum" and derived.column == "revenue"
    assert plan.kpis[0].operation_id == derived.id


def test_kpi_on_ambiguous_non_scalar_operation_is_still_rejected():
    from pydantic import ValidationError

    two_columns = _group_by_revenue(aggregations=[
        {"alias": "total_revenue", "function": "sum", "column": "revenue"},
        {"alias": "total_cost", "function": "sum", "column": "cost"},
    ])
    vague_kpi = dict(_kpi(), label="Headline figure")
    with pytest.raises(
        ValidationError,
        match=r"KPI 'kpi1' must reference a scalar operation\.",
    ):
        WorkbookAnalyticsPlan.model_validate(
            _kpi_plan_payload([two_columns], [vague_kpi])
        )

    two_regions = {
        "id": "op_1", "operation_type": "comparison",
        "worksheet_name": "Sales", "title": "Compare", "description": "Cmp.",
        "category_column": "region", "baseline_value": "North",
        "comparison_value": "South",
        "metric": {"alias": "revenue_sum", "function": "sum",
                   "column": "revenue"},
    }
    # No column and no function named by the KPI text, but a single metric:
    # the comparison's measure is unambiguous, so this one is linked.
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload([two_regions], [vague_kpi])
    )
    assert plan.operations[-1].operation_type == "sum"


def _payroll_plan(kpi_id, kpi_label, source):
    return WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload(
            [source],
            [dict(_kpi(kpi_id, source["id"]), label=kpi_label)],
        )
    )


def test_kpi_picks_measure_named_by_its_id_from_multi_metric_group_by():
    source = _group_by_revenue(aggregations=[
        {"alias": "avg_gross_salary", "function": "average",
         "column": "gross_salary"},
        {"alias": "avg_net_salary", "function": "average",
         "column": "net_salary"},
        {"alias": "headcount", "function": "count", "column": None},
    ])
    plan = _payroll_plan("kpi_avg_gross_salary", "Average gross salary", source)

    derived = plan.operations[-1]
    assert plan.kpis[0].operation_id == derived.id
    assert (derived.operation_type, derived.column) == ("average", "gross_salary")


def test_kpi_on_top_n_uses_function_and_column_from_kpi_text():
    top_n = {
        "id": "top_depts", "operation_type": "top_n",
        "worksheet_name": "Sales", "title": "Top departments",
        "description": "Top departments.", "group_by_column": "region",
        "limit": 5,
        "metric": {"alias": "total_gross_salary", "function": "sum",
                   "column": "gross_salary"},
    }
    plan = _payroll_plan("kpi_avg_gross_salary", "Average gross salary", top_n)

    derived = plan.operations[-1]
    assert (derived.operation_type, derived.column) == ("average", "gross_salary")


def test_kpi_on_percentage_of_total_derives_total_of_value_column():
    pct = {
        "id": "share", "operation_type": "percentage_of_total",
        "worksheet_name": "Sales", "title": "Share", "description": "Share.",
        "category_column": "region", "value_column": "revenue",
    }
    plan = _payroll_plan("kpi_total_revenue", "Total revenue", pct)

    derived = plan.operations[-1]
    assert (derived.operation_type, derived.column) == ("sum", "revenue")


def test_kpi_repair_never_exceeds_operation_limit():
    from pydantic import ValidationError

    operations = [_group_by_revenue()] + [
        {
            "id": f"max_{i}", "operation_type": "max",
            "worksheet_name": "Sales", "title": f"Max {i}",
            "description": "Max.", "result_name": f"max_{i}",
            "column": f"col_{i}",
        }
        for i in range(11)
    ]
    with pytest.raises(ValidationError, match="must reference a scalar"):
        WorkbookAnalyticsPlan.model_validate(
            _kpi_plan_payload(operations, [_kpi()])
        )


def test_kpi_on_scalar_operation_is_left_untouched():
    plan = WorkbookAnalyticsPlan.model_validate(
        _kpi_plan_payload(
            [{
                "id": "total_revenue", "operation_type": "sum",
                "worksheet_name": "Sales", "title": "Total revenue",
                "description": "Sum revenue.", "result_name": "total_revenue",
                "column": "revenue",
            }],
            [_kpi(operation_id="total_revenue")],
        )
    )

    assert len(plan.operations) == 1
    assert plan.kpis[0].operation_id == "total_revenue"


def test_ollama_client_accepts_kpi_linked_to_group_by_without_schema_error(monkeypatch):
    payload = _kpi_plan_payload([_group_by_revenue()], [_kpi()])

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "done": True, "done_reason": "stop",
                "message": {"content": json.dumps(payload)},
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

    monkeypatch.setattr(
        "app.modules.analytics_planner.ollama_client.httpx.Client", FakeClient
    )
    plan = OllamaClient().generate_plan(
        [{"role": "user", "content": "make a plan"}]
    )

    assert plan.kpis[0].operation_id == "kpi1_overall"


def test_schema_correction_prompt_explains_how_to_link_kpis_to_scalars():
    error = PlanSchemaValidationError(
        "Invalid plan schema",
        generated_output="{}",
        validation_errors=[{
            "type": "value_error", "loc": (),
            "msg": "Value error, KPI 'kpi1' must reference a scalar operation.",
        }],
    )

    class FailsOnceGenerator:
        def __init__(self):
            self.calls = []

        def generate_plan(self, messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise error
            return make_plan()

    generator = FailsOnceGenerator()
    AnalyticsPlanner(plan_generator=generator).generate_plan(make_profile())

    retry = generator.calls[1][-1]["content"]
    assert "KPI 'kpi1' must reference a scalar operation" in retry
    assert "add one for the same worksheet and column" in retry


# ---------------------------------------------------------------------------
# Plan sanitizing, deterministic chart top-up and salvage
# ---------------------------------------------------------------------------

def _col(name, inferred, role, *, unique=4, stats=None):
    column = {
        "column_name": name, "original_name": name.replace("_", " ").title(),
        "pandas_dtype": "object", "inferred_type": inferred,
        "semantic_role": role, "non_null_count": 20,
        "missing_value_count": 0, "blank_string_count": 0,
        "missing_percentage": 0, "unique_value_count": unique,
        "unique_value_percentage": unique * 5,
    }
    if stats:
        column["numerical_statistics"] = stats
    return column


def payroll_profile() -> DatasetProfile:
    stats = {"minimum": 10, "maximum": 90, "mean": 50, "median": 50,
             "total": 1000, "standard_deviation": 5}
    columns = [
        _col("employee_id", "numerical", "identifier", unique=20),
        _col("department", "categorical", "category", unique=4),
        _col("region", "categorical", "category", unique=3),
        _col("join_date", "date", "date", unique=15),
        _col("gross_salary", "numerical", "amount", unique=18, stats=stats),
    ]
    return DatasetProfile.model_validate({
        "filename": "payroll.xlsx", "total_worksheet_count": 1,
        "successful_worksheet_count": 1, "failed_worksheet_count": 0,
        "worksheet_errors": {},
        "worksheets": {"Payroll": {
            "worksheet_name": "Payroll", "row_count": 20,
            "column_count": len(columns), "columns": columns,
        }},
    })


def payroll_plan(*, operations, kpis=(), visualizations=()):
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0",
        "workbook_summary": "Payroll of 20 employees, salary around $50.",
        "business_context": {"domain": "HR", "dataset_purpose": "Payroll review.",
                             "confidence": 0.6},
        "worksheet_analyses": [{
            "worksheet_name": "Payroll", "inferred_purpose": "Payroll records",
            "summary": "Employees with gross salary in USD.",
            "analysis_focus": ["Salary by department"],
        }],
        "operations": list(operations), "kpis": list(kpis),
        "visualizations": list(visualizations),
        "key_questions": ["Which department has the highest salary?"],
        "limitations": [],
    })


def _payroll_ops():
    return [
        {"id": "avg_salary", "operation_type": "average",
         "worksheet_name": "Payroll", "title": "Average salary",
         "description": "Mean gross salary.", "result_name": "avg_salary",
         "column": "gross_salary"},
        {"id": "salary_by_dept", "operation_type": "group_by",
         "worksheet_name": "Payroll", "title": "Salary by department",
         "description": "Average salary per department.",
         "group_by_columns": ["department"],
         "aggregations": [{"alias": "avg_salary", "function": "average",
                           "column": "gross_salary"}]},
    ]


def _payroll_kpi(**overrides):
    kpi = {"id": "kpi_avg_gross_salary", "operation_id": "avg_salary",
           "label": "Average gross salary", "description": "Mean salary in $.",
           "format_hint": "currency", "priority": "high"}
    kpi.update(overrides)
    return kpi


def _payroll_viz(viz_id="v1", operation_id="salary_by_dept", chart_type="bar"):
    return {"id": viz_id, "operation_id": operation_id,
            "chart_type": chart_type, "title": "Salary by department",
            "description": "Average salary by department.", "priority": "high"}


def test_sanitizer_replaces_currency_format_and_strips_unsupported_symbols():
    from app.modules.analytics_planner.plan_sanitizer import sanitize_plan

    plan = payroll_plan(operations=_payroll_ops(), kpis=[_payroll_kpi()])
    cleaned = sanitize_plan(plan, payroll_profile())

    assert cleaned.kpis[0].format_hint == "decimal"
    assert "$" not in cleaned.kpis[0].description
    assert "USD" not in cleaned.worksheet_analyses[0].summary
    assert "$" not in cleaned.workbook_summary
    assert plan.kpis[0].format_hint == "currency"  # input is not mutated
    validate_analytical_plan(cleaned, payroll_profile())


def test_sanitizer_drops_operations_that_do_not_fit_the_dataset():
    from app.modules.analytics_planner.plan_sanitizer import sanitize_plan

    bad_group = dict(_payroll_ops()[1], id="by_salary",
                     group_by_columns=["gross_salary"])
    missing_col = dict(_payroll_ops()[0], id="avg_bonus", column="bonus")
    plan = payroll_plan(
        operations=[*_payroll_ops(), bad_group, missing_col],
        kpis=[_payroll_kpi(), _payroll_kpi(id="kpi_bonus", operation_id="avg_bonus")],
        visualizations=[_payroll_viz(), _payroll_viz("v2", "by_salary")],
    )
    cleaned = sanitize_plan(plan, payroll_profile())

    assert [op.id for op in cleaned.operations] == ["avg_salary", "salary_by_dept"]
    assert [kpi.id for kpi in cleaned.kpis] == ["kpi_avg_gross_salary"]
    assert [viz.id for viz in cleaned.visualizations] == ["v1"]
    validate_analytical_plan(cleaned, payroll_profile())


def test_sanitizer_repairs_incompatible_and_duplicate_charts():
    from app.modules.analytics_planner.plan_sanitizer import sanitize_plan

    plan = payroll_plan(
        operations=_payroll_ops(),
        visualizations=[
            _payroll_viz("v1", chart_type="scatter"),   # -> bar
            _payroll_viz("v2", chart_type="bar"),       # duplicate of v1
            _payroll_viz("v3", chart_type="line"),      # -> bar, duplicate
            _payroll_viz("v4", chart_type="pie"),
        ],
    )
    cleaned = sanitize_plan(plan, payroll_profile())

    assert [(v.id, v.chart_type) for v in cleaned.visualizations] == [
        ("v1", "bar"), ("v4", "pie"),
    ]
    validate_analytical_plan(cleaned, payroll_profile())


def test_sanitizer_drops_unsupported_correlation_questions():
    from app.modules.analytics_planner.plan_sanitizer import sanitize_plan

    plan = payroll_plan(operations=_payroll_ops())
    plan.key_questions = ["Is salary correlated with tenure?", "Who earns most?"]
    cleaned = sanitize_plan(plan, payroll_profile())

    assert cleaned.key_questions == ["Who earns most?"]


def test_augmentation_adds_multiple_valid_charts_to_a_thin_plan():
    from app.modules.analytics_planner.plan_sanitizer import (
        augment_with_deterministic_charts, sanitize_plan,
    )

    profile = payroll_profile()
    plan = sanitize_plan(
        payroll_plan(
            operations=_payroll_ops(), kpis=[_payroll_kpi()],
            visualizations=[_payroll_viz()],
        ),
        profile,
    )

    result = augment_with_deterministic_charts(plan, profile)

    assert len(result.visualizations) >= 4
    assert len({v.id for v in result.visualizations}) == len(result.visualizations)
    assert result.visualizations[0].id == "v1"  # the model's own chart is kept
    validate_analytical_plan(result, profile)


def test_augmentation_leaves_plans_that_already_meet_the_target_unchanged():
    from app.modules.analytics_planner.plan_sanitizer import (
        augment_with_deterministic_charts, sanitize_plan,
    )

    profile = payroll_profile()
    plan = sanitize_plan(
        payroll_plan(operations=_payroll_ops(), visualizations=[_payroll_viz()]),
        profile,
    )
    assert augment_with_deterministic_charts(plan, profile, 1) is plan


class _OneShotGenerator:
    def __init__(self, plan):
        self.plan, self.calls = plan, 0

    def generate_plan(self, messages):
        self.calls += 1
        return self.plan


def test_planner_turns_currency_kpi_and_scatter_chart_into_valid_multi_chart_plan():
    # Reproduces the reported failure: KPI 'kpi_avg_gross_salary' with a
    # currency format on a profile that has no currency metadata.
    profile = payroll_profile()
    plan = payroll_plan(
        operations=_payroll_ops(), kpis=[_payroll_kpi()],
        visualizations=[_payroll_viz(chart_type="scatter")],
    )
    generator = _OneShotGenerator(plan)

    result = AnalyticsPlanner(plan_generator=generator).generate_plan(profile)

    assert generator.calls == 1            # no wasted correction round-trip
    assert result.kpis[0].format_hint == "decimal"
    assert len(result.visualizations) >= 4
    assert {v.chart_type for v in result.visualizations} >= {"bar", "line"}
    validate_analytical_plan(result, profile)


def test_planner_uses_deterministic_plan_when_final_validation_still_fails(monkeypatch):
    profile = payroll_profile()
    state = _fail_validation_times(monkeypatch, failures=2)
    generator = _OneShotGenerator(payroll_plan(operations=_payroll_ops()))

    result = AnalyticsPlanner(plan_generator=generator).generate_plan(profile)

    assert generator.calls == 2 and state["calls"] >= 2
    assert any(op.id.startswith("fallback_") for op in result.operations)
    assert result.visualizations
    validate_analytical_plan(result, profile)


def test_planner_output_executes_into_multiple_charts():
    import pandas as pd

    from app.modules.analytics_execution import execute_analytics_plan

    profile = payroll_profile()
    plan = payroll_plan(
        operations=_payroll_ops(), kpis=[_payroll_kpi()],
        visualizations=[_payroll_viz(chart_type="scatter")],
    )
    result = AnalyticsPlanner(plan_generator=_OneShotGenerator(plan)).generate_plan(profile)

    frame = pd.DataFrame({
        "employee_id": range(1, 9),
        "department": ["HR", "IT", "HR", "Ops"] * 2,
        "region": ["N", "S"] * 4,
        "join_date": pd.date_range("2024-01-01", periods=8, freq="MS"),
        "gross_salary": [10, 20, 30, 40, 50, 60, 70, 80],
    })
    execution = execute_analytics_plan({"Payroll": frame}, result)

    assert len(execution["charts"]) >= 4
    assert all(chart.get("data") or chart.get("points") or chart for chart in execution["charts"])
    assert any(k["value"] == 45 for k in execution["kpis"])  # average salary


# ---------------------------------------------------------------------------
# Chart-type selection
# ---------------------------------------------------------------------------

def _chart_types(plan, profile, vizzes):
    from app.modules.analytics_planner.plan_sanitizer import sanitize_plan

    cleaned = sanitize_plan(plan, profile)
    validate_analytical_plan(cleaned, profile)
    return {v.id: v.chart_type for v in cleaned.visualizations}


def _group_op(op_id, column, function, measure="gross_salary", group="department"):
    return {
        "id": op_id, "operation_type": "group_by", "worksheet_name": "Payroll",
        "title": f"{function} by {group}", "description": "Grouped result.",
        "group_by_columns": [group],
        "aggregations": [{"alias": "value", "function": function,
                          "column": None if function == "count" else measure}],
    }


def test_chart_type_follows_the_computation_not_a_bar_default():
    profile = payroll_profile()
    ops = [
        _group_op("sum_dept", "department", "sum"),                 # additive, 4 cats
        _group_op("avg_region", "region", "average", group="region"),  # not additive
        {"id": "trend_sum", "operation_type": "time_series",
         "worksheet_name": "Payroll", "title": "Salary trend",
         "description": "Monthly salary.", "date_column": "join_date",
         "interval": "month",
         "metric": {"alias": "total", "function": "sum", "column": "gross_salary"}},
        {"id": "share", "operation_type": "percentage_of_total",
         "worksheet_name": "Payroll", "title": "Share", "description": "Share.",
         "category_column": "region", "value_column": "gross_salary"},
    ]
    plan = payroll_plan(operations=ops, visualizations=[
        _payroll_viz("v_sum", "sum_dept", "bar"),
        _payroll_viz("v_avg", "avg_region", "bar"),
        _payroll_viz("v_trend", "trend_sum", "line"),
        _payroll_viz("v_share", "share", "bar"),
    ])
    types = _chart_types(plan, profile, None)

    assert types == {
        "v_sum": "pie",      # few additive categories
        "v_avg": "bar",      # averages are not parts of a whole
        "v_trend": "area",   # summed totals over time
        "v_share": "donut",  # explicit shares
    }


def test_average_trend_stays_a_line_and_deliberate_choices_are_respected():
    profile = payroll_profile()
    ops = [
        {"id": "trend_avg", "operation_type": "time_series",
         "worksheet_name": "Payroll", "title": "Trend", "description": "Trend.",
         "date_column": "join_date", "interval": "month",
         "metric": {"alias": "avg", "function": "average", "column": "gross_salary"}},
        _group_op("sum_dept", "department", "sum"),
    ]
    plan = payroll_plan(operations=ops, visualizations=[
        _payroll_viz("v_trend", "trend_avg", "line"),
        _payroll_viz("v_table", "sum_dept", "table"),
    ])
    assert _chart_types(plan, profile, None) == {
        "v_trend": "line", "v_table": "table",
    }


def test_part_to_whole_charts_are_capped_and_never_used_for_negative_measures():
    profile = payroll_profile()
    ops = [_group_op(f"count_{i}", "department", "count") for i in range(1)]
    ops += [
        _group_op("count_region", "region", "count", group="region"),
        _group_op("sum_region", "region", "sum", group="region"),
    ]
    plan = payroll_plan(operations=ops, visualizations=[
        _payroll_viz("v1", "count_0", "bar"),
        _payroll_viz("v2", "count_region", "bar"),
        _payroll_viz("v3", "sum_region", "bar"),
    ])
    types = _chart_types(plan, profile, None)
    assert sorted(types.values()).count("bar") == 1
    assert sum(t in {"pie", "donut"} for t in types.values()) == 2

    data = profile.model_dump(mode="json")
    for column in data["worksheets"]["Payroll"]["columns"]:
        if column["column_name"] == "gross_salary":
            column["numerical_statistics"]["minimum"] = -5
    negative = DatasetProfile.model_validate(data)
    only_sum = payroll_plan(
        operations=[_group_op("sum_dept", "department", "sum")],
        visualizations=[_payroll_viz("v1", "sum_dept", "bar")],
    )
    assert _chart_types(only_sum, negative, None) == {"v1": "bar"}


def test_wide_category_sets_use_a_table():
    data = payroll_profile().model_dump(mode="json")
    for column in data["worksheets"]["Payroll"]["columns"]:
        if column["column_name"] == "department":
            column["unique_value_count"] = 30
            column["non_null_count"] = 60
    profile = DatasetProfile.model_validate(data)
    plan = payroll_plan(
        operations=[_group_op("sum_dept", "department", "sum")],
        visualizations=[_payroll_viz("v1", "sum_dept", "bar")],
    )
    assert _chart_types(plan, profile, None) == {"v1": "table"}


def test_planner_produces_a_variety_of_chart_types():
    profile = payroll_profile()
    plan = payroll_plan(
        operations=_payroll_ops(), kpis=[_payroll_kpi()],
        visualizations=[_payroll_viz(chart_type="bar")],
    )
    result = AnalyticsPlanner(plan_generator=_OneShotGenerator(plan)).generate_plan(profile)

    kinds = {v.chart_type for v in result.visualizations}
    assert len(kinds) >= 3, kinds
    validate_analytical_plan(result, profile)



def test_user_request_is_included_and_explicitly_disables_generic_analytics():
    prepared = DatasetProfilePreparer().prepare(make_profile())
    messages = AnalyticsPromptBuilder().build_messages(
        prepared,
        user_request="Show revenue from 2025-01-01 to 2025-03-31.",
    )
    assert "Show revenue from 2025-01-01 to 2025-03-31." in messages[1]["content"]
    assert "ONLY for this request" in messages[1]["content"]
    assert "Do not add generic" in messages[1]["content"]



def test_validator_rejects_date_filter_on_non_date_column():
    plan = make_plan()
    payload = plan.model_dump(mode="python")
    payload["filters"] = [{
        "worksheet_name": "Sales", "column": "revenue",
        "start_date": "2025-01-01", "end_date": "2025-03-31",
    }]
    plan = WorkbookAnalyticsPlan.model_validate(payload)
    with pytest.raises(AnalyticalPlanValidationError, match="not a date column"):
        validate_analytical_plan(plan, make_profile())



def test_targeted_system_prompt_overrides_automatic_dashboard_targets():
    prompt = AnalyticsPromptBuilder().build_system_prompt(user_request=True)
    assert "USER-REQUESTED MODE" in prompt
    assert "there is no minimum chart/operation count" in prompt
    assert "inclusive" in prompt



def test_user_request_mode_does_not_apply_automatic_fallback_or_chart_augmentation(monkeypatch):
    from app.modules.analytics_planner import analytics_planner as planner_module

    class EmptyTargetedGenerator:
        def generate_plan(self, messages):
            assert "USER ANALYTICS REQUEST" in messages[1]["content"]
            return make_plan(operations=[])

    def unexpected_fallback(*args, **kwargs):
        raise AssertionError("Automatic fallback must not run in user-requested mode.")

    monkeypatch.setattr(
        planner_module, "build_deterministic_fallback_plan", unexpected_fallback
    )
    monkeypatch.setattr(
        planner_module, "deterministic_salvage_plan", unexpected_fallback
    )
    monkeypatch.setattr(
        planner_module, "augment_with_deterministic_charts", unexpected_fallback
    )

    plan = AnalyticsPlanner(
        plan_generator=EmptyTargetedGenerator()
    ).generate_plan(make_profile(), user_request="Show me only revenue trends.")

    assert plan.operations == []
    assert plan.visualizations == []



def _make_date_profile():
    return DatasetProfile.model_validate({
        "filename": "sales.xlsx", "total_worksheet_count": 1,
        "successful_worksheet_count": 1, "failed_worksheet_count": 0,
        "worksheets": {"Sales": {
            "worksheet_name": "Sales", "row_count": 3, "column_count": 2,
            "columns": [
                {"column_name": "order_date", "original_name": "Order Date",
                 "pandas_dtype": "datetime64[ns]", "inferred_type": "date",
                 "semantic_role": "date", "non_null_count": 3,
                 "missing_value_count": 0, "blank_string_count": 0,
                 "missing_percentage": 0, "unique_value_count": 3,
                 "unique_value_percentage": 100},
                {"column_name": "revenue", "original_name": "Revenue",
                 "pandas_dtype": "float64", "inferred_type": "numerical",
                 "semantic_role": "amount", "non_null_count": 3,
                 "missing_value_count": 0, "blank_string_count": 0,
                 "missing_percentage": 0, "unique_value_count": 3,
                 "unique_value_percentage": 100,
                 "numerical_statistics": {"minimum": 10, "maximum": 30,
                    "mean": 20, "median": 20, "total": 60,
                    "standard_deviation": 10}},
            ],
        }},
    })


def _date_group_plan():
    return WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0", "workbook_summary": "Sales data.",
        "business_context": {"domain": "sales", "dataset_purpose": "Sales trends", "confidence": 0.8},
        "worksheet_analyses": [{"worksheet_name": "Sales", "inferred_purpose": "Sales",
            "summary": "Sales by date.", "analysis_focus": ["Monthly revenue"]}],
        "operations": [{"id": "monthly_revenue", "operation_type": "group_by",
            "worksheet_name": "Sales", "title": "Monthly revenue",
            "description": "Revenue grouped by date.", "group_by_columns": ["order_date"],
            "aggregations": [{"alias": "total_revenue", "function": "sum", "column": "revenue"}]}],
        "kpis": [], "visualizations": [{"id": "monthly_chart", "operation_id": "monthly_revenue",
            "chart_type": "line", "title": "Monthly revenue",
            "description": "Revenue trend by month.", "priority": "high"}],
        "key_questions": [], "limitations": [],
    })


def test_explicit_natural_language_date_range_is_enforced_even_if_llm_omits_filter():
    from app.modules.analytics_planner.analytics_planner import _enforce_explicit_date_filter
    plan = make_plan(worksheets=[{"worksheet_name": "Sales", "inferred_purpose": "Sales",
        "summary": "Sales rows.", "analysis_focus": []}])
    _enforce_explicit_date_filter(
        plan, _make_date_profile(),
        "Show total sales from 1 February 2025 to 28 February 2025.",
    )
    assert len(plan.filters) == 1
    assert plan.filters[0].worksheet_name == "Sales"
    assert plan.filters[0].column == "order_date"
    assert plan.filters[0].start_date == "2025-02-01"
    assert plan.filters[0].end_date == "2025-02-28"


def test_monthly_date_grouping_is_repaired_to_time_series_before_validation():
    from app.modules.analytics_planner.analytics_planner import _repair_date_groupings
    from app.schemas.analytics_plan import TimeSeriesOperation
    plan = _date_group_plan()
    _repair_date_groupings(
        plan, _make_date_profile(),
        "Show how revenue changes month by month.",
    )
    operation = plan.operations[0]
    assert isinstance(operation, TimeSeriesOperation)
    assert operation.operation_type == "time_series"
    assert operation.date_column == "order_date"
    assert operation.interval == "month"


def test_month_year_range_expands_to_full_calendar_months():
    from app.modules.analytics_planner.analytics_planner import _extract_explicit_date_range
    assert tuple(value.isoformat() for value in _extract_explicit_date_range(
        "Analyze sales from January 2025 to February 2025"
    )) == ("2025-01-01", "2025-02-28")


def test_requested_total_scalar_operation_gets_a_linked_kpi():
    from app.modules.analytics_planner.analytics_planner import _ensure_requested_total_kpis
    plan = make_plan()
    _ensure_requested_total_kpis(plan, "Show the total revenue for this period.")
    assert len(plan.kpis) == 1
    assert plan.kpis[0].operation_id == "total_revenue"
    assert plan.kpis[0].label == "Total revenue"


def test_full_category_comparison_removes_redundant_top_and_bottom_charts():
    from app.modules.analytics_planner.analytics_planner import _remove_redundant_extreme_charts
    plan = WorkbookAnalyticsPlan.model_validate({
        "plan_version": "1.0", "workbook_summary": "Regional sales.",
        "business_context": {"domain": "sales", "dataset_purpose": "Compare regions", "confidence": 0.8},
        "worksheet_analyses": [{"worksheet_name": "Sales", "inferred_purpose": "Sales", "summary": "Regional revenue.", "analysis_focus": []}],
        "operations": [
            {"id": "region_all", "operation_type": "group_by", "worksheet_name": "Sales", "title": "Revenue by region", "description": "Compare all regions.", "group_by_columns": ["region"], "aggregations": [{"alias": "total_revenue", "function": "sum", "column": "revenue"}]},
            {"id": "region_top", "operation_type": "top_n", "worksheet_name": "Sales", "title": "Top region", "description": "Highest region.", "group_by_column": "region", "metric": {"alias": "total_revenue", "function": "sum", "column": "revenue"}, "limit": 1},
            {"id": "region_bottom", "operation_type": "bottom_n", "worksheet_name": "Sales", "title": "Bottom region", "description": "Lowest region.", "group_by_column": "region", "metric": {"alias": "total_revenue", "function": "sum", "column": "revenue"}, "limit": 1},
        ],
        "kpis": [],
        "visualizations": [
            {"id": "all_chart", "operation_id": "region_all", "chart_type": "bar", "title": "All regions", "description": "All regions.", "priority": "high"},
            {"id": "top_chart", "operation_id": "region_top", "chart_type": "bar", "title": "Top region", "description": "Top region.", "priority": "medium"},
            {"id": "bottom_chart", "operation_id": "region_bottom", "chart_type": "bar", "title": "Bottom region", "description": "Bottom region.", "priority": "medium"},
        ],
        "key_questions": [], "limitations": [],
    })
    _remove_redundant_extreme_charts(
        plan, "Compare total revenue across all regions and identify highest and lowest."
    )
    assert [operation.id for operation in plan.operations] == ["region_all"]
    assert [visualization.operation_id for visualization in plan.visualizations] == ["region_all"]
