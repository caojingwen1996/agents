from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

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


@dataclass(frozen=True)
class ChartPoint:
    date: date
    value: Decimal
    raw_price: Decimal


@dataclass(frozen=True)
class TradeMarker:
    chart_date: date
    trade_date: date
    kind: TradeKind
    grid_id: str
    value: Decimal
    price: Decimal
    quantity: Decimal
    note: str


@dataclass(frozen=True)
class GridSummary:
    grid_id: str
    completed_cycles: int
    sold_quantity: Decimal
    realized_profit: Decimal
    return_rate: Decimal | None
    average_holding_days: Decimal | None


@dataclass(frozen=True)
class Metrics:
    position_return: Decimal | None
    xirr: Decimal | None
    current_change: Decimal
    max_decline_from_build: Decimal
    withdrawal_count: int
    position_percentage: Decimal
    running_days: int
    build_date: date
    calculation_date: date
    current_quantity: Decimal
    remaining_cost: Decimal


def _json_value(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


@dataclass(frozen=True)
class DashboardReport:
    title: str
    stock_code: str
    stock_name: str
    price_points: tuple[ChartPoint, ...]
    cost_points: tuple[ChartPoint, ...]
    markers: tuple[TradeMarker, ...]
    grid_rows: tuple[GridSummary, ...]
    metrics: Metrics
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "warning": self.warning,
            "price_points": [
                {
                    "date": point.date.isoformat(),
                    "value": float(point.value),
                    "raw_price": float(point.raw_price),
                }
                for point in self.price_points
            ],
            "cost_points": [
                {
                    "date": point.date.isoformat(),
                    "value": float(point.value),
                    "raw_price": float(point.raw_price),
                }
                for point in self.cost_points
            ],
            "markers": [
                {
                    field: _json_value(getattr(marker, field))
                    for field in marker.__dataclass_fields__
                }
                for marker in self.markers
            ],
            "grid_rows": [
                {
                    field: _json_value(getattr(row, field))
                    for field in row.__dataclass_fields__
                }
                for row in self.grid_rows
            ],
            "metrics": {
                field: _json_value(getattr(self.metrics, field))
                for field in self.metrics.__dataclass_fields__
            },
        }
