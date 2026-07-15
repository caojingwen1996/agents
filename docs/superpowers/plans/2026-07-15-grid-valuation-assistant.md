# Grid Valuation Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local valuation assistant that resolves six-digit A-share ETF/index codes, prefers the public Youzhiyouxing thermometer, falls back to independent 10-year PE/PB percentiles, and carries a clearly dated valuation snapshot through strategy save/load and CSV export without producing investment advice.

**Architecture:** A Python `ThreadingHTTPServer` serves the existing page and a same-origin `/api/valuation` endpoint on `127.0.0.1`. Pure validation, matching, percentile, fallback, and cache rules live in `valuation_service.py`; third-party adapters live in `valuation_sources.py` and are injected in tests. The page keeps grid calculation independent from valuation state, while version-2 local records and CSV exports accept an optional immutable valuation snapshot and migrate version-1 records.

**Tech Stack:** Python 3.11, standard-library HTTP server, AKShare 1.x, Requests 2.x, Beautiful Soup 4.x, `unittest`, HTML/CSS/vanilla JavaScript, Node.js built-in test runner.

---

## File map

- Create `grid-strategy-generator/valuation_service.py`: validation, normalized matching, 10-year percentile calculation, response orchestration, one-hour success cache, public error model.
- Create `grid-strategy-generator/valuation_sources.py`: ETF/index resolution adapters, Youzhiyouxing HTML fetch/parser, AKShare PE/PB adapters.
- Create `grid-strategy-generator/server.py`: loopback-only static server and `/api/valuation` JSON endpoint.
- Create `grid-strategy-generator/requirements.txt`: bounded runtime dependencies.
- Create `grid-strategy-generator/start-grid-tool.bat`: dependency check/install, local server start, browser open.
- Create `grid-strategy-generator/tests/test_valuation_service.py`: deterministic service, matching, percentile, fallback, and cache tests.
- Create `grid-strategy-generator/tests/test_valuation_sources.py`: fixture-driven parser and adapter tests.
- Create `grid-strategy-generator/tests/test_server.py`: endpoint/status/content-type/path tests with fake service.
- Create `grid-strategy-generator/tests/fixtures/thermometer.html`: minimal public-page-shaped fixture with two index rows.
- Modify `grid-strategy-generator/index.html`: valuation panel/controller, record-v2 migration/snapshots, valuation-aware CSV and filename.
- Modify `grid-strategy-generator/tests/grid-calculator.test.mjs`: DOM/controller, migration, CSV, and filename regression tests.

## Task 1: Establish pure valuation rules

**Files:**
- Create: `grid-strategy-generator/valuation_service.py`
- Create: `grid-strategy-generator/tests/test_valuation_service.py`

- [ ] Write failing tests for code validation, name normalization, code-first/name-second thermometer matching, and the independent PE/PB percentile rule.

```python
class ValuationRuleTests(unittest.TestCase):
    def test_validate_code_accepts_exactly_six_digits(self):
        self.assertEqual(validate_code("510500"), "510500")
        for value in ("", "51050", "5105000", "51050A"):
            with self.subTest(value=value), self.assertRaises(ValuationError):
                validate_code(value)

    def test_match_thermometer_prefers_code_over_name(self):
        rows = [
            {"indexCode": "000905", "indexName": "其他名称", "temperature": 61},
            {"indexCode": "000300", "indexName": "中证500", "temperature": 20},
        ]
        self.assertEqual(match_thermometer(rows, "000905", "中证500")["temperature"], 61)

    def test_percentile_filters_invalid_values_and_uses_ten_year_window(self):
        points = [
            (date(2014, 1, 1), 1),
            (date(2016, 1, 1), 2),
            (date(2025, 1, 1), 4),
            (date(2026, 1, 1), 3),
            (date(2026, 2, 1), 0),
            (date(2026, 3, 1), float("nan")),
        ]
        metric = calculate_percentile(points)
        self.assertEqual(metric["sampleCount"], 3)
        self.assertEqual(metric["currentValue"], 3)
        self.assertAlmostEqual(metric["percentilePct"], 66.6666667)
```

- [ ] Run the focused test and verify it fails because the module does not exist.

Run: `python -m unittest grid-strategy-generator/tests/test_valuation_service.py -v`

Expected: `ModuleNotFoundError` for `valuation_service`.

- [ ] Implement the smallest pure rule layer.

```python
CODE_PATTERN = re.compile(r"^\d{6}$")

class ValuationError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

def validate_code(value: str) -> str:
    code = str(value or "").strip()
    if not CODE_PATTERN.fullmatch(code):
        raise ValuationError("INVALID_CODE", "请输入 6 位 ETF 或指数代码")
    return code

def normalize_name(value: str) -> str:
    return re.sub(r"[\s\-_/（）()]+", "", str(value or "")).lower()

def match_thermometer(rows, index_code, index_name):
    if index_code:
        exact = next((row for row in rows if row.get("indexCode") == index_code), None)
        if exact:
            return exact
    target = normalize_name(index_name)
    matches = [row for row in rows if normalize_name(row.get("indexName")) == target]
    return matches[0] if len(matches) == 1 else None

def calculate_percentile(points):
    valid = []
    for day, value in points:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if isinstance(day, date) and math.isfinite(numeric) and numeric > 0:
            valid.append((day, numeric))
    valid.sort()
    if not valid:
        return None
    end = valid[-1][0]
    start_cutoff = end - relativedelta(years=10)
    window = [(day, value) for day, value in valid if day >= start_cutoff]
    current = window[-1][1]
    return {
        "currentValue": current,
        "percentilePct": sum(value <= current for _, value in window) / len(window) * 100,
        "startDate": window[0][0].isoformat(),
        "endDate": window[-1][0].isoformat(),
        "sampleCount": len(window),
    }
```

Use `dateutil.relativedelta`, already included transitively by AKShare, to preserve exact calendar-year boundaries.

- [ ] Run the focused tests and verify all rule tests pass.

Run: `python -m unittest grid-strategy-generator/tests/test_valuation_service.py -v`

Expected: all tests in `ValuationRuleTests` pass.

- [ ] Commit the rule layer.

```powershell
git add grid-strategy-generator/valuation_service.py grid-strategy-generator/tests/test_valuation_service.py
git commit -m "feat: add valuation calculation rules"
```

## Task 2: Add deterministic source adapters

**Files:**
- Create: `grid-strategy-generator/valuation_sources.py`
- Create: `grid-strategy-generator/tests/test_valuation_sources.py`
- Create: `grid-strategy-generator/tests/fixtures/thermometer.html`
- Modify: `grid-strategy-generator/requirements.txt`

- [ ] Write fixture-driven failing tests for parsing thermometer fields, resolving an ETF through its benchmark, resolving a direct index code, rejecting ambiguous names, and independently converting AKShare PE/PB frames into dated points.

```python
def test_parse_thermometer_fixture():
    rows = parse_thermometer_html(FIXTURE.read_text(encoding="utf-8"))
    assert rows[0] == {
        "indexCode": "000905",
        "indexName": "中证500",
        "temperature": 72.0,
        "valuationBand": "偏高",
        "intrinsicReturnPct": 4.76,
        "dividendYieldPct": 1.54,
        "asOf": "2026-07-14",
        "url": THERMOMETER_URL,
    }

def test_resolve_etf_uses_benchmark_then_unique_index_name():
    source = AkshareSource(
        etf_rows=lambda: [{"代码": "510500", "名称": "中证500ETF"}],
        tracking_target=lambda code: "中证500指数",
        index_rows=lambda: [{"index_code": "000905", "display_name": "中证500"}],
    )
    assert source.resolve("510500").tracked_index_code == "000905"
```

- [ ] Run source tests and verify failure before implementation.

Run: `python -m unittest grid-strategy-generator/tests/test_valuation_sources.py -v`

Expected: import failure for `valuation_sources`.

- [ ] Implement explicit adapters with injected callables and timeouts.

```python
@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    instrument_type: str
    tracked_index_code: str
    tracked_index_name: str

class AkshareSource:
    def __init__(self, etf_rows=None, tracking_target=None, index_rows=None,
                 pe_history=None, pb_history=None):
        self._etf_rows = etf_rows or (lambda: ak.fund_etf_spot_em().to_dict("records"))
        self._tracking_target = tracking_target or fetch_eastmoney_tracking_target
        self._index_rows = index_rows or (lambda: ak.index_stock_info().to_dict("records"))
        self._pe_history = pe_history or ak.stock_index_pe_lg
        self._pb_history = pb_history or ak.stock_index_pb_lg

    def resolve(self, code: str) -> Instrument:
        indexes = self._index_rows()
        etf = next((row for row in self._etf_rows() if str(row["代码"]).zfill(6) == code), None)
        if etf:
            benchmark = self._tracking_target(code)
            index = _resolve_unique_benchmark(benchmark, indexes)
            return Instrument(code, str(etf["名称"]), "etf",
                              index["index_code"], index["display_name"])
        index = next((row for row in indexes if str(row["index_code"]).zfill(6) == code), None)
        if not index:
            raise SourceError("UNSUPPORTED_INSTRUMENT", "未识别为 A 股 ETF 或指数")
        return Instrument(code, index["display_name"], "index", code, index["display_name"])
```

`fetch_eastmoney_tracking_target` reads the public basic-information page at `https://fundf10.eastmoney.com/{code}.html`, extracts the table cell labelled “跟踪标的”, and rejects “该基金无跟踪标的”. The benchmark resolver removes “指数/收益率/全收益” suffixes and allocation expressions, then requires exactly one normalized index-name match. It raises `AMBIGUOUS_INDEX` instead of guessing. PE/PB calls use the resolved display name because AKShare 1.18.64's Legulegu functions accept named indexes; unsupported index names produce a clean missing-metric result rather than a fabricated value.

- [ ] Implement thermometer parsing with a fixture-backed contract and no arbitrary URL input.

```python
THERMOMETER_URL = "https://youzhiyouxing.cn/thermometer"

def fetch_thermometer(session=requests, timeout=10):
    response = session.get(THERMOMETER_URL, timeout=timeout,
                           headers={"User-Agent": "GridStrategyGenerator/1.0"})
    response.raise_for_status()
    return parse_thermometer_html(response.text)

def parse_thermometer_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    updated_at = _extract_temperature_update_time(soup.get_text(" ", strip=True))
    rows = _extract_index_observation_links(soup)
    if not rows:
        raise SourceError("THERMOMETER_FORMAT_CHANGED", "温度计页面结构已变化")
    return [_normalize_thermometer_row(row, updated_at) for row in rows]
```

The parser scopes itself to the heading “指数观察”, reads each observation link's visible text in the order `名称 代码 温度 内在收益率 股息率`, and extracts the page-level “温度更新时间”. It accepts exchange suffixes such as `.SH`, `.SZ`, and `.CSI`, normalizes them to six-character index codes for matching, and treats `--` as a missing numeric field. The HTML fixture reproduces only that structural contract and contains no copied article text.

- [ ] Add bounded dependencies.

```text
akshare>=1.18,<2
beautifulsoup4>=4.13,<5
python-dateutil>=2.9,<3
requests>=2.32,<3
```

- [ ] Run source and rule tests.

Run: `python -m unittest discover -s grid-strategy-generator/tests -p "test_valuation_*.py" -v`

Expected: parser, resolver, and existing rule tests pass without network access.

- [ ] Commit source adapters.

```powershell
git add grid-strategy-generator/valuation_sources.py grid-strategy-generator/requirements.txt grid-strategy-generator/tests/test_valuation_sources.py grid-strategy-generator/tests/fixtures/thermometer.html
git commit -m "feat: add valuation data adapters"
```

## Task 3: Orchestrate priority, fallback, warnings, and cache

**Files:**
- Modify: `grid-strategy-generator/valuation_service.py`
- Modify: `grid-strategy-generator/tests/test_valuation_service.py`

- [ ] Add failing service tests for thermometer hit, normal unmatched fallback, unavailable-with-warning fallback, single-metric history, both sources failing, success cache hit, and cache expiry.

```python
def test_thermometer_hit_does_not_fetch_percentiles(self):
    source = FakeSource(thermometer=[THERMOMETER_ROW])
    result = ValuationService(source, clock=fixed_clock).lookup("510500")
    self.assertEqual(result["source"], "youzhiyouxing")
    self.assertIsNone(result["percentiles"])
    self.assertEqual(source.history_calls, 0)

def test_unavailable_thermometer_falls_back_with_distinct_warning(self):
    source = FakeSource(thermometer_error=TimeoutError(), pe=PE_POINTS, pb=PB_POINTS)
    result = ValuationService(source, clock=fixed_clock).lookup("510500")
    self.assertEqual(result["source"], "historical_percentile")
    self.assertEqual(result["warnings"][0]["code"], "THERMOMETER_UNAVAILABLE")

def test_success_cache_expires_after_one_hour(self):
    clock = MutableClock()
    service = ValuationService(FakeSource(...), clock=clock, ttl=timedelta(hours=1))
    self.assertFalse(service.lookup("510500")["cached"])
    self.assertTrue(service.lookup("510500")["cached"])
    clock.advance(hours=1, seconds=1)
    self.assertFalse(service.lookup("510500")["cached"])
```

- [ ] Implement `ValuationService.lookup` with a success-only cache and stable version-1 response.

```python
def lookup(self, raw_code):
    code = validate_code(raw_code)
    cached = self._cache.get(code)
    now = self._clock()
    if cached and cached.expires_at > now:
        return {**copy.deepcopy(cached.value), "cached": True}

    instrument = self._source.resolve(code)
    warnings = []
    try:
        thermometer_rows = self._source.thermometer()
    except Exception:
        thermometer_rows = []
        warnings.append({"code": "THERMOMETER_UNAVAILABLE", "message": "温度计暂不可用"})

    match = match_thermometer(
        thermometer_rows, instrument.tracked_index_code, instrument.tracked_index_name
    )
    result = (self._thermometer_result(instrument, match, now, warnings)
              if match else self._percentile_result(instrument, now, warnings))
    self._cache[code] = CacheEntry(now + self._ttl, copy.deepcopy(result))
    return result
```

`_percentile_result` calculates PE and PB independently and returns `None` for an unavailable metric. If both are unavailable it raises `ValuationError("NO_VALUATION_DATA", "暂无估值数据", 502)`. Exceptions are not inserted into `_cache`.

- [ ] Run all valuation unit tests.

Run: `python -m unittest discover -s grid-strategy-generator/tests -p "test_valuation_*.py" -v`

Expected: all tests pass.

- [ ] Commit service orchestration.

```powershell
git add grid-strategy-generator/valuation_service.py grid-strategy-generator/tests/test_valuation_service.py
git commit -m "feat: add valuation source fallback and cache"
```

## Task 4: Serve the page and JSON API locally

**Files:**
- Create: `grid-strategy-generator/server.py`
- Create: `grid-strategy-generator/start-grid-tool.bat`
- Create: `grid-strategy-generator/tests/test_server.py`

- [ ] Write failing tests against a server handler factory with a fake valuation service.

```python
def test_api_returns_json_success(self):
    response = self.request("/api/valuation?code=510500")
    self.assertEqual(response.status, 200)
    self.assertEqual(response.headers.get_content_type(), "application/json")
    self.assertEqual(json.loads(response.read())["code"], "510500")

def test_api_returns_public_error_without_traceback(self):
    response = self.request("/api/valuation?code=abc")
    body = json.loads(response.read())
    self.assertEqual(response.status, 422)
    self.assertEqual(body, {"error": {"code": "INVALID_CODE", "message": "请输入 6 位 ETF 或指数代码"}})
```

- [ ] Implement a loopback-only server and handler factory.

```python
HOST, PREFERRED_PORTS = "127.0.0.1", tuple(range(18765, 18775))

def make_handler(service, directory):
    class GridRequestHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/api/valuation":
                return super().do_GET()
            code = parse_qs(parsed.query).get("code", [""])[0]
            try:
                self._write_json(200, service.lookup(code))
            except ValuationError as error:
                self._write_json(error.status, {"error": {"code": error.code, "message": error.message}})
            except Exception:
                self._write_json(502, {"error": {"code": "UPSTREAM_FAILURE", "message": "估值数据暂不可用，请稍后重试"}})
    return functools.partial(GridRequestHandler, directory=directory)

def main():
    server = create_available_server(build_service(), ports=PREFERRED_PORTS)
    print(f"网格策略工具：http://{HOST}:{server.server_port}/")
    server.serve_forever()
```

- [ ] Add the launcher. It checks imports first, installs only when missing, starts `server.py`, waits for the loopback URL, and opens the default browser.

```bat
@echo off
cd /d "%~dp0"
python -c "import akshare, bs4, requests" >nul 2>nul || python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
start "网格策略本地服务" /min python server.py --open-browser
```

- [ ] Run server tests and the full Python suite.

Run: `python -m unittest discover -s grid-strategy-generator/tests -p "test_*.py" -v`

Expected: all Python tests pass; tests bind an ephemeral loopback port and make no third-party requests.

- [ ] Commit the local runtime.

```powershell
git add grid-strategy-generator/server.py grid-strategy-generator/start-grid-tool.bat grid-strategy-generator/tests/test_server.py
git commit -m "feat: serve valuation API locally"
```

## Task 5: Add the compact valuation panel and request controller

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] Add failing structural tests for the panel above parameters, six-digit code input, retry button, `aria-live`, 44px controls, mobile single-column layout, and absence of decision phrases.

```javascript
test("places a non-advisory valuation panel before parameters", () => {
  const valuation = html.indexOf('id="valuation-panel"');
  const parameters = html.indexOf('id="parameter-title"');
  assert.ok(valuation > 0 && valuation < parameters);
  assert.match(html, /id="instrument-code"[^>]*inputmode="numeric"[^>]*maxlength="6"/);
  assert.match(html, /id="valuation-status"[^>]*aria-live="polite"/);
  assert.match(html, /id="valuation-retry"/);
  for (const phrase of ["建议开启", "暂不建议", "信号不一致", "可考虑开启"]) {
    assert.doesNotMatch(html, new RegExp(phrase));
  }
});
```

- [ ] Add the panel markup and compact responsive CSS. Remove `symbol-name` from the parameter form.

```html
<section id="valuation-panel" class="panel valuation-panel" aria-labelledby="valuation-title">
  <div class="section-heading"><h2 id="valuation-title">0. 估值辅助</h2></div>
  <div class="valuation-query">
    <label for="instrument-code">标的代码</label>
    <input id="instrument-code" inputmode="numeric" autocomplete="off"
           maxlength="6" pattern="[0-9]{6}" placeholder="6 位 ETF 或指数代码">
    <button id="valuation-retry" type="button" class="preset-button">重试</button>
  </div>
  <div id="valuation-status" class="valuation-status" aria-live="polite"></div>
  <div id="valuation-content" class="valuation-grid"></div>
</section>
```

- [ ] Extract a testable `GRID_VALUATION_UI` block and write failing Node VM tests for 400ms debounce, short-code suppression, stale-request suppression via `AbortController` plus monotonically increasing request id, thermometer rendering, percentile rendering, and error rendering.

```javascript
async function queryValuation(code, { fetchImpl = fetch } = {}) {
  const normalized = String(code).replace(/\D/g, "").slice(0, 6);
  if (normalized.length !== 6) return null;
  const requestId = ++valuationRequestId;
  valuationAbortController?.abort();
  valuationAbortController = new AbortController();
  setValuationState("loading");
  try {
    const response = await fetchImpl(`/api/valuation?code=${encodeURIComponent(normalized)}`, {
      signal: valuationAbortController.signal,
    });
    const payload = await response.json();
    if (requestId !== valuationRequestId) return null;
    if (!response.ok) throw new Error(payload.error?.message || "估值数据暂不可用");
    currentValuation = cloneSnapshot(payload, false);
    renderValuation(currentValuation);
    return currentValuation;
  } catch (error) {
    if (error.name !== "AbortError" && requestId === valuationRequestId) renderValuationError(error);
    return null;
  }
}
```

- [ ] Connect input sanitization and automatic querying without adding code input to `calculationFieldIds`; valuation failure therefore never invalidates or blocks the grid plan.

- [ ] Run Node tests.

Run: `node --test grid-strategy-generator/tests/grid-calculator.test.mjs`

Expected: new valuation UI tests and all existing grid tests pass.

- [ ] Commit the panel/controller.

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: add valuation assistant panel"
```

## Task 6: Migrate saved strategies and preserve valuation snapshots

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] Write failing store tests for version-2 records, optional snapshots, version-1 migration, old symbol-only records, code-based upsert/delete, and snapshot-first load.

```javascript
test("migrates v1 records without discarding grid inputs", () => {
  const parsed = store.parseStore(JSON.stringify({ version: 1, records: [legacyRecord] }));
  assert.equal(parsed.records[0].version, 2);
  assert.equal(parsed.records[0].code, "");
  assert.equal(parsed.records[0].name, legacyRecord.symbol);
  assert.equal(parsed.records[0].valuationSnapshot, null);
});

test("normalizes a snapshot without changing its source date", () => {
  const record = store.createRecord(
    { code: "510500", name: "中证500ETF" }, input, SNAPSHOT, savedAt,
  );
  assert.equal(record.valuationSnapshot.asOf, "2026-07-14");
  assert.equal(record.valuationSnapshot.isSnapshot, true);
});
```

- [ ] Upgrade records to version 2 while retaining the same localStorage key and accepting both envelope versions.

```javascript
const STORE_VERSION = 2;

function createRecord(instrument, input, valuationSnapshot = null, savedAt = new Date()) {
  const code = normalizeCode(instrument?.code, { allowEmpty: true });
  const name = String(instrument?.name ?? "").trim();
  if (!code && !name) throw new Error("标的代码或名称不能为空");
  return {
    version: STORE_VERSION,
    code,
    name,
    symbol: name || code,
    savedAt: toIso(savedAt),
    input: normalizeInput(input),
    valuationSnapshot: normalizeSnapshot(valuationSnapshot),
  };
}

function migrateV1(record) {
  return createRecord(
    { code: /^\d{6}$/.test(record.symbol) ? record.symbol : "", name: record.symbol },
    record.input,
    null,
    record.savedAt,
  );
}
```

Use `code || name` as the record identity so old records remain loadable. A version-2 snapshot always stores `isSnapshot: true` while retaining `source`, `asOf`, `queriedAt`, `warnings`, and the thermometer/percentile payload.

- [ ] Update loading behavior: populate the code when present; render a snapshot immediately; call `queryValuation(code)` afterward; for code-less legacy records show “历史策略未保存代码，请补充 6 位代码” and still submit the grid form.

- [ ] Update save behavior: require a six-digit code for new records, use the resolved name when available, allow `valuationSnapshot: null`, and keep CSV download/localStorage outcomes independent.

- [ ] Run Node tests.

Run: `node --test grid-strategy-generator/tests/grid-calculator.test.mjs`

Expected: migration/snapshot tests and all prior save/load tests pass.

- [ ] Commit storage migration.

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: save valuation snapshots with strategies"
```

## Task 7: Export valuation data and resolved filenames

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] Write failing exporter tests for thermometer fields, independent PE/PB rows, unavailable valuation, historical snapshot marker, and resolved/unresolved filenames.

```javascript
test("exports thermometer snapshot before pressure rows", () => {
  const csv = exporter.buildGridCsv(input, result, THERMOMETER_SNAPSHOT);
  assert.ok(csv.indexOf("估值辅助,数值") < csv.indexOf("压力测试,数值"));
  assert.match(csv, /标的代码,510500/);
  assert.match(csv, /指数温度,72\.00/);
  assert.match(csv, /快照状态,历史快照，不是最新数据/);
});

test("creates code-name filename and omits empty names", () => {
  assert.equal(exporter.createExportFilename("510500", "中证500ETF", date),
               "510500-中证500ETF-网格策略-20260715-100000.csv");
  assert.equal(exporter.createExportFilename("000905", "", date),
               "000905-网格策略-20260715-100000.csv");
});
```

- [ ] Change exporter signatures to `buildGridCsv(input, result, valuationSnapshot = null)` and `createExportFilename(code, name, date = new Date())`.

```javascript
function buildValuationRows(snapshot) {
  if (!snapshot) return [["估值辅助", "数值"], ["估值数据", "暂无估值数据"], []];
  const rows = [
    ["估值辅助", "数值"],
    ["标的代码", snapshot.code],
    ["标的名称", snapshot.name],
    ["跟踪指数", [snapshot.trackedIndex?.code, snapshot.trackedIndex?.name].filter(Boolean).join(" ")],
    ["数据来源", snapshot.source],
    ["数据日期", snapshot.asOf || ""],
    ["查询时间", snapshot.queriedAt || ""],
    ["缓存状态", snapshot.cached ? "缓存结果" : "实时查询结果"],
    ["快照状态", snapshot.isSnapshot ? "历史快照，不是最新数据" : "最新查询结果"],
  ];
  // Append either thermometer rows or separate PE and PB rows; never combine percentiles.
  return [...rows, []];
}
```

Insert `...buildValuationRows(snapshot)` before the existing pressure section. Write empty strings for missing PE or PB fields rather than substituting the other metric.

- [ ] Update `downloadPlanCsv` to pass `currentValuation` (or the loaded snapshot) and to build the filename from the six-digit code plus resolved name.

- [ ] Run Node tests and the complete Python suite.

Run: `node --test grid-strategy-generator/tests/grid-calculator.test.mjs`

Run: `python -m unittest discover -s grid-strategy-generator/tests -p "test_*.py" -v`

Expected: all tests pass.

- [ ] Commit valuation export.

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: export valuation snapshots"
```

## Task 8: End-to-end verification and documentation check

**Files:**
- Modify only if verification finds a defect directly caused by Tasks 1-7.

- [ ] Run placeholder and forbidden-copy scans.

Run: `rg -n "TODO|TBD|FIXME|建议开启|暂不建议|信号不一致|可考虑开启" grid-strategy-generator docs/superpowers/plans/2026-07-15-grid-valuation-assistant.md`

Expected: no production placeholder or decision-copy matches; occurrences inside negative test assertions and this plan are reviewed and accepted.

- [ ] Run all repeatable tests from a clean process.

Run: `python -m unittest discover -s grid-strategy-generator/tests -p "test_*.py" -v`

Run: `node --test grid-strategy-generator/tests/grid-calculator.test.mjs`

Expected: both suites exit 0.

- [ ] Start the service and verify local-only binding plus HTTP behavior.

Run: `python grid-strategy-generator/server.py`

In another shell:

```powershell
Get-NetTCPConnection -LocalPort 18765 | Select-Object LocalAddress,LocalPort,State
Invoke-WebRequest http://127.0.0.1:18765/ -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest "http://127.0.0.1:18765/api/valuation?code=abc" -SkipHttpErrorCheck | Select-Object StatusCode,Content
```

Expected: the first available port in `18765`-`18774` listens only on `127.0.0.1`, page status is 200, and invalid code status is 422 with JSON and no traceback.

- [ ] Use the in-app browser for desktop and 375px checks: empty, loading, successful thermometer or PE/PB, upstream failure, loaded snapshot, retry, keyboard order, and no horizontal overflow. Confirm grid generation still works while valuation is in error.

- [ ] Perform one optional live query for a known supported code. Treat upstream failure as an explicitly reported live-source limitation, not as a unit-test failure; confirm source date and warning labels are visible when a response succeeds.

- [ ] Inspect the final diff and confirm every changed line maps to the approved design, old v1 records remain covered, no credential or arbitrary proxy was introduced, and no decision text exists.

Run: `git diff --check`

Run: `git status --short`

- [ ] Commit only verification fixes, if any.

```powershell
git add grid-strategy-generator
git commit -m "fix: complete valuation assistant verification"
```

Skip this commit when verification required no code changes.
