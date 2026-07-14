# 网格策略 2.1 留利润 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有离线网格生成器中增加关闭、留 1 份、留 2 份、留 3 份利润选项，并完整展示逐档卖出、留存、完成一轮汇总和 CSV。

**Architecture:** 扩展现有 `calculateGrid(input)`，由一个纯计算入口同时产生 1.0 兼容字段、留利润字段和完成一轮汇总。页面根据 `result.meta.profitRetentionMultiple` 动态切换 1.0/2.1 表头与汇总区，CSV 使用同一结果对象，避免页面和导出重复计算。

**Tech Stack:** HTML、CSS、原生 JavaScript、Node.js `node:test`

---

## 文件结构

- Modify: `grid-strategy-generator/index.html` — 扩展计算器、参数表单、完成一轮汇总、动态表格和 CSV。
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs` — 覆盖 1/2/3 份、费用、100 份边界、汇总、页面结构和 CSV。

不创建新运行时文件，不引入第三方依赖，不修改网格回测仪表盘。

### Task 1: 留利润计算与完成一轮汇总

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html` 的 `GRID_CALCULATOR_START/END` 区块

- [ ] **Step 1: 写入留 1/2/3 份的失败测试**

在测试文件末尾增加：

```js
test("retains one, two, or three profit portions in 100-share lots", () => {
  const { calculateGrid } = loadCalculator();
  const base = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  };

  const rows = [1, 2, 3].map((multiple) => calculateGrid({
    ...base,
    profitRetentionMultiple: multiple,
  }).levels[0]);

  assert.deepEqual(
    Array.from(rows, (row) => [
      row.sellQuantity,
      row.retainedQuantity,
      row.sellAmount,
      row.retainedMarketValue,
      row.cashPnl,
      row.combinedProfit,
    ]),
    [
      [9_600, 400, 10_080, 420, 80, 500],
      [9_100, 900, 9_555, 945, -445, 500],
      [8_600, 1_400, 9_030, 1_470, -970, 500],
    ],
  );
});
```

- [ ] **Step 2: 运行测试，确认因留利润字段不存在而失败**

Run:

```powershell
node --test --test-name-pattern="retains one" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL，实际结果中的 `sellQuantity` 等字段为 `undefined`。

- [ ] **Step 3: 扩展每档计算**

在 `calculateGrid` 读取 `feePct` 后增加：

```js
const profitRetentionMultiple = Number(input.profitRetentionMultiple ?? 0);
if (![0, 1, 2, 3].includes(profitRetentionMultiple)) {
  throw new Error("留利润策略必须为关闭、留 1 份、留 2 份或留 3 份");
}
```

把 `levels` 中金额和利润计算替换为：

```js
const actualBuyAmount = roundMoney(quantity * buyPrice);
const fullSellAmount = roundMoney(quantity * sellPrice);
const fullGrossProfit = roundMoney(fullSellAmount - actualBuyAmount);
const targetSellProceeds = profitRetentionMultiple === 0
  ? fullSellAmount
  : Math.max(
    0,
    actualBuyAmount - (profitRetentionMultiple - 1) * fullGrossProfit,
  );
const sellQuantity = profitRetentionMultiple === 0
  ? quantity
  : Math.min(
    quantity,
    targetSellProceeds <= 0
      ? 0
      : Math.ceil(targetSellProceeds / sellPrice / 100 - 1e-12) * 100,
  );
const retainedQuantity = quantity - sellQuantity;
const sellAmount = roundMoney(sellQuantity * sellPrice);
const retainedMarketValue = roundMoney(retainedQuantity * sellPrice);
const buyFee = roundMoney(actualBuyAmount * feeRate);
const sellFee = roundMoney(sellAmount * feeRate);
const cashPnl = roundMoney(sellAmount - actualBuyAmount - buyFee - sellFee);
const combinedProfit = roundMoney(cashPnl + retainedMarketValue);
const grossProfit = fullGrossProfit;
const netProfit = profitRetentionMultiple === 0 ? cashPnl : combinedProfit;
```

在每档返回对象中保留原字段并加入：

```js
fullSellAmount,
sellQuantity,
retainedQuantity,
retainedMarketValue,
cashPnl,
combinedProfit,
```

`netReturnPct` 继续使用 `netProfit / actualBuyAmount * 100`，因此关闭策略时与 1.0 完全一致；开启时代表综合利润率，但 2.1 页面不直接展示该字段。

- [ ] **Step 4: 运行定向测试，确认 1/2/3 份示例通过**

Run:

```powershell
node --test --test-name-pattern="retains one" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: PASS。

- [ ] **Step 5: 写入费用、边界、汇总和兼容性失败测试**

增加：

```js
test("keeps retention quantities independent from fees", () => {
  const { calculateGrid } = loadCalculator();
  const row = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0.1,
    profitRetentionMultiple: 1,
  }).levels[0];

  assert.equal(row.sellQuantity, 9_600);
  assert.equal(row.retainedQuantity, 400);
  assert.equal(row.cashPnl, 59.92);
  assert.equal(row.combinedProfit, 479.92);
});

test("handles zero retained shares, full retention, and invalid multiples", () => {
  const { calculateGrid } = loadCalculator();
  const base = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 100,
    feePct: 0,
  };

  const noRemainder = calculateGrid({
    ...base,
    profitRetentionMultiple: 1,
  }).levels[0];
  assert.equal(noRemainder.sellQuantity, 100);
  assert.equal(noRemainder.retainedQuantity, 0);

  const fullRetention = calculateGrid({
    ...base,
    stepPct: 90,
    maxDropPct: 90,
    profitRetentionMultiple: 3,
  }).levels[0];
  assert.equal(fullRetention.sellQuantity, 0);
  assert.equal(fullRetention.retainedQuantity, 100);

  assert.throws(
    () => calculateGrid({ ...base, profitRetentionMultiple: 4 }),
    /留利润策略必须为/,
  );
});

test("summarizes one completed round without changing pressure results", () => {
  const { calculateGrid } = loadCalculator();
  const base = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 10,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  };
  const plain = calculateGrid(base);
  const retained = calculateGrid({ ...base, profitRetentionMultiple: 1 });

  assert.equal(retained.pressure.maxCashUsed, plain.pressure.maxCashUsed);
  assert.deepEqual(
    JSON.parse(JSON.stringify(retained.completion)),
    {
      totalSellProceeds: retained.levels.reduce((sum, row) => sum + row.sellAmount, 0),
      totalRetainedQuantity: retained.levels.reduce((sum, row) => sum + row.retainedQuantity, 0),
      totalRetainedMarketValue: retained.levels.reduce((sum, row) => sum + row.retainedMarketValue, 0),
      totalCashPnl: retained.levels.reduce((sum, row) => sum + row.cashPnl, 0),
      totalCombinedProfit: retained.levels.reduce((sum, row) => sum + row.combinedProfit, 0),
    },
  );
  assert.equal(plain.levels[0].sellQuantity, plain.levels[0].quantity);
  assert.equal(plain.levels[0].retainedQuantity, 0);
  assert.equal(plain.levels[0].netProfit, 500);
});
```

- [ ] **Step 6: 运行新增边界测试，确认缺少汇总而失败**

Run:

```powershell
node --test --test-name-pattern="fees|zero retained|completed round" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 费用和边界测试 PASS；完成一轮测试 FAIL，因为 `result.completion` 尚不存在。

- [ ] **Step 7: 增加完成一轮汇总与元数据**

在压力测试计算之前增加：

```js
const completion = {
  totalSellProceeds: roundMoney(levels.reduce((sum, row) => sum + row.sellAmount, 0)),
  totalRetainedQuantity: levels.reduce((sum, row) => sum + row.retainedQuantity, 0),
  totalRetainedMarketValue: roundMoney(
    levels.reduce((sum, row) => sum + row.retainedMarketValue, 0),
  ),
  totalCashPnl: roundMoney(levels.reduce((sum, row) => sum + row.cashPnl, 0)),
  totalCombinedProfit: roundMoney(
    levels.reduce((sum, row) => sum + row.combinedProfit, 0),
  ),
};
```

在 `meta` 中增加：

```js
profitRetentionMultiple,
```

在最终返回对象中增加：

```js
completion,
```

- [ ] **Step 8: 运行所有计算器测试**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 当前 19 项测试全部 PASS。

- [ ] **Step 9: 提交计算功能**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: calculate retained grid profits"
```

### Task 2: 参数、完成一轮汇总与动态表格

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html` 的表单、结果区和页面脚本

- [ ] **Step 1: 写入页面结构失败测试**

增加：

```js
test("contains profit-retention controls and completion summary", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  for (const id of [
    "profit-retention",
    "completion-panel",
    "completion-summary",
    "grid-table-head",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /每档完成一轮后/);
  assert.match(html, /综合利润未扣除留存份额未来卖出费用/);
});
```

- [ ] **Step 2: 运行页面测试，确认控件不存在**

Run:

```powershell
node --test --test-name-pattern="profit-retention controls" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL，缺少 `profit-retention`。

- [ ] **Step 3: 增加表单与结果区结构**

在费率字段后增加：

```html
<label for="profit-retention">留利润策略
  <select id="profit-retention">
    <option value="0" selected>关闭（网格 1.0）</option>
    <option value="1">留 1 份利润</option>
    <option value="2">留 2 份利润</option>
    <option value="3">留 3 份利润</option>
  </select>
  <span class="helper">按税费前利润计算留存，费用另外计入盈亏</span>
</label>
```

在压力测试面板后增加：

```html
<section id="completion-panel" class="panel" aria-labelledby="completion-title" hidden>
  <div class="section-heading">
    <h2 id="completion-title">3. 每档完成一轮后</h2>
    <p>各档分别完成一次买入和计划卖出</p>
  </div>
  <div id="completion-summary" class="metric-grid"></div>
  <p class="note">综合利润未扣除留存份额未来卖出费用。</p>
</section>
```

把现有表头改为：

```html
<thead>
  <tr id="grid-table-head"></tr>
</thead>
```

- [ ] **Step 4: 提交表单中的留利润倍数**

在表单输入快照中增加：

```js
profitRetentionMultiple: Number(byId("profit-retention").value),
```

- [ ] **Step 5: 动态渲染表头、完成一轮汇总和明细**

在 `renderResult(result)` 压力测试渲染之后增加：

```js
const retentionEnabled = result.meta.profitRetentionMultiple > 0;
const completionPanel = byId("completion-panel");
completionPanel.hidden = !retentionEnabled;
byId("completion-title").textContent = "3. 每档完成一轮后";
byId("table-title").textContent = retentionEnabled ? "4. 网格计划" : "3. 网格计划";

if (retentionEnabled) {
  byId("completion-summary").replaceChildren(
    metric("累计卖出回款", `¥${money.format(result.completion.totalSellProceeds)}`),
    metric("累计留存份额", `${integer.format(result.completion.totalRetainedQuantity)} 份`),
    metric("累计留存市值", `¥${money.format(result.completion.totalRetainedMarketValue)}`),
    metric("累计现金盈亏", `¥${money.format(result.completion.totalCashPnl)}`),
    metric("累计综合利润", `¥${money.format(result.completion.totalCombinedProfit)}`),
  );
} else {
  byId("completion-summary").replaceChildren();
}

const headers = retentionEnabled
  ? ["档位", "买入价", "卖出价", "买入数量", "实际买入金额", "卖出数量", "卖出回款", "留存数量", "留存市值", "现金盈亏", "综合利润"]
  : ["档位", "买入价", "卖出价", "计划预算", "数量", "实际买入金额", "卖出金额", "税费前利润", "税费后利润", "净收益率"];
byId("grid-table-head").replaceChildren(...headers.map((label) => {
  const th = document.createElement("th");
  th.scope = "col";
  th.textContent = label;
  return th;
}));
```

把逐档 `values` 定义替换为：

```js
const values = retentionEnabled
  ? [
    row.index,
    row.buyPrice.toFixed(3),
    row.sellPrice.toFixed(3),
    integer.format(row.quantity),
    money.format(row.actualBuyAmount),
    integer.format(row.sellQuantity),
    money.format(row.sellAmount),
    integer.format(row.retainedQuantity),
    money.format(row.retainedMarketValue),
    money.format(row.cashPnl),
    money.format(row.combinedProfit),
  ]
  : [
    row.index,
    row.buyPrice.toFixed(3),
    row.sellPrice.toFixed(3),
    money.format(row.plannedBudget),
    integer.format(row.quantity),
    money.format(row.actualBuyAmount),
    money.format(row.sellAmount),
    money.format(row.grossProfit),
    money.format(row.netProfit),
    `${row.netReturnPct.toFixed(2)}%`,
  ];
const profitIndexes = retentionEnabled ? [9, 10] : [8, 9];
```

把颜色判断改为：

```js
if (profitIndexes.includes(index)) {
  const profit = retentionEnabled
    ? (index === 9 ? row.cashPnl : row.combinedProfit)
    : row.netProfit;
  td.className = profit >= 0 ? "positive" : "negative";
}
```

- [ ] **Step 6: 运行页面结构和全部测试**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 20 项测试全部 PASS。

- [ ] **Step 7: 提交页面功能**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: show retained profit grid plan"
```

### Task 3: 留利润 CSV

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html` 的 `GRID_EXPORT_START/END` 区块

- [ ] **Step 1: 写入留利润 CSV 失败测试**

增加：

```js
test("exports retention settings, completion summary, and retained rows", () => {
  const { buildGridCsv } = loadExporter();
  const { calculateGrid } = loadCalculator();
  const input = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
    profitRetentionMultiple: 2,
  };
  const csv = buildGridCsv(input, calculateGrid(input));

  assert.match(csv, /留利润策略,留 2 份利润/);
  assert.match(csv, /每档完成一轮后,数值/);
  assert.match(csv, /累计留存份额/);
  assert.match(csv, /序号,档位,买入价格,卖出价格,买入数量,买入金额,卖出数量,卖出回款,留存数量,留存市值,现金盈亏,综合利润/);
  assert.match(csv, /1,1\.000,1\.000,1\.050,10000,10000\.00,9100,9555\.00,900,945\.00,-445\.00,500\.00/);
});
```

- [ ] **Step 2: 运行 CSV 测试，确认缺少留利润内容**

Run:

```powershell
node --test --test-name-pattern="exports retention" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL，CSV 中没有“留利润策略”。

- [ ] **Step 3: 按策略分支生成 CSV 行**

在 `buildGridCsv` 开头增加：

```js
const retentionMultiple = Number(input.profitRetentionMultiple ?? 0);
const retentionLabel = retentionMultiple === 0
  ? "关闭（网格 1.0）"
  : `留 ${retentionMultiple} 份利润`;
const retentionEnabled = retentionMultiple > 0;
```

在输入参数段的单边费率后增加：

```js
["留利润策略", retentionLabel],
```

把压力测试后的固定明细行拆成以下分支并追加到 `rows`：

```js
if (retentionEnabled) {
  rows.push(
    [],
    ["每档完成一轮后", "数值"],
    ["累计卖出回款", result.completion.totalSellProceeds.toFixed(2)],
    ["累计留存份额", result.completion.totalRetainedQuantity],
    ["累计留存市值", result.completion.totalRetainedMarketValue.toFixed(2)],
    ["累计现金盈亏", result.completion.totalCashPnl.toFixed(2)],
    ["累计综合利润", result.completion.totalCombinedProfit.toFixed(2)],
    [],
    ["序号", "档位", "买入价格", "卖出价格", "买入数量", "买入金额", "卖出数量", "卖出回款", "留存数量", "留存市值", "现金盈亏", "综合利润"],
    ...result.levels.map((row) => [
      row.index,
      row.buyPrice.toFixed(3),
      row.buyPrice.toFixed(3),
      row.sellPrice.toFixed(3),
      row.quantity,
      row.actualBuyAmount.toFixed(2),
      row.sellQuantity,
      row.sellAmount.toFixed(2),
      row.retainedQuantity,
      row.retainedMarketValue.toFixed(2),
      row.cashPnl.toFixed(2),
      row.combinedProfit.toFixed(2),
    ]),
  );
} else {
  rows.push(
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
  );
}
```

保留现有输入参数和压力测试段，删除原来直接写在数组末尾的固定逐档明细行。

- [ ] **Step 4: 运行留利润 CSV 和原有 CSV 测试**

Run:

```powershell
node --test --test-name-pattern="CSV|exports retention" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 留利润 CSV、1.0 CSV、转义和文件名测试全部 PASS。

- [ ] **Step 5: 提交 CSV 功能**

```powershell
git add -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: export retained profit grid plans"
```

### Task 4: 完整回归与浏览器验收

**Files:**
- Verify: `grid-strategy-generator/index.html`
- Verify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: 运行全部自动测试**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 21 项测试全部 PASS，0 FAIL。

- [ ] **Step 2: 检查提交补丁格式和任务文件**

Run:

```powershell
git diff --check HEAD~3..HEAD
git status --short
```

Expected: 补丁检查无输出；任务提交只包含 `index.html` 与测试文件。用户原有仪表盘数据文件和未跟踪目录保持原状。

- [ ] **Step 3: 浏览器验证默认 1.0**

1. 打开本地网格生成器。
2. 保持“关闭（网格 1.0）”。
3. 输入起始价 1、步长 5%、最大跌幅 5%、固定每格金额 10,000、费率 0。
4. 生成计划。

Expected: 不显示“每档完成一轮后”；表格继续显示原 1.0 的 10 列；第一档税费后利润为 500。

- [ ] **Step 4: 浏览器验证留 2 份利润**

1. 把“留利润策略”切换为“留 2 份利润”。
2. 重新生成。

Expected:

- 显示“每档完成一轮后”汇总。
- 表格切换为 11 列留利润明细。
- 第一档买入 10,000 份、卖出 9,100 份、留存 900 份。
- 第一档卖出回款 9,555 元、留存市值 945 元、现金盈亏 -445 元、综合利润 500 元。

- [ ] **Step 5: 浏览器验证 CSV 入口仍可用**

1. 填写标的名称。
2. 点击“导出完整方案 CSV”。

Expected: 未出现页面错误；导出按钮仍使用最近一次生成的留 2 份方案。由于内置浏览器可能限制 Blob 文件自动落盘，以自动测试确认 CSV 实际内容和文件名逻辑。
