from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

TradeKind = Literal["买入", "卖出", "分红"]


@dataclass(frozen=True)
class Settings:
    stock_code: str
    chart_title: str
    adjustment: str
    strategy_budget: Decimal


@dataclass(frozen=True)
class Trade:
    trade_date: date
    kind: TradeKind
    grid_id: str | None
    quantity: Decimal
    price: Decimal
    commission: Decimal
    stamp_tax: Decimal
    cash_amount: Decimal
    note: str
    excel_row: int


@dataclass(frozen=True)
class WorkbookData:
    settings: Settings
    trades: tuple[Trade, ...]
