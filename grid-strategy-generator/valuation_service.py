"""Pure valuation rules and source orchestration for the local grid tool."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: datetime
    value: dict[str, Any]


def _public_source_error(error: Exception) -> ValuationError:
    code = getattr(error, "code", "INSTRUMENT_LOOKUP_FAILED")
    message = getattr(error, "message", "无法识别标的代码")
    status = 422 if code in {
        "UNSUPPORTED_INSTRUMENT",
        "TRACKING_INDEX_NOT_FOUND",
        "AMBIGUOUS_INDEX",
    } else 502
    return ValuationError(code, message, status)


class ValuationService:
    """Apply source priority and return a stable, cacheable API response."""

    def __init__(
        self,
        source: Any,
        *,
        thermometer_listing: Any,
        thermometer_detail: Any,
        clock: Any = None,
        ttl: timedelta = timedelta(hours=1),
    ):
        self._source = source
        self._thermometer_listing = thermometer_listing
        self._thermometer_detail = thermometer_detail
        self._clock = clock or (lambda: datetime.now(timezone(timedelta(hours=8))))
        self._ttl = ttl
        self._cache: dict[str, _CacheEntry] = {}

    def lookup(self, raw_code: Any) -> dict[str, Any]:
        code = validate_code(raw_code)
        now = self._clock()
        cached = self._cache.get(code)
        if cached is not None and cached.expires_at > now:
            result = deepcopy(cached.value)
            result["cached"] = True
            return result

        try:
            instrument = self._source.resolve(code)
        except ValuationError:
            raise
        except Exception as error:
            raise _public_source_error(error) from error

        warnings: list[dict[str, str]] = []
        listing: Sequence[Mapping[str, Any]] = []
        thermometer_failed = False
        try:
            listing = self._thermometer_listing()
        except Exception:
            thermometer_failed = True

        match = match_thermometer(
            listing,
            instrument.tracked_index_code,
            instrument.tracked_index_name,
        )
        detail = None
        if match is not None:
            try:
                detail = self._thermometer_detail(match["url"])
            except Exception:
                thermometer_failed = True

        if thermometer_failed:
            warnings.append({
                "code": "THERMOMETER_UNAVAILABLE",
                "message": "温度计暂不可用",
            })

        queried_at = now.isoformat()
        if detail is not None:
            result = self._thermometer_result(instrument, detail, queried_at, warnings)
        else:
            result = self._percentile_result(instrument, queried_at, warnings)

        self._cache[code] = _CacheEntry(now + self._ttl, deepcopy(result))
        return result

    @staticmethod
    def _base_result(instrument: Any, queried_at: str, warnings: list[dict[str, str]]):
        return {
            "version": 1,
            "code": instrument.code,
            "name": instrument.name,
            "instrumentType": instrument.instrument_type,
            "trackedIndex": {
                "code": instrument.tracked_index_code,
                "name": instrument.tracked_index_name,
            },
            "queriedAt": queried_at,
            "cached": False,
            "warnings": warnings,
        }

    def _thermometer_result(
        self,
        instrument: Any,
        detail: Mapping[str, Any],
        queried_at: str,
        warnings: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            **self._base_result(instrument, queried_at, warnings),
            "source": "youzhiyouxing",
            "asOf": detail.get("asOf"),
            "thermometer": {
                "temperature": detail.get("temperature"),
                "valuationBand": detail.get("valuationBand"),
                "intrinsicReturnPct": detail.get("intrinsicReturnPct"),
                "dividendYieldPct": detail.get("dividendYieldPct"),
                "url": detail.get("url"),
            },
            "percentiles": None,
        }

    def _percentile_result(
        self,
        instrument: Any,
        queried_at: str,
        warnings: list[dict[str, str]],
    ) -> dict[str, Any]:
        pe = self._metric_or_none(self._source.pe_points, instrument)
        pb = self._metric_or_none(self._source.pb_points, instrument)
        if pe is None and pb is None:
            raise ValuationError("NO_VALUATION_DATA", "暂无估值数据", 502)
        dates = [metric["endDate"] for metric in (pe, pb) if metric is not None]
        return {
            **self._base_result(instrument, queried_at, warnings),
            "source": "historical_percentile",
            "asOf": max(dates),
            "thermometer": None,
            "percentiles": {"pe": pe, "pb": pb},
        }

    @staticmethod
    def _metric_or_none(fetcher: Any, instrument: Any) -> Optional[dict[str, Any]]:
        try:
            return calculate_percentile(fetcher(instrument))
        except Exception:
            return None
