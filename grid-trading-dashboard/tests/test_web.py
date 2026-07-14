from grid_dashboard.web import create_app


class StubService:
    def __init__(self):
        self.report = {"title": "测试", "warning": None}
        self.last_success = self.report

    def refresh(self):
        return self.report

    def current(self):
        return self.report


def test_health_route_returns_ok():
    app = create_app(service=None)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_refresh_route_returns_report_json():
    app = create_app(StubService())

    response = app.test_client().post("/api/refresh")

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "report": {"title": "测试", "warning": None},
    }


class SelectorStub:
    last_success = None

    def current(self):
        return {
            "positions": [{"file_id": "000001-平安银行.xlsx", "display_name": "平安银行", "stock_code": "000001", "error": None}],
            "selected_file_id": "000001-平安银行.xlsx",
            "report": {"title": "平安银行", "warning": None},
        }

    def select(self, file_id):
        state = self.current()
        state["selected_file_id"] = file_id
        return state


def test_select_route_switches_by_catalog_file_id():
    app = create_app(SelectorStub())

    response = app.test_client().post(
        "/api/select-position",
        json={"file_id": "000001-平安银行.xlsx"},
    )

    assert response.status_code == 200
    assert response.get_json()["selected_file_id"] == "000001-平安银行.xlsx"
