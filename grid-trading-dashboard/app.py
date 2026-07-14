from pathlib import Path
from threading import Timer
import webbrowser

from grid_dashboard.market_data import MarketDataRepository
from grid_dashboard.service import DashboardService
from grid_dashboard.web import create_app


ROOT = Path(__file__).resolve().parent


def build_app():
    repository = MarketDataRepository(ROOT / "data" / "cache")
    service = DashboardService(ROOT / "data" / "交易记录.xlsx", repository)
    return create_app(service)


def open_dashboard():
    webbrowser.open_new_tab("http://127.0.0.1:8765")


if __name__ == "__main__":
    Timer(0.8, open_dashboard).start()
    build_app().run(
        host="127.0.0.1",
        port=8765,
        debug=False,
        use_reloader=False,
    )
