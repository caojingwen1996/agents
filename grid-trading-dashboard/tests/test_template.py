from grid_dashboard.excel_io import load_workbook
from scripts.create_template import create_template


def test_generated_template_is_valid_input(tmp_path):
    path = tmp_path / "交易记录.xlsx"

    create_template(path)
    loaded = load_workbook(path)

    assert loaded.settings.stock_code == "000001"
    assert loaded.settings.strategy_budget == 100000
    assert loaded.trades[0].grid_id == "G3"
    assert {trade.kind for trade in loaded.trades} == {"买入", "卖出", "分红"}
