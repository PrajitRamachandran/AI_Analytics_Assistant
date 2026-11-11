
"""Orchestration layer for the AI analytics planner."""

from __future__ import annotations

import logging
from typing import Protocol

from app.modules.analytics_planner.errors import PlanSchemaValidationError
from app.modules.analytics_planner.deterministic_plan import (
    build_deterministic_fallback_plan,
)
from app.modules.analytics_planner.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
)
from app.modules.analytics_planner.llm_client import (
    LLMConnectionError,
    LLMTimeoutError,
    create_llm_client,
)
from app.modules.analytics_planner.plan_validator import (
    AnalyticalPlanValidationError,
    validate_analytical_plan,
)
from app.modules.analytics_planner.profile_preparation import (
    DatasetProfilePreparer,
    ProfilePreparationError,
)
from app.modules.analytics_planner.prompt_builder import (
    AnalyticsPromptBuilder,
    PromptBuilderError,
)
from app.schemas.analytics_plan import WorkbookAnalyticsPlan, WorksheetAnalysis
from app.schemas.data_understanding import DatasetProfile
from app.modules.analytics_planner.worksheet_classifier import classify_worksheet


logger = logging.getLogger(__name__)


class PlanGenerator(Protocol):
    """Provider-neutral contract for structured analytics-plan generation."""

    def generate_plan(
        self,
        messages: list[dict[str, str]],
    ) -> WorkbookAnalyticsPlan:
        ...


class AnalyticsPlannerError(Exception):
    """Base exception for analytics planner failures."""


class AnalyticsPlanningError(AnalyticsPlannerError):
    """Raised when analytics plan generation fails."""


class AnalyticsPlanningTimeoutError(AnalyticsPlanningError):
    """Raised when the configured LLM provider exceeds its inference timeout."""


class AnalyticsProviderUnavailableError(AnalyticsPlanningError):
    """Raised when the configured LLM provider cannot be reached."""


class AnalyticsPlanner:
    """
    Coordinate profile preparation, prompt construction, LLM inference,
    and analytical plan validation.
    """

    def __init__(
        self,
        profile_preparer: DatasetProfilePreparer | None = None,
        prompt_builder: AnalyticsPromptBuilder | None = None,
        ollama_client: OllamaClient | None = None,
        plan_generator: PlanGenerator | None = None,
    ) -> None:
        self.profile_preparer = (
            profile_preparer or DatasetProfilePreparer()
        )

        self.prompt_builder = (
            prompt_builder or AnalyticsPromptBuilder()
        )

        if plan_generator is not None and ollama_client is not None:
            raise ValueError(
                "Provide either plan_generator or ollama_client, not both."
            )

        # Use the provider registry unless a client was explicitly injected.
        # LLM_PROVIDER selects Groq or Ollama from the backend environment.
        self.plan_generator: PlanGenerator = (
            plan_generator or ollama_client or create_llm_client()
        )
        # Backward-compatible attribute for existing diagnostics/callers.
        self.ollama_client = self.plan_generator

    def generate_plan(
        self,
        dataset_profile: DatasetProfile,
    ) -> WorkbookAnalyticsPlan:
        """
        Generate and validate a workbook-level analytics plan.

        The LLM proposes analytical operations but does not execute
        calculations or generate numerical results.
        """

        if not isinstance(dataset_profile, DatasetProfile):
            raise TypeError(
                "dataset_profile must be a DatasetProfile instance."
            )

        logger.info("Starting analytics plan generation.")

        # Step 1: Prepare the Module 3 profile.
        try:
            prepared_profile = self.profile_preparer.prepare(
                dataset_profile
            )

        except ProfilePreparationError:
            logger.exception("Dataset profile preparation failed.")
            raise

        # Step 2: Build LLM messages.
        try:
            messages = self.prompt_builder.build_messages(
                prepared_profile
            )

        except PromptBuilderError:
            logger.exception("Analytics prompt construction failed.")
            raise

        # Step 3: Generate a structured plan and validate it against the real
        # dataset. One correction attempt is allowed for either schema or
        # dataset-validation failures; retries are bounded to avoid loops.
        request_messages = list(messages)
        analytical_plan: WorkbookAnalyticsPlan | None = None

        for attempt in range(2):
            try:
                logger.info(
                    "ACTIVE LLM PROVIDER: %s | MODEL: %s",
                    getattr(
                        self.plan_generator,
                        "provider",
                        "ollama" if isinstance(self.plan_generator, OllamaClient)
                        else type(self.plan_generator).__name__,
                    ),
                    getattr(self.plan_generator, "model", "unknown"),
                )
                analytical_plan = self.plan_generator.generate_plan(
                    request_messages
                )

            except PlanSchemaValidationError as exc:
                if attempt == 1:
                    logger.exception(
                        "Generated analytics plan failed schema validation after correction."
                    )
                    raise AnalyticsPlanningError(
                        "The generated analytics plan still failed schema validation "
                        "after one correction attempt."
                    ) from exc

                logger.warning(
                    "Generated plan failed Pydantic schema validation; "
                    "requesting one corrected plan. Errors: %s",
                    exc.validation_errors,
                )
                request_messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": exc.generated_output,
                    },
                    {
                        "role": "user",
                        "content": (
                            "Your previous JSON was valid JSON but did not satisfy "
                            "the required analytics-plan schema. Validation errors: "
                            f"{exc.validation_errors}. Correct the reported fields "
                            "and return a complete replacement JSON object. Do not use null for required scalar fields. The root "
                            "object must contain exactly these fields: plan_version, "
                            "workbook_summary, business_context, worksheet_analyses, "
                            "operations, kpis, visualizations, key_questions, and "
                            "limitations. Do not wrap the object in a 'workbook' field. "
                            "Every operation must include its exact operation_type "
                            "discriminator. Use 'label' (never 'name') for KPI labels, "
                            "and 'chart_type' (never 'type') for visualizations. "
                            "Every KPI operation_id must exactly match the id of a "
                            "scalar operation (sum, average, count, min, max, or "
                            "distinct_count). Every visualization operation_id must "
                            "exactly match the id of a NON-SCALAR operation "
                            "(group_by, top_n, bottom_n, time_series, "
                            "percentage_of_total, or comparison). Never attach a "
                            "visualization to sum, average, count, min, max, or "
                            "distinct_count. If there is no compatible non-scalar "
                            "operation, return an empty visualizations array. Do not "
                            "use an operation type or result_name as operation_id. "
                            "For group_by, include group_by_columns and aggregations; "
                            "each aggregation requires alias and function, and a "
                            "column for every function except count. For comparison, "
                            "use two distinct observed category values from the "
                            "profile. Do not invent values, columns, units, or statistics."
                        ),
                    },
                ]
                continue

            except (OllamaTimeoutError, LLMTimeoutError) as exc:
                logger.exception(
                    "LLM provider timed out while generating the analytics plan."
                )
                raise AnalyticsPlanningTimeoutError(str(exc)) from exc

            except (OllamaConnectionError, LLMConnectionError) as exc:
                logger.exception(
                    "LLM provider is unavailable while generating the analytics plan."
                )
                raise AnalyticsProviderUnavailableError(str(exc)) from exc

            except Exception as exc:
                # Keep provider-specific exception classes behind the adapter,
                # but preserve a safe actionable message for the API response.
                logger.exception("LLM analytics plan generation failed.")
                raise AnalyticsPlanningError(
                    f"The configured language-model provider could not generate "
                    f"an analytics plan: {exc}"
                ) from exc

            # Complete worksheet coverage deterministically. Reference/documentation
            # sheets remain represented in the workbook summary, but do not need
            # to be guessed by the LLM and are excluded from execution later.
            supplied_names = {item.worksheet_name for item in analytical_plan.worksheet_analyses}
            missing_analyses = []
            for sheet_name, sheet_profile in dataset_profile.worksheets.items():
                if sheet_name in supplied_names:
                    continue
                classification = classify_worksheet(sheet_name, sheet_profile)
                missing_analyses.append(WorksheetAnalysis(
                    worksheet_name=sheet_name,
                    inferred_purpose=(
                        "Reference or documentation worksheet"
                        if classification["role"] == "reference"
                        else "Worksheet requiring profile-grounded review"
                    ),
                    summary=(
                        f"Automatically classified as {classification['role']}: "
                        f"{classification['reason']} Rows: {sheet_profile.row_count}; "
                        f"columns: {sheet_profile.column_count}."
                    ),
                    analysis_focus=(
                        ["Retain as workbook reference; exclude from business aggregations."]
                        if classification["role"] == "reference"
                        else ["Review eligible columns and data quality."]
                    ),
                ))
            if missing_analyses:
                analytical_plan = analytical_plan.model_copy(update={
                    "worksheet_analyses": [
                        *analytical_plan.worksheet_analyses, *missing_analyses
                    ]
                })

            # Small local models can return a syntactically valid narrative
            # plan while leaving all executable arrays empty. Do not send that
            # empty plan to Module 5 when the profile contains analyzable data.
            if not analytical_plan.operations:
                fallback_plan = build_deterministic_fallback_plan(
                    dataset_profile,
                    analytical_plan,
                )
                if fallback_plan is not None:
                    logger.warning(
                        "LLM returned an empty operation list; using a "
                        "conservative profile-grounded deterministic plan."
                    )
                    analytical_plan = fallback_plan

            try:
                validate_analytical_plan(
                    analytical_plan,
                    dataset_profile,
                )
                break

            except AnalyticalPlanValidationError as exc:
                if attempt == 1:
                    logger.exception(
                        "Generated analytics plan failed validation after correction."
                    )
                    raise

                logger.warning(
                    "Generated plan failed deterministic validation; requesting "
                    "one corrected plan. Reason: %s",
                    exc,
                )
                # Keep the repair request compact. Re-sending the entire prior
                # JSON plan as an assistant turn consumes context and often causes
                # small local models to hit their output-token limit on the
                # replacement plan. The authoritative workbook profile and
                # system rules are already present in `messages`.
                request_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "The plan you just generated failed deterministic "
                            "validation. Fix this specific issue and return one "
                            "complete replacement JSON object matching the schema. "
                            f"Validation error: {exc}. "
                            "Do not use a numerical column as a category/group/"
                            "comparison column. For comparison, category_column "
                            "must be a categorical or boolean column, and both "
                            "values must be distinct observed categories from that "
                            "column. If no suitable category exists, omit comparison "
                            "and choose a valid supported operation instead. "
                            "Keep the plan concise: at most 2 operations, 1 "
                            "visualization, and 2 key questions. KPI operation_id "
                            "must reference a scalar operation id only "
                            "(sum/average/count/min/max/distinct_count). Visualization "
                            "operation_id must reference a non-scalar operation id "
                            "only (group_by/top_n/bottom_n/time_series/"
                            "percentage_of_total/comparison). Never link a chart to "
                            "a scalar operation. If no non-scalar operation exists, "
                            "return visualizations: []. Do not invent columns, "
                            "values, units, or statistics."
                        ),
                    },
                ]

        if analytical_plan is None:
            # Defensive guard; the loop either returns a plan or raises.
            raise AnalyticsPlanningError(
                "The language model did not produce an analytical plan."
            )

        logger.info(
            "Analytics plan generated and validated successfully."
        )

        return analytical_plan


def generate_analytics_plan(
    dataset_profile: DatasetProfile,
) -> WorkbookAnalyticsPlan:
    """Convenience function for generating a validated analytics plan."""

    planner = AnalyticsPlanner()
    return planner.generate_plan(dataset_profile)
