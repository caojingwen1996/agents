"""Pure valuation rules and source orchestration for the local grid tool."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from dateutil.relativedelta import relativedelta


CODE_PATTERN = re.compile(r"^\d{6}$")
NAME_NOISE_PATTERN = re.compile(r"[\s\-_/（）()]+")
NAME_SUFFIX_PATTERN = re.compile(r"(?:全收益|指数|etf)$", re.IGNORECASE)


class ValuationError(Exception):
    """An expected error that is safe to return through the local API."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def validate_code(value: Any) -> str:
    code = str(value or "").strip()
    if not CODE_PATTERN.fullmatch(code):
        raise ValuationError("INVALID_CODE", "请输入 6 位 ETF 或指数代码")
    return code


def normalize_name(value: Any) -> str:
    normalized = NAME_NOISE_PATTERN.sub("", str(value or "")).lower()
    while True:
        trimmed = NAME_SUFFIX_PATTERN.sub("", normalized)
        if trimmed == normalized:
            return trimmed
        normalized = trimmed


def match_thermometer(
    rows: Sequence[Mapping[str, Any]],
    index_code: Any,
    index_name: Any,
) -> Optional[Mapping[str, Any]]:
    code = str(index_code or "").strip()
    if code:
        exact = next((row for row in rows if str(row.get("indexCode") or "") == code), None)
        if exact is not None:
            return exact

    target_name = normalize_name(index_name)
    if not target_name:
        return None
    matches = [row for row in rows if normalize_name(row.get("indexName")) == target_name]
    return matches[0] if len(matches) == 1 else None


def calculate_percentile(
    points: Iterable[Tuple[date, Any]],
) -> Optional[dict[str, Any]]:
    valid: list[Tuple[date, float]] = []
    for day, value in points:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if isinstance(day, date) and math.isfinite(numeric) and numeric > 0:
            valid.append((day, numeric))

    if not valid:
        return None

    valid.sort(key=lambda item: item[0])
    end = valid[-1][0]
    cutoff = end - relativedelta(years=10)
    window = [(day, value) for day, value in valid if day >= cutoff]
    current = window[-1][1]
    return {
        "currentValue": current,
        "percentilePct": sum(value <= current for _, value in window) / len(window) * 100,
        "startDate": window[0][0].isoformat(),
        "endDate": window[-1][0].isoformat(),
        "sampleCount": len(window),
    }
