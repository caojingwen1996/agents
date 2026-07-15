from __future__ import annotations

import csv
import html
import json
import math
import subprocess
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WESTOCK = ROOT / "strategy-backtest-expert" / "skills" / "westock-data" / "scripts" / "index.js"
OUT = ROOT / "output" / "daily_dca_2008_report"
START = date(2008, 1, 1)
END = date(2026, 6, 5)
DAILY_AMOUNT = 100.0
MONTHLY_AMOUNT = 100.0

ASSETS = [
    {"code": "us.INX", "name": "标普500", "currency": "USD", "market": "美国"},
    {"code": "us.NDX", "name": "纳斯达克100", "currency": "USD", "market": "美国"},
    {"code": "sh000922", "name": "中证红利", "currency": "CNY", "market": "中国A股"},
]

TREND_FUND = {
    "code": "usQQQ.OQ",
    "name": "QQQ趋势定投",
    "currency": "USD",
    "market": "美国",
}


def run_westock_kline(code: str) -> list[dict[str, str]]:
    cmd = [
        "node",
        str(WESTOCK),
        "kline",
        code,
        "--period",
        "day",
        "--limit",
        "8000",
        "--fq",
        "qfq",
    ]
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "date" in line:
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 8:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5],
                "amount": parts[6],
                "exchange": parts[7],
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows


def to_float(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= 0:
        return None
    return number


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if not cashflows:
        return None
    if not any(v > 0 for _, v in cashflows) or not any(v < 0 for _, v in cashflows):
        return None
    start = cashflows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for flow_date, value in cashflows:
            years = (flow_date - start).days / 365.25
            total += value / ((1.0 + rate) ** years)
        return total

    low, high = -0.9999, 10.0
    low_v, high_v = npv(low), npv(high)
    while low_v * high_v > 0 and high < 1000:
        high *= 2
        high_v = npv(high)
    if low_v * high_v > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        mid_v = npv(mid)
        if abs(mid_v) < 1e-7:
            return mid
        if low_v * mid_v <= 0:
            high = mid
            high_v = mid_v
        else:
            low = mid
            low_v = mid_v
    return (low + high) / 2


def max_drawdown(values: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def backtest_asset(asset: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, object]]:
    raw = run_westock_kline(asset["code"])
    rows: list[dict[str, object]] = []
    shares = 0.0
    total_invested = 0.0
    cashflows: list[tuple[date, float]] = []
    account_values: list[float] = []
    value_to_cost: list[float] = []

    for row in raw:
        d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        if d < START or d > END:
            continue
        close = to_float(row["close"])
        if close is None:
            continue
        bought_shares = DAILY_AMOUNT / close
        shares += bought_shares
        total_invested += DAILY_AMOUNT
        value = shares * close
        cashflows.append((d, -DAILY_AMOUNT))
        account_values.append(value)
        value_to_cost.append(value / total_invested)
        rows.append(
            {
                "date": d.isoformat(),
                "close": close,
                "daily_invest": DAILY_AMOUNT,
                "shares_bought": bought_shares,
                "total_shares": shares,
                "total_invested": total_invested,
                "market_value": value,
                "profit": value - total_invested,
                "return_on_invested_pct": (value / total_invested - 1.0) * 100,
            }
        )

    if not rows:
        raise RuntimeError(f"No rows for {asset['code']} in evaluation window")

    final_date = datetime.strptime(str(rows[-1]["date"]), "%Y-%m-%d").date()
    final_value = float(rows[-1]["market_value"])
    cashflows.append((final_date, final_value))
    irr = xirr(cashflows)

    summary = {
        "code": asset["code"],
        "name": asset["name"],
        "market": asset["market"],
        "currency": asset["currency"],
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "trading_days": len(rows),
        "daily_amount": DAILY_AMOUNT,
        "total_invested": total_invested,
        "final_value": final_value,
        "profit": final_value - total_invested,
        "return_on_invested_pct": (final_value / total_invested - 1.0) * 100,
        "xirr_pct": None if irr is None else irr * 100,
        "max_account_drawdown_pct": max_drawdown(account_values) * 100,
        "max_value_to_cost_drawdown_pct": max_drawdown(value_to_cost) * 100,
        "first_close": rows[0]["close"],
        "last_close": rows[-1]["close"],
        "price_return_pct": (float(rows[-1]["close"]) / float(rows[0]["close"]) - 1.0) * 100,
    }
    return rows, summary


def backtest_trend_dca(asset: dict[str, str]) -> tuple[list[dict[str, object]], dict[str, object]]:
    raw = run_westock_kline(asset["code"])
    prices: list[dict[str, object]] = []
    for row in raw:
        d = datetime.strptime(row["date"], "%Y-%m-%d").date()
        if d > END:
            continue
        close = to_float(row["close"])
        if close is None:
            continue
        prices.append({"date": d, "close": close})

    rows: list[dict[str, object]] = []
    shares = 0.0
    total_invested = 0.0
    cashflows: list[tuple[date, float]] = []
    account_values: list[float] = []
    value_to_cost: list[float] = []
    current_active = True
    current_multiplier = 1
    next_active = current_active
    next_multiplier = current_multiplier
    last_month: tuple[int, int] | None = None
    investment_count = 0
    paused_months = 0

    for idx, row in enumerate(prices):
        d = row["date"]
        close = float(row["close"])
        is_month_first_trade = last_month != (d.year, d.month)
        can_evaluate = d >= START and idx >= 251
        if is_month_first_trade:
            last_month = (d.year, d.month)
            current_active = next_active
            current_multiplier = next_multiplier

            if can_evaluate and current_active:
                invest_amount = MONTHLY_AMOUNT * current_multiplier
                bought_shares = invest_amount / close
                shares += bought_shares
                total_invested += invest_amount
                cashflows.append((d, -invest_amount))
                investment_count += 1
            else:
                invest_amount = 0.0
                bought_shares = 0.0
                if can_evaluate:
                    paused_months += 1

            if idx >= 251:
                last_5 = [float(p["close"]) for p in prices[idx - 4 : idx + 1]]
                ma_values = []
                for ma_idx in range(idx - 4, idx + 1):
                    if ma_idx >= 199:
                        ma_window = prices[ma_idx - 199 : ma_idx + 1]
                        ma_values.append(sum(float(p["close"]) for p in ma_window) / 200)
                if len(ma_values) == 5 and all(price < ma for price, ma in zip(last_5, ma_values)):
                    signal_active = False
                elif len(ma_values) == 5 and all(price > ma for price, ma in zip(last_5, ma_values)):
                    signal_active = True
                else:
                    signal_active = current_active

                high_252 = max(float(p["close"]) for p in prices[idx - 251 : idx + 1])
                drawdown = close / high_252 - 1.0
                if signal_active:
                    if drawdown <= -0.20:
                        signal_multiplier = 3
                    elif drawdown <= -0.10:
                        signal_multiplier = 2
                    else:
                        signal_multiplier = 1
                else:
                    signal_multiplier = current_multiplier

                next_active = signal_active
                next_multiplier = signal_multiplier
            else:
                signal_active = current_active
                signal_multiplier = current_multiplier
                drawdown = None

            if can_evaluate:
                value = shares * close
                account_values.append(value)
                if total_invested > 0:
                    value_to_cost.append(value / total_invested)
                rows.append(
                    {
                        "date": d.isoformat(),
                        "close": close,
                        "monthly_invest": invest_amount,
                        "multiplier": current_multiplier if current_active else 0,
                        "active": current_active,
                        "signal_active_for_next_month": signal_active,
                        "signal_multiplier_for_next_month": signal_multiplier if signal_active else 0,
                        "drawdown_from_252d_high_pct": None if drawdown is None else drawdown * 100,
                        "shares_bought": bought_shares,
                        "total_shares": shares,
                        "total_invested": total_invested,
                        "market_value": value,
                        "profit": value - total_invested,
                        "return_on_invested_pct": 0.0 if total_invested == 0 else (value / total_invested - 1.0) * 100,
                    }
                )
        elif can_evaluate and shares > 0:
            value = shares * close
            account_values.append(value)
            if total_invested > 0:
                value_to_cost.append(value / total_invested)
            rows.append(
                {
                    "date": d.isoformat(),
                    "close": close,
                    "monthly_invest": 0.0,
                    "multiplier": current_multiplier if current_active else 0,
                    "active": current_active,
                    "signal_active_for_next_month": next_active,
                    "signal_multiplier_for_next_month": next_multiplier if next_active else 0,
                    "drawdown_from_252d_high_pct": None,
                    "shares_bought": 0.0,
                    "total_shares": shares,
                    "total_invested": total_invested,
                    "market_value": value,
                    "profit": value - total_invested,
                    "return_on_invested_pct": (value / total_invested - 1.0) * 100,
                }
            )

    if not rows or total_invested <= 0:
        raise RuntimeError(f"No investable rows for {asset['code']} in evaluation window")

    final_date = datetime.strptime(str(rows[-1]["date"]), "%Y-%m-%d").date()
    final_value = float(rows[-1]["market_value"])
    cashflows.append((final_date, final_value))
    irr = xirr(cashflows)
    invested_rows = [row for row in rows if float(row["monthly_invest"]) > 0]
    summary = {
        "code": asset["code"],
        "name": asset["name"],
        "market": asset["market"],
        "currency": asset["currency"],
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "trading_days": investment_count,
        "daily_amount": MONTHLY_AMOUNT,
        "total_invested": total_invested,
        "final_value": final_value,
        "profit": final_value - total_invested,
        "return_on_invested_pct": (final_value / total_invested - 1.0) * 100,
        "xirr_pct": None if irr is None else irr * 100,
        "max_account_drawdown_pct": max_drawdown(account_values) * 100,
        "max_value_to_cost_drawdown_pct": max_drawdown(value_to_cost) * 100,
        "first_close": rows[0]["close"],
        "last_close": rows[-1]["close"],
        "price_return_pct": (float(rows[-1]["close"]) / float(rows[0]["close"]) - 1.0) * 100,
        "investment_count": investment_count,
        "paused_months": paused_months,
        "max_multiplier": max(int(row["multiplier"]) for row in invested_rows) if invested_rows else 0,
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_pct(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def fmt_num(value: object, digits: int = 2) -> str:
    return f"{float(value):,.{digits}f}"


def render_html(summaries: list[dict[str, object]], curves: dict[str, list[dict[str, object]]]) -> None:
    rows_html = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(s['name']))}</td>"
        f"<td>{html.escape(str(s['currency']))}</td>"
        f"<td>{s['start']} 至 {s['end']}</td>"
        f"<td>{int(s['trading_days'])}</td>"
        f"<td>{fmt_num(s['total_invested'])}</td>"
        f"<td>{fmt_num(s['final_value'])}</td>"
        f"<td>{fmt_pct(s['return_on_invested_pct'])}</td>"
        f"<td>{fmt_pct(s['xirr_pct'])}</td>"
        f"<td>{fmt_pct(s['max_account_drawdown_pct'])}</td>"
        f"<td>{fmt_pct(s['price_return_pct'])}</td>"
        "</tr>"
        for s in summaries
    )
    all_points: list[tuple[date, float]] = []
    for points in curves.values():
        for point in points:
            all_points.append(
                (
                    datetime.strptime(str(point["date"]), "%Y-%m-%d").date(),
                    float(point["return_on_invested_pct"]),
                )
            )
    min_date = min(d for d, _ in all_points)
    max_date = max(d for d, _ in all_points)
    min_value = min(0.0, min(v for _, v in all_points))
    max_value = max(v for _, v in all_points)
    width, height = 1040, 420
    left, right, top, bottom = 64, 24, 24, 44
    plot_w = width - left - right
    plot_h = height - top - bottom
    date_span = max(1, (max_date - min_date).days)
    value_span = max(1.0, max_value - min_value)

    def xy(point_date: str, value: object) -> tuple[float, float]:
        d = datetime.strptime(point_date, "%Y-%m-%d").date()
        x = left + ((d - min_date).days / date_span) * plot_w
        y = top + (1.0 - ((float(value) - min_value) / value_span)) * plot_h
        return x, y

    colors = ["#2563eb", "#16a34a", "#dc2626", "#7c3aed"]
    polylines = []
    legend = []
    for idx, (name, points) in enumerate(curves.items()):
        coords = " ".join(
            f"{x:.1f},{y:.1f}"
            for x, y in (xy(str(p["date"]), p["return_on_invested_pct"]) for p in points)
        )
        color = colors[idx % len(colors)]
        polylines.append(
            f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.2" />'
        )
        legend.append(
            f'<span><i style="background:{color}"></i>{html.escape(name)}</span>'
        )
    y_ticks = [min_value + value_span * i / 4 for i in range(5)]
    grid = []
    for tick in y_ticks:
        y = top + (1.0 - ((tick - min_value) / value_span)) * plot_h
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e5eaf1" />'
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="#526070">{tick:.0f}%</text>'
        )
    svg_chart = f"""
<div class="legend">{''.join(legend)}</div>
<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="投入收益率曲线">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fff" />
  {''.join(grid)}
  <line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#b7c0cc" />
  <line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#b7c0cc" />
  <text x="{left}" y="{height - 12}" font-size="12" fill="#526070">{min_date.isoformat()}</text>
  <text x="{width - right}" y="{height - 12}" text-anchor="end" font-size="12" fill="#526070">{max_date.isoformat()}</text>
  {''.join(polylines)}
</svg>
"""
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>定投回测：标普500 vs 纳斯达克100 vs 中证红利 vs QQQ趋势定投</title>
<style>
body {{ margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; color: #1d2433; background: #f6f7f9; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 44px; }}
h1 {{ font-size: 28px; margin: 0 0 8px; }}
p {{ line-height: 1.65; }}
.panel {{ background: #fff; border: 1px solid #dde2ea; border-radius: 8px; padding: 18px; margin-top: 18px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ border-bottom: 1px solid #e8edf3; padding: 10px 8px; text-align: right; white-space: nowrap; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
th {{ color: #526070; font-weight: 600; }}
.chart {{ width: 100%; height: auto; display: block; }}
.legend {{ display: flex; gap: 18px; align-items: center; margin: 4px 0 12px; color: #526070; }}
.legend i {{ display: inline-block; width: 18px; height: 3px; margin-right: 7px; vertical-align: middle; }}
.note {{ color: #526070; font-size: 14px; }}
</style>
</head>
<body>
<main>
<h1>定投回测：标普500 vs 纳斯达克100 vs 中证红利 vs QQQ趋势定投</h1>
<p class="note">前三个指数按每个本市场交易日投入 100 个本币单位计算；QQQ趋势策略以每月基础金额 100 USD 为 1M，按每月第一个美股交易日检查趋势并执行。所有结果不计手续费、税费、汇率和现金利息。</p>
<section class="panel">
<table>
<thead><tr><th>资产</th><th>币种</th><th>区间</th><th>投入次数/天数</th><th>累计投入</th><th>期末市值</th><th>累计收益</th><th>资金流年化</th><th>账户最大回撤</th><th>标的涨幅</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</section>
<section class="panel">
<h2>投入收益率曲线</h2>
{svg_chart}
</section>
</main>
</body>
</html>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, object]] = []
    curves: dict[str, list[dict[str, object]]] = {}
    for asset in ASSETS:
        rows, summary = backtest_asset(asset)
        write_csv(OUT / f"{asset['code'].replace('.', '_')}_daily_dca.csv", rows)
        summaries.append(summary)
        curves[asset["name"]] = [
            {"date": row["date"], "return_on_invested_pct": row["return_on_invested_pct"]}
            for row in rows
        ]
    trend_rows, trend_summary = backtest_trend_dca(TREND_FUND)
    write_csv(OUT / f"{TREND_FUND['code'].replace('.', '_')}_trend_dca.csv", trend_rows)
    summaries.append(trend_summary)
    curves[TREND_FUND["name"]] = [
        {"date": row["date"], "return_on_invested_pct": row["return_on_invested_pct"]}
        for row in trend_rows
    ]

    write_csv(OUT / "daily_dca_summary.csv", summaries)
    (OUT / "daily_dca_summary.json").write_text(
        json.dumps(
            {
                "assumptions": {
                    "start": START.isoformat(),
                    "end": END.isoformat(),
                    "daily_amount": DAILY_AMOUNT,
                    "monthly_amount": MONTHLY_AMOUNT,
                    "execution": "buy at daily close on each local trading day",
                    "fees": 0,
                    "dividends": "not separately reinvested; uses index price series returned by data source",
                    "trend_dca": "usQQQ.OQ uses the first US trading day of each month; trend signal is confirmed on that day and applied from the next monthly investment.",
                },
                "summary": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    render_html(summaries, curves)


if __name__ == "__main__":
    main()
