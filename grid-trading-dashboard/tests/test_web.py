from grid_dashboard.web import create_app


def test_health_route_returns_ok():
    app = create_app(service=None)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
