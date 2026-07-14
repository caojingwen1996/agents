from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from grid_dashboard.calculations import CalculationError, calculate_report
from grid_dashboard.models import Settings, Trade, WorkbookData


def trade(day, kind, grid, quantity, price, fee="0", tax="0", cash="0", row=2):
    return Trade(
        day,
        kind,
        grid,
        Decimal(quantity),
        Decimal(price),
        Decimal(fee),
        Decimal(tax),
        Decimal(cash),
        "",
        row,
    )


def prices(*rows):
    return pd.DataFrame(
        {
            "date": pd.to_datetime([row[0] for row in rows]),
            "close": [row[1] for row in rows],
        }
    )


def workbook(*trades, budget="100000"):
    return WorkbookData(
        Settings("000001", "网格提款足迹", "不复权", Decimal(budget)),
        tuple(trades),
    )


def test_round_trip_grid_profit_and_portfolio_metrics():
    data = workbook(
        trade(date(2025, 1, 2), "买入", "G3", "100", "10", fee="5"),
        trade(
            date(2025, 1, 10),
            "卖出",
            "G3",
            "100",
            "11",
            fee="5",
            tax="1.1",
            row=3,
        ),
    )

    report = calculate_report(
        data,
        prices(("2025-01-02", 10.0), ("2025-01-10", 11.0)),
        "平安银行",
    )

    assert report.metrics.withdrawal_count == 1
    assert report.metrics.position_return is None
    assert report.grid_rows[0].completed_cycles == 1
    assert report.grid_rows[0].realized_profit == Decimal("88.9")


def test_partial_sale_keeps_moving_average_cost_and_fifo_grid_profit():
    data = workbook(
        trade(date(2025, 1, 2), "买入", "G1", "100", "10", fee="10"),
        trade(date(2025, 1, 3), "买入", "G1", "100", "12", fee="10", row=3),
        trade(date(2025, 1, 4), "卖出", "G1", "100", "13", fee="5", tax="1", row=4),
    )

    report = calculate_report(
        data,
        prices(
            ("2025-01-02", 10),
            ("2025-01-03", 12),
            ("2025-01-04", 13),
        ),
        "平安银行",
    )

    assert report.metrics.remaining_cost == Decimal("1110")
    assert report.metrics.current_quantity == Decimal("100")
    assert report.grid_rows[0].realized_profit == Decimal("284")
    assert report.grid_rows[0].completed_cycles == 0


def test_grid_oversell_names_excel_row():
    data = workbook(
        trade(date(2025, 1, 2), "买入", "G3", "100", "10"),
        trade(date(2025, 1, 3), "卖出", "G3", "101", "11", row=8),
    )

    with pytest.raises(CalculationError, match="交易流水第 8 行.*G3.*可卖数量"):
        calculate_report(
            data,
            prices(("2025-01-02", 10), ("2025-01-03", 11)),
            "平安银行",
        )


def test_weekend_trade_marker_moves_to_next_market_day():
    data = workbook(
        trade(date(2025, 1, 4), "买入", "G2", "100", "10"),
    )

    report = calculate_report(
        data,
        prices(("2025-01-06", 10), ("2025-01-07", 11)),
        "平安银行",
    )

    assert report.markers[0].chart_date == date(2025, 1, 6)
    assert report.markers[0].trade_date == date(2025, 1, 4)
    assert report.metrics.position_percentage == Decimal("0.011")


def test_chart_keeps_buy_year_prices_before_first_buy_as_baseline():
    data = workbook(
        trade(date(2025, 2, 15), "买入", "G1", "100", "10"),
    )

    report = calculate_report(
        data,
        prices(
            ("2024-12-31", 8.5),
            ("2025-01-01", 9),
            ("2025-01-14", 9),
            ("2025-01-15", 9.5),
            ("2025-01-31", 10),
            ("2025-02-15", 11),
        ),
        "平安银行",
    )

    assert [point.date for point in report.price_points] == [
        date(2025, 1, 1),
        date(2025, 1, 14),
        date(2025, 1, 15),
        date(2025, 1, 31),
        date(2025, 2, 15),
    ]
    assert [point.date for point in report.cost_points] == [date(2025, 2, 15)]


def test_dividend_contributes_to_xirr_and_repeat_cycle_count():
    data = workbook(
        trade(date(2024, 1, 2), "买入", "G1", "100", "10"),
        trade(date(2024, 6, 1), "分红", None, "0", "0", cash="50", row=3),
        trade(date(2024, 7, 2), "卖出", "G1", "100", "11", row=4),
        trade(date(2024, 8, 2), "买入", "G1", "100", "10", row=5),
        trade(date(2025, 1, 2), "卖出", "G1", "100", "11", row=6),
    )

    report = calculate_report(
        data,
        prices(
            ("2024-01-02", 10),
            ("2024-07-02", 11),
            ("2024-08-02", 10),
            ("2025-01-02", 11),
        ),
        "平安银行",
    )

    assert report.grid_rows[0].completed_cycles == 2
    assert report.metrics.xirr is not None
    assert report.metrics.xirr > Decimal("0")
    assert report.metrics.withdrawal_count == 2
