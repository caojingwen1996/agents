from app import ROOT, build_app


def test_application_uses_data_directory_position_coordinator():
    app = build_app()
    service = app.config["DASHBOARD_SERVICE"]

    assert service.data_dir == ROOT / "data"
