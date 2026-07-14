from grid_dashboard.web import create_app


class PageService:
    last_success = None

    def current(self):
        return {
            "title": "网格提款足迹",
            "stock_code": "000001",
            "stock_name": "平安银行",
            "warning": None,
            "price_points": [],
            "cost_points": [],
            "markers": [],
            "grid_rows": [],
            "metrics": {},
        }

    def refresh(self):
        return self.current()


def test_dashboard_contains_chart_metrics_grid_table_and_refresh():
    app = create_app(PageService())

    response = app.test_client().get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="performance-chart"' in html
    assert 'id="metrics-panel"' in html
    assert 'id="grid-summary"' in html
    assert 'id="refresh-button"' in html
    assert 'src="/static/vendor/echarts.min.js"' in html


def test_dashboard_has_accessible_status_and_chart_summary():
    app = create_app(PageService())

    html = app.test_client().get("/").get_data(as_text=True)

    assert 'role="alert"' in html
    assert 'aria-label="刷新交易数据"' in html
    assert 'aria-describedby="chart-summary"' in html
    assert 'id="chart-summary"' in html
