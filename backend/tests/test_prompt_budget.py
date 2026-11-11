"""Regression tests for local-model context budgeting in the analytics planner.

Root cause covered here: the Ollama client counted the structured-output JSON
schema (``format``) as prompt tokens even though Ollama applies it as a
sampling grammar, so a ~3.5K-token prompt was rejected as ~8.8K tokens against
an 8,601-token budget (context 12288, output 3072).
"""

import json

import pytest

from app.modules.analytics_planner.analytics_planner import (
    MAX_REPAIR_ECHO_CHARS,
    AnalyticsPlanner,
    AnalyticsPlanningError,
)
from app.modules.analytics_planner.errors import PlanSchemaValidationError
from app.modules.analytics_planner.llm_client import estimate_tokens
from app.modules.analytics_planner.ollama_client import (
    OllamaClient,
    OllamaResponseError,
)
from app.modules.analytics_planner.profile_preparation import (
    DatasetProfilePreparer,
    ProfilePreparationError,
)
from app.modules.analytics_planner.prompt_builder import (
    SYSTEM_PROMPT,
    AnalyticsPromptBuilder,
)
from app.schemas.analytics_plan import WorkbookAnalyticsPlan
from app.schemas.data_understanding import DatasetProfile


def _column(index: int) -> dict:
    return {
        "column_name": f"measure_{index}", "original_name": f"Measure {index}",
        "pandas_dtype": "float64", "inferred_type": "numerical",
        "semantic_role": "amount", "non_null_count": 500,
        "missing_value_count": 0, "blank_string_count": 0,
        "missing_percentage": 0, "unique_value_count": 400,
        "unique_value_percentage": 80,
        "numerical_statistics": {
            "minimum": 1, "maximum": 99999, "mean": 5000.5, "median": 4000.25,
            "total": 2500250, "standard_deviation": 1234.56,
        },
    }


def make_wide_profile(columns_per_sheet: int = 20, sheets: int = 2) -> DatasetProfile:
    worksheets = {
        f"Sheet{s}": {
            "worksheet_name": f"Sheet{s}", "row_count": 500,
            "column_count": columns_per_sheet,
            "columns": [_column(i) for i in range(columns_per_sheet)],
        }
        for s in range(sheets)
    }
    return DatasetProfile.model_validate({
        "filename": "wide.xlsx", "total_worksheet_count": sheets,
        "successful_worksheet_count": sheets, "failed_worksheet_count": 0,
        "worksheet_errors": {}, "worksheets": worksheets,
    })


class _CapturingOllama(OllamaClient):
    """Real budget arithmetic, but no network: records the messages it is sent."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sent: list[list[dict[str, str]]] = []

    def generate_plan(self, messages):
        self.sent.append(messages)
        raise OllamaResponseError("captured")


# ---------------------------------------------------------------------------
# Ollama client budget accounting
# ---------------------------------------------------------------------------

def test_reported_configuration_budget_matches_the_original_error():
    client = OllamaClient(context_length=12288, max_output_tokens=3072)
    assert client.available_prompt_tokens == 8601


def test_output_schema_is_not_counted_as_prompt_tokens():
    client = OllamaClient(context_length=12288, max_output_tokens=3072)
    schema_chars = len(json.dumps(
        WorkbookAnalyticsPlan.model_json_schema(), separators=(",", ":")
    ))
    messages = [{"role": "user", "content": "x" * 3200}]
    estimate = client.estimate_prompt_tokens(messages)
    assert estimate < 1100
    # The pre-fix formula would have added the whole schema (~5K tokens).
    assert estimate + estimate_tokens("x" * schema_chars) > 5000


def test_prompt_that_was_wrongly_rejected_now_reaches_ollama(monkeypatch):
    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"done": False, "done_reason": "length", "message": {"content": "{}"}}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, **kwargs):
            posted["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.modules.analytics_planner.ollama_client.httpx.Client", FakeClient
    )
    client = OllamaClient(context_length=12288, max_output_tokens=3072)
    # ~12K characters: 3.8K real tokens, but >8.6K under the old formula.
    messages = [{"role": "user", "content": "word " * 2400}]
    with pytest.raises(OllamaResponseError, match="output-token limit"):
        client.generate_plan(messages)
    assert posted["payload"]["options"]["num_ctx"] == 12288
    assert posted["payload"]["format"]  # structured-output constraint still sent


def test_genuinely_oversized_prompt_is_still_rejected_with_actionable_message():
    client = OllamaClient(context_length=12288, max_output_tokens=3072)
    with pytest.raises(OllamaResponseError, match="too large") as excinfo:
        client.generate_plan([{"role": "user", "content": "x" * 40000}])
    assert "OLLAMA_CONTEXT_LENGTH" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def test_system_prompt_is_compact_and_keeps_core_rules():
    assert len(SYSTEM_PROMPT.strip()) < 6500
    for phrase in (
        "normalized execution identifier",
        "NEVER add currency symbols/codes",
        "Correlation analysis is not supported",
        "operation_type",
        "NON-SCALAR",
        "SCALAR operation",
        "Never exceed 8 operations, 8 visualizations, 2 key_questions, or 4 KPIs",
        'plan_version is the string "1.0"',
    ):
        assert phrase in SYSTEM_PROMPT


def test_user_prompt_omits_budget_only_metadata():
    prepared = DatasetProfilePreparer().prepare(make_wide_profile(3, 1))
    user = AnalyticsPromptBuilder().build_messages(prepared)[1]["content"]
    for key in ("profile_characters", "estimated_profile_tokens", "max_profile_characters"):
        assert key not in user
    assert "sample_values_included" in user
    # The authoritative profile is untouched by the metadata slimming.
    assert "measure_0" in user


def test_prepared_profile_token_estimate_is_an_integer():
    prepared = DatasetProfilePreparer().prepare(make_wide_profile(3, 1))
    estimate = prepared["preparation_metadata"]["estimated_profile_tokens"]
    assert isinstance(estimate, int)


# ---------------------------------------------------------------------------
# Profile preparation budget override
# ---------------------------------------------------------------------------

def test_prepare_accepts_a_tighter_per_call_limit_and_never_a_looser_one():
    profile = make_wide_profile(20, 2)  # ~9.7K chars full, ~7.5K compacted
    preparer = DatasetProfilePreparer(max_profile_chars=12000)

    default = preparer.prepare(profile)
    tight = preparer.prepare(profile, max_profile_chars=8500)
    loose = preparer.prepare(profile, max_profile_chars=50000)

    assert tight["preparation_metadata"]["profile_characters"] <= 8500
    assert tight["preparation_metadata"]["max_profile_characters"] == 8500
    assert tight["preparation_metadata"]["profile_characters"] < (
        default["preparation_metadata"]["profile_characters"]
    )
    assert loose["preparation_metadata"]["max_profile_characters"] == 12000


def test_prepare_still_never_drops_columns_under_a_tight_limit():
    profile = make_wide_profile(20, 2)
    prepared = DatasetProfilePreparer().prepare(profile, max_profile_chars=8500)["profile"]
    assert all(len(sheet["columns"]) == 20 for sheet in prepared["worksheets"].values())


def test_prepare_rejects_profile_that_cannot_meet_the_limit_and_invalid_limits():
    profile = make_wide_profile(20, 2)
    with pytest.raises(ProfilePreparationError):
        DatasetProfilePreparer().prepare(profile, max_profile_chars=1000)
    with pytest.raises(ValueError):
        DatasetProfilePreparer().prepare(profile, max_profile_chars=999)


# ---------------------------------------------------------------------------
# Planner: context-aware profile sizing and bounded retries
# ---------------------------------------------------------------------------

def _context_for_available_prompt_tokens(target: int, output_tokens: int = 1024) -> int:
    context = target + output_tokens + 128
    while OllamaClient(
        context_length=context, max_output_tokens=output_tokens
    ).available_prompt_tokens < target:
        context += 16
    return context


def test_planner_sizes_the_profile_to_the_providers_context_budget():
    profile = make_wide_profile(20, 2)
    unconstrained = AnalyticsPromptBuilder().build_messages(
        DatasetProfilePreparer().prepare(profile)
    )
    # A window ~600 tokens smaller than the default-size prompt: the profile
    # must be compacted (not rejected) for the request to fit.
    target = OllamaClient.estimate_prompt_tokens(unconstrained) - 600
    client = _CapturingOllama(
        context_length=_context_for_available_prompt_tokens(target),
        max_output_tokens=1024,
    )
    assert client.estimate_prompt_tokens(unconstrained) > client.available_prompt_tokens

    with pytest.raises(AnalyticsPlanningError, match="captured"):
        AnalyticsPlanner(plan_generator=client).generate_plan(profile)

    assert len(client.sent) == 1, "planner must reach the provider, not fail on size"
    assert client.estimate_prompt_tokens(client.sent[0]) <= client.available_prompt_tokens
    assert '"mean"' not in client.sent[0][1]["content"]  # statistics were compacted
    assert client.sent[0][1]["content"].count('"column_name"') == 40  # no column dropped


def test_planner_leaves_generous_contexts_uncompacted():
    profile = make_wide_profile(20, 2)
    client = _CapturingOllama(context_length=16384, max_output_tokens=2048)
    with pytest.raises(AnalyticsPlanningError, match="captured"):
        AnalyticsPlanner(plan_generator=client).generate_plan(profile)
    assert '"mean"' in client.sent[0][1]["content"]
    assert client.estimate_prompt_tokens(client.sent[0]) <= client.available_prompt_tokens


def test_planner_reports_profile_too_large_when_nothing_can_be_compacted_enough():
    profile = make_wide_profile(20, 2)
    unconstrained = AnalyticsPromptBuilder().build_messages(
        DatasetProfilePreparer().prepare(profile)
    )
    target = OllamaClient.estimate_prompt_tokens(unconstrained) - 1800
    client = _CapturingOllama(
        context_length=_context_for_available_prompt_tokens(target),
        max_output_tokens=1024,
    )
    with pytest.raises(ProfilePreparationError, match="OLLAMA_CONTEXT_LENGTH"):
        AnalyticsPlanner(plan_generator=client).generate_plan(profile)
    assert client.sent == []


def test_planner_without_provider_budget_behaves_as_before():
    class PlainGenerator:
        def __init__(self):
            self.calls = 0

        def generate_plan(self, messages):
            self.calls += 1
            raise OllamaResponseError("stop")

    generator = PlainGenerator()
    planner = AnalyticsPlanner(plan_generator=generator)
    assert planner._profile_char_budget() is None
    with pytest.raises(Exception):
        planner.generate_plan(make_wide_profile(3, 1))
    assert generator.calls == 1


def _schema_error_generator(generated_output: str):
    class Generator:
        def __init__(self):
            self.calls = []

        def generate_plan(self, messages):
            self.calls.append(messages)
            raise PlanSchemaValidationError(
                "Invalid plan schema",
                generated_output=generated_output,
                validation_errors=[{"loc": ["operations"], "msg": "invalid"}],
            )

    return Generator()


def test_schema_repair_echo_is_bounded():
    generator = _schema_error_generator("{" + "a" * 20000)
    with pytest.raises(Exception):
        AnalyticsPlanner(plan_generator=generator).generate_plan(make_wide_profile(3, 1))
    assert len(generator.calls) == 2
    echo = generator.calls[1][-2]
    assert echo["role"] == "assistant"
    assert len(echo["content"]) == MAX_REPAIR_ECHO_CHARS


def test_schema_repair_never_sends_an_empty_assistant_message():
    generator = _schema_error_generator("")
    with pytest.raises(Exception):
        AnalyticsPlanner(plan_generator=generator).generate_plan(make_wide_profile(3, 1))
    assert len(generator.calls) == 2
    assert all(m["role"] != "assistant" for m in generator.calls[1])
    assert all(m["content"].strip() for m in generator.calls[1])


def test_schema_repair_drops_echo_when_it_would_overflow_the_context():
    class TightGenerator(_CapturingOllama):
        def generate_plan(self, messages):
            self.sent.append(messages)
            raise PlanSchemaValidationError(
                "Invalid plan schema",
                generated_output="{" + "a" * 2400,
                validation_errors=[{"loc": ["operations"], "msg": "invalid"}],
            )

    # Window sized so the first prompt fits but prompt + echo + instructions cannot.
    probe = AnalyticsPromptBuilder().build_messages(
        DatasetProfilePreparer().prepare(make_wide_profile(3, 1))
    )
    base = OllamaClient.estimate_prompt_tokens(probe)
    context = 1024 + 308 + base + 400
    client = TightGenerator(context_length=context, max_output_tokens=1024)
    with pytest.raises(Exception):
        AnalyticsPlanner(plan_generator=client).generate_plan(make_wide_profile(3, 1))
    assert len(client.sent) == 2
    assert all(m["role"] != "assistant" for m in client.sent[1])
