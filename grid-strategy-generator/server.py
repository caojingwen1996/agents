"""Loopback-only web server for the grid strategy generator."""

from __future__ import annotations

import argparse
import functools
import json
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from strategy_file_store import StrategyFileStore, StrategyStoreError
from valuation_service import ValuationError, ValuationService
from valuation_sources import (
    AkshareSource,
    fetch_thermometer_detail,
    fetch_thermometer_listing,
)


HOST = "127.0.0.1"
PREFERRED_PORTS = tuple(range(18765, 18775))
HERE = Path(__file__).resolve().parent
MAX_STRATEGY_BODY_BYTES = 2_000_000
STRATEGY_STORE_PATH = HERE / "data" / "saved-strategies.json"


def make_handler(
    service: Any,
    directory: Path,
    strategy_store: StrategyFileStore,
    migration_status: dict[int, bool],
):
    class GridRequestHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/api/strategies":
                return self._strategy_action(strategy_store.read)
            if parsed.path == "/api/strategies/migration-status":
                ports = [
                    {"port": port, "available": available}
                    for port, available in sorted(migration_status.items())
                ]
                return self._write_json(200, {"ports": ports})
            if parsed.path == "/api/valuation":
                return self._valuation(parsed)
            return super().do_GET()

        def do_PUT(self):
            if urlsplit(self.path).path != "/api/strategies":
                return self._not_found()
            return self._strategy_action(
                lambda: strategy_store.write(self._read_json()),
            )

        def do_POST(self):
            if urlsplit(self.path).path != "/api/strategies/import":
                return self._not_found()
            return self._strategy_action(
                lambda: strategy_store.import_records(self._read_json()),
            )

        def _valuation(self, parsed):
            code = parse_qs(parsed.query).get("code", [""])[0]
            try:
                return self._write_json(200, service.lookup(code))
            except ValuationError as error:
                return self._write_json(error.status, {
                    "error": {"code": error.code, "message": error.message},
                })
            except Exception:
                return self._write_json(502, {
                    "error": {
                        "code": "UPSTREAM_FAILURE",
                        "message": "估值数据暂不可用，请稍后重试",
                    },
                })

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise StrategyStoreError(
                    "INVALID_STRATEGY_STORE",
                    "请求长度无效",
                    400,
                ) from error
            if length > MAX_STRATEGY_BODY_BYTES:
                raise StrategyStoreError(
                    "REQUEST_TOO_LARGE",
                    "策略数据超过大小限制",
                    413,
                )
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise StrategyStoreError(
                    "INVALID_STRATEGY_STORE",
                    "策略数据不是有效 JSON",
                    422,
                ) from error

        def _strategy_action(self, operation):
            try:
                return self._write_json(200, operation())
            except StrategyStoreError as error:
                return self._write_json(error.status, {
                    "error": {"code": error.code, "message": error.message},
                })
            except Exception:
                return self._write_json(500, {
                    "error": {
                        "code": "STRATEGY_STORE_FAILURE",
                        "message": "策略文件操作失败",
                    },
                })

        def _not_found(self):
            return self._write_json(404, {
                "error": {"code": "NOT_FOUND", "message": "接口不存在"},
            })

        def _write_json(self, status: int, payload: Any):
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format, *_args):
            return

    return functools.partial(GridRequestHandler, directory=str(directory))


def create_server(
    service: Any,
    directory: Path = HERE,
    *,
    strategy_store: StrategyFileStore | None = None,
    migration_status: dict[int, bool] | None = None,
    host: str = HOST,
    port: int = PREFERRED_PORTS[0],
) -> ThreadingHTTPServer:
    store = strategy_store if strategy_store is not None else StrategyFileStore(STRATEGY_STORE_PATH)
    status = migration_status if migration_status is not None else {}
    return ThreadingHTTPServer(
        (host, port),
        make_handler(service, directory, store, status),
    )


def create_available_server(
    service: Any,
    directory: Path = HERE,
    *,
    host: str = HOST,
    ports=PREFERRED_PORTS,
    server_factory=create_server,
) -> ThreadingHTTPServer:
    last_error = None
    for port in ports:
        try:
            return server_factory(service, directory, host=host, port=port)
        except OSError as error:
            last_error = error
    if last_error is not None:
        raise last_error
    raise RuntimeError("没有配置可用的本地端口")


def build_service() -> ValuationService:
    return ValuationService(
        AkshareSource(),
        thermometer_listing=fetch_thermometer_listing,
        thermometer_detail=fetch_thermometer_detail,
    )


def main():
    parser = argparse.ArgumentParser(description="网格策略本地服务")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    server = create_available_server(build_service())
    url = f"http://{HOST}:{server.server_port}/"
    print(f"网格策略工具：{url}")
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
