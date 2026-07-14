from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Callable

from .calculations import calculate_report
from .errors import MarketDataError
from .excel_io import load_workbook


def _one_calendar_month_before(day: date) -> date:
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, monthrange(year, month)[1]))


class DashboardService:
    def __init__(
        self,
        workbook_path: str | Path,
        market_repository,
        *,
        workbook_loader=load_workbook,
        calculator=calculate_report,
        today: Callable[[], date] = date.today,
    ):
        self.workbook_path = Path(workbook_path)
        self.market_repository = market_repository
        self.workbook_loader = workbook_loader
        self.calculator = calculator
        self.today = today
        self._last_success: dict | None = None

    @property
    def last_success(self) -> dict | None:
        return self._last_success

    def current(self) -> dict:
        if self._last_success is None:
            return self.refresh()
        return self._last_success

    def refresh(self) -> dict:
        workbook = self.workbook_loader(self.workbook_path)
        first_buy_date = min(
            trade.trade_date for trade in workbook.trades if trade.kind == "买入"
        )
        latest_trade_date = max(trade.trade_date for trade in workbook.trades)
        market = self.market_repository.load(
            workbook.settings.stock_code,
            _one_calendar_month_before(first_buy_date).isoformat(),
            self.today().isoformat(),
        )
        if market.as_of_date < latest_trade_date:
            raise MarketDataError(
                "缓存行情不足以覆盖交易流水："
                f"行情截至 {market.as_of_date.isoformat()}，"
                f"最新交易为 {latest_trade_date.isoformat()}"
            )
        report = self.calculator(workbook, market.prices, market.name)
        payload = report.to_dict()
        payload["warning"] = market.warning
        payload["market_as_of"] = market.as_of_date.isoformat()
        self._last_success = payload
        return payload
