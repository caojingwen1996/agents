import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import akshare as ak
import pandas as pd

from .errors import MarketDataError

MarketFetcher = Callable[[str, str, str], tuple[str, pd.DataFrame]]


@dataclass(frozen=True)
class MarketDataResult:
    name: str
    prices: pd.DataFrame
    warning: str | None
    as_of_date: date


def _extract_name(stock_code: str) -> str:
    try:
        info = ak.stock_individual_info_em(symbol=stock_code)
        if {"item", "value"}.issubset(info.columns):
            names = info.loc[info["item"].isin(["股票简称", "名称"]), "value"]
            if not names.empty:
                return str(names.iloc[0])
    except Exception:
        pass
    return stock_code


def _tencent_symbol(stock_code: str) -> str:
    if stock_code.startswith(("5", "60", "68", "69")):
        return f"sh{stock_code}"
    if stock_code.startswith(("4", "8")):
        return f"bj{stock_code}"
    return f"sz{stock_code}"


def fetch_a_share(stock_code: str, start_date: str, end_date: str):
    compact_start = start_date.replace("-", "")
    compact_end = end_date.replace("-", "")
    try:
        frame = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=compact_start,
            end_date=compact_end,
            adjust="",
        )
    except Exception as eastmoney_error:
        try:
            frame = ak.stock_zh_a_hist_tx(
                symbol=_tencent_symbol(stock_code),
                start_date=compact_start,
                end_date=compact_end,
                adjust="",
            )
        except Exception as tencent_error:
            raise RuntimeError(
                "东方财富和腾讯行情源均不可用："
                f"东方财富={type(eastmoney_error).__name__}，"
                f"腾讯={type(tencent_error).__name__}"
            ) from tencent_error
    return _extract_name(stock_code), frame.rename(columns={"日期": "date", "收盘": "close"})


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.rename(columns={"日期": "date", "收盘": "close"})
    if not {"date", "close"}.issubset(renamed.columns):
        raise MarketDataError("行情源返回数据缺少日期或收盘价")
    normalized = renamed[["date", "close"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    normalized = normalized.dropna()
    normalized = normalized[normalized["close"] > 0]
    return (
        normalized.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )


class MarketDataRepository:
    def __init__(self, cache_dir: str | Path, fetcher: MarketFetcher = fetch_a_share):
        self.cache_dir = Path(cache_dir)
        self.fetcher = fetcher

    def _paths(self, stock_code: str) -> tuple[Path, Path]:
        stem = f"{stock_code}-daily-none"
        return self.cache_dir / f"{stem}.csv", self.cache_dir / f"{stem}.json"

    def _read_cache(self, price_path: Path) -> pd.DataFrame:
        if not price_path.exists():
            return pd.DataFrame(columns=["date", "close"])
        try:
            return _normalize(pd.read_csv(price_path))
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            raise MarketDataError(f"行情缓存损坏：{price_path.name}（{exc}）") from exc

    def _read_name(self, metadata_path: Path, stock_code: str) -> str:
        if not metadata_path.exists():
            return stock_code
        try:
            return str(json.loads(metadata_path.read_text(encoding="utf-8"))["name"])
        except (OSError, ValueError, KeyError, TypeError):
            return stock_code

    def _write_cache(
        self,
        price_path: Path,
        metadata_path: Path,
        name: str,
        prices: pd.DataFrame,
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        price_tmp = price_path.with_suffix(".csv.tmp")
        metadata_tmp = metadata_path.with_suffix(".json.tmp")
        prices.to_csv(price_tmp, index=False, date_format="%Y-%m-%d")
        metadata_tmp.write_text(
            json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8"
        )
        price_tmp.replace(price_path)
        metadata_tmp.replace(metadata_path)

    def load(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> MarketDataResult:
        requested_start = date.fromisoformat(start_date)
        requested_end = date.fromisoformat(end_date)
        price_path, metadata_path = self._paths(stock_code)
        cached = self._read_cache(price_path)
        name = self._read_name(metadata_path, stock_code)

        fetch_start = requested_start
        if not cached.empty:
            cache_end = cached["date"].iloc[-1].date()
            fetch_start = max(requested_start, cache_end + timedelta(days=1))

        warning = None
        if fetch_start <= requested_end:
            try:
                fetched_name, fetched = self.fetcher(
                    stock_code,
                    fetch_start.isoformat(),
                    requested_end.isoformat(),
                )
                incoming = _normalize(fetched)
                name = fetched_name or name
                if not incoming.empty:
                    cached = (
                        incoming.copy()
                        if cached.empty
                        else _normalize(pd.concat([cached, incoming], ignore_index=True))
                    )
                if cached.empty:
                    raise MarketDataError("行情源没有返回可用数据")
                self._write_cache(price_path, metadata_path, name, cached)
            except Exception as exc:
                if cached.empty:
                    if isinstance(exc, MarketDataError):
                        detail = str(exc)
                    else:
                        detail = f"{type(exc).__name__}: {exc}"
                    raise MarketDataError(
                        f"无法获取 {stock_code} 行情：{detail}"
                    ) from exc
                as_of = cached["date"].iloc[-1].date()
                warning = f"行情获取失败，当前行情截至 {as_of.isoformat()}"

        if cached.empty:
            raise MarketDataError(f"无法获取 {stock_code} 行情：没有可用数据")
        available = cached[
            (cached["date"].dt.date >= requested_start)
            & (cached["date"].dt.date <= requested_end)
        ].reset_index(drop=True)
        if available.empty:
            raise MarketDataError(f"{stock_code} 在指定日期范围内没有行情")
        return MarketDataResult(
            name=name,
            prices=available,
            warning=warning,
            as_of_date=available["date"].iloc[-1].date(),
        )
