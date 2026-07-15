"""Loopback-only web server for the grid strategy generator."""

from __future__ import annotations

import functools
import json
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
PORT = 52341
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
    port: int = PORT,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service, directory))


def build_service() -> ValuationService:
    return ValuationService(
        AkshareSource(),
        thermometer_listing=fetch_thermometer_listing,
        thermometer_detail=fetch_thermometer_detail,
    )


def main():
    server = create_server(build_service())
    print(f"网格策略工具：http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
