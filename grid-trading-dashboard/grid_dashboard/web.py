from flask import Flask, jsonify


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

    return app
