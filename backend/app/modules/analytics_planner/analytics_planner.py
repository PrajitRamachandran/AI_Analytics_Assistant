
"""Orchestration layer for the AI analytics planner."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date
from dateutil import parser as date_parser
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
    CHARS_PER_ESTIMATED_TOKEN,
    LLMConnectionError,
    LLMTimeoutError,
    create_llm_client,
)
from app.modules.analytics_planner.plan_validator import (
    AnalyticalPlanValidationError,
    validate_analytical_plan,
)
from app.modules.analytics_planner.plan_sanitizer import (
    augment_with_deterministic_charts,
    deterministic_salvage_plan,
    sanitize_plan,
)
from app.modules.analytics_planner.profile_preparation import (
    DatasetProfilePreparer,
    ProfilePreparationError,
)
from app.modules.analytics_planner.prompt_builder import (
    AnalyticsPromptBuilder,
    PromptBuilderError,
)
from app.schemas.analytics_plan import (
    DateRangeFilter,
    GroupByOperation,
    KPIRecommendation,
    MetricAggregation,
    SumOperation,
    VisualizationRecommendation,
    TimeSeriesOperation,
    TopNOperation,
    BottomNOperation,
    WorkbookAnalyticsPlan,
    WorksheetAnalysis,
)
from app.schemas.data_understanding import DatasetProfile
from app.modules.analytics_planner.worksheet_classifier import classify_worksheet


logger = logging.getLogger(__name__)

# Tokens reserved for the user-prompt framing text and preparation metadata
# that surround the serialized profile.
USER_PROMPT_FRAMING_TOKENS = 299

# Smallest profile budget worth enforcing (matches DatasetProfilePreparer).
MIN_PROFILE_CHARS = 1000

# Cap on how much of an invalid previous response is echoed back in a repair
# request; the echo is context-only and must not crowd out the profile.
MAX_REPAIR_ECHO_CHARS = 2500


_DATE_TOKEN = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{4}|"
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4}|"
    r"[A-Za-z]+\s+\d{1,2},?\s+\d{4}|"
    r"[A-Za-z]+\s+\d{4})"
)
_DATE_RANGE_RE = re.compile(
    rf"\b(?:from|between)\s+({_DATE_TOKEN})\s+(?:to|through|and)\s+({_DATE_TOKEN})\b",
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(r"^[A-Za-z]+\s+\d{4}$")


def _parse_explicit_date(token: str, *, is_end: bool) -> date:
    token = token.strip().rstrip(".,")
    parsed = date_parser.parse(token, dayfirst=True, fuzzy=False).date()
    if _MONTH_YEAR_RE.fullmatch(token):
        last_day = calendar.monthrange(parsed.year, parsed.month)[1]
        return date(parsed.year, parsed.month, last_day if is_end else 1)
    return parsed


def _extract_explicit_date_range(request: str | None) -> tuple[date, date] | None:
    """Extract an unambiguous explicit 'from/between X to/and Y' date range."""
    if not request:
        return None
    match = _DATE_RANGE_RE.search(request)
    if not match:
        return None
    try:
        start = _parse_explicit_date(match.group(1), is_end=False)
        end = _parse_explicit_date(match.group(2), is_end=True)
    except (ValueError, OverflowError):
        return None
    return (start, end) if start <= end else None


def _requested_interval(request: str) -> str | None:
    text = request.lower()
    if re.search(r"\b(monthly|month[- ]by[- ]month|per month|each month)\b", text):
        return "month"
    if re.search(r"\b(daily|day[- ]by[- ]day|per day|each day)\b", text):
        return "day"
    if re.search(r"\b(weekly|week[- ]by[- ]week|per week|each week)\b", text):
        return "week"
    if re.search(r"\b(quarterly|quarter[- ]by[- ]quarter)\b", text):
        return "quarter"
    if re.search(r"\b(yearly|annually|annual|year[- ]by[- ]year)\b", text):
        return "year"
    return None


def _repair_date_groupings(
    plan: WorkbookAnalyticsPlan, dataset_profile: DatasetProfile, request: str | None,
) -> None:
    """Convert a model's raw-date group_by into the supported time-series form."""
    if not request:
        return
    interval = _requested_interval(request)
    if interval is None:
        return
    repaired = []
    for operation in plan.operations:
        if not isinstance(operation, GroupByOperation):
            repaired.append(operation)
            continue
        worksheet_profile = dataset_profile.worksheets.get(operation.worksheet_name)
        if worksheet_profile is None:
            repaired.append(operation)
            continue
        date_columns = [
            column_name for column_name in operation.group_by_columns
            if any(
                column.column_name == column_name and column.inferred_type == "date"
                for column in worksheet_profile.columns
            )
        ]
        if len(date_columns) != 1 or not operation.aggregations:
            repaired.append(operation)
            continue
        date_column = date_columns[0]
        metric = operation.aggregations[0]
        group_columns = [c for c in operation.group_by_columns if c != date_column]
        repaired.append(TimeSeriesOperation(
            id=operation.id,
            operation_type="time_series",
            worksheet_name=operation.worksheet_name,
            title=operation.title,
            description=operation.description,
            date_column=date_column,
            interval=interval,
            metric=metric,
            group_by_columns=group_columns,
        ))
        logger.info(
            "Repaired raw-date group_by '%s' into %s time_series operation.",
            operation.id, interval,
        )
    plan.operations = repaired


def _enforce_explicit_date_filter(
    plan: WorkbookAnalyticsPlan, dataset_profile: DatasetProfile, request: str | None,
) -> None:
    """Deterministically enforce an explicit date range before execution."""
    requested_range = _extract_explicit_date_range(request)
    if requested_range is None:
        # The model must never invent a date window. In particular, phrases
        # such as "entire available dataset" mean no date filter at all.
        if plan.filters:
            logger.warning(
                "Removed %d model-generated date filter(s): the user did not specify a date range.",
                len(plan.filters),
            )
            plan.filters = []
        plan.limitations = [
            item for item in plan.limitations
            if not re.search(r"root filter|date range specified|specified date range|within this date range", item, re.IGNORECASE)
        ]
        return
    start, end = requested_range
    candidates = [
        (sheet_name, column.column_name)
        for sheet_name, sheet in dataset_profile.worksheets.items()
        if classify_worksheet(sheet_name, sheet)["role"] == "analytical"
        for column in sheet.columns
        if column.inferred_type == "date"
    ]
    if len(candidates) != 1:
        raise AnalyticsPlanningError(
            "Your request specifies a date range, but the workbook does not have "
            "exactly one unambiguous date column. Please clarify which date column to use."
        )
    worksheet_name, column_name = candidates[0]
    plan.filters = [DateRangeFilter(
        worksheet_name=worksheet_name,
        column=column_name,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )]
    logger.info(
        "Enforced user-requested inclusive date filter: %s.%s from %s to %s.",
        worksheet_name, column_name, start.isoformat(), end.isoformat(),
    )


def _remove_redundant_extreme_charts(
    plan: WorkbookAnalyticsPlan, request: str | None,
) -> None:
    """Avoid separate top/bottom charts when one requested comparison answers both."""
    if not request or not re.search(r"\b(compare|comparison|across|between)\b", request, re.IGNORECASE):
        return
    if not re.search(r"\b(highest|lowest|top|bottom|best|worst)\b", request, re.IGNORECASE):
        return

    grouped = []
    for operation in plan.operations:
        if isinstance(operation, GroupByOperation) and len(operation.group_by_columns) == 1:
            grouped.append((operation.worksheet_name, operation.group_by_columns[0], operation))

    redundant_ids = set()
    for operation in plan.operations:
        if not isinstance(operation, (TopNOperation, BottomNOperation)):
            continue
        for worksheet_name, dimension, grouped_operation in grouped:
            if worksheet_name != operation.worksheet_name or dimension != operation.group_by_column:
                continue
            if any(
                aggregation.function == operation.metric.function
                and aggregation.column == operation.metric.column
                for aggregation in grouped_operation.aggregations
            ):
                redundant_ids.add(operation.id)
                break

    if redundant_ids:
        plan.operations = [op for op in plan.operations if op.id not in redundant_ids]
        plan.visualizations = [
            viz for viz in plan.visualizations if viz.operation_id not in redundant_ids
        ]
        logger.info(
            "Removed redundant top/bottom chart operations covered by a full comparison: %s",
            sorted(redundant_ids),
        )


def _ensure_requested_total_kpis(
    plan: WorkbookAnalyticsPlan, request: str | None,
) -> None:
    """Expose scalar totals as KPIs when the user explicitly asks for totals."""
    if not request or not re.search(r"\b(total|overall|sum|how much)\b", request, re.IGNORECASE):
        return
    linked = {item.operation_id for item in plan.kpis}
    for operation in plan.operations:
        if operation.operation_type not in {"sum", "average", "count", "min", "max", "distinct_count"}:
            continue
        if operation.id in linked or len(plan.kpis) >= 4:
            continue
        label = operation.title.strip() or operation.result_name.replace("_", " ").title()
        plan.kpis.append(KPIRecommendation(
            id=f"kpi_{operation.id}"[:64],
            operation_id=operation.id,
            label=label[:100],
            description=operation.description[:300],
            format_hint="number" if operation.operation_type in {"count", "distinct_count"} else "decimal",
            priority="high",
        ))
        linked.add(operation.id)


_MEASURE_TERMS = {
    "revenue": ("revenue", "sales_amount", "sales_value", "amount"),
    "sales": ("revenue", "sales_amount", "sales_value", "amount"),
    "profit": ("profit", "margin"),
    "quantity": ("quantity", "units", "qty"),
    "orders": ("order", "orders"),
}
_DIMENSION_TERMS = {
    "product": ("product", "item", "sku"),
    "region": ("region", "territory", "zone"),
    "category": ("category", "product_category"),
    "city": ("city", "location"),
    "salesperson": ("sales_rep", "salesperson", "representative", "agent"),
}


def _analytical_sheets(dataset_profile: DatasetProfile):
    return [
        (name, sheet) for name, sheet in dataset_profile.worksheets.items()
        if classify_worksheet(name, sheet)["role"] == "analytical"
    ]


def _find_measure(dataset_profile: DatasetProfile, request: str) -> tuple[str, str] | None:
    text = request.lower()
    requested_terms = []
    for intent, aliases in _MEASURE_TERMS.items():
        if re.search(rf"\b{re.escape(intent)}\b", text):
            requested_terms.extend(aliases)
    if not requested_terms:
        requested_terms = ["revenue", "sales", "amount", "value", "quantity"]

    candidates = []
    for sheet_name, sheet in _analytical_sheets(dataset_profile):
        for column in sheet.columns:
            if column.inferred_type != "numerical" or column.semantic_role == "identifier":
                continue
            name = column.column_name.lower()
            score = max((5 if term == name else 3 if term in name else 0 for term in requested_terms), default=0)
            if score:
                # Prefer explicit revenue/sales measures for the common phrase "sales".
                if "sales" in text and any(token in name for token in ("revenue", "sales_amount", "sales_value")):
                    score += 4
                candidates.append((score, sheet_name, column.column_name))
    if not candidates:
        return None
    _, sheet_name, column_name = sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))[0]
    return sheet_name, column_name


def _find_dimension(dataset_profile: DatasetProfile, request: str) -> tuple[str, str] | None:
    text = request.lower()
    for intent, aliases in _DIMENSION_TERMS.items():
        if not re.search(rf"\b{re.escape(intent)}s?\b", text):
            continue
        for sheet_name, sheet in _analytical_sheets(dataset_profile):
            for column in sheet.columns:
                name = column.column_name.lower()
                if column.inferred_type in {"categorical", "boolean"} and any(
                    alias in name for alias in aliases
                ) and 1 < column.unique_value_count <= 100:
                    return sheet_name, column.column_name
    return None


def _measure_label(column_name: str) -> str:
    """Create a readable label without treating unit suffixes as currency claims."""
    cleaned = re.sub(r"_(?:inr|usd|eur|gbp|jpy)$", "", column_name, flags=re.IGNORECASE)
    return cleaned.replace("_", " ").title()


def _next_operation_id(plan: WorkbookAnalyticsPlan, prefix: str) -> str:
    used = {operation.id for operation in plan.operations}
    candidate = prefix[:64]
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = f"{prefix[:64-len(tail)]}{tail}"
        suffix += 1
    return candidate


def _ensure_visualization(
    plan: WorkbookAnalyticsPlan, operation_id: str, chart_type: str,
    title: str, description: str,
) -> None:
    existing = [viz for viz in plan.visualizations if viz.operation_id == operation_id]
    if existing:
        # In focused mode use one unambiguous chart per requested operation.
        existing[0].chart_type = chart_type
        existing[0].title = title[:150]
        plan.visualizations = [
            viz for viz in plan.visualizations
            if viz.operation_id != operation_id or viz is existing[0]
        ]
        return
    plan.visualizations.append(VisualizationRecommendation(
        id=f"viz_{operation_id}"[:64], operation_id=operation_id,
        chart_type=chart_type, title=title[:150],
        description=description[:300], priority="high",
    ))


def _ensure_focused_request_operations(
    plan: WorkbookAnalyticsPlan, dataset_profile: DatasetProfile,
    request: str | None,
) -> None:
    """Fill essential, unambiguous request operations the LLM omitted.

    This is deliberately narrow: it only repairs explicit totals, requested
    time trends, and named categorical breakdowns. It does not invent a broad
    dashboard or calculate any values.
    """
    if not request:
        return
    text = request.lower()
    measure = _find_measure(dataset_profile, request)
    if measure is None:
        return
    sheet_name, measure_column = measure
    sheet = dataset_profile.worksheets[sheet_name]

    # Monthly/daily/etc. trend requests must produce a supported time-series
    # operation, even when a small model omits it or emits an invalid grouping.
    interval = _requested_interval(request)
    trend_requested = interval is not None or bool(re.search(
        r"\b(trend|over time|changes? month|month by month|day by day)\b", text
    ))
    if trend_requested:
        date_columns = [
            column.column_name for column in sheet.columns
            if column.inferred_type == "date" and column.non_null_count >= 2
        ]
        if len(date_columns) == 1:
            date_column = date_columns[0]
            matching = next((
                op for op in plan.operations
                if isinstance(op, TimeSeriesOperation)
                and op.worksheet_name == sheet_name
                and op.date_column == date_column
                and op.metric.column == measure_column
            ), None)
            if matching is None:
                matching = TimeSeriesOperation(
                    id=_next_operation_id(plan, "requested_time_series"),
                    operation_type="time_series", worksheet_name=sheet_name,
                    title=f"{interval.title() if interval else 'Time'} {_measure_label(measure_column)} Trend",
                    description=f"{_measure_label(measure_column)} aggregated by {interval or 'time interval'}.",
                    date_column=date_column, interval=interval or "month",
                    metric=MetricAggregation(
                        alias=f"{interval or 'period'}_{measure_column}"[:80],
                        function="sum", column=measure_column,
                    ), group_by_columns=[],
                )
                plan.operations.append(matching)
            _ensure_visualization(
                plan, matching.id, "line", matching.title,
                f"{_measure_label(measure_column)} over time.",
            )

    # Explicit totals should always have a scalar operation and a KPI.
    total_requested = bool(re.search(
        r"\b(?:show|display|give|calculate|what is|how much)\b.{0,45}\b(?:total|overall|sum)\b",
        text,
    )) or bool(re.search(r"\boverall total\b", text))
    if total_requested:
        scalar = next((
            op for op in plan.operations
            if op.worksheet_name == sheet_name
            and op.operation_type == "sum"
            and getattr(op, "column", None) == measure_column
        ), None)
        if scalar is None:
            scalar = SumOperation(
                id=_next_operation_id(plan, f"requested_total_{measure_column}"),
                operation_type="sum", worksheet_name=sheet_name,
                title=f"Total {_measure_label(measure_column)}",
                description=f"Sum of {_measure_label(measure_column)} over the requested records.",
                result_name=f"total_{measure_column}"[:80], column=measure_column,
            )
            plan.operations.append(scalar)
        if not any(kpi.operation_id == scalar.id for kpi in plan.kpis):
            plan.kpis.append(KPIRecommendation(
                id=f"kpi_{scalar.id}"[:64], operation_id=scalar.id,
                label=scalar.title[:100], description=scalar.description[:300],
                format_hint="decimal", priority="high",
            ))

    # A named breakdown/comparison should have one category aggregation chart.
    dimension = _find_dimension(dataset_profile, request)
    dimension_breakdown_requested = bool(re.search(
        r"\b(breakdown|compare|comparison|across|distribution)\b", text
    ))
    if dimension:
        _, requested_dimension_column = dimension
        dimension_phrase = requested_dimension_column.replace("_", " ")
        dimension_breakdown_requested = dimension_breakdown_requested or bool(re.search(
            rf"\b(?:by|per)\s+(?:all\s+)?{re.escape(dimension_phrase)}s?\b", text
        ))
    if dimension and dimension_breakdown_requested:
        dimension_sheet, dimension_column = dimension
        if dimension_sheet == sheet_name:
            group_op = next((
                op for op in plan.operations
                if isinstance(op, GroupByOperation)
                and op.worksheet_name == sheet_name
                and op.group_by_columns == [dimension_column]
                and any(a.function == "sum" and a.column == measure_column for a in op.aggregations)
            ), None)
            if group_op is None:
                group_op = GroupByOperation(
                    id=_next_operation_id(plan, f"requested_{dimension_column}_breakdown"),
                    operation_type="group_by", worksheet_name=sheet_name,
                    title=f"{_measure_label(measure_column)} by {dimension_column.replace('_', ' ').title()}",
                    description=f"Total {_measure_label(measure_column)} for each {dimension_column.replace('_', ' ')}.",
                    group_by_columns=[dimension_column],
                    aggregations=[MetricAggregation(
                        alias=f"total_{measure_column}"[:80], function="sum", column=measure_column,
                    )],
                )
                plan.operations.append(group_op)
            composition = bool(re.search(r"\b(share|shares|proportion|proportions|composition|percentage)\b", text))
            _ensure_visualization(
                plan, group_op.id, "pie" if composition else "bar",
                group_op.title, group_op.description,
            )

    # Do not allow multiple visualizations for the same operation in focused mode.
    by_operation: dict[str, list[VisualizationRecommendation]] = {}
    for viz in plan.visualizations:
        by_operation.setdefault(viz.operation_id, []).append(viz)
    duplicate_ids = {
        viz.id for items in by_operation.values() for viz in items[1:]
    }
    if duplicate_ids:
        plan.visualizations = [viz for viz in plan.visualizations if viz.id not in duplicate_ids]


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

    def _context_budget(self) -> tuple[int, object] | None:
        """Return (available prompt tokens, estimator) when the provider exposes them."""
        available = getattr(self.plan_generator, "available_prompt_tokens", None)
        estimate = getattr(self.plan_generator, "estimate_prompt_tokens", None)
        if (
            not isinstance(available, int)
            or isinstance(available, bool)
            or not callable(estimate)
        ):
            return None
        return available, estimate

    def _profile_char_budget(self, user_request: str | None = None) -> int | None:
        """
        Characters the serialized profile may use for this provider.

        Derived from the provider's real input budget minus the fixed system
        prompt and user-prompt framing, so the profile preparer's own
        reduction ladder (drop category values, then compact columns) runs
        before the provider rejects the request. Returns None when the
        provider does not expose a budget or when too little room remains to
        enforce a meaningful limit (the provider then reports the overflow).
        """
        budget = self._context_budget()
        if budget is None:
            return None
        available, estimate = budget
        fixed_tokens = estimate([
            {
                "role": "system",
                "content": self.prompt_builder.build_system_prompt(
                    user_request=bool(user_request and user_request.strip())
                ),
            },
            {"role": "user", "content": user_request or ""},
        ]) + USER_PROMPT_FRAMING_TOKENS
        chars = int((available - fixed_tokens) * CHARS_PER_ESTIMATED_TOKEN)
        return chars if chars >= MIN_PROFILE_CHARS else None

    def _fits_context(self, messages: list[dict[str, str]]) -> bool:
        """Whether ``messages`` fit the provider budget (True when unknown)."""
        budget = self._context_budget()
        if budget is None:
            return True
        available, estimate = budget
        return estimate(messages) <= available

    def generate_plan(
        self,
        dataset_profile: DatasetProfile,
        user_request: str | None = None,
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
            profile_char_budget = self._profile_char_budget(user_request)
            if profile_char_budget is None:
                prepared_profile = self.profile_preparer.prepare(
                    dataset_profile
                )
            else:
                prepared_profile = self.profile_preparer.prepare(
                    dataset_profile,
                    max_profile_chars=profile_char_budget,
                )

        except ProfilePreparationError:
            logger.exception("Dataset profile preparation failed.")
            raise

        # Step 2: Build LLM messages.
        try:
            messages = self.prompt_builder.build_messages(
                prepared_profile,
                user_request=user_request,
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
                echo = exc.generated_output or ""
                if len(echo) > MAX_REPAIR_ECHO_CHARS:
                    echo = echo[:MAX_REPAIR_ECHO_CHARS]
                request_messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": echo,
                    },
                    {
                        "role": "user",
                        "content": (
                            "Your previous JSON was valid JSON but did not satisfy "
                            "the required analytics-plan schema. Validation errors: "
                            f"{exc.validation_errors}. Correct the reported fields "
                            "and return a complete replacement JSON object. Do not use null for required scalar fields. The root "
                            "object must contain exactly these fields: plan_version, "
                            "workbook_summary, business_context, worksheet_analyses, filters, "
                            "operations, kpis, visualizations, key_questions, and "
                            "limitations. Do not wrap the object in a 'workbook' field. "
                            "Every operation must include its exact operation_type "
                            "discriminator. Use 'label' (never 'name') for KPI labels, "
                            "and 'chart_type' (never 'type') for visualizations. "
                            "Every KPI operation_id must exactly match the id of a "
                            "scalar operation (sum, average, count, min, max, or "
                            "distinct_count). If no scalar operation exists for a KPI, "
                            "add one for the same worksheet and column and reference "
                            "its id; never reference a group_by or other non-scalar "
                            "operation from a KPI. Every visualization operation_id must "
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
                if not echo.strip() or not self._fits_context(request_messages):
                    # Keep the correction request inside the context window by
                    # dropping the echoed output; the validation errors in the
                    # final message still identify what must be fixed.
                    request_messages = [
                        message
                        for message in request_messages
                        if message["role"] != "assistant"
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

            # Repair common request-mode mistakes deterministically before
            # sanitization: raw date grouping -> time_series, and explicit
            # natural-language date ranges -> mandatory inclusive filters.
            _repair_date_groupings(analytical_plan, dataset_profile, user_request)

            # Repair fixable model mistakes (currency formats, incompatible
            # chart types, operations that do not fit the data) instead of
            # rejecting the whole plan. The result is still fully validated.
            analytical_plan = sanitize_plan(analytical_plan, dataset_profile)
            _enforce_explicit_date_filter(analytical_plan, dataset_profile, user_request)
            _ensure_focused_request_operations(analytical_plan, dataset_profile, user_request)
            _remove_redundant_extreme_charts(analytical_plan, user_request)
            _ensure_requested_total_kpis(analytical_plan, user_request)

            # Small local models can return a syntactically valid narrative
            # plan while leaving all executable arrays empty. Do not send that
            # empty plan to Module 5 when the profile contains analyzable data.
            if not analytical_plan.operations and not (user_request and user_request.strip()):
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
                    # Last resort before failing: a profile-grounded plan that
                    # passes the same validation, so charts are still produced.
                    salvaged = (
                        None if (user_request and user_request.strip())
                        else deterministic_salvage_plan(analytical_plan, dataset_profile)
                    )
                    if salvaged is not None:
                        logger.warning(
                            "LLM plan could not be validated after correction; "
                            "using a deterministic profile-grounded plan. "
                            "Reason: %s",
                            exc,
                        )
                        analytical_plan = salvaged
                        break
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
                            "Keep the plan concise: at most 6 operations, 4 "
                            "visualizations, and 2 key questions. KPI operation_id "
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

        # Broaden a thin dashboard with profile-grounded charts; the helper
        # returns the plan unchanged unless the enlarged plan validates.
        if not (user_request and user_request.strip()):
            analytical_plan = augment_with_deterministic_charts(
                analytical_plan, dataset_profile,
            )

        logger.info(
            "Analytics plan generated and validated successfully."
        )

        return analytical_plan


def generate_analytics_plan(
    dataset_profile: DatasetProfile,
    user_request: str | None = None,
) -> WorkbookAnalyticsPlan:
    """Convenience function for generating a validated analytics plan."""

    planner = AnalyticsPlanner()
    return planner.generate_plan(dataset_profile, user_request=user_request)
