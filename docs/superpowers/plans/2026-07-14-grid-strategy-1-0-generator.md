# Grid Strategy 1.0 Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline local webpage that turns manually entered Grid Strategy 1.0 parameters into an executable price table and worst-case capital stress test.

**Architecture:** Keep the user-facing tool in one `index.html` with an inline pure calculation module and a small DOM adapter. A dependency-free Node test loads only the marked calculation module from the HTML, so formulas can be tested without duplicating production logic or adding a build system.

**Tech Stack:** HTML5, CSS, browser JavaScript, Node.js built-in `node:test`, `assert`, `fs`, and `vm` modules.

---

## File Structure

- Create `grid-strategy-generator/index.html`: complete offline page, pure calculator, validation, rendering, and responsive styles.
- Create `grid-strategy-generator/tests/grid-calculator.test.mjs`: extracts the marked calculator block from `index.html` and verifies article formulas, funding modes, fees, validation, pressure output, and required UI structure.

### Task 1: Establish the article price-grid kernel

**Files:**
- Create: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Create: `grid-strategy-generator/index.html`

- [ ] **Step 1: Write the failing article-example test**

Create the test loader and first test:

```js
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.resolve(here, "..", "index.html");

function loadCalculator() {
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(
    /\/\* GRID_CALCULATOR_START \*\/([\s\S]*?)\/\* GRID_CALCULATOR_END \*\//,
  );
  assert.ok(match, "calculator block must be present");
  const context = { window: {} };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context.window.GridCalculator;
}

test("reproduces the article's arithmetic price grid", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 30,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  });

  assert.deepEqual(
    Array.from(result.levels, (row) => row.buyPrice),
    [1, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7],
  );
  assert.deepEqual(
    Array.from(result.levels, (row) => row.sellPrice),
    [1.05, 1, 0.95, 0.9, 0.85, 0.8, 0.75],
  );
});
```

- [ ] **Step 2: Run the test and verify the expected failure**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL with `ENOENT` for `grid-strategy-generator/index.html`.

- [ ] **Step 3: Add the minimal offline page and pure price-grid function**

Create `index.html` with the marked production block. Percent inputs are human-readable values such as `5`, not decimals such as `0.05`.

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>网格策略 1.0 计划生成器</title>
</head>
<body>
  <main><h1>网格策略 1.0 计划生成器</h1></main>
  <script>
  /* GRID_CALCULATOR_START */
  (() => {
    const roundPrice = (value) => Math.round((value + Number.EPSILON) * 1000) / 1000;

    function calculateGrid(input) {
      const stepRate = input.stepPct / 100;
      const downwardSteps = Math.ceil(input.maxDropPct / input.stepPct - 1e-12);
      const rawStep = input.startPrice * stepRate;
      const levels = [];

      for (let index = 0; index <= downwardSteps; index += 1) {
        const buyPrice = roundPrice(input.startPrice - index * rawStep);
        const sellPrice = index === 0
          ? roundPrice(input.startPrice + rawStep)
          : levels[index - 1].buyPrice;
        levels.push({ index: index + 1, buyPrice, sellPrice });
      }

      return { levels };
    }

    window.GridCalculator = { calculateGrid, roundPrice };
  })();
  /* GRID_CALCULATOR_END */
  </script>
</body>
</html>
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 1 test passes, 0 fail.

- [ ] **Step 5: Commit the kernel**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: add grid 1.0 price calculator"
```

### Task 2: Add funding, fees, pressure calculations, and validation

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Add failing funding and pressure tests**

Append these tests:

```js
test("rounds each order down to a 100-share lot", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 10,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  });

  assert.deepEqual(
    Array.from(result.levels, (row) => row.quantity),
    [10_000, 10_500, 11_100],
  );
  assert.equal(result.levels[1].actualBuyAmount, 9_975);
});

test("keeps total-funds cash usage inside the entered cap including buy fees", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1.2,
    stepPct: 5,
    maxDropPct: 20,
    fundingMode: "total",
    amount: 50_000,
    feePct: 0.03,
  });

  assert.ok(result.pressure.maxCashUsed <= 50_000);
  assert.equal(result.pressure.plannedCash, 50_000);
  assert.ok(result.pressure.unusedCash >= 0);
});

test("subtracts fees on both sides from grid profit", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 5,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0.1,
  });
  const row = result.levels[0];

  assert.equal(row.grossProfit, 500);
  assert.equal(row.netProfit, 479.5);
  assert.equal(row.netReturnPct, 4.8);
});

test("reports the all-levels-triggered stress state", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 10,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  });

  assert.equal(result.pressure.totalQuantity, 31_600);
  assert.equal(result.pressure.lowestPrice, 0.9);
  assert.equal(result.pressure.marketValueAtBottom, 28_440);
  assert.ok(result.pressure.unrealizedPnl < 0);
  assert.ok(result.pressure.averageCost > result.pressure.lowestPrice);
});
```

- [ ] **Step 2: Add failing validation tests**

Append:

```js
test("covers a non-multiple maximum drop with one extra step", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 43,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  });
  assert.equal(result.meta.coveragePct, 45);
  assert.equal(result.levels.at(-1).buyPrice, 0.55);
});

test("rejects invalid values, unaffordable lots, and duplicate rounded prices", () => {
  const { calculateGrid } = loadCalculator();
  const base = {
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 30,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0,
  };

  assert.throws(() => calculateGrid({ ...base, startPrice: 0 }), /起始价必须大于 0/);
  assert.throws(() => calculateGrid({ ...base, feePct: -1 }), /费率不能为负数/);
  assert.throws(() => calculateGrid({ ...base, amount: 50 }), /至少买入 100 份/);
  assert.throws(
    () => calculateGrid({ ...base, startPrice: 0.01, stepPct: 1 }),
    /三位小数报价下过小/,
  );
  assert.throws(
    () => calculateGrid({ ...base, stepPct: 40, maxDropPct: 90 }),
    /最低档价格必须大于 0/,
  );
});
```

- [ ] **Step 3: Run the expanded tests and verify they fail**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: the original article test passes; new tests fail because quantities, fees, pressure output, metadata, and validation are absent.

- [ ] **Step 4: Implement the complete pure calculator**

Replace `calculateGrid` with logic equivalent to the following, keeping `roundPrice` and the same public signature:

```js
const roundMoney = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
const roundPct = (value) => Math.round((value + Number.EPSILON) * 100) / 100;

function positiveNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${label}必须大于 0`);
  return number;
}

function calculateGrid(input) {
  const startPrice = positiveNumber(input.startPrice, "起始价");
  const stepPct = positiveNumber(input.stepPct, "步长比例");
  const maxDropPct = positiveNumber(input.maxDropPct, "最大跌幅");
  const amount = positiveNumber(input.amount, input.fundingMode === "total" ? "总资金" : "每格金额");
  const feePct = Number(input.feePct);
  if (!Number.isFinite(feePct) || feePct < 0) throw new Error("费率不能为负数");
  if (stepPct >= 100 || maxDropPct >= 100) throw new Error("步长比例和最大跌幅必须小于 100%");
  if (!["perGrid", "total"].includes(input.fundingMode)) throw new Error("请选择有效的资金模式");

  const downwardSteps = Math.ceil(maxDropPct / stepPct - 1e-12);
  const rawStep = startPrice * stepPct / 100;
  if (startPrice - downwardSteps * rawStep <= 0) throw new Error("最低档价格必须大于 0");

  const prices = Array.from(
    { length: downwardSteps + 1 },
    (_, index) => roundPrice(startPrice - index * rawStep),
  );
  if (prices.some((price, index) => index > 0 && price >= prices[index - 1])) {
    throw new Error("价格步长在三位小数报价下过小");
  }

  const feeRate = feePct / 100;
  const levelCount = prices.length;
  const cashPerLevel = input.fundingMode === "total" ? amount / levelCount : amount * (1 + feeRate);
  const securityBudget = input.fundingMode === "total" ? cashPerLevel / (1 + feeRate) : amount;

  const levels = prices.map((buyPrice, index) => {
    const sellPrice = index === 0 ? roundPrice(startPrice + rawStep) : prices[index - 1];
    const quantity = Math.floor(securityBudget / buyPrice / 100) * 100;
    if (quantity < 100) throw new Error("每格资金不足以至少买入 100 份");
    const actualBuyAmount = roundMoney(quantity * buyPrice);
    const sellAmount = roundMoney(quantity * sellPrice);
    const buyFee = roundMoney(actualBuyAmount * feeRate);
    const sellFee = roundMoney(sellAmount * feeRate);
    const grossProfit = roundMoney(sellAmount - actualBuyAmount);
    const netProfit = roundMoney(grossProfit - buyFee - sellFee);
    return {
      index: index + 1,
      buyPrice,
      sellPrice,
      plannedBudget: roundMoney(securityBudget),
      quantity,
      actualBuyAmount,
      sellAmount,
      buyFee,
      sellFee,
      grossProfit,
      netProfit,
      netReturnPct: roundPct(netProfit / actualBuyAmount * 100),
    };
  });

  const totalQuantity = levels.reduce((sum, row) => sum + row.quantity, 0);
  const maxCashUsed = roundMoney(levels.reduce((sum, row) => sum + row.actualBuyAmount + row.buyFee, 0));
  const plannedCash = roundMoney(input.fundingMode === "total" ? amount : cashPerLevel * levelCount);
  const lowestPrice = levels.at(-1).buyPrice;
  const marketValueAtBottom = roundMoney(totalQuantity * lowestPrice);
  const unrealizedPnl = roundMoney(marketValueAtBottom - maxCashUsed);

  return {
    meta: {
      rawStep: roundPrice(rawStep),
      coveragePct: roundPct(downwardSteps * stepPct),
      levelCount,
      fundingMode: input.fundingMode,
    },
    levels,
    pressure: {
      plannedCash,
      maxCashUsed,
      unusedCash: roundMoney(plannedCash - maxCashUsed),
      totalQuantity,
      averageCost: roundPrice(maxCashUsed / totalQuantity),
      lowestPrice,
      marketValueAtBottom,
      unrealizedPnl,
      unrealizedPnlPct: roundPct(unrealizedPnl / maxCashUsed * 100),
    },
  };
}
```

Export `roundMoney` and `roundPct` with `calculateGrid` for direct test diagnostics.

- [ ] **Step 5: Run all calculator tests and verify they pass**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 7 tests pass, 0 fail.

- [ ] **Step 6: Commit the complete calculator**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: calculate grid funding and stress test"
```

### Task 3: Build the responsive local-page interaction

**Files:**
- Modify: `grid-strategy-generator/index.html`
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Add a failing HTML contract test**

Append a string-level smoke test that requires the agreed controls and results without adding a DOM dependency:

```js
test("contains the agreed offline form and result regions", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  for (const id of [
    "grid-form",
    "symbol-name",
    "start-price",
    "step-pct",
    "max-drop-pct",
    "funding-mode",
    "funding-amount",
    "fee-pct",
    "error-message",
    "pressure-summary",
    "grid-table-body",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.doesNotMatch(html, /\bfetch\s*\(/);
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: the new HTML contract test fails on missing `grid-form`.

- [ ] **Step 3: Add the complete linear-layout markup**

Replace the minimal `<main>` with semantic sections using these exact IDs and fields:

```html
<main class="page-shell">
  <header class="hero">
    <p class="eyebrow">固定步长 · 网格策略 1.0</p>
    <h1>网格策略 1.0 计划生成器</h1>
    <p>手工设定参数，先查看资金压力，再查看每一档买卖计划。</p>
  </header>

  <section class="panel" aria-labelledby="parameter-title">
    <h2 id="parameter-title">1. 设置参数</h2>
    <form id="grid-form" novalidate>
      <div class="form-grid">
        <label>标的名称<input id="symbol-name" type="text" placeholder="例如：中证500 ETF"></label>
        <label>起始价（元）<input id="start-price" type="number" min="0" step="0.001" required></label>
        <label>步长比例（%）<input id="step-pct" type="number" min="0" max="100" step="0.01" value="5" required></label>
        <label>最大跌幅（%）<input id="max-drop-pct" type="number" min="0" max="100" step="0.01" required></label>
        <label>资金模式
          <select id="funding-mode">
            <option value="total" selected>限定总资金</option>
            <option value="perGrid">固定每格金额</option>
          </select>
        </label>
        <label><span id="funding-label">总资金（元）</span><input id="funding-amount" type="number" min="0" step="0.01" required></label>
        <label>单边费率（%）<input id="fee-pct" type="number" min="0" step="0.001" value="0"></label>
      </div>
      <div class="step-presets" aria-label="步长快捷值">
        <button type="button" data-step="5">普通 5%</button>
        <button type="button" data-step="10">高波动 10%</button>
      </div>
      <p id="error-message" class="error" role="alert" hidden></p>
      <button class="primary-button" type="submit">生成网格计划</button>
    </form>
  </section>

  <section id="results" hidden>
    <section class="panel" aria-labelledby="pressure-title">
      <h2 id="pressure-title">2. 压力测试</h2>
      <div id="pressure-summary" class="metric-grid"></div>
    </section>
    <section class="panel table-panel" aria-labelledby="table-title">
      <h2 id="table-title">3. 网格计划</h2>
      <div class="table-scroll"><table><thead></thead><tbody id="grid-table-body"></tbody></table></div>
      <p class="note">若价格跳空跨越多档，应逐档执行；每一档仍按自己的卖出价退出。</p>
    </section>
  </section>
</main>
```

The table header must name all fields from the design: 档位、买入价、卖出价、计划预算、数量、实际买入金额、卖出金额、税费前利润、税费后利润、净收益率.

- [ ] **Step 4: Add local DOM binding and rendering**

After the calculator block, add a separate browser-only script. It must read the current form only on submit, clear stale errors, call `calculateGrid`, and render with text content rather than HTML interpolation for user-entered values.

```js
const byId = (id) => document.getElementById(id);
const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

function metric(label, value, tone = "") {
  const item = document.createElement("div");
  item.className = `metric ${tone}`.trim();
  const name = document.createElement("span");
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value;
  item.append(name, number);
  return item;
}

function renderResult(result) {
  const summary = byId("pressure-summary");
  summary.replaceChildren(
    metric("实际价格步长", result.meta.rawStep.toFixed(3)),
    metric("覆盖跌幅", `${result.meta.coveragePct.toFixed(2)}%`),
    metric("网格档数", `${result.meta.levelCount} 档`),
    metric("计划现金", `¥${money.format(result.pressure.plannedCash)}`),
    metric("最大实际投入", `¥${money.format(result.pressure.maxCashUsed)}`),
    metric("未使用现金", `¥${money.format(result.pressure.unusedCash)}`),
    metric("平均成本", result.pressure.averageCost.toFixed(3)),
    metric("最低档浮亏", `¥${money.format(result.pressure.unrealizedPnl)} (${result.pressure.unrealizedPnlPct.toFixed(2)}%)`, "loss"),
  );

  const body = byId("grid-table-body");
  body.replaceChildren(...result.levels.map((row) => {
    const tr = document.createElement("tr");
    const values = [
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
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    return tr;
  }));
  byId("results").hidden = false;
}

byId("funding-mode").addEventListener("change", (event) => {
  byId("funding-label").textContent = event.target.value === "total" ? "总资金（元）" : "每格金额（元）";
});

for (const button of document.querySelectorAll("[data-step]")) {
  button.addEventListener("click", () => { byId("step-pct").value = button.dataset.step; });
}

byId("grid-form").addEventListener("submit", (event) => {
  event.preventDefault();
  byId("error-message").hidden = true;
  try {
    renderResult(window.GridCalculator.calculateGrid({
      startPrice: byId("start-price").value,
      stepPct: byId("step-pct").value,
      maxDropPct: byId("max-drop-pct").value,
      fundingMode: byId("funding-mode").value,
      amount: byId("funding-amount").value,
      feePct: byId("fee-pct").value || 0,
    }));
  } catch (error) {
    byId("results").hidden = true;
    byId("error-message").textContent = error.message;
    byId("error-message").hidden = false;
  }
});
```

- [ ] **Step 5: Add focused responsive styling**

Use CSS custom properties for a neutral finance-tool palette, a maximum content width near 1180px, two-column `.form-grid` above 720px, one column below it, visible focus states, red `.loss` values, and `.table-scroll { overflow-x: auto; }`. Do not add charts, animation, dark mode, persistence, or export controls.

```css
:root { color-scheme: light; --ink:#18212b; --muted:#657180; --line:#dce3ea; --panel:#fff; --accent:#176b5b; --loss:#b83b3b; --bg:#f4f7f8; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif; }
.page-shell { width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:48px 0 72px; }
.panel { margin-top:24px; padding:24px; border:1px solid var(--line); border-radius:16px; background:var(--panel); box-shadow:0 10px 30px rgba(24,33,43,.06); }
.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
label { display:grid; gap:8px; font-weight:650; }
input,select,button { font:inherit; }
input,select { width:100%; padding:11px 12px; border:1px solid #bcc8d2; border-radius:9px; background:#fff; }
input:focus,select:focus,button:focus-visible { outline:3px solid rgba(23,107,91,.22); outline-offset:2px; }
.primary-button { margin-top:20px; padding:12px 18px; border:0; border-radius:9px; color:#fff; background:var(--accent); font-weight:700; cursor:pointer; }
.metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.metric { padding:14px; border:1px solid var(--line); border-radius:12px; }
.metric span,.metric strong { display:block; }
.metric.loss strong,.error { color:var(--loss); }
.table-scroll { overflow-x:auto; }
table { width:100%; min-width:1040px; border-collapse:collapse; }
th,td { padding:12px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child,td:first-child { text-align:left; }
@media (max-width:720px) { .form-grid,.metric-grid { grid-template-columns:1fr; } .page-shell { width:min(100% - 20px,1180px); padding-top:24px; } .panel { padding:18px; } }
```

- [ ] **Step 6: Run tests and verify the complete page contract**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 8 tests pass, 0 fail.

- [ ] **Step 7: Commit the local webpage**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: build grid strategy generator page"
```

### Task 4: Verify the delivered tool end to end

**Files:**
- Modify only if verification finds a defect: `grid-strategy-generator/index.html`
- Modify only if a regression test is needed: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Run the repository baseline tests**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'TradeRuleSentinel').Path
python -m unittest discover -s TradeRuleSentinel/tests -v
```

Expected: 3 tests pass, 0 fail.

- [ ] **Step 2: Run the complete feature suite**

Run:

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: 8 tests pass, 0 fail.

- [ ] **Step 3: Serve the page locally and inspect it in a browser**

Run a local static server from the worktree:

```powershell
python -m http.server 8765 --directory grid-strategy-generator
```

Open `http://localhost:8765/` and verify the desktop layout, then narrow the viewport below 720px and verify the form and metric cards become one column while the table scrolls horizontally.

- [ ] **Step 4: Verify the article example in the browser**

Enter: start price `1`, step `5`, maximum drop `30`, funding mode `固定每格金额`, amount `10000`, fee `0`.

Expected:

- 7 levels;
- first buy/sell `1.000 / 1.050`;
- last buy/sell `0.700 / 0.750`;
- first quantity `10,000` and second quantity `10,500` because of the confirmed 100-share lot rule;
- pressure summary appears before the table;
- browser console has no errors.

- [ ] **Step 5: Verify total funds, fees, and an invalid input**

Enter start price `1.2`, step `5`, maximum drop `20`, total funds `50000`, fee `0.03`.

Expected: maximum actual investment does not exceed ¥50,000 and net profit is lower than gross profit. Then change the amount to `50`; expected: results hide and the page reports that each level must buy at least 100 shares.

- [ ] **Step 6: Re-run verification after any correction**

If any browser check fails, first add or adjust the smallest reproducing test, confirm it fails, patch the production HTML, rerun both feature and repository suites, then repeat Steps 3–5. Do not deliver an older browser render after a code fix.

- [ ] **Step 7: Confirm the branch is clean**

Run:

```powershell
git status --short
git log --oneline -4
```

Expected: no uncommitted files; the log contains the calculator and page commits after the plan commit.
