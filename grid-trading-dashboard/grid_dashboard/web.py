from flask import Flask, current_app, jsonify, render_template

from .errors import DashboardError


def create_app(service):
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.config["DASHBOARD_SERVICE"] = service

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/")
    def dashboard():
        dashboard_service = current_app.config["DASHBOARD_SERVICE"]
        try:
            initial = dashboard_service.current()
            error = None
        except DashboardError as exc:
            initial = dashboard_service.last_success
            error = str(exc)
        return render_template(
            "dashboard.html",
            initial_report=initial,
            initial_error=error,
        )

    @app.post("/api/refresh")
    def refresh():
        dashboard_service = current_app.config["DASHBOARD_SERVICE"]
        try:
            return jsonify(ok=True, report=dashboard_service.refresh())
        except DashboardError as exc:
            return (
                jsonify(
                    ok=False,
                    error=str(exc),
                    report=dashboard_service.last_success,
                ),
                422,
            )

    return app
