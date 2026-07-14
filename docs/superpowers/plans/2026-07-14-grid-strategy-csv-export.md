# 网格策略完整方案 CSV 导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有离线网格策略页面增加完整方案 CSV 导出，文件可由 Excel 正确打开，且标的名称仅用于文件名。

**Architecture:** 继续保持单文件离线网页结构。在 `index.html` 中增加一组可独立测试的纯函数，负责 CSV 转义、内容组装、文件名清理和时间格式化；页面事件层只保存最近一次成功计算的输入与结果，并通过浏览器原生 Blob 下载。

**Tech Stack:** HTML、CSS、原生 JavaScript、浏览器 Blob/Object URL、Node.js `node:test`

---

## 文件结构

- Modify: `grid-strategy-generator/index.html` — 增加导出按钮、纯 CSV 工具函数、最近一次方案快照和浏览器下载事件。
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs` — 增加纯函数单元测试、页面结构测试和导出交互静态约束。

不创建服务端文件，不引入第三方依赖，不拆分现有单文件页面。

## 执行前状态

当前工作区中 `index.html` 与测试文件还保留着上一项已验证的“最低档情景-持仓总市值”改名。执行本计划前先用以下命令把这项既有改动单独提交，避免它混入 CSV 功能提交：

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: clarify bottom-level market value label"
```

Expected: 提交只包含标签文字及其对应测试。

### Task 1: CSV 内容、转义与文件名纯函数

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html`，在 `GRID_CALCULATOR_END` 后增加 `GRID_EXPORT_START/END` 纯函数块

- [ ] **Step 1: 写入失败测试，加载导出纯函数**

在测试文件的 `loadCalculator()` 后增加：

```js
function loadExporter() {
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(
    /\/\* GRID_EXPORT_START \*\/([\s\S]*?)\/\* GRID_EXPORT_END \*\//,
  );
  assert.ok(match, "export block must be present");
  const context = { window: {} };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context.window.GridExporter;
}
```

在测试文件末尾增加：

```js
test("serializes a complete grid plan as Excel-friendly CSV", () => {
  const { buildGridCsv } = loadExporter();
  const { calculateGrid } = loadCalculator();
  const input = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0.1,
  };
  const csv = buildGridCsv(input, calculateGrid(input));

  assert.equal(csv.charCodeAt(0), 0xFEFF);
  assert.match(csv, /输入参数,数值\r\n起始价格,1\.000/);
  assert.match(csv, /资金模式,固定每格金额/);
  assert.match(csv, /压力测试,数值/);
  assert.match(csv, /最低档情景-持仓总市值/);
  assert.match(csv, /序号,档位,买入价格,卖出价格,买入数量,买入金额,卖出数量,卖出金额,盈利金额,盈利比例/);
  assert.match(csv, /1,1\.000,1\.000,1\.050,10000,10000\.00,10000,10500\.00,479\.50,4\.80%/);
});

test("escapes CSV cells and creates a safe timestamped filename", () => {
  const { serializeCsv, createExportFilename } = loadExporter();

  assert.equal(
    serializeCsv([["名称", "含,逗号"], ["说明", "有\"引号\""]]),
    "\uFEFF名称,\"含,逗号\"\r\n说明,\"有\"\"引号\"\"\"",
  );
  assert.equal(
    createExportFilename("  中证/500:ETF  ", new Date(2026, 6, 14, 9, 8, 7)),
    "中证-500-ETF-网格策略-20260714-090807.csv",
  );
});
```

- [ ] **Step 2: 运行定向测试，确认因导出模块不存在而失败**

Run:

```powershell
node --test --test-name-pattern="CSV|filename" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL，错误包含 `export block must be present`。

- [ ] **Step 3: 增加最小纯函数实现**

在计算器脚本块之后、页面事件脚本之前增加：

```html
<script>
/* GRID_EXPORT_START */
(() => {
  function escapeCsvCell(value) {
    const text = String(value ?? "");
    return /[",\r\n]/.test(text)
      ? `"${text.replaceAll('"', '""')}"`
      : text;
  }

  function serializeCsv(rows) {
    return `\uFEFF${rows.map((row) => row.map(escapeCsvCell).join(",")).join("\r\n")}`;
  }

  function formatTimestamp(date) {
    const pad = (value) => String(value).padStart(2, "0");
    return [
      date.getFullYear(),
      pad(date.getMonth() + 1),
      pad(date.getDate()),
      "-",
      pad(date.getHours()),
      pad(date.getMinutes()),
      pad(date.getSeconds()),
    ].join("");
  }

  function sanitizeFilenamePart(value) {
    return String(value ?? "")
      .trim()
      .replace(/[\\/:*?"<>|]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/[. ]+$/g, "");
  }

  function createExportFilename(symbol, date = new Date()) {
    return `${sanitizeFilenamePart(symbol)}-网格策略-${formatTimestamp(date)}.csv`;
  }

  function buildGridCsv(input, result) {
    const fundingModeLabel = input.fundingMode === "total" ? "限定总资金" : "固定每格金额";
    const fundingLabel = input.fundingMode === "total" ? "总资金（元）" : "每格金额（元）";
    const rows = [
      ["输入参数", "数值"],
      ["起始价格", Number(input.startPrice).toFixed(3)],
      ["步长比例", `${Number(input.stepPct).toFixed(2)}%`],
      ["最大跌幅", `${Number(input.maxDropPct).toFixed(2)}%`],
      ["资金模式", fundingModeLabel],
      [fundingLabel, Number(input.amount).toFixed(2)],
      ["单边费率", `${Number(input.feePct).toFixed(3)}%`],
      [],
      ["压力测试", "数值"],
      ["实际价格步长", result.meta.rawStep.toFixed(3)],
      ["覆盖跌幅", `${result.meta.coveragePct.toFixed(2)}%`],
      ["网格档数", result.meta.levelCount],
      ["证券本金预算", result.pressure.plannedSecurityPrincipal.toFixed(2)],
      ["计划现金", result.pressure.plannedCash.toFixed(2)],
      ["最大实际投入", result.pressure.maxCashUsed.toFixed(2)],
      ["未使用现金", result.pressure.unusedCash.toFixed(2)],
      ["总持仓", result.pressure.totalQuantity],
      ["平均成本", result.pressure.averageCost.toFixed(3)],
      ["最低买入价", result.pressure.lowestPrice.toFixed(3)],
      ["最低档情景-持仓总市值", result.pressure.marketValueAtBottom.toFixed(2)],
      ["最低档浮亏", result.pressure.unrealizedPnl.toFixed(2)],
      ["最低档浮亏比例", `${result.pressure.unrealizedPnlPct.toFixed(2)}%`],
      [],
      ["序号", "档位", "买入价格", "卖出价格", "买入数量", "买入金额", "卖出数量", "卖出金额", "盈利金额", "盈利比例"],
      ...result.levels.map((row) => [
        row.index,
        row.buyPrice.toFixed(3),
        row.buyPrice.toFixed(3),
        row.sellPrice.toFixed(3),
        row.quantity,
        row.actualBuyAmount.toFixed(2),
        row.quantity,
        row.sellAmount.toFixed(2),
        row.netProfit.toFixed(2),
        `${row.netReturnPct.toFixed(2)}%`,
      ]),
    ];
    return serializeCsv(rows);
  }

  window.GridExporter = {
    buildGridCsv,
    createExportFilename,
    escapeCsvCell,
    formatTimestamp,
    sanitizeFilenamePart,
    serializeCsv,
  };
})();
/* GRID_EXPORT_END */
</script>
```

- [ ] **Step 4: 运行定向测试，确认纯函数通过**

Run:

```powershell
node --test --test-name-pattern="CSV|filename" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 新增的 2 项测试 PASS，其余测试因名称过滤而 SKIP。

- [ ] **Step 5: 提交纯函数与测试**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: build grid strategy CSV content"
```

### Task 2: 页面导出按钮与最近方案快照

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html`，结果区和页面事件脚本

- [ ] **Step 1: 写入失败的页面结构测试**

在测试文件末尾增加：

```js
test("contains an offline CSV export action and latest-plan snapshot", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /id=["']export-csv-button["']/);
  assert.match(html, /let latestPlan = null/);
  assert.match(html, /new Blob\(\[csv\], \{ type: "text\/csv;charset=utf-8" \}\)/);
  assert.match(html, /URL\.revokeObjectURL/);
  assert.doesNotMatch(html, /\bfetch\s*\(/);
});
```

- [ ] **Step 2: 运行定向测试，确认按钮和下载逻辑尚不存在**

Run:

```powershell
node --test --test-name-pattern="offline CSV export" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL，缺少 `export-csv-button`。

- [ ] **Step 3: 在结果区增加导出按钮**

把 `plan-title` 后的内容改为：

```html
<div class="plan-toolbar">
  <p id="plan-title" class="plan-name"></p>
  <button id="export-csv-button" class="preset-button" type="button">导出完整方案 CSV</button>
</div>
```

在 `.plan-name` 样式附近增加：

```css
.plan-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: -8px 0 18px;
}
.plan-toolbar .plan-name { margin: 0; }
@media (max-width: 720px) {
  .plan-toolbar { align-items: stretch; flex-direction: column; }
}
```

- [ ] **Step 4: 保存最近一次成功方案并实现本地下载**

在页面事件脚本的格式化对象之后增加：

```js
let latestPlan = null;
```

把表单提交中的计算与渲染改为先保存输入快照：

```js
const input = {
  startPrice: byId("start-price").value,
  stepPct: byId("step-pct").value,
  maxDropPct: byId("max-drop-pct").value,
  fundingMode: byId("funding-mode").value,
  amount: byId("funding-amount").value,
  feePct: byId("fee-pct").value || 0,
};
const result = window.GridCalculator.calculateGrid(input);
latestPlan = { input: { ...input }, result };
renderResult(result);
```

在表单事件之后增加：

```js
byId("export-csv-button").addEventListener("click", () => {
  if (!latestPlan) return;

  const symbolInput = byId("symbol-name");
  const symbol = symbolInput.value.trim();
  const errorBox = byId("error-message");
  if (!symbol) {
    errorBox.textContent = "请先填写标的名称。";
    errorBox.hidden = false;
    symbolInput.focus();
    return;
  }

  errorBox.hidden = true;
  const csv = window.GridExporter.buildGridCsv(latestPlan.input, latestPlan.result);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = window.GridExporter.createExportFilename(symbol);
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
});
```

- [ ] **Step 5: 运行定向测试，确认页面导出结构通过**

Run:

```powershell
node --test --test-name-pattern="offline CSV export" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 新增测试 PASS。

- [ ] **Step 6: 提交页面交互**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: download the latest grid plan as CSV"
```

### Task 3: 完整回归与浏览器验收

**Files:**
- Verify: `grid-strategy-generator/index.html`
- Verify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: 运行全部自动测试**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 全部 15 项测试 PASS，0 FAIL。

- [ ] **Step 2: 检查补丁格式**

Run:

```powershell
git diff --check HEAD~2..HEAD
```

Expected: 无输出，退出码为 0。

- [ ] **Step 3: 在本地网页验证未填写标的名称的行为**

1. 打开 `grid-strategy-generator/index.html`。
2. 保持标的名称为空，填写有效计算参数并生成网格。
3. 点击“导出完整方案 CSV”。

Expected: 页面显示“请先填写标的名称。”，焦点回到标的名称输入框，不产生下载文件。

- [ ] **Step 4: 在本地网页验证下载内容**

1. 输入标的名称 `中证/500:ETF`。
2. 再次点击“导出完整方案 CSV”。
3. 用 Excel 打开下载文件。

Expected:

- 文件名形如 `中证-500-ETF-网格策略-20260714-090807.csv`。
- 中文无乱码。
- 文件包含输入参数、压力测试、逐档网格三段。
- 标的名称不出现在 CSV 内容中。
- 修改页面参数但不重新生成时，导出内容仍与页面当前结果一致。

- [ ] **Step 5: 查看最终状态，确认未混入无关文件**

Run:

```powershell
git status --short
```

Expected: 本任务相关提交已完成；既有无关未跟踪目录和此前未提交改动保持原状，没有被纳入本任务提交。
