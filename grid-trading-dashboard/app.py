from grid_dashboard.web import create_app


if __name__ == "__main__":
    create_app(service=None).run(
        host="127.0.0.1",
        port=8765,
        debug=False,
    )
