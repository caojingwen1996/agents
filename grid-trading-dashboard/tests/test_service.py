from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from grid_dashboard.errors import DashboardError, MarketDataError
from grid_dashboard.market_data import MarketDataResult
from grid_dashboard.models import Settings, Trade, WorkbookData
from grid_dashboard.service import DashboardService


@dataclass(frozen=True)
class FakeReport:
    value: str

    def to_dict(self):
        return {"value": self.value, "warning": None}


def sample_workbook():
    return WorkbookData(
        Settings("000001", "测试", "不复权", Decimal("100000")),
        (
            Trade(
                date(2025, 1, 2),
                "买入",
                "G1",
                Decimal("100"),
                Decimal("10"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                "",
                2,
            ),
        ),
    )


class StubMarketRepository:
    def __init__(self, as_of=date(2025, 1, 3), warning=None):
        self.as_of = as_of
        self.warning = warning
        self.calls = []

    def load(self, code, start_date, end_date):
        self.calls.append((code, start_date, end_date))
        return MarketDataResult(
            "平安银行",
            pd.DataFrame(
                {"date": pd.to_datetime([self.as_of]), "close": [10.0]}
            ),
            self.warning,
            self.as_of,
        )


def test_failed_refresh_preserves_last_success(tmp_path):
    calls = 0

    def calculator(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DashboardError("计算失败")
        return FakeReport("first")

    service = DashboardService(
        tmp_path / "交易记录.xlsx",
        StubMarketRepository(),
        workbook_loader=lambda path: sample_workbook(),
        calculator=calculator,
        today=lambda: date(2025, 1, 3),
    )

    assert service.refresh()["value"] == "first"
    with pytest.raises(DashboardError, match="计算失败"):
        service.refresh()
    assert service.current()["value"] == "first"


def test_stale_cache_must_cover_latest_trade(tmp_path):
    data = sample_workbook()
    repository = StubMarketRepository(
        as_of=date(2025, 1, 1),
        warning="行情获取失败，当前行情截至 2025-01-01",
    )
    service = DashboardService(
        tmp_path / "交易记录.xlsx",
        repository,
        workbook_loader=lambda path: data,
        calculator=lambda *args: FakeReport("unused"),
        today=lambda: date(2025, 1, 3),
    )

    with pytest.raises(MarketDataError, match="缓存行情不足以覆盖交易流水"):
        service.refresh()


def test_market_warning_is_attached_to_report(tmp_path):
    repository = StubMarketRepository(warning="行情已缓存")
    service = DashboardService(
        tmp_path / "交易记录.xlsx",
        repository,
        workbook_loader=lambda path: sample_workbook(),
        calculator=lambda *args: FakeReport("ok"),
        today=lambda: date(2025, 1, 3),
    )

    result = service.refresh()

    assert result["warning"] == "行情已缓存"


def test_market_load_starts_on_first_day_of_buy_year(tmp_path):
    repository = StubMarketRepository()
    service = DashboardService(
        tmp_path / "交易记录.xlsx",
        repository,
        workbook_loader=lambda path: sample_workbook(),
        calculator=lambda *args: FakeReport("ok"),
        today=lambda: date(2025, 1, 3),
    )

    service.refresh()

    assert repository.calls == [("000001", "2025-01-01", "2025-01-03")]
