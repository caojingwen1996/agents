import json
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from server import create_server  # noqa: E402
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


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeValuationService()
        self.server = create_server(self.service, PROJECT_DIR, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, headers, body

    def test_api_returns_json_success(self):
        status, headers, body = self.request("/api/valuation?code=510500")

        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        self.assertEqual(json.loads(body)["code"], "510500")
        self.assertEqual(self.service.codes, ["510500"])

    def test_api_returns_public_error_without_traceback(self):
        self.service.error = ValuationError("INVALID_CODE", "请输入 6 位 ETF 或指数代码", 422)

        status, _, body = self.request("/api/valuation?code=abc")

        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body), {
            "error": {"code": "INVALID_CODE", "message": "请输入 6 位 ETF 或指数代码"},
        })
        self.assertNotIn(b"Traceback", body)

    def test_api_returns_generic_public_error_for_unexpected_exception(self):
        self.service.error = RuntimeError("secret upstream detail")

        status, _, body = self.request("/api/valuation?code=510500")

        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "UPSTREAM_FAILURE")
        self.assertNotIn(b"secret upstream detail", body)

    def test_static_index_is_served_from_configured_directory(self):
        status, headers, body = self.request("/")

        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn("网格策略 1.0 生成器".encode("utf-8"), body)


if __name__ == "__main__":
    unittest.main()
