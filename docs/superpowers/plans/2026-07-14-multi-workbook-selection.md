# One Workbook per Position Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the local dashboard discover `data/000001-标的名称.xlsx` files and switch safely between one independent workbook per A-share position.

**Architecture:** Add a small position-file catalog that owns discovery, filename validation, and safe file identifiers. A multi-position coordinator owns one `DashboardService` per discovered file and provides the selected report to Flask; the browser receives the catalog and selects a file by its opaque filename identifier rather than a path.

**Tech Stack:** Python 3.11, Flask, pandas, openpyxl, AKShare, PyXIRR, ECharts, pytest

---

## File map

- `grid-trading-dashboard/grid_dashboard/position_files.py`: file discovery, filename/config validation, and position metadata.
- `grid-trading-dashboard/grid_dashboard/position_service.py`: selected-position coordinator and isolated report services.
- `grid-trading-dashboard/grid_dashboard/web.py`: catalog-aware page and selection endpoint.
- `grid-trading-dashboard/app.py`: construct the multi-position coordinator from `data/`.
- `grid-trading-dashboard/templates/dashboard.html`: labeled position selector.
- `grid-trading-dashboard/static/dashboard.js`: populate and switch the selector without accepting arbitrary paths.
- `grid-trading-dashboard/scripts/create_template.py`: create a correctly named starter workbook.
- `grid-trading-dashboard/data/000001-平安银行.xlsx`: renamed editable starter workbook.
- `grid-trading-dashboard/.gitignore`: ignore Excel's temporary lock files.
- `grid-trading-dashboard/README.md`: new directory rule and migration instructions.
- `grid-trading-dashboard/tests/test_position_files.py`: discovery/validation coverage.
- `grid-trading-dashboard/tests/test_position_service.py`: selection and service isolation coverage.
- `grid-trading-dashboard/tests/test_web.py`: selection route coverage.
- `grid-trading-dashboard/tests/test_dashboard_page.py`: selector structure coverage.

### Task 1: Discover and validate position workbooks

**Files:**
- Create: `grid-trading-dashboard/grid_dashboard/position_files.py`
- Create: `grid-trading-dashboard/tests/test_position_files.py`

- [ ] **Step 1: Write failing catalog tests**

```python
from grid_dashboard.position_files import discover_positions


def test_discovery_sorts_workbooks_and_ignores_cache_and_excel_locks(tmp_path):
    write_position(tmp_path / "600519-贵州茅台.xlsx", "600519")
    write_position(tmp_path / "000001-平安银行.xlsx", "000001")
    write_position(tmp_path / "~$000001-平安银行.xlsx", "000001")
    (tmp_path / "cache").mkdir()

    positions = discover_positions(tmp_path)

    assert [position.file_id for position in positions] == [
        "000001-平安银行.xlsx",
        "600519-贵州茅台.xlsx",
    ]
    assert all(position.error is None for position in positions)


def test_discovery_marks_filename_and_config_code_mismatch(tmp_path):
    write_position(tmp_path / "000001-平安银行.xlsx", "600519")

    [position] = discover_positions(tmp_path)

    assert position.error == "文件名代码 000001 与配置股票代码 600519 不一致"
```

- [ ] **Step 2: Run the tests and verify missing-module failure**

Run: `python -m pytest tests/test_position_files.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'grid_dashboard.position_files'`.

- [ ] **Step 3: Implement the catalog without path input from callers**

```python
@dataclass(frozen=True)
class PositionFile:
    file_id: str
    path: Path
    stock_code: str | None
    display_name: str
    error: str | None


def discover_positions(data_dir: str | Path) -> tuple[PositionFile, ...]:
    """Return direct, non-temporary .xlsx files sorted by filename."""
```

Match only `^(?P<code>\d{6})-(?P<name>.+)\.xlsx$`; report malformed names as catalog errors instead of silently loading them. Call `load_workbook` only after the filename is valid; carry workbook validation failures in `error`. Resolve each candidate and verify it stays directly under the resolved `data_dir` before exposing it.

- [ ] **Step 4: Run focused catalog tests**

Run: `python -m pytest tests/test_position_files.py -v`

Expected: discovery ordering, lock-file exclusion, malformed name, missing sheet, and code mismatch tests pass.

- [ ] **Step 5: Commit the catalog**

```powershell
git add grid-trading-dashboard/grid_dashboard/position_files.py grid-trading-dashboard/tests/test_position_files.py
git commit -m "feat: discover per-position workbooks"
```

### Task 2: Coordinate reports by selected workbook

**Files:**
- Create: `grid-trading-dashboard/grid_dashboard/position_service.py`
- Create: `grid-trading-dashboard/tests/test_position_service.py`

- [ ] **Step 1: Write failing selection and isolation tests**

```python
from grid_dashboard.position_service import PositionDashboardService


def test_initial_selection_uses_first_valid_filename(tmp_path):
    catalog = stub_catalog("000001-平安银行.xlsx", "600519-贵州茅台.xlsx")
    service = PositionDashboardService(tmp_path, catalog_factory=lambda _: catalog, service_factory=stub_service_factory)

    state = service.current()

    assert state["selected_file_id"] == "000001-平安银行.xlsx"
    assert state["report"]["source"] == "000001-平安银行.xlsx"


def test_selection_rejects_unknown_or_invalid_file_id(tmp_path):
    service = PositionDashboardService(tmp_path, catalog_factory=lambda _: stub_catalog("000001-平安银行.xlsx"), service_factory=stub_service_factory)

    with pytest.raises(DashboardError, match="未找到可用标的文件"):
        service.select("../../outside.xlsx")
```

- [ ] **Step 2: Run the tests and verify missing-module failure**

Run: `python -m pytest tests/test_position_service.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'grid_dashboard.position_service'`.

- [ ] **Step 3: Implement the selected-position coordinator**

```python
class PositionDashboardService:
    def __init__(self, data_dir, *, catalog_factory=discover_positions, service_factory):
        self.data_dir = Path(data_dir)
        self.catalog_factory = catalog_factory
        self.service_factory = service_factory
        self.selected_file_id: str | None = None
        self._services: dict[str, DashboardService] = {}

    def current(self) -> dict: ...
    def select(self, file_id: str) -> dict: ...
    def refresh(self) -> dict: ...
```

`current()` rescans and selects the first valid file if none is selected. `select()` accepts only a `file_id` from the fresh catalog and creates/reuses a service for that exact catalog path. `refresh()` rescans, keeps the current file when it still exists, refreshes only that service, and returns a payload containing `positions`, `selected_file_id`, and `report`. Remove stale service entries for deleted files.

- [ ] **Step 4: Run coordinator tests**

Run: `python -m pytest tests/test_position_service.py -v`

Expected: default selection, explicit switching, unknown identifier rejection, deleted-file handling, and per-file last-success isolation tests pass.

- [ ] **Step 5: Commit the coordinator**

```powershell
git add grid-trading-dashboard/grid_dashboard/position_service.py grid-trading-dashboard/tests/test_position_service.py
git commit -m "feat: switch dashboard position workbooks"
```

### Task 3: Expose safe selection through Flask and the dashboard

**Files:**
- Modify: `grid-trading-dashboard/grid_dashboard/web.py`
- Modify: `grid-trading-dashboard/templates/dashboard.html`
- Modify: `grid-trading-dashboard/static/dashboard.js`
- Modify: `grid-trading-dashboard/tests/test_web.py`
- Modify: `grid-trading-dashboard/tests/test_dashboard_page.py`

- [ ] **Step 1: Write failing endpoint and page tests**

```python
def test_select_route_switches_by_catalog_file_id():
    app = create_app(SelectorStub())

    response = app.test_client().post(
        "/api/select-position",
        json={"file_id": "600519-贵州茅台.xlsx"},
    )

    assert response.status_code == 200
    assert response.get_json()["selected_file_id"] == "600519-贵州茅台.xlsx"


def test_dashboard_contains_labeled_position_selector():
    html = create_app(SelectorStub()).test_client().get("/").get_data(as_text=True)

    assert 'id="position-selector"' in html
    assert 'label for="position-selector"' in html
```

- [ ] **Step 2: Run the tests and verify missing route/selector failures**

Run: `python -m pytest tests/test_web.py tests/test_dashboard_page.py -v`

Expected: selection test returns 404 and page test cannot find `position-selector`.

- [ ] **Step 3: Add the route and selector behavior**

Add `POST /api/select-position`: read only JSON field `file_id`, call `service.select(file_id)`, and return `422` with `DashboardError` text on invalid selection. Update `GET /` and `POST /api/refresh` to use coordinator payloads.

In the template add:

```html
<label class="position-label" for="position-selector">当前标的</label>
<select id="position-selector" aria-label="选择标的"></select>
```

In `dashboard.js`, render valid entries as enabled options and invalid entries as disabled options with their error. On a selector `change`, POST its selected `file_id` to `/api/select-position`; disable both select and refresh during the request; retain the existing report and show the returned error if selection fails.

- [ ] **Step 4: Run page/API tests**

Run: `python -m pytest tests/test_web.py tests/test_dashboard_page.py -v`

Expected: page and selection endpoint tests pass.

- [ ] **Step 5: Commit the web change**

```powershell
git add grid-trading-dashboard/grid_dashboard/web.py grid-trading-dashboard/templates/dashboard.html grid-trading-dashboard/static/dashboard.js grid-trading-dashboard/tests/test_web.py grid-trading-dashboard/tests/test_dashboard_page.py
git commit -m "feat: select dashboard position from data files"
```

### Task 4: Migrate starter data, launcher, and documentation

**Files:**
- Modify: `grid-trading-dashboard/app.py`
- Modify: `grid-trading-dashboard/scripts/create_template.py`
- Delete: `grid-trading-dashboard/data/交易记录.xlsx`
- Create: `grid-trading-dashboard/data/000001-平安银行.xlsx`
- Modify: `grid-trading-dashboard/README.md`
- Create: `grid-trading-dashboard/tests/test_app.py`

- [ ] **Step 1: Write the failing application-path test**

```python
from app import ROOT, build_app


def test_application_uses_data_directory_position_coordinator():
    app = build_app()
    service = app.config["DASHBOARD_SERVICE"]

    assert service.data_dir == ROOT / "data"
```

- [ ] **Step 2: Run the test and verify the old single-file service fails it**

Run: `python -m pytest tests/test_app.py -v`

Expected: assertion fails because the configured service exposes a single `workbook_path`.

- [ ] **Step 3: Migrate default files and startup wiring**

Update `build_app()` to construct `PositionDashboardService(ROOT / "data", service_factory=...)`; that factory must give every per-file `DashboardService` the shared `data/cache/` market-data cache. Update `create_template.py` to create `data/000001-平安银行.xlsx` by default. Generate and commit that workbook, and delete the old `data/交易记录.xlsx`. Keep `data/cache/` untouched and ignored; add an ignore rule for `data/~$*.xlsx`.

Rewrite README usage to state: one workbook per stock; filename rule; dashboard selector; refresh scans for added/deleted files; and migration instruction `交易记录.xlsx` -> `000001-名称.xlsx` after checking the code in `配置`.

- [ ] **Step 4: Run the full dashboard suite**

Run: `python -m pytest -q`

Expected: all tests pass with the new starter file.

- [ ] **Step 5: Run a browser acceptance check**

Run: `python app.py`

Verify at `http://127.0.0.1:8765`: selector lists `000001-平安银行.xlsx`; default report loads; adding a second valid workbook then clicking refresh exposes it; selecting it replaces the chart title and metrics; malformed/locked files do not become selectable.

- [ ] **Step 6: Commit migration and docs**

```powershell
git add grid-trading-dashboard
git commit -m "feat: organize one workbook per position"
```

### Task 5: Final verification

**Files:**
- Modify only files needed to fix failed checks below.

- [ ] **Step 1: Run all dashboard tests and JavaScript syntax validation**

Run:

```powershell
python -m pytest -q
node --check static/dashboard.js
```

Expected: all tests pass and JavaScript syntax check exits 0.

- [ ] **Step 2: Run the existing project baseline**

Run from `TradeRuleSentinel`: `python -m pytest -q`

Expected: `3 passed`.

- [ ] **Step 3: Audit scope and working tree**

Run:

```powershell
git diff --check master...HEAD
git status --short
git log --oneline master..HEAD
```

Expected: no whitespace errors; all tracked changes directly serve the one-workbook-per-position feature; unrelated existing untracked files remain untouched.

- [ ] **Step 4: Commit only verification fixes if needed**

```powershell
git add grid-trading-dashboard
git commit -m "fix: verify position workbook selection"
```

Skip this commit when verification finds no fixes.
