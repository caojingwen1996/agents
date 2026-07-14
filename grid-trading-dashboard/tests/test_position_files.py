from datetime import date

import openpyxl

from grid_dashboard.position_files import discover_positions


def write_position(path, stock_code):
    book = openpyxl.Workbook()
    config = book.active
    config.title = "配置"
    config.append(["字段", "值"])
    config.append(["股票代码", stock_code])
    config.append(["图表标题", "网格策略"])
    config.append(["行情复权", "不复权"])
    config.append(["策略预算", 100000])
    trades = book.create_sheet("交易流水")
    trades.append(["日期", "类型", "网格编号", "数量", "成交价", "手续费", "印花税", "现金金额", "备注"])
    trades.append([date(2025, 1, 2), "买入", "G1", 100, 10, 1, 0, 0, "建仓"])
    book.save(path)


def test_discovery_sorts_valid_workbooks_and_ignores_excel_lock_files(tmp_path):
    write_position(tmp_path / "600519-贵州茅台.xlsx", "600519")
    write_position(tmp_path / "000001-平安银行.xlsx", "000001")
    write_position(tmp_path / "~$000001-平安银行.xlsx", "000001")
    (tmp_path / "cache").mkdir()

    positions = discover_positions(tmp_path)

    assert [position.file_id for position in positions] == [
        "000001-平安银行.xlsx",
        "600519-贵州茅台.xlsx",
    ]
    assert all(position.error is None for position in positions)


def test_discovery_marks_filename_and_config_code_mismatch(tmp_path):
    write_position(tmp_path / "000001-平安银行.xlsx", "600519")

    [position] = discover_positions(tmp_path)

    assert position.error == "文件名代码 000001 与配置股票代码 600519 不一致"


def test_discovery_marks_malformed_filename_as_unavailable(tmp_path):
    write_position(tmp_path / "交易记录.xlsx", "000001")

    [position] = discover_positions(tmp_path)

    assert position.error == "文件名必须为 6位代码-标的名称.xlsx"
