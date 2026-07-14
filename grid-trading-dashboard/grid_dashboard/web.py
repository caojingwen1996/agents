from flask import Flask, current_app, jsonify, render_template, request

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
        state = initial if initial and "report" in initial else None
        return render_template(
            "dashboard.html",
            initial_report=state["report"] if state else initial,
            initial_state=state,
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

    @app.post("/api/select-position")
    def select_position():
        dashboard_service = current_app.config["DASHBOARD_SERVICE"]
        file_id = (request.get_json(silent=True) or {}).get("file_id")
        try:
            return jsonify(dashboard_service.select(file_id))
        except DashboardError as exc:
            return jsonify(error=str(exc), report=dashboard_service.last_success), 422

    return app
