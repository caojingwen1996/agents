from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
from pyxirr import xirr

from .errors import DashboardError
from .models import (
    ChartPoint,
    DashboardReport,
    GridSummary,
    Metrics,
    Trade,
    TradeMarker,
    WorkbookData,
)


class CalculationError(DashboardError):
    pass


@dataclass
class _Lot:
    trade_date: date
    quantity: Decimal
    unit_cost: Decimal


@dataclass
class _GridLedger:
    lots: deque[_Lot]
    completed_cycles: int = 0
    sold_quantity: Decimal = Decimal("0")
    realized_profit: Decimal = Decimal("0")
    matched_cost: Decimal = Decimal("0")
    weighted_holding_days: Decimal = Decimal("0")

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), Decimal("0"))


def _money(value) -> Decimal:
    return Decimal(str(value))


def _normalized_prices(prices: pd.DataFrame) -> list[tuple[date, Decimal]]:
    if not {"date", "close"}.issubset(prices.columns):
        raise CalculationError("行情数据缺少 date 或 close 列")
    normalized = prices[["date", "close"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    normalized = normalized.dropna().sort_values("date").drop_duplicates("date", keep="last")
    rows = [
        (row.date.date(), _money(row.close))
        for row in normalized.itertuples(index=False)
        if row.close > 0
    ]
    if not rows:
        raise CalculationError("没有可用的历史行情")
    return rows


def _apply_overall_trade(
    trade: Trade,
    quantity: Decimal,
    cost: Decimal,
) -> tuple[Decimal, Decimal]:
    if trade.kind == "买入":
        return (
            quantity + trade.quantity,
            cost + trade.quantity * trade.price + trade.commission + trade.stamp_tax,
        )
    if trade.kind == "卖出":
        if trade.quantity > quantity:
            raise CalculationError(
                f"交易流水第 {trade.excel_row} 行：卖出数量超过整体可卖数量"
            )
        unit_cost = cost / quantity
        return quantity - trade.quantity, cost - unit_cost * trade.quantity
    return quantity, cost


def _replay_ledgers(workbook: WorkbookData):
    overall_quantity = Decimal("0")
    overall_cost = Decimal("0")
    grid_ledgers: dict[str, _GridLedger] = defaultdict(lambda: _GridLedger(deque()))
    cash_flows: dict[date, Decimal] = defaultdict(Decimal)
    withdrawal_count = 0

    for trade in workbook.trades:
        if trade.kind == "买入":
            total_cost = trade.quantity * trade.price + trade.commission + trade.stamp_tax
            ledger = grid_ledgers[trade.grid_id or ""]
            ledger.lots.append(_Lot(trade.trade_date, trade.quantity, total_cost / trade.quantity))
            cash_flows[trade.trade_date] -= total_cost
        elif trade.kind == "卖出":
            ledger = grid_ledgers[trade.grid_id or ""]
            available = ledger.quantity
            if trade.quantity > available:
                raise CalculationError(
                    f"交易流水第 {trade.excel_row} 行：网格 {trade.grid_id} "
                    f"卖出 {trade.quantity}，可卖数量仅 {available}"
                )
            sell_net = trade.quantity * trade.price - trade.commission - trade.stamp_tax
            sell_unit_net = sell_net / trade.quantity
            remaining = trade.quantity
            matched_cost = Decimal("0")
            while remaining > 0:
                lot = ledger.lots[0]
                matched = min(remaining, lot.quantity)
                lot_cost = matched * lot.unit_cost
                matched_cost += lot_cost
                ledger.weighted_holding_days += matched * Decimal(
                    (trade.trade_date - lot.trade_date).days
                )
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity == 0:
                    ledger.lots.popleft()
            ledger.sold_quantity += trade.quantity
            ledger.matched_cost += matched_cost
            ledger.realized_profit += sell_unit_net * trade.quantity - matched_cost
            if ledger.quantity == 0:
                ledger.completed_cycles += 1
            withdrawal_count += 1
            cash_flows[trade.trade_date] += sell_net
        else:
            cash_flows[trade.trade_date] += (
                trade.cash_amount - trade.commission - trade.stamp_tax
            )
        overall_quantity, overall_cost = _apply_overall_trade(
            trade, overall_quantity, overall_cost
        )
        if overall_quantity == 0:
            overall_cost = Decimal("0")

    return (
        overall_quantity,
        overall_cost,
        grid_ledgers,
        cash_flows,
        withdrawal_count,
    )


def _build_chart(
    workbook: WorkbookData,
    market_rows: list[tuple[date, Decimal]],
    first_price: Decimal,
):
    first_buy_date = next(trade.trade_date for trade in workbook.trades if trade.kind == "买入")
    baseline_date = (pd.Timestamp(first_buy_date) - pd.DateOffset(months=1)).date()
    visible_rows = [row for row in market_rows if row[0] >= baseline_date]
    if not visible_rows:
        raise CalculationError("首笔买入日之后没有可用行情")

    price_points = tuple(
        ChartPoint(day, close / first_price - 1, close) for day, close in visible_rows
    )
    cost_points = []
    quantity = Decimal("0")
    cost = Decimal("0")
    trade_index = 0
    trades = workbook.trades
    for market_date, _close in visible_rows:
        while trade_index < len(trades) and trades[trade_index].trade_date <= market_date:
            quantity, cost = _apply_overall_trade(trades[trade_index], quantity, cost)
            if quantity == 0:
                cost = Decimal("0")
            trade_index += 1
        if quantity > 0:
            unit_cost = cost / quantity
            cost_points.append(
                ChartPoint(market_date, unit_cost / first_price - 1, unit_cost)
            )

    markers = []
    for trade in trades:
        if trade.kind not in {"买入", "卖出"}:
            continue
        matching_row = next((row for row in visible_rows if row[0] >= trade.trade_date), None)
        if matching_row is None:
            raise CalculationError(
                f"交易流水第 {trade.excel_row} 行：交易日期之后缺少行情"
            )
        chart_date, chart_close = matching_row
        markers.append(
            TradeMarker(
                chart_date=chart_date,
                trade_date=trade.trade_date,
                kind=trade.kind,
                grid_id=trade.grid_id or "",
                value=chart_close / first_price - 1,
                price=trade.price,
                quantity=trade.quantity,
                note=trade.note,
            )
        )
    return price_points, tuple(cost_points), tuple(markers)


def _calculate_xirr(cash_flows: dict[date, Decimal]) -> Decimal | None:
    amounts = list(cash_flows.values())
    if not amounts or not any(value < 0 for value in amounts) or not any(
        value > 0 for value in amounts
    ):
        return None
    try:
        result = xirr(list(cash_flows.keys()), [float(value) for value in amounts])
    except (ValueError, TypeError, OverflowError):
        return None
    return None if result is None else Decimal(str(result))


def calculate_report(
    workbook: WorkbookData,
    prices: pd.DataFrame,
    stock_name: str,
) -> DashboardReport:
    market_rows = _normalized_prices(prices)
    first_buy = next(trade for trade in workbook.trades if trade.kind == "买入")
    latest_date, latest_close = market_rows[-1]
    if any(trade.trade_date > latest_date for trade in workbook.trades):
        raise CalculationError("交易流水包含晚于最新行情日的记录")

    (
        current_quantity,
        remaining_cost,
        ledgers,
        cash_flows,
        withdrawal_count,
    ) = _replay_ledgers(workbook)
    current_value = current_quantity * latest_close
    if current_quantity > 0:
        cash_flows[latest_date] += current_value

    price_points, cost_points, markers = _build_chart(
        workbook, market_rows, first_buy.price
    )
    visible_closes = [
        close for day, close in market_rows if day >= first_buy.trade_date
    ]
    grid_rows = []
    for grid_id in sorted(ledgers):
        ledger = ledgers[grid_id]
        grid_rows.append(
            GridSummary(
                grid_id=grid_id,
                completed_cycles=ledger.completed_cycles,
                sold_quantity=ledger.sold_quantity,
                realized_profit=ledger.realized_profit,
                return_rate=(
                    ledger.realized_profit / ledger.matched_cost
                    if ledger.matched_cost > 0
                    else None
                ),
                average_holding_days=(
                    ledger.weighted_holding_days / ledger.sold_quantity
                    if ledger.sold_quantity > 0
                    else None
                ),
            )
        )

    metrics = Metrics(
        position_return=(
            (current_value - remaining_cost) / remaining_cost
            if remaining_cost > 0
            else None
        ),
        xirr=_calculate_xirr(cash_flows),
        current_change=latest_close / first_buy.price - 1,
        max_decline_from_build=min(visible_closes) / first_buy.price - 1,
        withdrawal_count=withdrawal_count,
        position_percentage=current_value / workbook.settings.strategy_budget,
        running_days=(latest_date - first_buy.trade_date).days,
        build_date=first_buy.trade_date,
        calculation_date=latest_date,
        current_quantity=current_quantity,
        remaining_cost=remaining_cost,
    )
    return DashboardReport(
        title=workbook.settings.chart_title,
        stock_code=workbook.settings.stock_code,
        stock_name=stock_name,
        price_points=price_points,
        cost_points=cost_points,
        markers=markers,
        grid_rows=tuple(grid_rows),
        metrics=metrics,
    )
