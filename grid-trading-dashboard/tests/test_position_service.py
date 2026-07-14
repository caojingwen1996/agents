from pathlib import Path

import pytest

from grid_dashboard.errors import DashboardError
from grid_dashboard.position_files import PositionFile
from grid_dashboard.position_service import PositionDashboardService


class StubReportService:
    def __init__(self, path):
        self.path = path
        self.last_success = None
        self.refresh_count = 0

    def current(self):
        if self.last_success is None:
            return self.refresh()
        return self.last_success

    def refresh(self):
        self.refresh_count += 1
        self.last_success = {"source": self.path.name, "refresh_count": self.refresh_count}
        return self.last_success


def positions(*names):
    return tuple(
        PositionFile(name, Path(name), name[:6], name[7:-5], None)
        for name in names
    )


def test_current_selects_first_valid_filename_and_exposes_catalog(tmp_path):
    catalog = positions("000001-平安银行.xlsx", "600519-贵州茅台.xlsx")
    service = PositionDashboardService(
        tmp_path,
        catalog_factory=lambda _: catalog,
        service_factory=StubReportService,
    )

    state = service.current()

    assert state["selected_file_id"] == "000001-平安银行.xlsx"
    assert state["report"]["source"] == "000001-平安银行.xlsx"
    assert [item["file_id"] for item in state["positions"]] == [
        "000001-平安银行.xlsx",
        "600519-贵州茅台.xlsx",
    ]


def test_selection_rejects_unknown_file_identifier(tmp_path):
    service = PositionDashboardService(
        tmp_path,
        catalog_factory=lambda _: positions("000001-平安银行.xlsx"),
        service_factory=StubReportService,
    )

    with pytest.raises(DashboardError, match="未找到可用标的文件"):
        service.select("../../outside.xlsx")


def test_refresh_only_updates_the_selected_position_service(tmp_path):
    catalog = positions("000001-平安银行.xlsx", "600519-贵州茅台.xlsx")
    service = PositionDashboardService(
        tmp_path,
        catalog_factory=lambda _: catalog,
        service_factory=StubReportService,
    )

    service.current()
    service.select("600519-贵州茅台.xlsx")
    state = service.refresh()

    assert state["report"] == {"source": "600519-贵州茅台.xlsx", "refresh_count": 2}
    assert service._services["000001-平安银行.xlsx"].refresh_count == 1
