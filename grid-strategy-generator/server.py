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

from valuation_service import ValuationError, ValuationService
from valuation_sources import (
    AkshareSource,
    fetch_thermometer_detail,
    fetch_thermometer_listing,
)


HOST = "127.0.0.1"
PREFERRED_PORTS = tuple(range(18765, 18775))
HERE = Path(__file__).resolve().parent


def make_handler(service: Any, directory: Path):
    class GridRequestHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/api/valuation":
                return super().do_GET()

            code = parse_qs(parsed.query).get("code", [""])[0]
            try:
                self._write_json(200, service.lookup(code))
            except ValuationError as error:
                self._write_json(error.status, {
                    "error": {"code": error.code, "message": error.message},
                })
            except Exception:
                self._write_json(502, {
                    "error": {
                        "code": "UPSTREAM_FAILURE",
                        "message": "估值数据暂不可用，请稍后重试",
                    },
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
    host: str = HOST,
    port: int = PREFERRED_PORTS[0],
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service, directory))


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
