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
    records: [
      good,
      { ...good, symbol: "" },
      { ...good, symbol: "bad-price", input: { ...good.input, startPrice: "garbage" } },
      { ...good, symbol: "bad-step", input: { ...good.input, stepPct: "999" } },
      { ...good, symbol: "bad-amount", input: { ...good.input, amount: "-1" } },
      { ...good, symbol: "bad-fee", input: { ...good.input, feePct: "not-a-number" } },
    ],
  })))), {
    records: [good], skippedCount: 5,
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

test("rejects a positive raw price that rounds to a zero-priced order", () => {
  const { calculateGrid } = loadCalculator();
  assert.throws(
    () => calculateGrid({
      startPrice: 0.002,
      stepPct: 40,
      maxDropPct: 50,
      fundingMode: "perGrid",
      amount: 1_000,
      feePct: 0,
    }),
    /取整后必须大于 0/,
  );
});

test("rejects plans that exceed the safe grid-count limit", () => {
  const { calculateGrid } = loadCalculator();
  assert.throws(
    () => calculateGrid({
      startPrice: 1_000,
      stepPct: 0.1,
      maxDropPct: 50.1,
      fundingMode: "perGrid",
      amount: 1_000_000,
      feePct: 0,
    }),
    /不能超过 500 档/,
  );
});

test("reports securities principal separately from fee-inclusive cash", () => {
  const { calculateGrid } = loadCalculator();
  const result = calculateGrid({
    startPrice: 1,
    stepPct: 5,
    maxDropPct: 30,
    fundingMode: "perGrid",
    amount: 10_000,
    feePct: 0.03,
  });

  assert.equal(result.pressure.plannedSecurityPrincipal, 70_000);
  assert.ok(result.pressure.plannedCash > result.pressure.plannedSecurityPrincipal);
  assert.match(fs.readFileSync(htmlPath, "utf8"), /证券本金预算/);
});

test("labels the bottom-price scenario as total holding market value", () => {
  assert.match(fs.readFileSync(htmlPath, "utf8"), /最低档情景-持仓总市值/);
});

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

test("contains an offline CSV export action and latest-plan snapshot", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /id=["']export-csv-button["']/);
  assert.match(html, /let latestPlan = null/);
  assert.match(html, /new Blob\(\[csv\], \{ type: "text\/csv;charset=utf-8" \}\)/);
  assert.match(html, /URL\.revokeObjectURL/);
  assert.doesNotMatch(html, /\bfetch\s*\(/);
});

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

test("shows both return-rate columns in retained-profit grid plans", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /"现金收益率", "综合收益率"/);
  assert.match(html, /row\.cashReturnPct\.toFixed\(2\)/);
  assert.match(html, /row\.combinedReturnPct\.toFixed\(2\)/);
});

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
  assert.match(
    csv,
    /序号,档位,买入价格,卖出价格,买入数量,买入金额,卖出数量,卖出回款,留存数量,留存市值,现金盈亏,综合利润,现金收益率,综合收益率/,
  );
  assert.match(
    csv,
    /1,1\.000,1\.000,1\.050,10000,10000\.00,9100,9555\.00,900,945\.00,-445\.00,500\.00,-4\.45%,5\.00%/,
  );
});

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
  assert.match(html, /\.strategy-item\.is-active \.strategy-load strong\s*{[^}]*font-weight:\s*800/);
});

test("places generate and save actions in the compact page header", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  const header = html.match(/<header class="top-toolbar">([\s\S]*?)<\/header>/)?.[1] ?? "";
  const form = html.match(/<form id="grid-form"[^>]*>([\s\S]*?)<\/form>/)?.[1] ?? "";

  assert.match(header, /<h1>网格策略 1\.0 生成器<\/h1>/);
  assert.match(header, /type="submit" form="grid-form"/);
  assert.match(header, /id="save-strategy-button"/);
  assert.doesNotMatch(form, /class="form-actions"/);
  assert.match(html, /<section id="results"[\s\S]*id="export-csv-button"/);
});

test("defines compact desktop and responsive parameter-pressure layouts", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /class="panel parameter-panel"/);
  assert.match(html, /class="panel pressure-panel"/);
  assert.match(html, /id="pressure-summary" class="metric-grid pressure-grid"/);
  assert.match(html, /\.form-grid\s*{[^}]*grid-template-columns:\s*repeat\(4,/);
  assert.match(html, /\.pressure-grid\s*{[^}]*grid-template-columns:\s*repeat\(6,/);
  assert.match(html, /@media \(max-width: 1100px\)[\s\S]*?\.form-grid[^}]*repeat\(2,/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*?\.form-grid, \.metric-grid[^}]*1fr/);
});

test("keeps form controls before saved-strategy actions in keyboard order", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.ok(html.indexOf('id="tool-column"') < html.indexOf('class="panel strategy-sidebar"'));
  assert.match(html, /\.app-layout\s*{[^}]*grid-template-areas:\s*"sidebar tool"/);
  assert.match(html, /@media \(max-width: 900px\)[\s\S]*?grid-template-areas:\s*"tool"\s*"sidebar"/);
});

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
