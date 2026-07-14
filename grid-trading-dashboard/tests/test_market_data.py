import pandas as pd
import pytest

from grid_dashboard.errors import MarketDataError
from grid_dashboard import market_data
from grid_dashboard.market_data import MarketDataRepository


def test_tencent_symbol_maps_shanghai_etf_to_sh_prefix():
    assert market_data._tencent_symbol("512400") == "sh512400"


def test_fetcher_uses_sina_daily_history_for_shanghai_etf(monkeypatch):
    calls = []

    def sina(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-04"]),
                "close": [1.0, 1.1, 1.2],
            }
        )

    monkeypatch.setattr(market_data.ak, "fund_etf_hist_sina", sina)

    name, prices = market_data.fetch_a_share("512400", "2025-01-02", "2025-01-02")

    assert name == "512400"
    assert calls == [{"symbol": "sh512400"}]
    assert prices["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-02"]
    assert prices["close"].tolist() == [1.1]


def test_fetcher_appends_today_etf_spot_price_when_daily_history_is_stale(monkeypatch):
    monkeypatch.setattr(
        market_data.ak,
        "fund_etf_hist_sina",
        lambda **_kwargs: pd.DataFrame(
            {"date": pd.to_datetime(["2026-07-13"]), "close": [1.679]}
        ),
    )
    monkeypatch.setattr(
        market_data.ak,
        "fund_etf_spot_em",
        lambda: pd.DataFrame(
            {"代码": ["512400"], "数据日期": [pd.Timestamp("2026-07-14")], "最新价": [1.774]}
        ),
    )

    _name, prices = market_data.fetch_a_share("512400", "2026-07-13", "2026-07-14")

    assert prices["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-13", "2026-07-14"]
    assert prices["close"].tolist() == [1.679, 1.774]


def test_fetcher_uses_today_etf_spot_when_requested_day_has_no_daily_row(monkeypatch):
    monkeypatch.setattr(
        market_data.ak,
        "fund_etf_hist_sina",
        lambda **_kwargs: pd.DataFrame(
            {"date": pd.to_datetime(["2026-07-13"]), "close": [1.679]}
        ),
    )
    monkeypatch.setattr(
        market_data.ak,
        "fund_etf_spot_em",
        lambda: pd.DataFrame(
            {"代码": ["512400"], "数据日期": [pd.Timestamp("2026-07-14")], "最新价": [1.774]}
        ),
    )

    _name, prices = market_data.fetch_a_share("512400", "2026-07-14", "2026-07-14")

    assert prices["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-14"]
    assert prices["close"].tolist() == [1.774]


def test_second_load_fetches_only_dates_after_cache(tmp_path):
    calls = []

    def fetcher(code, start_date, end_date):
        calls.append((code, start_date, end_date))
        return "平安银行", pd.DataFrame(
            {"date": pd.to_datetime([start_date]), "close": [10.0]}
        )

    repository = MarketDataRepository(tmp_path, fetcher)

    repository.load("000001", "2025-01-02", "2025-01-02")
    result = repository.load("000001", "2025-01-02", "2025-01-03")

    assert calls == [
        ("000001", "2025-01-02", "2025-01-02"),
        ("000001", "2025-01-03", "2025-01-03"),
    ]
    assert result.name == "平安银行"
    assert result.as_of_date.isoformat() == "2025-01-03"


def test_load_backfills_dates_before_existing_cache(tmp_path):
    calls = []

    def fetcher(code, start_date, end_date):
        calls.append((code, start_date, end_date))
        return "平安银行", pd.DataFrame(
            {"date": pd.to_datetime([start_date]), "close": [10.0]}
        )

    repository = MarketDataRepository(tmp_path, fetcher)
    repository.load("000001", "2025-01-03", "2025-01-03")
    repository.load("000001", "2025-01-01", "2025-01-03")

    assert calls == [
        ("000001", "2025-01-03", "2025-01-03"),
        ("000001", "2025-01-01", "2025-01-02"),
    ]


def test_fetch_failure_returns_existing_cache_with_warning(tmp_path):
    repository = MarketDataRepository(
        tmp_path,
        lambda *args: (
            "平安银行",
            pd.DataFrame(
                {"date": pd.to_datetime(["2025-01-02"]), "close": [10.0]}
            ),
        ),
    )
    repository.load("000001", "2025-01-02", "2025-01-02")
    repository.fetcher = lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))

    result = repository.load("000001", "2025-01-02", "2025-01-03")

    assert result.warning == "行情获取失败，当前行情截至 2025-01-02"
    assert result.as_of_date.isoformat() == "2025-01-02"


def test_fetch_failure_without_cache_is_user_facing(tmp_path):
    repository = MarketDataRepository(
        tmp_path,
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(MarketDataError, match="无法获取 000001 行情"):
        repository.load("000001", "2025-01-02", "2025-01-03")


def test_cache_merge_deduplicates_dates_and_keeps_latest_value(tmp_path):
    responses = iter(
        [
            (
                "平安银行",
                pd.DataFrame(
                    {"date": pd.to_datetime(["2025-01-02"]), "close": [10.0]}
                ),
            ),
            (
                "平安银行",
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                        "close": [10.5, 11.0],
                    }
                ),
            ),
        ]
    )
    repository = MarketDataRepository(tmp_path, lambda *args: next(responses))
    repository.load("000001", "2025-01-02", "2025-01-02")

    result = repository.load("000001", "2025-01-02", "2025-01-03")

    assert result.prices["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-01-02",
        "2025-01-03",
    ]
    assert result.prices["close"].tolist() == [10.5, 11.0]


def test_default_fetcher_falls_back_to_tencent_when_eastmoney_fails(monkeypatch):
    def unavailable(**_kwargs):
        raise RuntimeError("eastmoney blocked")

    calls = []

    def tencent(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {"date": pd.to_datetime(["2025-01-02"]), "close": [10.0]}
        )

    monkeypatch.setattr(market_data.ak, "stock_zh_a_hist", unavailable)
    monkeypatch.setattr(market_data.ak, "stock_zh_a_hist_tx", tencent)
    monkeypatch.setattr(market_data, "_extract_name", lambda _code: "平安银行")

    name, prices = market_data.fetch_a_share("000001", "2025-01-02", "2025-01-03")

    assert name == "平安银行"
    assert calls == [
        {
            "symbol": "sz000001",
            "start_date": "20250102",
            "end_date": "20250103",
            "adjust": "",
        }
    ]
    assert prices.columns.tolist() == ["date", "close"]
