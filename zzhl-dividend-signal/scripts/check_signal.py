#!/usr/bin/env python
"""Check CSI Dividend Index dividend-yield signal and write local records."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib import error, request


INDEX_CODE = "000922"
LIXINGER_INDEX_PATH = "sh/000922/922"
LIXINGER_PUBLIC_URL = (
    "https://www.lixinger.com/equity/index/detail/"
    f"{LIXINGER_INDEX_PATH}/fundamental/valuation/dyr"
)
LIXINGER_API_URL = "https://open.lixinger.com/api/a/indice/fundamental"
LIXINGER_DEFAULT_DYR_METRIC = "dyr"
LOCAL_ENV_PATH = Path(".agents/skills/zzhl-dividend-signal/local.env")
LIXINGER_CACHE_PATH = Path("sources/manual/中证红利信号/理杏仁分位缓存.json")


@dataclass
class LixingerPercentile:
    date: str
    dividend_yield: float
    percentile_10y: float | None
    percentile_80_value: float | None
    source: str
    note: str


@dataclass
class Signal:
    run_date: str
    run_time: str
    index_date: str
    bond_date: str
    akshare_dividend_yield_2: float
    lixinger_date: str
    lixinger_dividend_yield: str
    lixinger_percentile_10y: str
    lixinger_percentile_80_value: str
    lixinger_source: str
    bond_10y_yield: float
    spread: float
    percentile_signal: str
    absolute_signal: str
    spread_signal: str
    headline_signal: str
    source_note: str


def import_akshare():
    try:
        import akshare as ak  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "缺少 AKShare。请在自动化使用的 Python 环境中安装：pip install akshare"
        ) from exc
    return ak


def load_local_env(path: Path = LOCAL_ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.lstrip("\ufeff").split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_lixinger_token(cli_token: str | None = None) -> str | None:
    if cli_token:
        return cli_token.strip()
    env = load_local_env()
    return (
        os.environ.get("LIXINGER_TOKEN")
        or os.environ.get("LIXINGER_API_TOKEN")
        or env.get("LIXINGER_TOKEN")
        or env.get("LIXINGER_API_TOKEN")
    )


def to_float(value) -> float:
    if value is None:
        raise ValueError("empty numeric value")
    if isinstance(value, str):
        value = value.strip().replace("%", "").replace(",", "")
    return float(value)


def first_existing(columns: Iterable[str], candidates: Iterable[str]) -> str:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    raise KeyError(f"missing expected columns; tried {', '.join(candidates)}")


def normalize_percentile(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100 if 0 <= value <= 1 else value


def nested_get(data: dict, path: list[str]):
    cur = data
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def post_json(url: str, payload: dict, timeout: int = 25) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_http_429(exc: Exception) -> bool:
    return isinstance(exc, error.HTTPError) and exc.code == 429


def read_lixinger_cache(date: str | None = None) -> LixingerPercentile | None:
    if not LIXINGER_CACHE_PATH.exists():
        return None
    try:
        rows = json.loads(LIXINGER_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    candidates = [
        row
        for row in rows
        if isinstance(row, dict) and (date is None or row.get("date") == date)
    ]
    if not candidates:
        candidates = [row for row in rows if isinstance(row, dict)]
    if not candidates:
        return None
    row = sorted(candidates, key=lambda item: str(item.get("date", "")))[-1]
    try:
        return LixingerPercentile(
            date=str(row.get("date", "")),
            dividend_yield=to_float(row.get("dividend_yield")),
            percentile_10y=(
                None
                if row.get("percentile_10y") in (None, "")
                else to_float(row.get("percentile_10y"))
            ),
            percentile_80_value=(
                None
                if row.get("percentile_80_value") in (None, "")
                else to_float(row.get("percentile_80_value"))
            ),
            source=str(row.get("source", "理杏仁缓存")),
            note=str(row.get("note", "来自本地缓存")),
        )
    except Exception:
        return None


def write_lixinger_cache(value: LixingerPercentile) -> None:
    if not value.date or value.dividend_yield <= 0:
        return
    LIXINGER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if LIXINGER_CACHE_PATH.exists():
        try:
            loaded = json.loads(LIXINGER_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = [row for row in loaded if isinstance(row, dict)]
        except Exception:
            rows = []
    rows = [row for row in rows if row.get("date") != value.date]
    rows.append(
        {
            "date": value.date,
            "dividend_yield": value.dividend_yield,
            "percentile_10y": value.percentile_10y,
            "percentile_80_value": value.percentile_80_value,
            "source": value.source,
            "note": value.note,
            "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    rows = sorted(rows, key=lambda row: str(row.get("date", "")))[-60:]
    LIXINGER_CACHE_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_lixinger_api_percentile(
    token: str,
    date: str,
    metric: str = LIXINGER_DEFAULT_DYR_METRIC,
) -> LixingerPercentile:
    payload = {
        "token": token,
        "date": date,
        "stockCodes": [INDEX_CODE],
        "metrics": [
            f"{metric}.weightedAvg",
            f"{metric}.y_10.weightedAvg",
        ],
    }
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0, 8, 20), start=1):
        if delay:
            time.sleep(delay)
        try:
            result = post_json(LIXINGER_API_URL, payload)
            break
        except Exception as exc:
            last_exc = exc
            if not is_http_429(exc) or attempt == 3:
                raise
    else:
        raise RuntimeError(f"理杏仁 Open API 请求失败：{last_exc}")

    if result.get("code") != 0:
        raise RuntimeError(f"理杏仁 Open API 返回失败：{result.get('msg') or result}")
    rows = result.get("data") or []
    if not rows:
        raise RuntimeError("理杏仁 Open API 未返回中证红利估值数据")

    row = rows[0]
    metric_obj = row.get(metric)
    if not isinstance(metric_obj, dict):
        raise RuntimeError(f"理杏仁 Open API 未返回指标 {metric}")

    current = nested_get(metric_obj, ["y_10", "weightedAvg", "latestVal"])
    if current is None:
        current = metric_obj.get("weightedAvg")
    percentile = normalize_percentile(
        nested_get(metric_obj, ["y_10", "weightedAvg", "latestValPos"])
    )
    y10 = nested_get(metric_obj, ["y_10", "weightedAvg"]) or {}
    candidates = [
        to_float(y10[key])
        for key in ("p80Val", "percentile80Val", "riskVal", "chanceVal")
        if y10.get(key) is not None
    ]
    percentile_80_value = max(candidates) if candidates else None

    return LixingerPercentile(
        date=str(row.get("date", date))[:10],
        dividend_yield=to_float(current),
        percentile_10y=percentile,
        percentile_80_value=percentile_80_value,
        source="理杏仁 Open API",
        note=f"endpoint=a/indice/fundamental, metric={metric}.weightedAvg",
    )


def extract_percent(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return to_float(match.group(1)) if match else None


def fetch_lixinger_public_percentile() -> LixingerPercentile:
    req = request.Request(
        LIXINGER_PUBLIC_URL,
        headers={"User-Agent": "Mozilla/5.0 zzhl-dividend-signal"},
    )
    with request.urlopen(req, timeout=60) as response:
        text = response.read().decode("utf-8", errors="replace")
    date_match = re.search(r"最后更新于：(\d{4}-\d{2}-\d{2})", text)
    current = extract_percent(r"当前值:\s*([0-9.]+)%", text)
    percentile = extract_percent(r"当前分位点\s*([0-9.]+)%", text)
    p80 = extract_percent(r"80%分位点\s*([0-9.]+)%", text)
    if current is None:
        raise RuntimeError("无法从理杏仁公开页面解析当前股息率")
    return LixingerPercentile(
        date=date_match.group(1) if date_match else "",
        dividend_yield=current,
        percentile_10y=percentile,
        percentile_80_value=p80,
        source="理杏仁公开页面",
        note=LIXINGER_PUBLIC_URL,
    )


def fetch_lixinger_percentile(date: str, token: str | None) -> LixingerPercentile:
    errors: list[str] = []
    cached = read_lixinger_cache(date)
    if cached:
        cached.source = "理杏仁本地缓存"
        cached.note = f"{cached.note}; 命中日期 {cached.date} 缓存，避免重复请求理杏仁"
        return cached

    if token:
        metric = (
            os.environ.get("LIXINGER_DYR_METRIC")
            or load_local_env().get("LIXINGER_DYR_METRIC")
            or LIXINGER_DEFAULT_DYR_METRIC
        )
        try:
            value = fetch_lixinger_api_percentile(token, date, metric=metric)
            write_lixinger_cache(value)
            return value
        except Exception as exc:
            errors.append(f"Open API 失败：{exc}")
            stale = read_lixinger_cache()
            if stale:
                stale.source = "理杏仁本地缓存"
                stale.note = f"{stale.note}; Open API 失败后使用最近缓存：{exc}"
                return stale
            if is_http_429(exc):
                return LixingerPercentile(
                    date="",
                    dividend_yield=0.0,
                    percentile_10y=None,
                    percentile_80_value=None,
                    source="理杏仁限流",
                    note=(
                        "Open API 返回 HTTP 429 Too Many Requests；"
                        "为避免加重限流，已跳过公开页面回退"
                    ),
                )
            try:
                public = fetch_lixinger_public_percentile()
                write_lixinger_cache(public)
                public.note = f"{public.note}; Open API 失败后回退：{exc}"
                return public
            except Exception as public_exc:
                errors.append(f"公开页面失败：{public_exc}")
    else:
        errors.append("未配置 LIXINGER_TOKEN")
        try:
            public = fetch_lixinger_public_percentile()
            write_lixinger_cache(public)
            return public
        except Exception as public_exc:
            errors.append(f"公开页面失败：{public_exc}")
            stale = read_lixinger_cache()
            if stale:
                stale.source = "理杏仁本地缓存"
                stale.note = f"{stale.note}; 公开页面失败后使用最近缓存：{public_exc}"
                return stale

    return LixingerPercentile(
        date="",
        dividend_yield=0.0,
        percentile_10y=None,
        percentile_80_value=None,
        source="理杏仁待验证",
        note="; ".join(errors),
    )


def evaluate_percentile(percentile: float | None) -> str:
    if percentile is None:
        return "历史分位点待验证"
    if percentile >= 80:
        return "强买入"
    if percentile >= 70:
        return "分批买入"
    if percentile < 50:
        return "观望"
    return "中性等待"


def evaluate_absolute(dividend_yield: float) -> str:
    if dividend_yield < 4.0:
        return "不买或少买"
    if dividend_yield < 5.0:
        return "小额定投"
    if dividend_yield <= 6.0:
        return "加大买入"
    return "重点买入"


def evaluate_spread(spread: float) -> str:
    if spread > 3.0:
        return "历史上偏强买点"
    if spread > 2.5:
        return "红利性价比较高"
    if spread >= 1.5:
        return "有配置价值"
    return "红利吸引力一般"


def fetch_signal(lixinger_token: str | None = None) -> Signal:
    ak = import_akshare()
    valuation = ak.stock_zh_index_value_csindex(symbol=INDEX_CODE)
    if valuation.empty:
        raise RuntimeError(f"AKShare did not return valuation data for {INDEX_CODE}")

    date_col = first_existing(valuation.columns, ["日期", "date"])
    dividend_col = first_existing(
        valuation.columns, ["股息率2", "股息率1", "股息率", "dividend_yield"]
    )

    valuation = valuation.copy()
    valuation[date_col] = valuation[date_col].astype(str)
    valuation["_date"] = valuation[date_col].apply(
        lambda value: datetime.fromisoformat(value[:10])
    )
    valuation["_dividend_yield"] = valuation[dividend_col].apply(to_float)
    valuation = valuation.sort_values("_date")

    latest = valuation.iloc[-1]
    latest_date = latest["_date"]
    index_date = latest_date.strftime("%Y-%m-%d")
    dividend_yield_2 = float(latest["_dividend_yield"])

    bond = ak.bond_zh_us_rate(start_date=latest_date.replace(year=latest_date.year - 10).strftime("%Y%m%d"))
    if bond.empty:
        raise RuntimeError("AKShare did not return China government bond yield data")
    bond_date_col = first_existing(bond.columns, ["日期", "date"])
    bond_rate_col = first_existing(bond.columns, ["中国国债收益率10年", "中国10年期国债"])
    bond = bond.copy()
    bond[bond_date_col] = bond[bond_date_col].astype(str)
    bond["_date"] = bond[bond_date_col].apply(
        lambda value: datetime.fromisoformat(value[:10])
    )
    bond["_bond_10y_yield"] = bond[bond_rate_col].apply(to_float)
    bond = bond[bond["_date"] <= latest_date].sort_values("_date")
    if bond.empty:
        raise RuntimeError("No bond-yield rows on or before the latest index valuation date")
    latest_bond = bond.iloc[-1]
    bond_10y = float(latest_bond["_bond_10y_yield"])
    spread = dividend_yield_2 - bond_10y

    lixinger = fetch_lixinger_percentile(index_date, lixinger_token)
    percentile_signal = evaluate_percentile(lixinger.percentile_10y)
    absolute_signal = evaluate_absolute(dividend_yield_2)
    spread_signal = evaluate_spread(spread)
    percentile_pass = (
        lixinger.percentile_10y is not None
        and lixinger.percentile_10y >= 80
    )
    headline = (
        "重点买入区间"
        if percentile_pass and spread >= 2.5
        else "未进入重点买入区间"
    )
    if lixinger.percentile_10y is None:
        headline = "历史分位点待验证，暂不判定重点买入区间"

    return Signal(
        run_date=datetime.now().strftime("%Y-%m-%d"),
        run_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        index_date=index_date,
        bond_date=latest_bond["_date"].strftime("%Y-%m-%d"),
        akshare_dividend_yield_2=dividend_yield_2,
        lixinger_date=lixinger.date,
        lixinger_dividend_yield=(
            "" if lixinger.dividend_yield <= 0 else f"{lixinger.dividend_yield:.2f}"
        ),
        lixinger_percentile_10y=(
            "" if lixinger.percentile_10y is None else f"{lixinger.percentile_10y:.2f}"
        ),
        lixinger_percentile_80_value=(
            ""
            if lixinger.percentile_80_value is None
            else f"{lixinger.percentile_80_value:.2f}"
        ),
        lixinger_source=lixinger.source,
        bond_10y_yield=bond_10y,
        spread=spread,
        percentile_signal=percentile_signal,
        absolute_signal=absolute_signal,
        spread_signal=spread_signal,
        headline_signal=headline,
        source_note=(
            "AKShare: stock_zh_index_value_csindex(000922, 股息率2), "
            f"bond_zh_us_rate; {lixinger.source}: {lixinger.note}"
        ),
    )


def write_csv(signal: Signal, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(signal.__dataclass_fields__.keys())
    rows = []
    if csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                row_run_date = row.get("run_date") or row.get("run_time", "")[:10]
                if row_run_date != signal.run_date:
                    rows.append({name: row.get(name, "") for name in fieldnames})
    rows.append(signal.__dict__)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(signal: Signal, md_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    percentile_text = (
        f"{float(signal.lixinger_percentile_10y):.2f}%"
        if signal.lixinger_percentile_10y
        else "待验证"
    )
    p80_text = (
        f"{float(signal.lixinger_percentile_80_value):.2f}%"
        if signal.lixinger_percentile_80_value
        else "待验证"
    )
    lixinger_yield_text = (
        signal.lixinger_dividend_yield + "%"
        if signal.lixinger_dividend_yield
        else "待验证"
    )
    percentile_met = (
        "待验证"
        if not signal.lixinger_percentile_10y
        else ("是" if float(signal.lixinger_percentile_10y) >= 80 else "否")
    )
    absolute_met = "是" if signal.akshare_dividend_yield_2 >= 4.0 else "否"
    spread_met = "是" if signal.spread >= 2.5 else "否"
    akshare_date_note = (
        "今日数据"
        if signal.index_date == signal.run_date
        else f"非今日数据，当前数据源最新日期为 {signal.index_date}"
    )
    text = f"""# 中证红利最新股息率信号

- 运行时间：{signal.run_time}
- AKShare 指数估值日期：{signal.index_date}（{akshare_date_note}）
- 理杏仁估值日期：{signal.lixinger_date or "待确认"}
- 10年国债收益率日期：{signal.bond_date}

## 判断

| 规则 | 当前值 | 是否满足条件 |
|---|---|---|
| 历史分位点：理杏仁近10年股息率分位 >= 80% | 理杏仁股息率：{lixinger_yield_text}；当前分位：{percentile_text}；80%分位点：{p80_text} | {percentile_met}（{signal.percentile_signal}） |
| 绝对股息率：AKShare 股息率2 >= 4.0% | AKShare 股息率2：{signal.akshare_dividend_yield_2:.2f}% | {absolute_met}（{signal.absolute_signal}） |
| 股债利差：AKShare 股息率2 - 中国10年国债收益率 >= 2.5% | {signal.akshare_dividend_yield_2:.2f}% - {signal.bond_10y_yield:.2f}% = {signal.spread:.2f}% | {spread_met}（{signal.spread_signal}） |

最终结论：{signal.headline_signal}

## 来源

- {signal.source_note}

## 说明

- 本记录只是按既定规则生成的观察信号，不构成投资建议。
- AKShare `股息率2` 用于绝对股息率和股债利差判断。
- 理杏仁市值加权股息率用于近10年历史分位判断。
- 若数据源字段、接口或口径变化，需要重新核对脚本。
"""
    md_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="sources/manual/中证红利信号")
    parser.add_argument("--lixinger-token", default=None)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    signal = fetch_signal(lixinger_token=get_lixinger_token(args.lixinger_token))
    write_csv(signal, output_dir / "中证红利每日信号.csv")
    write_markdown(signal, output_dir / "最新信号.md")
    percentile_print = (
        f"{signal.lixinger_percentile_10y}%"
        if signal.lixinger_percentile_10y
        else "待验证"
    )
    print(
        f"{signal.index_date} {signal.headline_signal}："
        f"AKShare股息率2 {signal.akshare_dividend_yield_2:.2f}%，"
        f"理杏仁分位 {percentile_print}，利差 {signal.spread:.2f}%"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"中证红利信号检查失败：{exc}", file=sys.stderr)
        raise
