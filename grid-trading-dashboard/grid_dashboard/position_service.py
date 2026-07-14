from pathlib import Path

from .errors import DashboardError
from .position_files import discover_positions


class PositionDashboardService:
    def __init__(self, data_dir, *, catalog_factory=discover_positions, service_factory):
        self.data_dir = Path(data_dir)
        self.catalog_factory = catalog_factory
        self.service_factory = service_factory
        self.selected_file_id: str | None = None
        self._services = {}
        self._last_success = None

    @property
    def last_success(self):
        return self._last_success

    def _catalog(self):
        catalog = self.catalog_factory(self.data_dir)
        available = {position.file_id: position for position in catalog if position.error is None}
        self._services = {
            file_id: service for file_id, service in self._services.items() if file_id in available
        }
        return catalog, available

    def _state(self, catalog, report):
        return {
            "positions": [position.to_dict() for position in catalog],
            "selected_file_id": self.selected_file_id,
            "report": report,
        }

    def _select_default(self, available):
        if self.selected_file_id not in available:
            self.selected_file_id = next(iter(available), None)
        if self.selected_file_id is None:
            raise DashboardError("未找到可用标的文件，请在 data 目录放入 6位代码-标的名称.xlsx")

    def _service_for(self, position):
        if position.file_id not in self._services:
            self._services[position.file_id] = self.service_factory(position.path)
        return self._services[position.file_id]

    def current(self):
        catalog, available = self._catalog()
        self._select_default(available)
        report = self._service_for(available[self.selected_file_id]).current()
        self._last_success = self._state(catalog, report)
        return self._last_success

    def select(self, file_id):
        catalog, available = self._catalog()
        position = available.get(file_id)
        if position is None:
            raise DashboardError("未找到可用标的文件")
        self.selected_file_id = file_id
        report = self._service_for(position).current()
        self._last_success = self._state(catalog, report)
        return self._last_success

    def refresh(self):
        catalog, available = self._catalog()
        self._select_default(available)
        report = self._service_for(available[self.selected_file_id]).refresh()
        self._last_success = self._state(catalog, report)
        return self._last_success
