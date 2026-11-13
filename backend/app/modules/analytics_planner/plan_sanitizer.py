"""Deterministic clean-up of LLM analytics plans before dataset validation.

Small local models routinely produce plans that are structurally valid but
contain a few fixable mistakes (a currency format on an unitless profile, a
scatter chart, an operation on an unsuitable column, a duplicate chart).
Rejecting the whole plan for one such mistake wastes the generation, so this
module repairs or drops only the offending pieces. Nothing here calculates a
value, and the sanitized plan still has to pass ``validate_analytical_plan``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.modules.analytics_planner.deterministic_plan import (
    build_deterministic_fallback_plan,
)
from app.modules.analytics_planner.plan_validator import (
    AnalyticalPlanValidationError,
    AnalyticalPlanValidator,
    validate_analytical_plan,
)
from app.schemas.analytics_plan import WorkbookAnalyticsPlan
from app.schemas.data_understanding import DatasetProfile

logger = logging.getLogger(__name__)

# Same markers the validator rejects when the profile has no unit metadata.
_CURRENCY_MARKER = re.compile(
    r"[₹$€£¥]|\b(?:USD|INR|EUR|GBP|JPY|CAD|AUD)\b", re.IGNORECASE,
)
_CORRELATION = re.compile(r"\bcorrelat(?:e|es|ed|ion|ions)\b", re.IGNORECASE)

SCALAR_TYPES = {"sum", "average", "count", "min", "max", "distinct_count"}

# Chart types the validator accepts per non-scalar operation type; the first
# entry is the replacement used when the model chose an incompatible chart.
_CHARTS_BY_OPERATION: dict[str, tuple[str, ...]] = {
    "group_by": ("bar", "pie", "donut", "table"),
    "top_n": ("bar", "table"),
    "bottom_n": ("bar", "table"),
    "comparison": ("bar", "table"),
    "percentage_of_total": ("bar", "pie", "donut", "table"),
    "time_series": ("line", "area", "table"),
    "scatter": ("scatter",),
    "histogram": ("histogram", "table"),
}

MAX_OPERATIONS = 12
MAX_VISUALIZATIONS = 12
MAX_KPIS = 4
MAX_KEY_QUESTIONS = 2
MAX_LIMITATIONS = 15

# Charts the dashboard should aim for when the profile can support them.
DEFAULT_TARGET_VISUALIZATIONS = 4


def _clean_text(text: str) -> str:
    """Remove unsupported currency markers; never return an empty string."""
    if not isinstance(text, str):
        return text
    cleaned = re.sub(r"\s{2,}", " ", _CURRENCY_MARKER.sub("", text)).strip()
    return cleaned or "Not specified"


def _operation_signature(operation: Any) -> str:
    payload = operation.model_dump(mode="json")
    for cosmetic in ("id", "title", "description"):
        payload.pop(cosmetic, None)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _clean_narratives(plan: WorkbookAnalyticsPlan) -> None:
    plan.workbook_summary = _clean_text(plan.workbook_summary)
    plan.business_context.domain = _clean_text(plan.business_context.domain)
    plan.business_context.dataset_purpose = _clean_text(
        plan.business_context.dataset_purpose
    )
    for analysis in plan.worksheet_analyses:
        analysis.inferred_purpose = _clean_text(analysis.inferred_purpose)
        analysis.summary = _clean_text(analysis.summary)
        analysis.analysis_focus = [
            _clean_text(item) for item in analysis.analysis_focus
        ]
    for operation in plan.operations:
        operation.title = _clean_text(operation.title)
        operation.description = _clean_text(operation.description)
    for kpi in plan.kpis:
        kpi.label = _clean_text(kpi.label)
        kpi.description = _clean_text(kpi.description)
        # The profile carries no currency metadata, so a currency format would
        # be an invented unit. Show the same value as a plain decimal.
        if kpi.format_hint == "currency":
            kpi.format_hint = "decimal"
    for visualization in plan.visualizations:
        visualization.title = _clean_text(visualization.title)
        visualization.description = _clean_text(visualization.description)
    plan.key_questions = [
        _clean_text(question)
        for question in plan.key_questions
        if not _CORRELATION.search(question)
    ][:MAX_KEY_QUESTIONS]
    plan.limitations = [
        _clean_text(item) for item in plan.limitations
    ][:MAX_LIMITATIONS]


def _prune_operations(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
) -> None:
    """Drop operations that do not fit the real dataset, and duplicates."""
    validator = AnalyticalPlanValidator(dataset_profile)
    kept, seen = [], set()
    for operation in plan.operations:
        try:
            validator._validate_operation(operation)
        except (AnalyticalPlanValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "Dropping operation '%s' that does not fit the dataset: %s",
                operation.id, exc,
            )
            continue
        signature = _operation_signature(operation)
        if signature in seen:
            logger.warning(
                "Dropping duplicate operation '%s'.", operation.id,
            )
            continue
        seen.add(signature)
        kept.append(operation)
    plan.operations = kept[:MAX_OPERATIONS]


# Part-to-whole charts only make sense for a few additive categories.
_MAX_PART_TO_WHOLE_CATEGORIES = 6
_MAX_PART_TO_WHOLE_CHARTS = 2
# Beyond this many categories a bar chart is unreadable; show a table.
_MAX_BAR_CATEGORIES = 20
_ADDITIVE_FUNCTIONS = {"sum", "count", "distinct_count"}


def _column_profile(
    dataset_profile: DatasetProfile, worksheet: str, column: Optional[str],
) -> Any:
    sheet = dataset_profile.worksheets.get(worksheet)
    if sheet is None or column is None:
        return None
    return next((c for c in sheet.columns if c.column_name == column), None)


def _is_non_negative(
    dataset_profile: DatasetProfile, worksheet: str, aggregation: Any,
) -> bool:
    """Whether an additive measure is known to contain no negative values."""
    if aggregation.function == "count":
        return True
    column = _column_profile(dataset_profile, worksheet, aggregation.column)
    stats = getattr(column, "numerical_statistics", None)
    return stats is not None and stats.minimum is not None and stats.minimum >= 0


def _recommend_chart_type(
    operation: Any, dataset_profile: DatasetProfile, part_to_whole_used: int,
) -> Optional[str]:
    """
    Pick the chart that best fits what an operation computes.

    Returns None to keep the chart type the model chose. Bar remains the
    answer for rankings, comparisons and wide category sets.
    """
    kind = operation.operation_type

    if kind == "histogram":
        return "histogram"

    if kind == "scatter":
        return "scatter"

    if kind == "time_series":
        function = operation.metric.function
        # Cumulative-looking totals read well as areas; rates and averages as lines.
        return "area" if function in {"sum", "count"} else "line"

    if kind == "group_by":
        aggregation = operation.aggregations[0]
        dimension = _column_profile(
            dataset_profile, operation.worksheet_name,
            operation.group_by_columns[0],
        )
        categories = int(getattr(dimension, "unique_value_count", 0) or 0)
        if len(operation.group_by_columns) > 1 or categories < 2:
            return "table" if len(operation.group_by_columns) > 1 else None
        if categories > _MAX_BAR_CATEGORIES:
            return "table"
        if (
            categories <= _MAX_PART_TO_WHOLE_CATEGORIES
            and aggregation.function in _ADDITIVE_FUNCTIONS
            and _is_non_negative(
                dataset_profile, operation.worksheet_name, aggregation,
            )
            and part_to_whole_used < _MAX_PART_TO_WHOLE_CHARTS
        ):
            return "pie" if categories <= 4 else "donut"
        return "bar"

    if kind == "percentage_of_total":
        dimension = _column_profile(
            dataset_profile, operation.worksheet_name, operation.category_column,
        )
        value = _column_profile(
            dataset_profile, operation.worksheet_name, operation.value_column,
        )
        stats = getattr(value, "numerical_statistics", None)
        categories = int(getattr(dimension, "unique_value_count", 0) or 0)
        if (
            2 <= categories <= _MAX_PART_TO_WHOLE_CATEGORIES
            and stats is not None and stats.minimum is not None
            and stats.minimum >= 0
            and part_to_whole_used < _MAX_PART_TO_WHOLE_CHARTS
        ):
            return "donut"
        return "bar"

    return None


def _repair_visualizations(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
) -> None:
    """Keep charts linked to real non-scalar operations with valid types."""
    operations = {operation.id: operation for operation in plan.operations}
    kept, seen_ids = [], set()
    types_by_operation: dict[str, set[str]] = {}

    for visualization in plan.visualizations:
        operation = operations.get(visualization.operation_id)
        if operation is None or operation.operation_type in SCALAR_TYPES:
            continue
        if visualization.id in seen_ids:
            continue

        allowed = _CHARTS_BY_OPERATION.get(operation.operation_type)
        if not allowed:
            continue
        if visualization.chart_type not in allowed:
            visualization.chart_type = allowed[0]

        # Small models default to bar for everything. Replace that default
        # with the type that fits the computation; deliberate choices of any
        # other type are respected.
        if visualization.chart_type in {"bar", "line"}:
            recommended = _recommend_chart_type(
                operation, dataset_profile,
                sum(1 for v in kept if v.chart_type in {"pie", "donut"}),
            )
            if recommended in allowed:
                visualization.chart_type = recommended

        chosen = types_by_operation.setdefault(operation.id, set())
        chart_type = visualization.chart_type
        if (
            chart_type in chosen
            or len(chosen) >= 2
            or (chart_type in {"pie", "donut"} and chosen & {"pie", "donut"})
            or (chart_type in {"line", "area"} and chosen & {"line", "area"})
        ):
            continue
        chosen.add(chart_type)
        seen_ids.add(visualization.id)
        kept.append(visualization)

    plan.visualizations = kept[:MAX_VISUALIZATIONS]


def _repair_kpis(plan: WorkbookAnalyticsPlan) -> None:
    operations = {operation.id: operation for operation in plan.operations}
    kept, seen_ids = [], set()
    for kpi in plan.kpis:
        operation = operations.get(kpi.operation_id)
        if (
            operation is None
            or operation.operation_type not in SCALAR_TYPES
            or kpi.id in seen_ids
        ):
            continue
        seen_ids.add(kpi.id)
        kept.append(kpi)
    plan.kpis = kept[:MAX_KPIS]


def sanitize_plan(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
) -> WorkbookAnalyticsPlan:
    """Return a repaired copy of ``plan``; the input plan is not modified."""
    cleaned = plan.model_copy(deep=True)

    known = set(dataset_profile.worksheets)
    cleaned.worksheet_analyses = [
        item for item in cleaned.worksheet_analyses
        if item.worksheet_name in known
    ]
    _clean_narratives(cleaned)
    _prune_operations(cleaned, dataset_profile)
    _repair_kpis(cleaned)
    _repair_visualizations(cleaned, dataset_profile)
    return cleaned


def _unique(base: str, taken: set[str]) -> str:
    candidate, suffix = base[:60], 2
    while candidate in taken:
        candidate = f"{base[:56]}_{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def augment_with_deterministic_charts(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
    target_visualizations: int = DEFAULT_TARGET_VISUALIZATIONS,
) -> WorkbookAnalyticsPlan:
    """
    Top up a valid plan with profile-grounded charts when it has too few.

    Candidate operations come from the deterministic fallback builder (safe
    dimensions and measures only) and are added only if they are not already
    in the plan. The result must pass full dataset validation; otherwise the
    original plan is returned unchanged.
    """
    if len(plan.visualizations) >= target_visualizations:
        return plan
    try:
        fallback = build_deterministic_fallback_plan(dataset_profile, plan)
    except Exception:  # noqa: BLE001 - augmentation must never break a plan
        logger.exception("Deterministic chart augmentation failed.")
        return plan
    if fallback is None:
        return plan

    candidate = plan.model_copy(deep=True)
    operation_ids = {op.id for op in candidate.operations}
    visualization_ids = {viz.id for viz in candidate.visualizations}
    kpi_ids = {kpi.id for kpi in candidate.kpis}
    by_signature = {
        _operation_signature(op): op.id for op in candidate.operations
    }
    chart_pairs = {
        (viz.operation_id, viz.chart_type) for viz in candidate.visualizations
    }
    fallback_viz = {}
    for viz in fallback.visualizations:
        fallback_viz.setdefault(viz.operation_id, []).append(viz)
    fallback_kpi = {kpi.operation_id: kpi for kpi in fallback.kpis}
    added = False

    for operation in fallback.operations:
        is_scalar = operation.operation_type in SCALAR_TYPES
        if not is_scalar and len(candidate.visualizations) >= target_visualizations:
            continue
        if is_scalar and len(candidate.kpis) >= 2:
            continue

        signature = _operation_signature(operation)
        target_id = by_signature.get(signature)
        if target_id is None:
            if len(candidate.operations) >= MAX_OPERATIONS:
                continue
            target_id = _unique(operation.id, operation_ids)
            candidate.operations.append(
                operation.model_copy(update={"id": target_id})
            )
            by_signature[signature] = target_id
            added = True

        if is_scalar:
            kpi = fallback_kpi.get(operation.id)
            if kpi is not None and len(candidate.kpis) < MAX_KPIS:
                candidate.kpis.append(kpi.model_copy(update={
                    "id": _unique(kpi.id, kpi_ids),
                    "operation_id": target_id,
                }))
                added = True
            continue

        for viz in fallback_viz.get(operation.id, []):
            if (
                len(candidate.visualizations) >= target_visualizations
                or len(candidate.visualizations) >= MAX_VISUALIZATIONS
                or (target_id, viz.chart_type) in chart_pairs
            ):
                continue
            candidate.visualizations.append(viz.model_copy(update={
                "id": _unique(viz.id, visualization_ids),
                "operation_id": target_id,
            }))
            chart_pairs.add((target_id, viz.chart_type))
            added = True

    if not added:
        return plan

    candidate = sanitize_plan(candidate, dataset_profile)
    if len(candidate.limitations) < MAX_LIMITATIONS:
        candidate.limitations.append(
            "Additional charts were added deterministically from the "
            "dataset profile to broaden the dashboard."
        )
    try:
        validate_analytical_plan(candidate, dataset_profile)
    except AnalyticalPlanValidationError as exc:
        logger.warning(
            "Deterministic chart augmentation was discarded: %s", exc,
        )
        return plan
    return candidate


def deterministic_salvage_plan(
    plan: WorkbookAnalyticsPlan,
    dataset_profile: DatasetProfile,
) -> Optional[WorkbookAnalyticsPlan]:
    """Build a validated profile-grounded plan to replace an unusable one."""
    try:
        fallback = build_deterministic_fallback_plan(dataset_profile, plan)
        if fallback is None:
            return None
        fallback = sanitize_plan(fallback, dataset_profile)
        return validate_analytical_plan(fallback, dataset_profile)
    except Exception:  # noqa: BLE001 - caller keeps the original failure
        logger.exception("Deterministic salvage plan could not be built.")
        return None
