# Grid Strategy Local Save Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual CSV-backed strategy saving with a persistent left-side strategy list that overwrites by symbol, reloads and regenerates saved parameters, and supports confirmed deletion.

**Architecture:** Keep the tool as one offline HTML file. Add a pure `GridStrategyStore` script block for versioned record validation, parsing, upsert, removal, and serialization; keep browser `localStorage`, DOM rendering, CSV download, and form orchestration in the existing page controller. Reuse `GridExporter.buildGridCsv()` and `createExportFilename()` so “保存策略” downloads exactly the same CSV content as the existing export action.

**Tech Stack:** HTML5, CSS Grid, vanilla JavaScript, browser `localStorage`, CSV/Blob download, Node.js built-in test runner, `vm`-based pure-module tests, in-app browser acceptance testing.

---

## File Map

- Modify: `grid-strategy-generator/index.html`
  - Add the responsive left strategy list and save/status controls.
  - Add the pure `GridStrategyStore` block.
  - Add local-storage, stale-state, list rendering, load, save, and delete orchestration.
  - Preserve calculator and exporter behavior.
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
  - Load and test the new pure store block.
  - Add static page-contract tests for the sidebar and save wiring.
  - Continue running all calculator and CSV regression tests.

No new runtime files or dependencies are required. The generator remains a portable single-file page.

### Task 1: Versioned Saved-Strategy Store

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs:10-33`
- Modify: `grid-strategy-generator/index.html:626-627` (insert a new marked script block before the page controller)

- [ ] **Step 1: Add the store loader and failing record tests**

Add this loader beside `loadCalculator()` and `loadExporter()`:

```js
function loadStrategyStore() {
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(
    /\/\* GRID_STRATEGY_STORE_START \*\/([\s\S]*?)\/\* GRID_STRATEGY_STORE_END \*\//,
  );
  assert.ok(match, "strategy store block must be present");
  const context = { window: {} };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context.window.GridStrategyStore;
}
```

Add focused tests with these assertions:

```js
test("creates normalized versioned strategy records", () => {
  const { createRecord } = loadStrategyStore();
  const record = createRecord("  159198 港芯  ", {
    startPrice: "8.3",
    stepPct: "5",
    maxDropPct: "40",
    fundingMode: "perGrid",
    amount: "10000",
    feePct: "0.1",
    profitRetentionMultiple: 2,
  }, new Date("2026-07-14T10:20:30.000Z"));

  assert.deepEqual(JSON.parse(JSON.stringify(record)), {
    version: 1,
    symbol: "159198 港芯",
    savedAt: "2026-07-14T10:20:30.000Z",
    input: {
      startPrice: "8.3",
      stepPct: "5",
      maxDropPct: "40",
      fundingMode: "perGrid",
      amount: "10000",
      feePct: "0.1",
      profitRetentionMultiple: 2,
    },
  });
});

test("upserts saved strategies by exact trimmed symbol and sorts newest first", () => {
  const { createRecord, upsertRecord } = loadStrategyStore();
  const older = createRecord("港芯", {
    startPrice: "8", stepPct: "5", maxDropPct: "20", fundingMode: "total",
    amount: "90000", feePct: "0", profitRetentionMultiple: 0,
  }, new Date("2026-07-14T09:00:00.000Z"));
  const newer = createRecord("有色", {
    startPrice: "1", stepPct: "5", maxDropPct: "30", fundingMode: "perGrid",
    amount: "10000", feePct: "0", profitRetentionMultiple: 1,
  }, new Date("2026-07-14T10:00:00.000Z"));
  const replacement = createRecord("港芯", {
    startPrice: "8.3", stepPct: "10", maxDropPct: "40", fundingMode: "perGrid",
    amount: "12000", feePct: "0.1", profitRetentionMultiple: 2,
  }, new Date("2026-07-14T11:00:00.000Z"));

  const records = upsertRecord(upsertRecord([older], newer), replacement);
  assert.deepEqual(Array.from(records, (record) => record.symbol), ["港芯", "有色"]);
  assert.equal(records[0].input.startPrice, "8.3");
});

test("parses valid saved records while skipping damaged data", () => {
  const { parseStore } = loadStrategyStore();
  const good = {
    version: 1,
    symbol: "港芯",
    savedAt: "2026-07-14T10:00:00.000Z",
    input: {
      startPrice: "8.3", stepPct: "5", maxDropPct: "40", fundingMode: "perGrid",
      amount: "10000", feePct: "0", profitRetentionMultiple: 0,
    },
  };

  assert.deepEqual(JSON.parse(JSON.stringify(parseStore("not json"))), {
    records: [], skippedCount: 1,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(parseStore(JSON.stringify({
    version: 1,
    records: [good, { ...good, symbol: "" }],
  })))), {
    records: [good], skippedCount: 1,
  });
});

test("removes one saved symbol and serializes the versioned envelope", () => {
  const { createRecord, removeRecord, serializeStore } = loadStrategyStore();
  const record = createRecord("港芯", {
    startPrice: "8.3", stepPct: "5", maxDropPct: "40", fundingMode: "perGrid",
    amount: "10000", feePct: "0", profitRetentionMultiple: 0,
  }, new Date("2026-07-14T10:00:00.000Z"));
  assert.deepEqual(Array.from(removeRecord([record], " 港芯 ")), []);
  assert.equal(serializeStore([record]), JSON.stringify({ version: 1, records: [record] }));
});
```

- [ ] **Step 2: Run the new store tests and verify the expected failure**

Run:

```powershell
node --test --test-name-pattern="saved strateg|strategy record|damaged data" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because the `GRID_STRATEGY_STORE_START` block does not yet exist.

- [ ] **Step 3: Add the minimal pure store implementation**

Insert this block between the exporter and page-controller scripts:

```html
<script>
/* GRID_STRATEGY_STORE_START */
(() => {
  const STORE_VERSION = 1;
  const ALLOWED_FUNDING_MODES = new Set(["total", "perGrid"]);
  const ALLOWED_RETENTION_MULTIPLES = new Set([0, 1, 2, 3]);

  function normalizeInput(input) {
    const normalized = {
      startPrice: String(input?.startPrice ?? ""),
      stepPct: String(input?.stepPct ?? ""),
      maxDropPct: String(input?.maxDropPct ?? ""),
      fundingMode: String(input?.fundingMode ?? ""),
      amount: String(input?.amount ?? ""),
      feePct: String(input?.feePct ?? "0"),
      profitRetentionMultiple: Number(input?.profitRetentionMultiple),
    };
    if (
      !normalized.startPrice
      || !normalized.stepPct
      || !normalized.maxDropPct
      || !normalized.amount
      || !ALLOWED_FUNDING_MODES.has(normalized.fundingMode)
      || !ALLOWED_RETENTION_MULTIPLES.has(normalized.profitRetentionMultiple)
    ) {
      throw new Error("保存的策略参数无效");
    }
    return normalized;
  }

  function createRecord(symbol, input, savedAt = new Date()) {
    const normalizedSymbol = String(symbol ?? "").trim();
    if (!normalizedSymbol) throw new Error("标的名称不能为空");
    const isoTime = savedAt instanceof Date ? savedAt.toISOString() : new Date(savedAt).toISOString();
    return {
      version: STORE_VERSION,
      symbol: normalizedSymbol,
      savedAt: isoTime,
      input: normalizeInput(input),
    };
  }

  function normalizeRecord(record) {
    if (record?.version !== STORE_VERSION) throw new Error("保存记录版本无效");
    return createRecord(record.symbol, record.input, record.savedAt);
  }

  function sortNewestFirst(records) {
    return [...records].sort((left, right) => right.savedAt.localeCompare(left.savedAt));
  }

  function upsertRecord(records, record) {
    const normalized = normalizeRecord(record);
    return sortNewestFirst([
      ...records.filter((item) => item.symbol !== normalized.symbol),
      normalized,
    ]);
  }

  function removeRecord(records, symbol) {
    const normalizedSymbol = String(symbol ?? "").trim();
    return records.filter((record) => record.symbol !== normalizedSymbol);
  }

  function parseStore(raw) {
    if (!raw) return { records: [], skippedCount: 0 };
    let envelope;
    try {
      envelope = JSON.parse(raw);
    } catch {
      return { records: [], skippedCount: 1 };
    }
    if (envelope?.version !== STORE_VERSION || !Array.isArray(envelope.records)) {
      return { records: [], skippedCount: 1 };
    }
    const records = [];
    let skippedCount = 0;
    for (const candidate of envelope.records) {
      try {
        const record = normalizeRecord(candidate);
        const existingIndex = records.findIndex((item) => item.symbol === record.symbol);
        if (existingIndex >= 0) records.splice(existingIndex, 1);
        records.push(record);
      } catch {
        skippedCount += 1;
      }
    }
    return { records: sortNewestFirst(records), skippedCount };
  }

  function serializeStore(records) {
    return JSON.stringify({ version: STORE_VERSION, records: records.map(normalizeRecord) });
  }

  window.GridStrategyStore = {
    STORE_VERSION,
    createRecord,
    parseStore,
    removeRecord,
    serializeStore,
    upsertRecord,
  };
})();
/* GRID_STRATEGY_STORE_END */
</script>
```

- [ ] **Step 4: Run the targeted and full tests**

Run:

```powershell
node --test --test-name-pattern="saved strateg|strategy record|damaged data" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: all four new store tests PASS; all existing 21 tests PASS.

- [ ] **Step 5: Commit the store unit**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: persist saved grid strategy records"
```

### Task 2: Responsive Saved-Strategy Sidebar

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs:430` (append page-contract test)
- Modify: `grid-strategy-generator/index.html:31-310`

- [ ] **Step 1: Add a failing sidebar contract test**

Append:

```js
test("contains a responsive saved-strategy sidebar and save feedback", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  for (const id of [
    "saved-strategy-list",
    "saved-strategy-empty",
    "save-strategy-button",
    "save-status",
    "tool-column",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /class=["'][^"']*app-layout/);
  assert.match(html, /aria-live=["']polite["']/);
  assert.match(html, /@media \(max-width: 900px\)/);
});
```

- [ ] **Step 2: Run the page-contract test and verify it fails**

Run:

```powershell
node --test --test-name-pattern="responsive saved-strategy sidebar" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because the sidebar IDs are absent.

- [ ] **Step 3: Add the sidebar and action markup**

Keep the hero full-width. After it, add an `.app-layout` containing:

```html
<aside class="panel strategy-sidebar" aria-labelledby="saved-strategy-title">
  <div class="section-heading strategy-heading">
    <h2 id="saved-strategy-title">已保存策略</h2>
  </div>
  <p id="saved-strategy-empty" class="strategy-empty">暂无已保存策略，生成方案后可保存。</p>
  <div id="saved-strategy-list" class="strategy-list" role="list"></div>
</aside>
<div id="tool-column" class="tool-column">
```

Insert the opening `tool-column` tag immediately before the existing parameter section. Insert its closing `</div>` immediately after the existing disclaimer, so the existing parameter section, results section, and disclaimer become its children without altering their contents.

Replace the lone submit button with an action row:

```html
<div class="form-actions">
  <button class="primary-button" type="submit">生成网格计划</button>
  <button id="save-strategy-button" class="secondary-button" type="button" disabled>保存策略</button>
</div>
<p id="save-status" class="save-status" aria-live="polite" hidden></p>
```

- [ ] **Step 4: Add current-style responsive CSS**

Extend the current tokens and button styles, without changing the established palette:

```css
.page-shell { width: min(1480px, calc(100% - 32px)); }
.app-layout {
  display: grid;
  grid-template-columns: minmax(240px, 280px) minmax(0, 1fr);
  align-items: start;
  gap: 24px;
}
.strategy-sidebar { position: sticky; top: 24px; }
.strategy-heading { margin-bottom: 12px; }
.strategy-empty { margin: 0; color: var(--muted); font-size: 0.92rem; }
.strategy-list { display: grid; gap: 10px; }
.strategy-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: #fbfdfd;
}
.strategy-item.is-active {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent);
}
.strategy-load, .strategy-delete {
  min-height: 52px;
  border: 0;
  background: transparent;
  cursor: pointer;
}
.strategy-load { padding: 10px 12px; text-align: left; color: var(--ink); }
.strategy-load strong, .strategy-load time { display: block; }
.strategy-load time { margin-top: 2px; color: var(--muted); font-size: 0.78rem; }
.strategy-delete { border-left: 1px solid var(--line); color: var(--loss); font-weight: 800; }
.form-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 20px; }
.form-actions .primary-button { margin-top: 0; }
.secondary-button {
  min-height: 48px;
  padding: 11px 18px;
  border: 1px solid #a9cfc5;
  border-radius: 10px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-weight: 800;
  cursor: pointer;
}
.secondary-button:disabled { cursor: not-allowed; opacity: 0.48; }
.save-status { margin: 12px 0 0; color: var(--muted); font-weight: 650; }
.save-status.is-error { color: var(--loss); }

@media (max-width: 900px) {
  .app-layout { grid-template-columns: 1fr; }
  .strategy-sidebar { position: static; }
}
```

At the existing 720px breakpoint, make `.form-actions` and its buttons full width. Keep visible focus styles for the new buttons through the existing `button:focus-visible` rule.

- [ ] **Step 5: Run tests and inspect the static layout contract**

Run:

```powershell
node --test --test-name-pattern="responsive saved-strategy sidebar" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: sidebar test PASS; full suite PASS.

- [ ] **Step 6: Commit the layout unit**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: add saved strategy sidebar"
```

### Task 3: Save, Load, Overwrite, Stale-State, and Delete Wiring

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs` (append controller contract tests)
- Modify: `grid-strategy-generator/index.html:629-807`

- [ ] **Step 1: Add a failing controller contract test**

Append:

```js
test("wires local save, reload, overwrite, and confirmed delete behavior", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  assert.match(html, /localStorage\.getItem\(STRATEGY_STORAGE_KEY\)/);
  assert.match(html, /localStorage\.setItem\(STRATEGY_STORAGE_KEY/);
  assert.match(html, /window\.confirm\(/);
  assert.match(html, /requestSubmit\(\)/);
  assert.match(html, /GridStrategyStore\.upsertRecord/);
  assert.match(html, /GridStrategyStore\.removeRecord/);
  assert.match(html, /GridExporter\.buildGridCsv/);
  assert.match(html, /saveStrategyButton\.disabled = !planIsCurrent/);
});
```

- [ ] **Step 2: Run the controller contract test and verify it fails**

Run:

```powershell
node --test --test-name-pattern="wires local save" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because controller storage wiring is absent.

- [ ] **Step 3: Add controller state and small reusable helpers**

At controller startup add:

```js
const STRATEGY_STORAGE_KEY = "grid-strategy-generator.saved-strategies.v1";
const calculationFieldIds = new Set([
  "symbol-name", "start-price", "step-pct", "max-drop-pct", "funding-mode",
  "funding-amount", "fee-pct", "profit-retention",
]);
const saveStrategyButton = byId("save-strategy-button");
let savedStrategies = [];
let activeSavedSymbol = null;
let planIsCurrent = false;
```

Add these helpers using the shown responsibilities and signatures:

```js
function setSaveStatus(message, isError = false) {
  const status = byId("save-status");
  status.textContent = message;
  status.classList.toggle("is-error", isError);
  status.hidden = !message;
}

function setPlanCurrent(isCurrent) {
  planIsCurrent = isCurrent;
  saveStrategyButton.disabled = !planIsCurrent;
}

function downloadPlanCsv(symbol, plan) {
  const csv = window.GridExporter.buildGridCsv(plan.input, plan.result);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = window.GridExporter.createExportFilename(symbol);
    document.body.append(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
```

Refactor the existing export click handler to call `downloadPlanCsv(symbol, latestPlan)`. This guarantees save and export share the same serializer, MIME type, naming function, and URL cleanup.

- [ ] **Step 4: Load and render the saved-strategy index**

Implement startup reading with independent corruption feedback:

```js
function loadSavedStrategies() {
  try {
    const parsed = window.GridStrategyStore.parseStore(
      localStorage.getItem(STRATEGY_STORAGE_KEY),
    );
    savedStrategies = parsed.records;
    if (parsed.skippedCount > 0) {
      setSaveStatus(`有 ${parsed.skippedCount} 条本地策略记录无法读取，已跳过。`, true);
    }
  } catch (error) {
    savedStrategies = [];
    setSaveStatus(`无法读取本地策略：${error.message}`, true);
  }
  renderSavedStrategies();
}
```

`renderSavedStrategies()` must:

- toggle `saved-strategy-empty` based on record count;
- create DOM nodes with `textContent`, never interpolate symbols through `innerHTML`;
- render one `role="listitem"` wrapper per record;
- render a load button containing `<strong>` and `<time>`;
- format `savedAt` with `Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" })`;
- give the delete button `aria-label="删除 ${record.symbol} 策略"` and visible text `删除`;
- apply `.is-active` only when `record.symbol === activeSavedSymbol`.

Call `loadSavedStrategies()` once after registering handlers.

- [ ] **Step 5: Invalidate stale plans and restore saved inputs**

On form `input` and `change`, when `event.target.id` is in `calculationFieldIds`, call:

```js
setPlanCurrent(false);
setSaveStatus(latestPlan ? "参数已修改，请重新生成后再保存。" : "");
if (event.target.id === "symbol-name") {
  activeSavedSymbol = null;
  renderSavedStrategies();
}
```

The step preset handler must call `setPlanCurrent(false)` after changing the step value and show the same stale-plan message when `latestPlan` exists.

On successful form submission, after assigning `latestPlan`, call `setPlanCurrent(true)`. On calculation failure call `setPlanCurrent(false)`.

Implement saved-strategy loading:

```js
function loadStrategy(record) {
  byId("symbol-name").value = record.symbol;
  byId("start-price").value = record.input.startPrice;
  byId("step-pct").value = record.input.stepPct;
  byId("max-drop-pct").value = record.input.maxDropPct;
  byId("funding-mode").value = record.input.fundingMode;
  byId("funding-amount").value = record.input.amount;
  byId("fee-pct").value = record.input.feePct;
  byId("profit-retention").value = String(record.input.profitRetentionMultiple);
  updateFundingLabel();
  activeSavedSymbol = record.symbol;
  renderSavedStrategies();
  setSaveStatus("");
  byId("grid-form").requestSubmit();
}
```

Extract `updateFundingLabel()` so both the funding-mode listener and saved loading use the same label update.

- [ ] **Step 6: Implement save with independent CSV and index outcomes**

The save handler must first reject three states in this order:

1. empty trimmed symbol: show “请填写标的名称并重新生成网格计划。” and focus the symbol input;
2. no `latestPlan`: show “请先生成网格计划。”;
3. `planIsCurrent === false`: show “参数已修改，请重新生成后再保存。”.

Then create a record from `latestPlan.input`. Attempt download and `localStorage.setItem()` in separate `try/catch` blocks:

```js
const record = window.GridStrategyStore.createRecord(symbol, latestPlan.input, new Date());
const nextRecords = window.GridStrategyStore.upsertRecord(savedStrategies, record);
let csvSaved = false;
let indexSaved = false;

try {
  downloadPlanCsv(symbol, latestPlan);
  csvSaved = true;
} catch (error) {
  console.error("CSV download failed", error);
}

try {
  localStorage.setItem(
    STRATEGY_STORAGE_KEY,
    window.GridStrategyStore.serializeStore(nextRecords),
  );
  savedStrategies = nextRecords;
  activeSavedSymbol = symbol;
  renderSavedStrategies();
  indexSaved = true;
} catch (error) {
  console.error("Strategy index save failed", error);
}
```

Show one of four truthful messages:

- both true: “策略已保存到左侧列表，CSV 已下载。”;
- CSV only: “CSV 已下载，但左侧列表保存失败。”;
- index only: “策略已保存到左侧列表，但 CSV 下载失败。”;
- neither: “策略保存失败，CSV 和左侧列表均未保存。”.

Use error styling for every partial or total failure.

- [ ] **Step 7: Implement confirmed deletion**

When the delete button is clicked:

```js
if (!window.confirm(`确定删除“${record.symbol}”策略吗？已下载的 CSV 不会被删除。`)) return;
const nextRecords = window.GridStrategyStore.removeRecord(savedStrategies, record.symbol);
try {
  localStorage.setItem(
    STRATEGY_STORAGE_KEY,
    window.GridStrategyStore.serializeStore(nextRecords),
  );
  savedStrategies = nextRecords;
  if (activeSavedSymbol === record.symbol) activeSavedSymbol = null;
  renderSavedStrategies();
  setSaveStatus(`已从左侧列表删除“${record.symbol}”。`);
} catch (error) {
  setSaveStatus(`删除失败：${error.message}`, true);
}
```

Do not clear `latestPlan`, the visible results, or downloaded files.

- [ ] **Step 8: Run targeted and full tests**

Run:

```powershell
node --test --test-name-pattern="wires local save|saved strateg|strategy record|damaged data|responsive saved-strategy sidebar" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: all save/store/sidebar tests PASS; full suite PASS with zero failures.

- [ ] **Step 9: Commit the controller unit**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: save and reload grid strategies"
```

### Task 4: Browser Acceptance and Final Regression

**Files:**
- Verify: `grid-strategy-generator/index.html`
- Verify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Start a temporary local server**

From `grid-strategy-generator` run:

```powershell
python -m http.server 52344 --bind 127.0.0.1
```

Open `http://127.0.0.1:52344/` in the in-app browser.

- [ ] **Step 2: Verify empty and disabled states on desktop**

At a viewport wider than 900px verify:

- “已保存策略” is left of the parameter/results column;
- the empty-state text is visible;
- “保存策略” is disabled before generation;
- focus rings are visible when tabbing through load/save/delete controls;
- no unrelated visual styles changed.

- [ ] **Step 3: Verify first save and persisted reload**

Use:

```text
标的名称: 港芯
起始价: 8.300
步长比例: 5
最大跌幅: 40
资金模式: 固定每格金额
每格金额: 10000
单边费率: 0
留利润策略: 留 2 份利润
```

Generate and save. Verify:

- the left list contains one “港芯” item and a save time;
- the saved item is visibly active;
- the status says both left index and CSV were saved;
- the existing CSV serializer test confirms the downloaded content contract;
- refreshing the page preserves the left item.

- [ ] **Step 4: Verify overwrite, load, stale-state, and delete**

- Change 港芯 step to 10%, regenerate, and save; verify the list still has one 港芯 item with a newer time.
- Change parameters without generating; verify “保存策略” becomes disabled.
- Save a second symbol “有色”; verify it appears above 港芯.
- Click 港芯; verify every field restores, funding label is correct, results regenerate, and 港芯 becomes active.
- Start deleting 港芯 and cancel; verify the item remains.
- Confirm deletion; verify 港芯 disappears while the current result remains visible.

- [ ] **Step 5: Verify the narrow layout**

At a 375px-wide viewport verify:

- the strategy list appears above the parameter panel;
- action buttons are full width and at least 44px high;
- no page-level horizontal scrolling is introduced;
- the existing result table remains usable through its own horizontal scroll container.

- [ ] **Step 6: Run final automated verification**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check
git status --short
```

Expected: full suite PASS with zero failures; `git diff --check` has no output; status contains only the two intended generator files if browser verification required a final correction, otherwise it is clean.

- [ ] **Step 7: Commit any browser-verification correction**

Only if Step 2-5 required a correction:

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: polish saved strategy interactions"
```

If no correction was needed, do not create an empty commit.
