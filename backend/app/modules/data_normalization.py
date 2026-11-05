"""Conservative, value-preserving normalization for Excel worksheets.

The normalizer standardizes recognizable values without performing data cleaning:
it does not replace missing markers, drop rows/columns, impute values, or discard
unknown categories. A value is converted only when its interpretation is
sufficiently reliable. Unrecognized values remain unchanged.

Public API compatibility is maintained through NormalizationConfig,
NormalizationResult, and normalize_workbook().
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.modules.excel_ingestion import WorkbookIngestionResult


# ---------------------------------------------------------------------------
# Configuration and result models (kept compatible with the existing pipeline)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizationConfig:
    normalize_values: bool = True
    ambiguous_dates_day_first: bool = True
    min_match_ratio: float = 0.80
    # Retained for backwards compatibility. Unknown values are now always
    # preserved; this option no longer causes unparseable values to be nulled.
    coerce_unparseable: bool = False
    # Retained for backwards compatibility. Missing markers are never changed.
    standardize_missing_values: bool = False
    standardize_text_case: bool = False
    boolean_as_yes_no: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.min_match_ratio <= 1:
            raise ValueError("min_match_ratio must be in the interval (0, 1].")


@dataclass(frozen=True)
class ColumnNameMapping:
    position: int
    original_name: Any
    normalized_name: str


@dataclass(frozen=True)
class ColumnTypeInfo:
    position: int
    original_name: Any
    normalized_name: str
    pandas_dtype: str
    data_category: str
    original_pandas_dtype: str = ""
    semantic_type: str = ""


@dataclass(frozen=True)
class ColumnValueNormalization:
    position: int
    original_name: Any
    normalized_name: str
    semantic_type: str
    target_format: str
    original_dtype: str
    normalized_dtype: str
    non_null_count: int
    cells_changed: int
    cells_nulled: int
    unparseable_count: int
    unparseable_samples: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class NormalizationResult:
    filename: str
    total_worksheet_count: int
    worksheet_names: List[str] = field(default_factory=list)
    worksheets: Dict[str, pd.DataFrame] = field(default_factory=dict)
    column_mappings: Dict[str, List[ColumnNameMapping]] = field(default_factory=dict)
    column_types: Dict[str, List[ColumnTypeInfo]] = field(default_factory=dict)
    worksheet_errors: Dict[str, str] = field(default_factory=dict)
    value_normalizations: Dict[str, List[ColumnValueNormalization]] = field(default_factory=dict)

    @property
    def successful_worksheet_count(self) -> int:
        return len(self.worksheets)

    @property
    def failed_worksheet_count(self) -> int:
        return len(self.worksheet_errors)


@dataclass
class _Outcome:
    series: pd.Series
    semantic_type: str
    target_format: str
    unparseable: List[str] = field(default_factory=list)
    unparseable_count: int = 0
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Header handling
# ---------------------------------------------------------------------------

_UNNAMED = re.compile(r"^unnamed:\s*\d+(_level_\d+)?$", re.I)


def _is_empty_header(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or bool(_UNNAMED.match(value.strip()))
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _base_column_name(value: Any, position: int) -> str:
    if _is_empty_header(value):
        return f"column_{position + 1}"
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return f"column_{position + 1}"
    if text[0].isdigit():
        text = f"column_{text}"
    return text


def _unique_name(base: str, used: Set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Shared scalar utilities
# ---------------------------------------------------------------------------

def _is_null(value: Any) -> bool:
    """Only actual null scalars are null; strings such as '-', 'N/A' stay intact."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if isinstance(result, (bool, np.bool_)) else False
    except (TypeError, ValueError):
        return False


def _comparison_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and math.isfinite(float(value)):
        n = float(value)
        return str(int(n)) if n.is_integer() else str(n)
    return None


def _display(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return repr(value)


def _same(a: Any, b: Any) -> bool:
    if _is_null(a) and _is_null(b):
        return True
    if _is_null(a) or _is_null(b):
        return False
    try:
        result = a == b
        return type(result) in (bool, np.bool_) and bool(result)
    except Exception:
        return False


def _series_preserving_values(values: List[Any], index: pd.Index, name: Any) -> pd.Series:
    """Build object output when mixed values must be preserved exactly."""
    return pd.Series(values, index=index, name=name, dtype=object)


def _hint(pattern: str, name: str) -> bool:
    return bool(re.search(pattern, name, flags=re.I))


# ---------------------------------------------------------------------------
# Semantic vocabularies. Unknown values are deliberately not mapped.
# ---------------------------------------------------------------------------

_ATTENDANCE = {
    "present": "Present", "pres": "Present", "prsnt": "Present",
    "attended": "Present", "attending": "Present", "here": "Present",
    "p": "Present", "pr": "Present", "1": "Present", "yes": "Present", "y": "Present", "true": "Present",
    "absent": "Absent", "abs": "Absent", "absnt": "Absent",
    "absentee": "Absent", "no show": "Absent", "noshow": "Absent",
    "not present": "Absent", "did not attend": "Absent", "a": "Absent", "0": "Absent", "no": "Absent", "n": "Absent", "false": "Absent",
    "ab": "Absent",
    "late": "Late", "tardy": "Late", "delayed": "Late", "late arrival": "Late",
    "leave": "Leave", "on leave": "Leave", "lv": "Leave", "sick": "Leave",
    "sick leave": "Leave", "medical leave": "Leave", "casual leave": "Leave",
    "vacation": "Leave", "pto": "Leave", "l": "Leave", "cl": "Leave", "sl": "Leave",
    "half day": "Half Day", "halfday": "Half Day", "half": "Half Day", "hd": "Half Day",
    "holiday": "Holiday", "hol": "Holiday", "weekly off": "Holiday",
    "week off": "Holiday", "day off": "Holiday", "wo": "Holiday", "h": "Holiday",
}

_GENDER = {
    "m": "Male", "male": "Male", "man": "Male", "boy": "Male", "gents": "Male",
    "f": "Female", "female": "Female", "woman": "Female", "girl": "Female",
    "ladies": "Female", "o": "Other", "other": "Other", "others": "Other",
    "nb": "Other", "non binary": "Other", "nonbinary": "Other",
    "transgender": "Other", "third gender": "Other",
    "prefer not to say": "Undisclosed", "undisclosed": "Undisclosed",
    "not specified": "Undisclosed",
}

_BOOLEAN = {
    "yes": True, "y": True, "true": True, "t": True, "1": True,
    "on": True, "yep": True, "yeah": True, "✓": True, "✔": True, "☑": True,
    "no": False, "n": False, "false": False, "f": False, "0": False,
    "off": False, "nope": False, "✗": False, "✘": False, "✕": False, "☐": False,
}

_STATUS = {
    "paid": "Paid", "unpaid": "Unpaid", "partially paid": "Partially Paid",
    "partial paid": "Partially Paid", "pending": "Pending", "overdue": "Overdue",
    "shipped": "Shipped", "shipping": "Shipped", "delivered": "Delivered",
    "in transit": "In Transit", "in-transit": "In Transit",
    "processing": "Processing", "processed": "Processed",
    "returned": "Returned", "refunded": "Refunded", "cancelled": "Cancelled",
    "canceled": "Cancelled", "open": "Open", "in progress": "In Progress",
    "resolved": "Resolved", "closed": "Closed", "on hold": "On Hold",
    "high": "High", "medium": "Medium", "low": "Low", "urgent": "Urgent",
    "critical": "Critical", "normal": "Normal",
}


# ---------------------------------------------------------------------------
# Date and time parsing
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?\s*([ap])?\.?m?\.?\s*$",
    re.I,
)
_HOUR_RE = re.compile(r"^\s*(\d{1,2})\s*([ap])\.?m\.?\s*$", re.I)
_NUMERIC_DATE = re.compile(r"^(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})(?:[ T](.+))?$")
_MONTH_YEAR = re.compile(
    r"^(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)[\s\-'/.,]*(\d{2}|\d{4})$",
    re.I,
)
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _parse_time(value: Any) -> Optional[str]:
    if isinstance(value, dt.time):
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _TIME_RE.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        second = int(match.group(3) or 0)
        meridiem = match.group(4)
        if meridiem:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
        if hour > 23 or minute > 59 or second > 59:
            return None
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    match = _HOUR_RE.match(text)
    if match:
        hour = int(match.group(1))
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if match.group(2).lower() == "p" else 0)
        return f"{hour:02d}:00:00"
    return None


def _parse_date(value: Any, day_first: bool, date_hint: bool) -> Optional[pd.Timestamp]:
    if isinstance(value, pd.Timestamp):
        stamp = value
    elif isinstance(value, dt.datetime):
        stamp = pd.Timestamp(value)
    elif isinstance(value, dt.date):
        stamp = pd.Timestamp(value)
    elif isinstance(value, np.datetime64):
        try:
            stamp = pd.Timestamp(value)
        except Exception:
            return None
    elif isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)):
        number = float(value)
        if not date_hint or not math.isfinite(number):
            return None
        # Excel serial date range. Do not reinterpret plausible year-like values.
        if 1 <= number <= 100000 and not (1900 <= number <= 2100):
            try:
                stamp = _EXCEL_EPOCH + pd.to_timedelta(number, unit="D")
            except Exception:
                return None
        elif number.is_integer() and 19000101 <= number <= 21001231:
            text = str(int(number))
            try:
                stamp = pd.Timestamp(year=int(text[:4]), month=int(text[4:6]), day=int(text[6:8]))
            except Exception:
                return None
        else:
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Strictly parse numeric dates ourselves to avoid inconsistent inference.
        match = _NUMERIC_DATE.match(text)
        if match:
            a, b, c, tail = match.groups()
            try:
                if len(a) == 4:
                    year, month, day = int(a), int(b), int(c)
                elif len(c) in (2, 4):
                    year = int(c) if len(c) == 4 else (2000 + int(c) if int(c) <= 68 else 1900 + int(c))
                    first, second = int(a), int(b)
                    day, month = (first, second) if day_first else (second, first)
                    if month > 12 and day <= 12:
                        day, month = month, day
                else:
                    return None
                stamp = pd.Timestamp(year=year, month=month, day=day)
                if tail:
                    parsed_time = _parse_time(tail)
                    if parsed_time is None:
                        # Permit ISO timestamps carrying a timezone offset or Z.
                        try:
                            stamp = pd.Timestamp(pd.to_datetime(text, errors="raise", utc=True))
                        except Exception:
                            return None
                    else:
                        hh, mm, ss = map(int, parsed_time.split(":"))
                        stamp = stamp + pd.Timedelta(hours=hh, minutes=mm, seconds=ss)
            except Exception:
                return None
        else:
            # Named month and ISO-like formats; pandas handles these well when
            # each cell is parsed independently.
            try:
                stamp = pd.to_datetime(text, dayfirst=day_first, errors="raise")
                stamp = pd.Timestamp(stamp)
            except Exception:
                return None
    else:
        return None

    try:
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return stamp.as_unit("ns") if hasattr(stamp, "as_unit") else stamp
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------

_CURRENCY_PREFIX = re.compile(r"^(?:[$€£¥₹]|rs\.?|inr|usd|eur|gbp)\s*", re.I)
_CURRENCY_SUFFIX = re.compile(r"\s+(?:[$€£¥₹]|rs\.?|inr|usd|eur|gbp)$", re.I)
_UNIT_SUFFIX = re.compile(
    r"\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?|months?|years?|"
    r"kg|kgs|g|grams?|mg|km|kms|m|cm|mm|l|litres?|liters?|ml|units?|pcs?|pieces?)\s*$",
    re.I,
)

_NUMBER_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}


def _parse_number_words(text: str) -> Optional[float]:
    """Parse common English number words (e.g. 'four', 'twenty five', 'one hundred')."""
    normalized = re.sub(r"[-,]", " ", text.casefold().strip())
    if " point " in f" {normalized} ":
        left, right = normalized.split(" point ", 1)
        whole = _parse_number_words(left)
        digit_words = right.split()
        if whole is None or not digit_words or any(w not in _NUMBER_WORDS or _NUMBER_WORDS[w] > 9 for w in digit_words):
            return None
        fraction = "".join(str(_NUMBER_WORDS[w]) for w in digit_words)
        return float(f"{int(whole)}.{fraction}")

    tokens = [w for w in normalized.split() if w != "and"]
    if not tokens:
        return None
    total = current = 0
    for word in tokens:
        if word in _NUMBER_WORDS:
            current += _NUMBER_WORDS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in {"thousand", "million", "billion"}:
            scale = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}[word]
            total += max(current, 1) * scale
            current = 0
        else:
            return None
    result = float(total + current)
    return result if math.isfinite(result) else None


def _parse_numeric(value: Any, column_name: str = "") -> Optional[Tuple[float, bool]]:
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)):
        number = float(value)
        return (number, False) if math.isfinite(number) else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    if text.startswith(("-", "−")):
        negative, text = True, text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    text = _CURRENCY_PREFIX.sub("", text)
    text = _CURRENCY_SUFFIX.sub("", text)
    unit_match = _UNIT_SUFFIX.search(text)
    unit = unit_match.group(1).casefold() if unit_match else ""
    if unit_match:
        text = text[:unit_match.start()].strip()

    # Natural-language quantities are common in operational spreadsheets.
    # Parse them only when a recognized unit is present, avoiding accidental
    # conversion of arbitrary text categories such as "fourth quarter".
    if unit and not re.search(r"\d", text):
        word_number = _parse_number_words(text)
        if word_number is None:
            return None
        if re.search(r"hours?|hrs?|resolution_time", column_name, re.I):
            if unit in {"minute", "minutes", "min", "mins"}:
                word_number /= 60.0
            elif unit in {"second", "seconds", "sec", "secs"}:
                word_number /= 3600.0
            elif unit in {"day", "days"}:
                word_number *= 24.0
        return (-word_number if negative else word_number), False

    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()

    # Spaces may be thousands separators, but only inside an otherwise numeric token.
    text = text.replace(" ", "").replace("\u00a0", "")
    if not re.fullmatch(r"\d[\d,]*(?:\.\d+)?|\.\d+", text):
        return None

    if "," in text:
        if "." in text:
            # Infer decimal separator from the last punctuation mark.
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif re.fullmatch(r"\d{1,2}(,\d{2})+,(\d{3})", text) or re.fullmatch(r"\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        elif re.fullmatch(r"\d+,\d{1,2}", text):
            text = text.replace(",", ".")
        else:
            return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    # Normalize explicit duration units when the destination column is clearly
    # measured in hours (e.g. avg_resolution_time). This keeps "45 minutes"
    # comparable with "3.5" and "four hours" in the same column.
    if re.search(r"hours?|hrs?|resolution_time", column_name, re.I):
        if unit in {"minute", "minutes", "min", "mins"}:
            number /= 60.0
        elif unit in {"second", "seconds", "sec", "secs"}:
            number /= 3600.0
        elif unit in {"day", "days"}:
            number *= 24.0
    return (-number if negative else number), percent


# ---------------------------------------------------------------------------
# Column inference and value-wise normalization
# ---------------------------------------------------------------------------

_DATE_HINT = r"(^|_)(date|dob|datetime|timestamp|created_at|updated_at|modified_at|due_date|joined_at|expiry|deadline)(_|$)"
_TIME_HINT = r"(^|_)(time|in_time|out_time|start_time|end_time|login_time|logout_time)(_|$)"
_IDENTIFIER_HINT = r"(^|_)(id|code|phone|mobile|contact|zip|pin|pincode|aadhaar|aadhar|ssn|reg|roll|account|acc|ifsc|isbn|sku|barcode)(_|$)"
_BOOLEAN_HINT = r"^(is|has|was|can|should|did|does)_.+|(^|_)(flag|enabled|active|eligible|verified|approved|paid|completed|passed|selected|available|required|opt_in|opted)(_|$)"
_ATTENDANCE_HINT = r"attend|(^|_)(presence|present|absent|absence)(_|$)"
_GENDER_HINT = r"(^|_)(gender|sex)(_|$)"
_STATUS_HINT = r"(^|_)(status|state|priority|level|type|category)(_|$)"
_NUMERIC_HINT = r"(^|_)(amount|price|cost|total|quantity|qty|count|number|num|hours|hrs|duration|score|rate|percent|percentage|salary|revenue|debit|credit|balance|worked|resolution_time)(_|$)"


def _match_ratio(matches: int, total: int) -> float:
    return matches / total if total else 0.0


def _normalize_column(
    series: pd.Series,
    name: str,
    config: NormalizationConfig,
    worksheet_attendance_context: bool = False,
) -> _Outcome:
    original = series.tolist()
    present_positions = [i for i, value in enumerate(original) if not _is_null(value)]
    present = [original[i] for i in present_positions]
    if not present:
        return _Outcome(series.copy(deep=True), "empty", str(series.dtype))

    attendance_hint = _hint(_ATTENDANCE_HINT, name)
    gender_hint = _hint(_GENDER_HINT, name)
    boolean_hint = _hint(_BOOLEAN_HINT, name)
    date_hint = _hint(_DATE_HINT, name)
    time_hint = _hint(_TIME_HINT, name)
    identifier_hint = _hint(_IDENTIFIER_HINT, name)
    status_hint = _hint(_STATUS_HINT, name)
    numeric_hint = _hint(_NUMERIC_HINT, name)

    # Native Boolean dtype is unambiguous.
    if ptypes.is_bool_dtype(series.dtype):
        return _Outcome(series.astype("boolean"), "boolean", "True/False")

    # Native datetime columns are already typed; normalize timezone to naive UTC.
    if ptypes.is_datetime64_any_dtype(series.dtype):
        out = series.copy(deep=True)
        notes: List[str] = []
        if getattr(out.dtype, "tz", None) is not None:
            out = out.dt.tz_convert("UTC").dt.tz_localize(None)
            notes.append("timezone-aware values converted to naive UTC")
        return _Outcome(out, "datetime", "datetime64[ns]", notes=notes)

    # Gender/boolean vocabularies are mapped per cell; unknown values survive.
    if gender_hint:
        mapped, changes = [], 0
        for value in original:
            key = _comparison_text(value)
            replacement = _GENDER.get(key) if key is not None else None
            if replacement is None:
                mapped.append(value)
            else:
                mapped.append(replacement)
                changes += not _same(value, replacement)
        if any(_comparison_text(v) in _GENDER for v in present):
            return _Outcome(_series_preserving_values(mapped, series.index, series.name),
                            "gender", "Male/Female/Other/Undisclosed",
                            notes=["Unrecognized gender categories were preserved."])
    if boolean_hint:
        mapped, changes, failures = [], 0, []
        for value in original:
            key = _comparison_text(value)
            if key in _BOOLEAN:
                replacement = ("Yes" if _BOOLEAN[key] else "No") if config.boolean_as_yes_no else _BOOLEAN[key]
                mapped.append(replacement)
                changes += not _same(value, replacement)
            else:
                mapped.append(value)
                if not _is_null(value):
                    failures.append(_display(value))
        if any(_comparison_text(v) in _BOOLEAN for v in present):
            return _Outcome(_series_preserving_values(mapped, series.index, series.name),
                            "boolean", "Yes/No" if config.boolean_as_yes_no else "True/False",
                            failures, len(failures),
                            ["Unrecognized values were preserved rather than nulled."])

    # Short attendance codes are ambiguous in isolation (P can mean Pending,
    # Paid, Priority, etc.). For generic status columns, interpret P/A only when
    # the worksheet contains strong attendance evidence in full words.
    if attendance_hint or (status_hint and worksheet_attendance_context):
        mapped, failures = [], []
        for value in original:
            key = _comparison_text(value)
            replacement = _ATTENDANCE.get(key) if key is not None else None
            if replacement is None:
                mapped.append(value)
                if not _is_null(value):
                    failures.append(_display(value))
            else:
                mapped.append(replacement)
        if any(_comparison_text(v) in _ATTENDANCE for v in present):
            return _Outcome(
                _series_preserving_values(mapped, series.index, series.name),
                "attendance", "canonical attendance labels; unknown values preserved",
                failures[:5], len(failures),
                ["Short attendance codes were interpreted using worksheet-level attendance evidence.",
                 "Unknown categories were preserved unchanged."],
            )

    # Known business status vocabulary. Unknown statuses remain byte-for-byte as
    # supplied (including abbreviations not in the controlled vocabulary).
    if status_hint:
        mapped, changes = [], 0
        for value in original:
            key = _comparison_text(value)
            replacement = _STATUS.get(key) if key is not None else None
            if replacement is None:
                mapped.append(value)
            else:
                mapped.append(replacement)
                changes += not _same(value, replacement)
        if any(_comparison_text(v) in _STATUS for v in present):
            return _Outcome(_series_preserving_values(mapped, series.index, series.name),
                            "categorical", "canonical known category labels",
                            notes=["Unknown categories were preserved unchanged."])

    # Dates are attempted before numeric parsing to avoid treating date-like
    # strings as quantities. A hinted date column may contain invalid entries;
    # valid cells are converted and invalid cells remain untouched.
    if date_hint or any(isinstance(v, (dt.date, dt.datetime, pd.Timestamp, np.datetime64)) for v in present):
        parsed = [_parse_date(v, config.ambiguous_dates_day_first, date_hint) for v in present]
        matched = sum(v is not None for v in parsed)
        should_parse = matched > 0 and (date_hint or _match_ratio(matched, len(present)) >= config.min_match_ratio)
        if should_parse:
            values = list(original)
            for pos, parsed_value in zip(present_positions, parsed):
                if parsed_value is not None:
                    values[pos] = parsed_value
            failures = [_display(v) for v, p in zip(present, parsed) if p is None]
            if not failures and not any(_is_null(v) for v in original):
                out = pd.Series(values, index=series.index, name=series.name)
                try:
                    out = pd.to_datetime(out)
                except Exception:
                    out = _series_preserving_values(values, series.index, series.name)
            else:
                out = _series_preserving_values(values, series.index, series.name)
            semantic = "datetime" if any(
                isinstance(v, pd.Timestamp) and v.time() != dt.time(0, 0) for v in parsed if v is not None
            ) else "date"
            return _Outcome(out, semantic, "ISO 8601 date/datetime; invalid values preserved",
                            failures[:5], len(failures),
                            ["Invalid or ambiguous date values were preserved unchanged."] if failures else [])

    # Time columns: same value-wise strategy.
    if time_hint or (present and _match_ratio(sum(_parse_time(v) is not None for v in present), len(present)) >= config.min_match_ratio):
        parsed_times = [_parse_time(v) for v in present]
        matched = sum(v is not None for v in parsed_times)
        if matched and (time_hint or _match_ratio(matched, len(present)) >= config.min_match_ratio):
            values = list(original)
            for pos, parsed_value in zip(present_positions, parsed_times):
                if parsed_value is not None:
                    values[pos] = parsed_value
            failures = [_display(v) for v, p in zip(present, parsed_times) if p is None]
            return _Outcome(_series_preserving_values(values, series.index, series.name),
                            "time", "HH:MM:SS; unrecognized values preserved",
                            failures[:5], len(failures))

    # Numeric conversion is conservative for identifiers and generic columns.
    if not identifier_hint:
        parsed_numbers = [_parse_numeric(v, name) for v in present]
        matched = sum(v is not None for v in parsed_numbers)
        ratio = _match_ratio(matched, len(present))
        if matched and (numeric_hint or ratio >= config.min_match_ratio):
            # A generic column of only 0/1 is not automatically Boolean.
            percentages = [p for p in parsed_numbers if p is not None and p[1]]
            numbers = [None if p is None else p[0] for p in parsed_numbers]
            if percentages:
                bare = [p[0] for p in parsed_numbers if p is not None and not p[1]]
                pct = [p[0] for p in percentages]
                if bare and all(0 <= n <= 1 for n in bare) and any(n > 1 for n in pct):
                    numbers = [None if p is None else (p[0] * 100 if not p[1] else p[0]) for p in parsed_numbers]
            failures = [_display(v) for v, p in zip(present, parsed_numbers) if p is None]
            values = list(original)
            for pos, number in zip(present_positions, numbers):
                if number is not None:
                    values[pos] = number
            finite_numbers = [n for n in numbers if n is not None]
            integral = bool(finite_numbers) and all(float(n).is_integer() for n in finite_numbers)
            if not failures and not any(_is_null(v) for v in original):
                if integral:
                    out = pd.Series(pd.array(values, dtype="Int64"), index=series.index, name=series.name)
                    fmt = "Int64"
                else:
                    out = pd.to_numeric(pd.Series(values, index=series.index), errors="raise")
                    fmt = "float64"
            else:
                # Preserve null sentinels and unrecognized values exactly.
                out = _series_preserving_values(values, series.index, series.name)
                fmt = "mixed numeric/object"
            semantic = "percentage" if percentages else "numeric"
            notes = ["Unrecognized values were preserved unchanged."] if failures else []
            if percentages:
                notes.append("Percent signs removed; values represented as percentage points.")
            return _Outcome(out, semantic, fmt, failures[:5], len(failures), notes)

    # Text fallback is deliberately non-destructive: no case folding, title
    # casing, trimming, or replacement of unknown categories.
    return _Outcome(series.copy(deep=True), "text", str(series.dtype),
                    notes=["Values not confidently recognized were preserved unchanged."])


# ---------------------------------------------------------------------------
# Worksheet-level contextual inference
# ---------------------------------------------------------------------------

_ATTENDANCE_FULL_WORDS = {
    "present", "pres", "prsnt", "attended", "attending", "here",
    "absent", "abs", "absnt", "absentee", "no show", "noshow",
    "not present", "did not attend",
}
_PRESENT_WORDS = {"present", "pres", "prsnt", "attended", "attending", "here"}
_ABSENT_WORDS = {"absent", "abs", "absnt", "absentee", "no show", "noshow", "not present", "did not attend"}


def _column_has_attendance_context(dataframe: pd.DataFrame, target_position: int) -> bool:
    """Infer P/A only with evidence local to the column or aligned peer cells.

    This avoids turning a payment/status "P" into Present merely because an
    unrelated attendance column exists elsewhere in the worksheet.
    """
    target = dataframe.iloc[:, target_position].tolist()
    target_keys = [_comparison_text(value) for value in target]
    has_present = any(key in _PRESENT_WORDS for key in target_keys)
    has_absent = any(key in _ABSENT_WORDS for key in target_keys)
    if has_present and has_absent:
        return True

    short_positions = [(i, key) for i, key in enumerate(target_keys) if key in {"p", "pr", "a", "ab"}]
    if not short_positions:
        return False

    corroborated = 0
    for row_position, short_code in short_positions:
        expected = _PRESENT_WORDS if short_code in {"p", "pr"} else _ABSENT_WORDS
        row_has_matching_peer = False
        for peer_position in range(dataframe.shape[1]):
            if peer_position == target_position:
                continue
            peer_key = _comparison_text(dataframe.iat[row_position, peer_position])
            if peer_key in expected:
                row_has_matching_peer = True
                break
        if row_has_matching_peer:
            corroborated += 1
    # Require all observed short codes to have row-aligned corroboration.
    return corroborated == len(short_positions)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _classify_dtype(series: pd.Series, semantic_type: str = "") -> str:
    if semantic_type == "time":
        return "time"
    if semantic_type == "boolean":
        return "boolean"
    if semantic_type in {"numeric", "percentage"}:
        return "numeric"
    if semantic_type in {"date", "datetime"}:
        return "datetime"
    if semantic_type in {"attendance", "gender", "categorical"}:
        return "categorical"
    if semantic_type == "empty":
        return "empty"
    dtype = series.dtype
    if ptypes.is_bool_dtype(dtype):
        return "boolean"
    if ptypes.is_datetime64_any_dtype(dtype):
        return "datetime"
    if ptypes.is_numeric_dtype(dtype):
        return "numeric"
    if ptypes.is_object_dtype(dtype) or ptypes.is_string_dtype(dtype):
        non_null = series.dropna()
        if non_null.empty:
            return "empty"
        inferred = pd.api.types.infer_dtype(non_null, skipna=True)
        if inferred in {"integer", "floating", "mixed-integer-float", "decimal"}:
            return "numeric"
        if inferred in {"datetime", "datetime64", "date"}:
            return "datetime"
        if inferred in {"mixed", "mixed-integer", "mixed-integer-float"}:
            return "mixed"
        return "text/object"
    return "other"


def normalize_workbook(
    ingestion_result: WorkbookIngestionResult,
    config: Optional[NormalizationConfig] = None,
) -> NormalizationResult:
    """Normalize headers and recognizable cell values on copied worksheet frames.

    Missing-value markers and unknown categories are never changed. Each
    worksheet is isolated: a failure is recorded without stopping other sheets.
    """
    if not isinstance(ingestion_result, WorkbookIngestionResult):
        raise TypeError("ingestion_result must be a WorkbookIngestionResult instance.")
    settings = config or NormalizationConfig()

    normalized_worksheets: Dict[str, pd.DataFrame] = {}
    column_mappings: Dict[str, List[ColumnNameMapping]] = {}
    column_types: Dict[str, List[ColumnTypeInfo]] = {}
    value_normalizations: Dict[str, List[ColumnValueNormalization]] = {}
    worksheet_errors = dict(ingestion_result.worksheet_errors)

    for worksheet_name, original_df in ingestion_result.worksheets.items():
        try:
            used_names: Set[str] = set()
            mappings: List[ColumnNameMapping] = []
            types: List[ColumnTypeInfo] = []
            audits: List[ColumnValueNormalization] = []
            output_columns: List[pd.Series] = []
            normalized_names: List[str] = []
            for position, original_name in enumerate(original_df.columns):
                normalized_name = _unique_name(_base_column_name(original_name, position), used_names)
                normalized_names.append(normalized_name)
                mappings.append(ColumnNameMapping(position, original_name, normalized_name))

                original_series = original_df.iloc[:, position].copy(deep=True)
                if settings.normalize_values:
                    try:
                        outcome = _normalize_column(
                            original_series, normalized_name, settings,
                            worksheet_attendance_context=_column_has_attendance_context(original_df, position),
                        )
                    except Exception as exc:
                        outcome = _Outcome(
                            original_series.copy(deep=True), "unchanged", str(original_series.dtype),
                            notes=[f"Normalization safely skipped after error: {type(exc).__name__}: {exc}"],
                        )
                else:
                    outcome = _Outcome(original_series.copy(deep=True), "unchanged", str(original_series.dtype))

                new_series = outcome.series.copy(deep=True)
                new_series.name = normalized_name
                output_columns.append(new_series)

                before, after = original_series.tolist(), new_series.tolist()
                changed = sum(not _same(a, b) for a, b in zip(before, after))
                audits.append(ColumnValueNormalization(
                    position=position,
                    original_name=original_name,
                    normalized_name=normalized_name,
                    semantic_type=outcome.semantic_type,
                    target_format=outcome.target_format,
                    original_dtype=str(original_series.dtype),
                    normalized_dtype=str(new_series.dtype),
                    non_null_count=int(original_series.notna().sum()),
                    cells_changed=changed,
                    cells_nulled=0,
                    unparseable_count=outcome.unparseable_count,
                    unparseable_samples=list(outcome.unparseable),
                    notes=list(outcome.notes),
                ))
                types.append(ColumnTypeInfo(
                    position=position,
                    original_name=original_name,
                    normalized_name=normalized_name,
                    pandas_dtype=str(new_series.dtype),
                    data_category=_classify_dtype(new_series, outcome.semantic_type),
                    original_pandas_dtype=str(original_series.dtype),
                    semantic_type=outcome.semantic_type,
                ))

            if output_columns:
                normalized_df = pd.concat(output_columns, axis=1)
                normalized_df.columns = normalized_names
            else:
                normalized_df = original_df.copy(deep=True)

            normalized_worksheets[worksheet_name] = normalized_df
            column_mappings[worksheet_name] = mappings
            column_types[worksheet_name] = types
            value_normalizations[worksheet_name] = audits
        except Exception as exc:
            worksheet_errors[worksheet_name] = (
                f"Unable to normalize worksheet '{worksheet_name}': {type(exc).__name__}: {exc}"
            )

    return NormalizationResult(
        filename=ingestion_result.filename,
        total_worksheet_count=ingestion_result.total_worksheet_count,
        worksheet_names=list(ingestion_result.worksheet_names),
        worksheets=normalized_worksheets,
        column_mappings=column_mappings,
        column_types=column_types,
        worksheet_errors=worksheet_errors,
        value_normalizations=value_normalizations,
    )
