# File-Backed Strategy Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace port-scoped browser persistence with a Git-tracked JSON strategy store and migrate legacy records from `localhost:52341` and `localhost:55018`.

**Architecture:** A new Python `StrategyFileStore` validates version 2 envelopes, serializes access with a lock, and atomically replaces the tracked JSON file. The loopback HTTP server exposes load/save/import/status endpoints and serves auxiliary migration listeners on the two historical ports. The single-file frontend keeps its existing record normalization, adds a testable HTTP persistence client, and uses a same-browser redirect chain to read each historical origin's `localStorage`.

**Tech Stack:** Python 3 standard library (`http.server`, `json`, `tempfile`, `threading`), vanilla HTML/CSS/JavaScript, Node built-in test runner, Python `unittest`.

---

## File map

- Create `grid-strategy-generator/strategy_file_store.py`: validation, file reads, atomic writes, and timestamp-aware import merge.
- Create `grid-strategy-generator/data/saved-strategies.json`: Git-tracked empty version 2 store.
- Create `grid-strategy-generator/tests/test_strategy_file_store.py`: storage behavior and failure protection.
- Modify `grid-strategy-generator/server.py`: strategy APIs, bounded JSON bodies, auxiliary migration servers, and lifecycle cleanup.
- Modify `grid-strategy-generator/tests/test_server.py`: API and auxiliary-port coverage.
- Modify `grid-strategy-generator/index.html`: persistence client, async UI flow, and legacy redirect migration.
- Modify `grid-strategy-generator/tests/grid-calculator.test.mjs`: persistence client, wiring, and migration URL coverage.

### Task 1: Implement the validated atomic file store

**Files:**
- Create: `grid-strategy-generator/strategy_file_store.py`
- Create: `grid-strategy-generator/data/saved-strategies.json`
- Create: `grid-strategy-generator/tests/test_strategy_file_store.py`

- [ ] **Step 1: Write failing file-store tests**

Create `tests/test_strategy_file_store.py` with real temporary files:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from strategy_file_store import StrategyFileStore, StrategyStoreError


def record(code="510500", saved_at="2026-07-15T10:00:00+08:00", price="8.3"):
    return {
        "version": 2,
        "code": code,
        "name": "中证500ETF南方",
        "symbol": "中证500ETF南方",
        "savedAt": saved_at,
        "input": {
            "startPrice": price,
            "stepPct": "5",
            "maxDropPct": "40",
            "fundingMode": "perGrid",
            "amount": "10000",
            "feePct": "0.1",
            "profitRetentionMultiple": 0,
        },
        "valuationSnapshot": None,
    }


class StrategyFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "data" / "saved-strategies.json"
        self.store = StrategyFileStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_file_reads_as_empty_store(self):
        self.assertEqual(self.store.read(), {"version": 2, "records": []})

    def test_write_creates_valid_utf8_store(self):
        envelope = {"version": 2, "records": [record()]}
        self.assertEqual(self.store.write(envelope), envelope)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), envelope)

    def test_corrupt_file_is_not_silently_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(StrategyStoreError) as context:
            self.store.read()
        self.assertEqual(context.exception.code, "STRATEGY_STORE_CORRUPT")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not json")

    def test_invalid_record_is_rejected_before_write(self):
        invalid = record()
        invalid["input"]["startPrice"] = "bad"
        with self.assertRaises(StrategyStoreError) as context:
            self.store.write({"version": 2, "records": [invalid]})
        self.assertEqual(context.exception.code, "INVALID_STRATEGY_STORE")
        self.assertFalse(self.path.exists())

    def test_replace_failure_preserves_previous_file(self):
        original = {"version": 2, "records": [record()]}
        self.store.write(original)
        with patch("strategy_file_store.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(StrategyStoreError) as context:
                self.store.write({"version": 2, "records": []})
        self.assertEqual(context.exception.code, "STRATEGY_STORE_WRITE_FAILED")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), original)

    def test_import_keeps_newest_record_and_is_idempotent(self):
        self.store.write({"version": 2, "records": [record(saved_at="2026-07-15T11:00:00+08:00")]})
        result = self.store.import_records({"version": 2, "records": [
            record(saved_at="2026-07-15T09:00:00+08:00", price="8.0"),
            record(code="000300", saved_at="2026-07-15T12:00:00+08:00", price="4.0"),
        ]})
        self.assertEqual(result, {"imported": 1, "updated": 0, "skipped": 1, "total": 2})
        self.assertEqual(self.store.read()["records"][0]["code"], "000300")
        repeat = self.store.import_records({"version": 2, "records": [record(code="000300", saved_at="2026-07-15T12:00:00+08:00", price="4.0")]})
        self.assertEqual(repeat, {"imported": 0, "updated": 0, "skipped": 1, "total": 2})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run:

```powershell
python -m unittest tests/test_strategy_file_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'strategy_file_store'`.

- [ ] **Step 3: Implement the minimal store**

Create `strategy_file_store.py` with these public contracts:

```python
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

EMPTY_STORE = {"version": 2, "records": []}


class StrategyStoreError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _number(value: Any, *, positive=False, non_negative=False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError from error
    if not math.isfinite(parsed):
        raise ValueError
    if positive and parsed <= 0:
        raise ValueError
    if non_negative and parsed < 0:
        raise ValueError
    return parsed


def _record_key(item: dict[str, Any]) -> str:
    return str(item.get("code") or item.get("symbol") or "").strip().lower()


def _saved_at(item: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(item["savedAt"]).replace("Z", "+00:00"))


def validate_store(payload: Any) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise ValueError
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError
        seen = set()
        for item in records:
            if not isinstance(item, dict) or item.get("version") != 2:
                raise ValueError
            code = item.get("code")
            if not isinstance(code, str) or (code and (len(code) != 6 or not code.isdigit())):
                raise ValueError
            if not isinstance(item.get("name"), str) or not isinstance(item.get("symbol"), str):
                raise ValueError
            key = _record_key(item)
            if not key or key in seen:
                raise ValueError
            seen.add(key)
            _saved_at(item)
            inputs = item.get("input")
            if not isinstance(inputs, dict) or inputs.get("fundingMode") not in {"total", "perGrid"}:
                raise ValueError
            _number(inputs.get("startPrice"), positive=True)
            _number(inputs.get("stepPct"), positive=True)
            _number(inputs.get("maxDropPct"), positive=True)
            _number(inputs.get("amount"), positive=True)
            _number(inputs.get("feePct"), non_negative=True)
            if inputs.get("profitRetentionMultiple") not in {0, 1, 2, 3}:
                raise ValueError
            snapshot = item.get("valuationSnapshot")
            if snapshot is not None and not isinstance(snapshot, dict):
                raise ValueError
        return copy.deepcopy({"version": 2, "records": records})
    except (KeyError, TypeError, ValueError) as error:
        raise StrategyStoreError("INVALID_STRATEGY_STORE", "策略数据格式无效", 422) from error


class StrategyFileStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(EMPTY_STORE)
        try:
            return validate_store(json.loads(self.path.read_text(encoding="utf-8")))
        except StrategyStoreError as error:
            raise StrategyStoreError("STRATEGY_STORE_CORRUPT", "策略文件格式损坏") from error
        except (OSError, json.JSONDecodeError) as error:
            raise StrategyStoreError("STRATEGY_STORE_CORRUPT", "策略文件无法读取") from error

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    def _write_unlocked(self, payload: Any) -> dict[str, Any]:
        validated = validate_store(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(validated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            return validated
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise StrategyStoreError("STRATEGY_STORE_WRITE_FAILED", "策略文件保存失败") from error

    def write(self, payload: Any) -> dict[str, Any]:
        with self._lock:
            return self._write_unlocked(payload)

    def import_records(self, payload: Any) -> dict[str, int]:
        incoming = validate_store(payload)["records"]
        with self._lock:
            current = self._read_unlocked()["records"]
            merged = {_record_key(item): item for item in current}
            imported = updated = skipped = 0
            for item in incoming:
                key = _record_key(item)
                previous = merged.get(key)
                if previous is None:
                    merged[key] = item
                    imported += 1
                elif _saved_at(item) > _saved_at(previous):
                    merged[key] = item
                    updated += 1
                else:
                    skipped += 1
            records = sorted(merged.values(), key=_saved_at, reverse=True)
            self._write_unlocked({"version": 2, "records": records})
            return {"imported": imported, "updated": updated, "skipped": skipped, "total": len(records)}
```

Create the tracked seed file:

```json
{
  "version": 2,
  "records": []
}
```

- [ ] **Step 4: Run focused and full Python tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests/test_strategy_file_store.py -v
python -m unittest discover -s tests -v
```

Expected: the new tests pass and all existing Python tests remain green.

- [ ] **Step 5: Commit the file store**

```powershell
git add grid-strategy-generator/strategy_file_store.py grid-strategy-generator/data/saved-strategies.json grid-strategy-generator/tests/test_strategy_file_store.py
git commit -m "feat: add file-backed strategy store"
```

### Task 2: Expose strategy persistence APIs

**Files:**
- Modify: `grid-strategy-generator/server.py`
- Modify: `grid-strategy-generator/tests/test_server.py`

- [ ] **Step 1: Add failing GET, PUT, import, and body-limit tests**

Extend the server test setup to use a real temporary strategy store and let the request helper send JSON:

```python
import tempfile

from strategy_file_store import StrategyFileStore

def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.service = FakeValuationService()
    self.strategy_store = StrategyFileStore(Path(self.temp.name) / "saved-strategies.json")
    self.server = create_server(
        self.service, PROJECT_DIR, strategy_store=self.strategy_store,
        migration_status={52341: True, 55018: False}, host="127.0.0.1", port=0,
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
    content = response.read()
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, content
```

Add tests using a shared valid envelope helper:

```python
def strategy_envelope():
    return {"version": 2, "records": [{
        "version": 2, "code": "510500", "name": "中证500ETF南方",
        "symbol": "中证500ETF南方", "savedAt": "2026-07-15T10:00:00+08:00",
        "input": {"startPrice": "8.3", "stepPct": "5", "maxDropPct": "40",
                  "fundingMode": "perGrid", "amount": "10000", "feePct": "0.1",
                  "profitRetentionMultiple": 0},
        "valuationSnapshot": None,
    }]}

def test_strategy_api_reads_and_writes_file_store(self):
    status, _, _ = self.request("PUT", "/api/strategies", strategy_envelope())
    self.assertEqual(status, 200)
    status, _, body = self.request("GET", "/api/strategies")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), strategy_envelope())

def test_strategy_import_returns_merge_counts(self):
    status, _, body = self.request("POST", "/api/strategies/import", strategy_envelope())
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), {"imported": 1, "updated": 0, "skipped": 0, "total": 1})

def test_migration_status_lists_available_and_unavailable_ports(self):
    status, _, body = self.request("GET", "/api/strategies/migration-status")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), {"ports": [{"port": 52341, "available": True}, {"port": 55018, "available": False}]})

def test_invalid_and_oversized_strategy_requests_are_public_errors(self):
    status, _, body = self.request("PUT", "/api/strategies", {"version": 9, "records": []})
    self.assertEqual(status, 422)
    self.assertEqual(json.loads(body)["error"]["code"], "INVALID_STRATEGY_STORE")
    status, _, body = self.request("PUT", "/api/strategies", None, {"Content-Length": str(2_000_001)})
    self.assertEqual(status, 413)
    self.assertEqual(json.loads(body)["error"]["code"], "REQUEST_TOO_LARGE")
```

Update existing GET calls to `self.request("GET", path)`.

- [ ] **Step 2: Run server tests and verify route failures**

Run:

```powershell
python -m unittest tests/test_server.py -v
```

Expected: FAIL because `create_server` does not accept `strategy_store` and the routes do not exist.

- [ ] **Step 3: Implement bounded JSON APIs in `server.py`**

Add imports and constants:

```python
from strategy_file_store import StrategyFileStore, StrategyStoreError

MAX_STRATEGY_BODY_BYTES = 2_000_000
STRATEGY_STORE_PATH = HERE / "data" / "saved-strategies.json"
```

Change `make_handler` and `create_server` to accept `strategy_store` and `migration_status`. Add route dispatch for:

```python
def do_GET(self):
    parsed = urlsplit(self.path)
    if parsed.path == "/api/strategies":
        return self._strategy_action(strategy_store.read)
    if parsed.path == "/api/strategies/migration-status":
        ports = [{"port": port, "available": available} for port, available in sorted(migration_status.items())]
        return self._write_json(200, {"ports": ports})
    if parsed.path == "/api/valuation":
        return self._valuation(parsed)
    return super().do_GET()

def do_PUT(self):
    if urlsplit(self.path).path != "/api/strategies":
        return self._write_json(404, {"error": {"code": "NOT_FOUND", "message": "接口不存在"}})
    return self._strategy_action(lambda: strategy_store.write(self._read_json()))

def do_POST(self):
    if urlsplit(self.path).path != "/api/strategies/import":
        return self._write_json(404, {"error": {"code": "NOT_FOUND", "message": "接口不存在"}})
    return self._strategy_action(lambda: strategy_store.import_records(self._read_json()))

def _read_json(self):
    try:
        length = int(self.headers.get("Content-Length", "0"))
    except ValueError as error:
        raise StrategyStoreError("INVALID_STRATEGY_STORE", "请求长度无效", 400) from error
    if length > MAX_STRATEGY_BODY_BYTES:
        raise StrategyStoreError("REQUEST_TOO_LARGE", "策略数据超过大小限制", 413)
    try:
        return json.loads(self.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StrategyStoreError("INVALID_STRATEGY_STORE", "策略数据不是有效 JSON", 422) from error

def _strategy_action(self, operation):
    try:
        return self._write_json(200, operation())
    except StrategyStoreError as error:
        return self._write_json(error.status, {"error": {"code": error.code, "message": error.message}})
    except Exception:
        return self._write_json(500, {"error": {"code": "STRATEGY_STORE_FAILURE", "message": "策略文件操作失败"}})
```

Keep valuation handling in a small `_valuation(parsed)` method with its existing public-error behavior. Default `strategy_store` to `StrategyFileStore(STRATEGY_STORE_PATH)` only when it is not injected.

- [ ] **Step 4: Run focused and full Python tests**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests/test_server.py -v
python -m unittest discover -s tests -v
```

Expected: all server and Python tests pass.

- [ ] **Step 5: Commit the APIs**

```powershell
git add grid-strategy-generator/server.py grid-strategy-generator/tests/test_server.py
git commit -m "feat: expose strategy file APIs"
```

### Task 3: Run auxiliary migration listeners

**Files:**
- Modify: `grid-strategy-generator/server.py`
- Modify: `grid-strategy-generator/tests/test_server.py`

- [ ] **Step 1: Write failing listener lifecycle tests**

Add tests for a factory that records partial success without blocking the main service:

```python
from server import create_migration_servers

def test_migration_servers_keep_partial_success(self):
    calls = []
    working = object()
    def factory(service, directory, **kwargs):
        calls.append(kwargs["port"])
        if kwargs["port"] == 52341:
            raise OSError("occupied")
        return working
    servers, status = create_migration_servers(
        self.service, PROJECT_DIR, self.strategy_store,
        ports=[52341, 55018], server_factory=factory,
    )
    self.assertEqual(servers, [working])
    self.assertEqual(status, {52341: False, 55018: True})
    self.assertEqual(calls, [52341, 55018])
```

- [ ] **Step 2: Run the focused test and verify the missing factory failure**

Run:

```powershell
python -m unittest tests/test_server.py -v
```

Expected: FAIL because `create_migration_servers` is not defined.

- [ ] **Step 3: Implement auxiliary server creation and cleanup**

Add:

```python
MIGRATION_PORTS = (52341, 55018)

def create_migration_servers(service, directory, strategy_store, *, ports=MIGRATION_PORTS, server_factory=create_server):
    servers = []
    shared_status = {port: False for port in ports}
    for port in ports:
        try:
            server = server_factory(
                service, directory, strategy_store=strategy_store,
                migration_status=shared_status, host=HOST, port=port,
            )
        except OSError:
            shared_status[port] = False
        else:
            servers.append(server)
            shared_status[port] = True
    return servers, shared_status
```

Every handler receives the same mutable `shared_status` dictionary before binding. Updating that dictionary after each bind makes the final status visible to all listeners without modifying `functools.partial` internals.

Update `main()` to construct one `StrategyFileStore`, start each auxiliary server in a daemon thread, pass the shared status into the main server, and close every server on exit:

```python
strategy_store = StrategyFileStore(STRATEGY_STORE_PATH)
service = build_service()
migration_servers, migration_status = create_migration_servers(service, HERE, strategy_store)
threads = [threading.Thread(target=item.serve_forever, daemon=True) for item in migration_servers]
for thread in threads:
    thread.start()
server = create_available_server(
    service, HERE, strategy_store=strategy_store, migration_status=migration_status,
)
try:
    server.serve_forever()
finally:
    server.server_close()
    for item in migration_servers:
        item.shutdown()
        item.server_close()
    for thread in threads:
        thread.join(timeout=2)
```

Extend `create_available_server` and its injected factory call to forward `strategy_store` and `migration_status`.

- [ ] **Step 4: Run the complete Python suite**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
```

Expected: all Python tests pass, including partial historical-port failure.

- [ ] **Step 5: Commit migration listener support**

```powershell
git add grid-strategy-generator/server.py grid-strategy-generator/tests/test_server.py
git commit -m "feat: serve legacy strategy migration ports"
```

### Task 4: Add a testable frontend persistence client

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Add failing client and migration URL tests**

Add a loader for a new marked script block:

```javascript
function loadPersistence(overrides = {}) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(
    /\/\* GRID_PERSISTENCE_START \*\/([\s\S]*?)\/\* GRID_PERSISTENCE_END \*\//,
  );
  assert.ok(match, "persistence block must be present");
  const context = { window: {}, URL, URLSearchParams, ...overrides };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context.window.GridPersistence;
}
```

Add tests:

```javascript
test("loads and saves the version two strategy envelope through the API", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => url === "/api/strategies"
      ? { version: 2, records: [] }
      : { version: 2, records: [{ code: "510500" }] } };
  };
  const client = loadPersistence().createClient(fetchImpl);
  assert.deepEqual(JSON.parse(JSON.stringify(await client.load())), { version: 2, records: [] });
  await client.save({ version: 2, records: [] });
  assert.equal(calls[1].options.method, "PUT");
  assert.equal(calls[1].options.headers["Content-Type"], "application/json");
});

test("surfaces public strategy API errors", async () => {
  const client = loadPersistence().createClient(async () => ({
    ok: false,
    json: async () => ({ error: { code: "STRATEGY_STORE_WRITE_FAILED", message: "策略文件保存失败" } }),
  }));
  await assert.rejects(() => client.save({ version: 2, records: [] }), /策略文件保存失败/);
});

test("builds an ordered same-browser migration chain from available ports", () => {
  const { buildMigrationUrl } = loadPersistence();
  const url = buildMigrationUrl(
    [{ port: 52341, available: true }, { port: 55018, available: true }],
    "http://127.0.0.1:18765/",
  );
  assert.match(url, /^http:\/\/localhost:52341\/\?migrate=1/);
  assert.match(decodeURIComponent(url), /remaining=55018/);
  assert.match(decodeURIComponent(url), /return=http:\/\/127\.0\.0\.1:18765\//);
});
```

- [ ] **Step 2: Run Node tests and verify the missing block failure**

Run:

```powershell
$files = (Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File).FullName
& 'D:\Program Files\nodejs\node.exe' --test $files
```

Expected: FAIL with `persistence block must be present`.

- [ ] **Step 3: Implement `GridPersistence` in `index.html`**

Add a pure marked block before the page orchestration script:

```javascript
/* GRID_PERSISTENCE_START */
(() => {
  async function request(fetchImpl, url, options) {
    const response = await fetchImpl(url, options);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.error?.message || "策略文件操作失败");
    }
    return payload;
  }

  function createClient(fetchImpl = fetch) {
    return {
      load: () => request(fetchImpl, "/api/strategies"),
      save: (store) => request(fetchImpl, "/api/strategies", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(store),
      }),
      importLegacy: (store) => request(fetchImpl, "/api/strategies/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(store),
      }),
      migrationStatus: () => request(fetchImpl, "/api/strategies/migration-status"),
    };
  }

  function buildMigrationUrl(ports, returnUrl) {
    const available = ports.filter((item) => item.available).map((item) => item.port);
    if (available.length === 0) return null;
    const [first, ...remaining] = available;
    const params = new URLSearchParams({
      migrate: "1",
      remaining: remaining.join(","),
      return: returnUrl,
    });
    return `http://localhost:${first}/?${params}`;
  }

  window.GridPersistence = { buildMigrationUrl, createClient };
})();
/* GRID_PERSISTENCE_END */
```

- [ ] **Step 4: Run the full Node suite**

Run:

```powershell
$files = (Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File).FullName
& 'D:\Program Files\nodejs\node.exe' --test $files
```

Expected: all existing and new Node tests pass.

- [ ] **Step 5: Commit the client**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: add strategy persistence client"
```

### Task 5: Switch the UI to file persistence and add legacy migration

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Add failing static wiring tests**

Add assertions that the production page no longer writes the normal strategy list to `localStorage`, provides migration UI, and awaits API confirmation:

```javascript
test("uses file persistence for normal load save and delete", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  assert.match(html, /const strategyPersistence = window\.GridPersistence\.createClient/);
  assert.match(html, /await strategyPersistence\.load\(\)/);
  assert.match(html, /await strategyPersistence\.save\(/);
  assert.doesNotMatch(html, /localStorage\.setItem\(STRATEGY_STORAGE_KEY/);
});

test("contains an idempotent legacy strategy migration action", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  assert.match(html, /id=["']migrate-strategies-button["']/);
  assert.match(html, /localStorage\.getItem\(STRATEGY_STORAGE_KEY\)/);
  assert.match(html, /strategyPersistence\.importLegacy/);
  assert.match(html, /window\.location\.replace/);
});
```

- [ ] **Step 2: Run Node tests and verify they fail on old wiring**

Run the complete Node command.

Expected: FAIL because normal persistence still calls `localStorage.setItem` and no migration button exists.

- [ ] **Step 3: Add the migration button and async file-backed orchestration**

Add a secondary button beside the saved-strategy heading:

```html
<button id="migrate-strategies-button" class="secondary-button" type="button">迁移旧策略</button>
```

Instantiate the client and replace `loadSavedStrategies`:

```javascript
const strategyPersistence = window.GridPersistence.createClient();

async function loadSavedStrategies() {
  try {
    const payload = await strategyPersistence.load();
    const parsed = window.GridStrategyStore.parseStore(JSON.stringify(payload));
    savedStrategies = parsed.records;
    if (parsed.skippedCount > 0) {
      setSaveStatus(`有 ${parsed.skippedCount} 条策略记录无法读取，已跳过。`, true);
    }
  } catch (error) {
    savedStrategies = [];
    setSaveStatus(`无法读取策略文件：${error.message}`, true);
  }
  renderSavedStrategies();
}
```

Make delete and save handlers `async`. For deletion, call:

```javascript
const nextRecords = window.GridStrategyStore.removeRecord(savedStrategies, recordKey);
try {
  await strategyPersistence.save(JSON.parse(window.GridStrategyStore.serializeStore(nextRecords)));
  savedStrategies = nextRecords;
  activeSavedSymbol = null;
  renderSavedStrategies();
  setSaveStatus("策略已从文件删除。");
} catch (error) {
  setSaveStatus(`策略文件删除失败：${error.message}`, true);
}
```

For save, keep CSV download independent, then persist before changing the rendered list:

```javascript
try {
  await strategyPersistence.save(JSON.parse(window.GridStrategyStore.serializeStore(nextRecords)));
  savedStrategies = nextRecords;
  activeSavedSymbol = window.GridStrategyStore.recordKey(record);
  renderSavedStrategies();
  indexSaved = true;
} catch (error) {
  console.error("Strategy file save failed", error);
}
```

Change status copy from “左侧列表保存失败” to “策略文件保存失败”.

- [ ] **Step 4: Implement the same-browser legacy redirect chain**

Add:

```javascript
async function runLegacyMigration() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("migrate") !== "1") return false;
  const returnUrl = params.get("return") || "";
  const remaining = (params.get("remaining") || "").split(",").filter(Boolean);
  const parsed = window.GridStrategyStore.parseStore(localStorage.getItem(STRATEGY_STORAGE_KEY));
  try {
    const result = await strategyPersistence.importLegacy(
      JSON.parse(window.GridStrategyStore.serializeStore(parsed.records)),
    );
    const next = remaining.shift();
    if (next) {
      const nextParams = new URLSearchParams({
        migrate: "1", remaining: remaining.join(","), return: returnUrl,
      });
      window.location.replace(`http://localhost:${next}/?${nextParams}`);
    } else {
      const target = new URL(returnUrl);
      if (!['127.0.0.1', 'localhost'].includes(target.hostname)) throw new Error("迁移返回地址无效");
      target.searchParams.set("migration", JSON.stringify({ ...result, skippedInvalid: parsed.skippedCount }));
      window.location.replace(target.toString());
    }
  } catch (error) {
    setSaveStatus(`旧策略迁移失败：${error.message}`, true);
  }
  return true;
}

byId("migrate-strategies-button").addEventListener("click", async () => {
  try {
    const status = await strategyPersistence.migrationStatus();
    const target = window.GridPersistence.buildMigrationUrl(status.ports, window.location.origin + window.location.pathname);
    if (!target) {
      setSaveStatus("历史端口当前不可用，无法迁移旧策略。", true);
      return;
    }
    window.location.assign(target);
  } catch (error) {
    setSaveStatus(`无法开始旧策略迁移：${error.message}`, true);
  }
});
```

At startup, run migration before normal loading:

```javascript
(async () => {
  renderValuationState({ kind: "empty", code: "" });
  if (await runLegacyMigration()) return;
  await loadSavedStrategies();
  const params = new URLSearchParams(window.location.search);
  if (params.has("migration")) {
    setSaveStatus("旧策略迁移完成，已刷新统一策略文件。");
    window.history.replaceState({}, "", window.location.pathname);
  }
})();
```

- [ ] **Step 5: Run full frontend and backend tests**

Run:

```powershell
$files = (Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File).FullName
& 'D:\Program Files\nodejs\node.exe' --test $files
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
```

Expected: all Node and Python tests pass.

- [ ] **Step 6: Commit the UI switch**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: persist and migrate saved strategies"
```

### Task 6: Verify persistence across ports and finish the branch

**Files:**
- Modify only if verification exposes a tested defect.

- [ ] **Step 1: Run static checks and full automated suites**

```powershell
git diff --check
$patterns = @('TO' + 'DO', 'TB' + 'D', 'FIX' + 'ME')
foreach ($pattern in $patterns) { rg -n $pattern grid-strategy-generator docs/superpowers/specs/2026-07-15-file-backed-strategy-store-design.md docs/superpowers/plans/2026-07-15-file-backed-strategy-store.md }
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
$files = (Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File).FullName
& 'D:\Program Files\nodejs\node.exe' --test $files
```

Expected: no diff errors or unfinished markers; every test passes.

- [ ] **Step 2: Verify normal save/load/delete in the in-app browser**

Start `python server.py` and verify:

1. Generate and save a strategy.
2. Confirm `data/saved-strategies.json` contains it.
3. Reload the page and confirm the left list restores it.
4. Delete it, reload, and confirm it stays deleted.
5. Confirm CSV download remains independent of file persistence status.

- [ ] **Step 3: Verify cross-port persistence**

Stop the service, occupy `18765`, restart so the main service selects `18766`, and confirm the same JSON-backed list loads without migration.

- [ ] **Step 4: Verify both historical origins**

Using the same in-app browser profile, place distinct version 1 or version 2 records into `localStorage` at `localhost:52341` and `localhost:55018`. Click “迁移旧策略” from the main page and verify:

- both records appear in `data/saved-strategies.json`;
- the browser returns to the main page;
- the left list refreshes;
- a second migration does not duplicate records;
- old `localStorage` values remain present.

- [ ] **Step 5: Review Git-tracked runtime data behavior**

Confirm `git status --short` reports `grid-strategy-generator/data/saved-strategies.json` after browser saves, then restore the verification-only sample content to the committed empty envelope using `apply_patch`. Do not use `git checkout --` because unrelated work must remain untouched.

- [ ] **Step 6: Commit verification fixes only if needed**

If verification required a tested production change:

```powershell
git add grid-strategy-generator/strategy_file_store.py grid-strategy-generator/server.py grid-strategy-generator/index.html grid-strategy-generator/tests/test_strategy_file_store.py grid-strategy-generator/tests/test_server.py grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: complete file-backed strategy verification"
```

If no production change was required, do not create an empty commit.

- [ ] **Step 7: Run final clean verification**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
$files = (Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File).FullName
& 'D:\Program Files\nodejs\node.exe' --test $files
git diff --check
git status --short
```

Expected: every test passes, `git diff --check` is silent, and `git status --short` is empty.
