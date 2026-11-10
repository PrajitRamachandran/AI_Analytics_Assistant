"""Small, deterministic normalization add-on prototype.

This is an isolated prototype, not a replacement for the production normalizer.
It is intended to run AFTER the existing header/value normalizer and BEFORE
data cleaning. It only converts values when the column name clearly specifies
a target unit/currency. Ambiguous and unsupported values are preserved.

Supported in this prototype:
- Explicit currency columns: *_inr, *_usd, *_gbp, *_eur
- Major/minor denominations: rupees/paise, dollars/cents, pounds/pence,
  euros/cents
- Explicit duration columns: *_hours, *_minutes, *_seconds
- Compound durations such as "1 hour 30 minutes"
- Safe Excel export of normalized worksheet DataFrames

No FX conversion, no LLM, no fuzzy matching, no missing-value changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class NormalizationChange:
    worksheet: str
    column: str
    row_position: int
    original_value: Any
    normalized_value: Any
    operation: str
    reason: str


@dataclass
class PrototypeReport:
    changed_cells: int = 0
    preserved_ambiguous_cells: int = 0
    preserved_unsupported_cells: int = 0
    changes: list[NormalizationChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PrototypeResult:
    worksheets: Dict[str, pd.DataFrame]
    report: PrototypeReport


_NUMBER = r"(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
_DURATION_TOKEN = re.compile(
    rf"(?P<number>{_NUMBER})\s*(?P<unit>milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b",
    re.IGNORECASE,
)
_CURRENCY_NUMBER = re.compile(
    rf"^\s*(?P<negative>\()?\s*(?P<sign>[+-])?\s*(?P<prefix>₹|rs\.?|inr|usd|us\$|eur|€|gbp|£|\$)?\s*"
    rf"(?P<number>{_NUMBER})\s*(?P<suffix>₹|rs\.?|inr|usd|us\$|eur|€|gbp|£|\$|rupees?|paise|paisa|dollars?|cents?|pounds?|pence|pennies|penny|euros?|eurocents?)?\s*\)?$",
    re.IGNORECASE,
)

_CURRENCY_TARGETS = {
    "inr": {
        "major": {"₹", "rs", "rs.", "inr", "rupee", "rupees"},
        "minor": {"paise", "paisa"},
        "minor_factor": Decimal("0.01"),
    },
    "usd": {
        "major": {"$", "usd", "us$", "dollar", "dollars"},
        "minor": {"cent", "cents"},
        "minor_factor": Decimal("0.01"),
    },
    "gbp": {
        "major": {"£", "gbp", "pound", "pounds"},
        "minor": {"pence", "penny", "pennies"},
        "minor_factor": Decimal("0.01"),
    },
    "eur": {
        "major": {"€", "eur", "euro", "euros"},
        "minor": {"cent", "cents", "eurocent", "eurocents"},
        "minor_factor": Decimal("0.01"),
    },
}

_DURATION_FACTORS_TO_SECONDS = {
    "ms": Decimal("0.001"),
    "msec": Decimal("0.001"),
    "msecs": Decimal("0.001"),
    "millisecond": Decimal("0.001"),
    "milliseconds": Decimal("0.001"),
    "s": Decimal("1"),
    "sec": Decimal("1"),
    "secs": Decimal("1"),
    "second": Decimal("1"),
    "seconds": Decimal("1"),
    "m": Decimal("60"),
    "min": Decimal("60"),
    "mins": Decimal("60"),
    "minute": Decimal("60"),
    "minutes": Decimal("60"),
    "h": Decimal("3600"),
    "hr": Decimal("3600"),
    "hrs": Decimal("3600"),
    "hour": Decimal("3600"),
    "hours": Decimal("3600"),
    "d": Decimal("86400"),
    "day": Decimal("86400"),
    "days": Decimal("86400"),
}

_DURATION_TARGETS = {
    "seconds": Decimal("1"),
    "second": Decimal("1"),
    "secs": Decimal("1"),
    "sec": Decimal("1"),
    "s": Decimal("1"),
    "minutes": Decimal("60"),
    "minute": Decimal("60"),
    "mins": Decimal("60"),
    "min": Decimal("60"),
    "hours": Decimal("3600"),
    "hour": Decimal("3600"),
    "hrs": Decimal("3600"),
    "hr": Decimal("3600"),
    "days": Decimal("86400"),
    "day": Decimal("86400"),
}


def _target_for_column(column_name: Any) -> Tuple[Optional[str], Optional[str]]:
    name = re.sub(r"[^a-z0-9]+", "_", str(column_name).casefold()).strip("_")
    currency_match = re.search(r"(?:^|_)(inr|usd|gbp|eur)(?:$|_)", name)
    if currency_match:
        return "currency", currency_match.group(1)

    duration_match = re.search(
        r"(?:^|_)(hours?|hrs?|minutes?|mins?|seconds?|secs?|days?)(?:$|_)", name
    )
    if duration_match:
        raw = duration_match.group(1)
        aliases = {
            "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
            "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
            "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
            "day": "days", "days": "days",
        }
        return "duration", aliases.get(raw, raw)
    return None, None


def _decimal_number(raw: str) -> Optional[Decimal]:
    cleaned = raw.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _parse_currency(value: Any, target: str) -> Tuple[Optional[Decimal], str]:
    if not isinstance(value, str):
        return None, "not_text"
    match = _CURRENCY_NUMBER.fullmatch(value)
    if not match:
        return None, "unparsed_currency"

    prefix = (match.group("prefix") or "").casefold().rstrip(".")
    suffix = (match.group("suffix") or "").casefold().rstrip(".")
    token = suffix or prefix
    number = _decimal_number(match.group("number"))
    if number is None:
        return None, "invalid_number"

    spec = _CURRENCY_TARGETS[target]
    if token:
        if token in spec["minor"]:
            number *= spec["minor_factor"]
            operation = f"{target.upper()} minor-to-major denomination"
        elif token in spec["major"]:
            operation = f"{target.upper()} major denomination"
        else:
            return None, "currency_mismatch"
    else:
        # A bare number is already in the target column's major unit.
        operation = f"{target.upper()} column context"

    if match.group("negative") or match.group("sign") == "-":
        number = -number
    return number, operation


def _parse_duration(value: Any, target: str) -> Tuple[Optional[Decimal], str]:
    if not isinstance(value, str) or not value.strip():
        return None, "not_text"

    text = value.strip().casefold()
    matches = list(_DURATION_TOKEN.finditer(text))
    if not matches:
        return None, "unparsed_duration"

    # Every non-whitespace character must belong to a parsed number/unit token.
    cursor = 0
    total_seconds = Decimal("0")
    for match in matches:
        gap = text[cursor:match.start()]
        if gap.strip() and gap.strip() not in {"+", "and", ","}:
            return None, "partial_or_ambiguous_parse"
        number = _decimal_number(match.group("number"))
        if number is None:
            return None, "invalid_number"
        unit = match.group("unit").casefold()
        total_seconds += number * _DURATION_FACTORS_TO_SECONDS[unit]
        cursor = match.end()

    if text[cursor:].strip():
        return None, "partial_or_ambiguous_parse"

    target_factor = _DURATION_TARGETS[target]
    result = total_seconds / target_factor
    return result, f"duration converted to {target}"


def normalize_worksheets(
    worksheets: Mapping[str, pd.DataFrame],
) -> PrototypeResult:
    """Normalize a mapping of worksheet names to DataFrames.

    The input DataFrames are never mutated. Only columns with explicit target
    units/currency in their names are eligible for unit conversion.
    """
    output: Dict[str, pd.DataFrame] = {}
    report = PrototypeReport()

    for sheet_name, source_df in worksheets.items():
        if not isinstance(source_df, pd.DataFrame):
            report.notes.append(f"{sheet_name}: skipped non-DataFrame worksheet")
            continue

        df = source_df.copy(deep=True)
        for column in df.columns:
            dimension, target = _target_for_column(column)
            if dimension is None:
                continue

            values = df[column].tolist()
            converted = list(values)
            for row_position, original in enumerate(values):
                if pd.isna(original) if not isinstance(original, (list, dict, tuple)) else False:
                    continue
                if not isinstance(original, str):
                    continue

                if dimension == "currency":
                    normalized, operation = _parse_currency(original, target)
                else:
                    normalized, operation = _parse_duration(original, target)

                if normalized is not None:
                    converted[row_position] = normalized
                    if str(normalized) != str(original):
                        report.changed_cells += 1
                        report.changes.append(
                            NormalizationChange(
                                worksheet=sheet_name,
                                column=str(column),
                                row_position=row_position,
                                original_value=original,
                                normalized_value=normalized,
                                operation=operation,
                                reason="Column name establishes an explicit target unit/currency.",
                            )
                        )
                elif operation in {"currency_mismatch", "partial_or_ambiguous_parse"}:
                    report.preserved_ambiguous_cells += 1
                    report.notes.append(
                        f"{sheet_name}.{column}[{row_position}]: preserved ambiguous value {original!r} ({operation})."
                    )
                elif operation not in {"not_text"}:
                    report.preserved_unsupported_cells += 1

            # Use object dtype so Decimal precision and preserved strings coexist.
            df[column] = pd.Series(converted, index=df.index, dtype=object)

        output[sheet_name] = df

    return PrototypeResult(worksheets=output, report=report)


def export_normalized_workbook(
    worksheets: Mapping[str, pd.DataFrame],
    output_path: str | Path,
) -> Path:
    """Export normalized worksheet DataFrames to a new .xlsx workbook."""
    path = Path(output_path)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Prototype export currently supports .xlsx output only.")
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, dataframe in worksheets.items():
            safe_name = str(sheet_name)[:31] or "Sheet"
            export_df = dataframe.copy(deep=True)
            # Excel numeric cells are written as int/float. Decimal arithmetic
            # is retained in the in-memory prototype result and audit; this
            # conversion is only at the XLSX serialization boundary.
            for column in export_df.columns:
                export_df[column] = export_df[column].map(
                    lambda value: float(value) if isinstance(value, Decimal) else value
                )
            export_df.to_excel(writer, sheet_name=safe_name, index=False)

    return path
