import json
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from server import HOST, create_available_server, create_server  # noqa: E402
from strategy_file_store import StrategyFileStore  # noqa: E402
from valuation_service import ValuationError  # noqa: E402


class FakeValuationService:
    def __init__(self, error=None):
        self.error = error
        self.codes = []

    def lookup(self, code):
        self.codes.append(code)
        if self.error:
            raise self.error
        return {"version": 1, "code": code, "source": "youzhiyouxing"}


def strategy_envelope():
    return {"version": 2, "records": [{
        "version": 2,
        "code": "510500",
        "name": "中证500ETF南方",
        "symbol": "中证500ETF南方",
        "savedAt": "2026-07-15T10:00:00+08:00",
        "input": {
            "startPrice": "8.3",
            "stepPct": "5",
            "maxDropPct": "40",
            "fundingMode": "perGrid",
            "amount": "10000",
            "feePct": "0.1",
            "profitRetentionMultiple": 0,
        },
        "valuationSnapshot": None,
    }]}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = FakeValuationService()
        self.strategy_store = StrategyFileStore(Path(self.temp.name) / "saved-strategies.json")
        self.server = create_server(
            self.service,
            PROJECT_DIR,
            strategy_store=self.strategy_store,
            migration_status={52341: True, 55018: False},
            host="127.0.0.1",
            port=0,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(body))
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        body = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, headers, body

    def test_api_returns_json_success(self):
        status, headers, body = self.request("GET", "/api/valuation?code=510500")

        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        self.assertEqual(json.loads(body)["code"], "510500")
        self.assertEqual(self.service.codes, ["510500"])

    def test_api_returns_public_error_without_traceback(self):
        self.service.error = ValuationError("INVALID_CODE", "请输入 6 位 ETF 或指数代码", 422)

        status, _, body = self.request("GET", "/api/valuation?code=abc")

        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body), {
            "error": {"code": "INVALID_CODE", "message": "请输入 6 位 ETF 或指数代码"},
        })
        self.assertNotIn(b"Traceback", body)

    def test_api_returns_generic_public_error_for_unexpected_exception(self):
        self.service.error = RuntimeError("secret upstream detail")

        status, _, body = self.request("GET", "/api/valuation?code=510500")

        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "UPSTREAM_FAILURE")
        self.assertNotIn(b"secret upstream detail", body)

    def test_static_index_is_served_from_configured_directory(self):
        status, headers, body = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn("网格策略 1.0 生成器".encode("utf-8"), body)

    def test_available_server_skips_an_occupied_port(self):
        calls = []
        available = object()

        def server_factory(service, directory, *, host, port):
            calls.append(port)
            if port == 18765:
                raise OSError("occupied")
            return available

        result = create_available_server(
            self.service,
            PROJECT_DIR,
            host=HOST,
            ports=[18765, 18766],
            server_factory=server_factory,
        )

        self.assertIs(result, available)
        self.assertEqual(calls, [18765, 18766])

    def test_strategy_api_reads_and_writes_file_store(self):
        status, _, _ = self.request("PUT", "/api/strategies", strategy_envelope())
        self.assertEqual(status, 200)

        status, _, body = self.request("GET", "/api/strategies")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), strategy_envelope())

    def test_strategy_import_returns_merge_counts(self):
        status, _, body = self.request(
            "POST",
            "/api/strategies/import",
            strategy_envelope(),
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "imported": 1,
            "updated": 0,
            "skipped": 0,
            "total": 1,
        })

    def test_migration_status_lists_available_and_unavailable_ports(self):
        status, _, body = self.request("GET", "/api/strategies/migration-status")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "ports": [
                {"port": 52341, "available": True},
                {"port": 55018, "available": False},
            ],
        })

    def test_invalid_and_oversized_strategy_requests_are_public_errors(self):
        status, _, body = self.request(
            "PUT",
            "/api/strategies",
            {"version": 9, "records": []},
        )
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["error"]["code"], "INVALID_STRATEGY_STORE")

        status, _, body = self.request(
            "PUT",
            "/api/strategies",
            None,
            {"Content-Length": str(2_000_001)},
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"]["code"], "REQUEST_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
