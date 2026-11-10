"""Classify profiled worksheets for analytics planning.

The classifier is deliberately conservative: it uses worksheet titles and
column metadata only. It never inspects or changes cell values and never
hardcodes a particular workbook or worksheet name.
"""

from __future__ import annotations

import re
from typing import Any


_REFERENCE_TITLE = re.compile(
    r"\b(guide|readme|metadata|dictionary|glossary|lookup|reference|"
    r"documentation|instructions?|schema|data.?catalog)\b",
    re.IGNORECASE,
)
_REFERENCE_HEADER = re.compile(
    r"\b(description|definition|issue|variation|expected|rule|"
    r"validation|meaning|notes?|introduced)\b",
    re.IGNORECASE,
)
_FIELD_HEADER = re.compile(
    r"\b(column|field|attribute|variable|parameter|property)\b",
    re.IGNORECASE,
)


def classify_worksheet(worksheet_name: str, worksheet: Any) -> dict[str, str]:
    """Return ``role`` and ``reason`` for a WorksheetProfile-like object.

    Roles are ``analytical``, ``reference``, ``empty`` or ``insufficient``.
    Reference sheets remain visible in workbook summaries but should not be
    used for business aggregations unless a future explicit workflow opts in.
    """

    columns = list(getattr(worksheet, "columns", []) or [])
    row_count = int(getattr(worksheet, "row_count", 0) or 0)

    if row_count <= 0 or not columns or not any(
        int(getattr(column, "non_null_count", 0) or 0) > 0
        for column in columns
    ):
        return {"role": "empty", "reason": "No usable populated rows or columns."}

    if _REFERENCE_TITLE.search(worksheet_name or ""):
        return {
            "role": "reference",
            "reason": "Worksheet title indicates documentation or reference content.",
        }

    headers = [
        " ".join(
            str(getattr(column, attr, "") or "")
            for attr in ("column_name", "original_name")
        ).strip()
        for column in columns
    ]
    has_field_header = bool(headers and _FIELD_HEADER.search(headers[0]))
    has_description_header = any(_REFERENCE_HEADER.search(header) for header in headers[1:])
    has_measure = any(
        getattr(column, "inferred_type", "") == "numerical"
        and getattr(column, "semantic_role", "") != "identifier"
        for column in columns
    )
    has_date = any(getattr(column, "inferred_type", "") == "date" for column in columns)

    if has_field_header and has_description_header and not has_measure and not has_date:
        return {
            "role": "reference",
            "reason": "Column/field descriptions indicate a data dictionary or test guide.",
        }

    if not has_measure and not has_date:
        usable_categorical = [
            column for column in columns
            if getattr(column, "inferred_type", "") in {"categorical", "boolean"}
            and getattr(column, "semantic_role", "") != "identifier"
        ]
        if not usable_categorical:
            return {
                "role": "insufficient",
                "reason": "No supported numerical, categorical or date fields were profiled.",
            }

    return {
        "role": "analytical",
        "reason": "Worksheet contains populated fields suitable for analytical review.",
    }
