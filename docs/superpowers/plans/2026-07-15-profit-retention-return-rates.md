# Profit Retention Return Rates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show cash return rate and combined return rate in retained-profit grid plans and CSV exports.

**Architecture:** Extend each calculated grid row with two explicitly named percentage fields, then consume those fields in the retained-profit HTML table and CSV exporter. Preserve the existing `netReturnPct` behavior for non-retained plans and avoid changing retention quantities, pressure metrics, or completion summaries.

**Tech Stack:** Offline HTML, vanilla JavaScript, Node.js built-in test runner, `node:assert`.

---

## File Map

- Modify: `grid-strategy-generator/index.html` — calculate both return rates and render/export them.
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs` — add calculation, table, and CSV regressions.

### Task 1: Calculate Explicit Retained-Profit Return Rates

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html:515-542`

- [ ] **Step 1: Write the failing calculator test**

Add this test after `keeps retention quantities independent from fees`:

```js
test("calculates cash and combined return rates for retained-profit rows", () => {
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

  assert.equal(row.cashReturnPct, 0.6);
  assert.equal(row.combinedReturnPct, 4.8);
  assert.equal(row.netReturnPct, row.combinedReturnPct);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node --test --test-name-pattern "calculates cash and combined return rates" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because `cashReturnPct` and `combinedReturnPct` are undefined.

- [ ] **Step 3: Implement the minimum calculation change**

In `calculateGrid`, calculate the two fields after `combinedProfit`:

```js
const cashReturnPct = roundPct(cashPnl / actualBuyAmount * 100);
const combinedReturnPct = roundPct(combinedProfit / actualBuyAmount * 100);
const netProfit = profitRetentionMultiple === 0 ? cashPnl : combinedProfit;
```

Return them on each row and keep the current net-return contract:

```js
cashPnl,
combinedProfit,
cashReturnPct,
combinedReturnPct,
netReturnPct: profitRetentionMultiple === 0 ? cashReturnPct : combinedReturnPct,
```

- [ ] **Step 4: Run the focused and full tests**

Run:

```powershell
node --test --test-name-pattern "calculates cash and combined return rates" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: focused test PASS; complete suite PASS.

- [ ] **Step 5: Commit the calculator behavior**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: calculate retained profit return rates"
```

### Task 2: Display Both Return Rates in the Grid Plan

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Modify: `grid-strategy-generator/index.html:1046-1097`

- [ ] **Step 1: Write the failing table regression test**

Add this source-level UI contract test after `contains profit-retention controls and completion summary`:

```js
test("shows both return-rate columns in retained-profit grid plans", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /"现金收益率", "综合收益率"/);
  assert.match(html, /row\.cashReturnPct\.toFixed\(2\)/);
  assert.match(html, /row\.combinedReturnPct\.toFixed\(2\)/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node --test --test-name-pattern "shows both return-rate columns" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because the retained-profit table has no return-rate headers or cells.

- [ ] **Step 3: Add headers, values, and sign coloring**

Append the retained-profit headers:

```js
"现金盈亏", "综合利润", "现金收益率", "综合收益率"
```

Append the retained-profit row values:

```js
`${row.cashReturnPct.toFixed(2)}%`,
`${row.combinedReturnPct.toFixed(2)}%`,
```

Treat indexes 9 and 11 as cash results and indexes 10 and 12 as combined results:

```js
const profitIndexes = retentionEnabled ? [9, 10, 11, 12] : [8, 9];
// ...
const profit = retentionEnabled
  ? ([9, 11].includes(index) ? row.cashPnl : row.combinedProfit)
  : row.netProfit;
```

- [ ] **Step 4: Run the focused and full tests**

Run:

```powershell
node --test --test-name-pattern "shows both return-rate columns" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: focused test PASS; complete suite PASS.

- [ ] **Step 5: Commit the table change**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: show retained profit return rates"
```

### Task 3: Export Both Return Rates to CSV

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs:506-525`
- Modify: `grid-strategy-generator/index.html:672-700`

- [ ] **Step 1: Strengthen the CSV test and verify RED**

Update `exports retention settings, completion summary, and retained rows` with these expectations:

```js
assert.match(
  csv,
  /序号,档位,买入价格,卖出价格,买入数量,买入金额,卖出数量,卖出回款,留存数量,留存市值,现金盈亏,综合利润,现金收益率,综合收益率/,
);
assert.match(
  csv,
  /1,1\.000,1\.000,1\.050,10000,10000\.00,9100,9555\.00,900,945\.00,-445\.00,500\.00,-4\.45%,5\.00%/,
);
```

Run:

```powershell
node --test --test-name-pattern "exports retention settings" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because the two CSV columns are absent.

- [ ] **Step 2: Add both CSV columns**

Append `"现金收益率", "综合收益率"` to the retained-profit CSV header, then append:

```js
`${row.cashReturnPct.toFixed(2)}%`,
`${row.combinedReturnPct.toFixed(2)}%`,
```

to each retained-profit CSV row.

- [ ] **Step 3: Run the focused and full tests**

Run:

```powershell
node --test --test-name-pattern "exports retention settings" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check
```

Expected: focused test PASS; complete suite PASS; diff check produces no output.

- [ ] **Step 4: Commit the export change**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "fix: export retained profit return rates"
```

### Task 4: Browser Acceptance and Final Verification

**Files:**
- Verify: `grid-strategy-generator/index.html`
- Verify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Run the complete automated verification**

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check master...HEAD
git status --short --branch
```

Expected: 32 tests pass, no diff-check output, and only committed feature changes are present.

- [ ] **Step 2: Verify the local webpage**

Open the local generator, select `留 1 份利润`, generate a plan, and confirm:

- The retained-profit grid contains both `现金收益率` and `综合收益率`.
- A row with fees can display a lower cash return than combined return.
- Positive and negative values use the existing green/red styling.
- The wide table remains available through its own horizontal scrolling area without causing page-level horizontal overflow.

- [ ] **Step 3: Review the final diff**

```powershell
git diff --stat master...HEAD
git diff master...HEAD -- grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: every changed line traces to the two return-rate fields, their rendering/export, or regression tests.
