"""Public data adapters used by the local valuation service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.parse import urljoin

import akshare as ak
import pandas as pd
import requests
from bs4 import BeautifulSoup

from valuation_service import normalize_name


THERMOMETER_URL = "https://youzhiyouxing.cn/thermometer"
EASTMONEY_FUND_URL = "https://fundf10.eastmoney.com/{code}.html"
INDEX_CODE_PATTERN = re.compile(r"\b([A-Z0-9]{6})\.(?:SH|SZ|CSI)\b", re.IGNORECASE)
PERCENT_PATTERN = re.compile(r"--|-?\d+(?:\.\d+)?%")


class SourceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    instrument_type: str
    tracked_index_code: str
    tracked_index_name: str


def _parse_pct(value: str) -> Optional[float]:
    return None if value == "--" else float(value.rstrip("%"))


def _parse_chinese_date(text: str) -> Optional[str]:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not match:
        return None
    return date(*(int(part) for part in match.groups())).isoformat()


def parse_thermometer_listing(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    update_match = re.search(
        r"温度更新时间[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日)",
        full_text,
    )
    as_of = _parse_chinese_date(update_match.group(1)) if update_match else None
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    grouped_links: dict[str, list[str]] = {}

    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "/data/indices/" not in href:
            continue
        grouped_links.setdefault(href, []).append(link.get_text(" ", strip=True))

    for href, fragments in grouped_links.items():
        text = " ".join(fragment for fragment in fragments if fragment)
        code_match = INDEX_CODE_PATTERN.search(text)
        if not code_match:
            continue
        before = text[: code_match.start()].strip()
        name = before.split()[-1] if before else ""
        values = text[code_match.end() :]
        temperature_match = re.search(r"(-?\d+(?:\.\d+)?)°", values)
        percentages = PERCENT_PATTERN.findall(values)
        if not name or not temperature_match or len(percentages) < 2:
            continue
        key = (code_match.group(1).upper(), name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "indexCode": key[0],
            "indexName": name,
            "temperature": float(temperature_match.group(1)),
            "intrinsicReturnPct": _parse_pct(percentages[0]),
            "dividendYieldPct": _parse_pct(percentages[1]),
            "asOf": as_of,
            "url": urljoin(THERMOMETER_URL, href),
        })

    if not rows:
        raise SourceError("THERMOMETER_FORMAT_CHANGED", "温度计页面结构已变化")
    return rows


def _labeled_percentage(text: str, label: str) -> Optional[float]:
    match = re.search(rf"{re.escape(label)}\s*(--|-?\d+(?:\.\d+)?)%", text)
    return _parse_pct(match.group(1)) if match else None


def _index_name_near_code(soup: BeautifulSoup) -> Optional[str]:
    code_node = soup.find(string=lambda value: bool(value and INDEX_CODE_PATTERN.search(value)))
    if code_node is None:
        return None
    previous = code_node.find_previous(string=lambda value: bool(value and value.strip()))
    return previous.strip() if previous else None


def parse_thermometer_detail(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    code_match = INDEX_CODE_PATTERN.search(text)
    temperature_match = re.search(r"(-?\d+(?:\.\d+)?)°\s*([^\s]+)", text)
    history_date_match = re.search(
        r"(\d{4}年\d{1,2}月\d{1,2}日)\s*指数温度",
        text,
    )
    heading = soup.find(["h1", "h2"])
    index_name = _index_name_near_code(soup)
    if index_name is None and heading is not None:
        index_name = heading.get_text(" ", strip=True)
    if not code_match or not temperature_match or not index_name:
        raise SourceError("THERMOMETER_FORMAT_CHANGED", "指数温度详情页结构已变化")
    return {
        "indexCode": code_match.group(1).upper(),
        "indexName": index_name,
        "temperature": float(temperature_match.group(1)),
        "valuationBand": temperature_match.group(2),
        "intrinsicReturnPct": _labeled_percentage(text, "内在收益率"),
        "dividendYieldPct": _labeled_percentage(text, "股息率"),
        "asOf": _parse_chinese_date(history_date_match.group(1)) if history_date_match else None,
        "url": url,
    }


def parse_tracking_target_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        for index, cell in enumerate(cells[:-1]):
            if cell.get_text(" ", strip=True) != "跟踪标的":
                continue
            target = cells[index + 1].get_text(" ", strip=True)
            if target and "无跟踪标的" not in target:
                return target
            raise SourceError("TRACKING_INDEX_NOT_FOUND", "该 ETF 没有可识别的跟踪指数")
    raise SourceError("TRACKING_INDEX_NOT_FOUND", "未找到 ETF 跟踪指数")


def _records(frame_or_rows: Any) -> list[Mapping[str, Any]]:
    if isinstance(frame_or_rows, pd.DataFrame):
        return frame_or_rows.to_dict("records")
    return list(frame_or_rows)


def frame_metric_points(
    frame_or_rows: Any,
    date_column: str,
    value_column: str,
) -> list[tuple[date, Any]]:
    points: list[tuple[date, Any]] = []
    for row in _records(frame_or_rows):
        raw_day = row.get(date_column)
        parsed = pd.to_datetime(raw_day, errors="coerce")
        if pd.isna(parsed):
            continue
        day = parsed.date()
        raw_value = row.get(value_column)
        try:
            value = float(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            value = raw_value
        points.append((day, value))
    return points


def fetch_tracking_target(code: str, session=requests, timeout: int = 10) -> str:
    response = session.get(
        EASTMONEY_FUND_URL.format(code=code),
        timeout=timeout,
        headers={"User-Agent": "GridStrategyGenerator/1.0"},
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return parse_tracking_target_html(response.text)


def fetch_thermometer_listing(session=requests, timeout: int = 10) -> list[dict[str, Any]]:
    response = session.get(
        THERMOMETER_URL,
        timeout=timeout,
        headers={"User-Agent": "GridStrategyGenerator/1.0"},
    )
    response.raise_for_status()
    return parse_thermometer_listing(response.text)


def fetch_thermometer_detail(url: str, session=requests, timeout: int = 10) -> dict[str, Any]:
    if not url.startswith("https://youzhiyouxing.cn/data/indices/"):
        raise SourceError("INVALID_SOURCE_URL", "温度计详情地址无效")
    response = session.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "GridStrategyGenerator/1.0"},
    )
    response.raise_for_status()
    return parse_thermometer_detail(response.text, url)


def _unique_index(target: str, index_rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    target_name = normalize_name(target)
    matches = [
        row for row in index_rows
        if normalize_name(row.get("display_name")) == target_name
    ]
    if len(matches) > 1:
        return {"index_code": "", "display_name": matches[0]["display_name"]}
    if not matches:
        raise SourceError("TRACKING_INDEX_NOT_FOUND", "ETF 跟踪指数未在指数目录中匹配")
    return matches[0]


class AkshareSource:
    def __init__(
        self,
        etf_rows: Optional[Callable[[], Any]] = None,
        tracking_target: Optional[Callable[[str], str]] = None,
        index_rows: Optional[Callable[[], Any]] = None,
        pe_history: Optional[Callable[[str], Any]] = None,
        pb_history: Optional[Callable[[str], Any]] = None,
    ):
        self._etf_rows = etf_rows or (lambda: ak.fund_etf_spot_em().to_dict("records"))
        self._tracking_target = tracking_target or fetch_tracking_target
        self._index_rows = index_rows or (lambda: ak.index_stock_info().to_dict("records"))
        self._pe_history = pe_history or ak.stock_index_pe_lg
        self._pb_history = pb_history or ak.stock_index_pb_lg

    def resolve(self, code: str) -> Instrument:
        indexes = _records(self._index_rows())
        etf = next(
            (
                row for row in _records(self._etf_rows())
                if str(row.get("代码", "")).zfill(6) == code
            ),
            None,
        )
        if etf is not None:
            index = _unique_index(self._tracking_target(code), indexes)
            tracked_index_code = str(index["index_code"] or "")
            return Instrument(
                code=code,
                name=str(etf.get("名称") or code),
                instrument_type="etf",
                tracked_index_code=tracked_index_code.zfill(6) if tracked_index_code else "",
                tracked_index_name=str(index["display_name"]),
            )

        index = next(
            (
                row for row in indexes
                if str(row.get("index_code", "")).zfill(6) == code
            ),
            None,
        )
        if index is None:
            raise SourceError("UNSUPPORTED_INSTRUMENT", "未识别为 A 股 ETF 或指数")
        return Instrument(code, str(index["display_name"]), "index", code, str(index["display_name"]))

    def pe_points(self, instrument: Instrument) -> list[tuple[date, Any]]:
        frame = self._pe_history(instrument.tracked_index_name)
        return frame_metric_points(frame, "日期", "滚动市盈率")

    def pb_points(self, instrument: Instrument) -> list[tuple[date, Any]]:
        frame = self._pb_history(instrument.tracked_index_name)
        return frame_metric_points(frame, "日期", "市净率")
