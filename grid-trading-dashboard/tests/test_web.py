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
