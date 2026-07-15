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

function loadValuation(overrides = {}) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(
    /\/\* GRID_VALUATION_START \*\/([\s\S]*?)\/\* GRID_VALUATION_END \*\//,
  );
  assert.ok(match, "valuation block must be present");
  const context = {
    window: {},
    AbortController: globalThis.AbortController,
    setTimeout,
    clearTimeout,
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context.window.GridValuation;
}

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

const savedInput = {
  startPrice: "8.3", stepPct: "5", maxDropPct: "40", fundingMode: "perGrid",
  amount: "10000", feePct: "0.1", profitRetentionMultiple: 2,
};

const valuationSnapshot = {
  version: 1,
  code: "510500",
  name: "中证500ETF南方",
  instrumentType: "etf",
  trackedIndex: { code: "000905", name: "中证500" },
  source: "youzhiyouxing",
  asOf: "2026-07-14",
  queriedAt: "2026-07-15T10:00:00+08:00",
  cached: false,
  thermometer: {
    temperature: 76, valuationBand: "偏高", intrinsicReturnPct: 4.42,
    dividendYieldPct: 1.53, url: "https://youzhiyouxing.cn/data/indices/000905.SH",
  },
  percentiles: null,
  warnings: [],
};

test("creates version two strategy records with an immutable valuation snapshot", () => {
  const { createRecord } = loadStrategyStore();
  const record = createRecord(
    { code: " 510500 ", name: " 中证500ETF南方 " },
    savedInput,
    valuationSnapshot,
    new Date("2026-07-14T10:20:30.000Z"),
  );

  assert.deepEqual(JSON.parse(JSON.stringify(record)), {
    version: 2,
    code: "510500",
    name: "中证500ETF南方",
    symbol: "中证500ETF南方",
    savedAt: "2026-07-14T10:20:30.000Z",
    input: savedInput,
    valuationSnapshot: { ...valuationSnapshot, isSnapshot: true },
  });
});

test("upserts saved strategies by code and sorts newest first", () => {
  const { createRecord, upsertRecord } = loadStrategyStore();
  const older = createRecord({ code: "510500", name: "旧名称" }, savedInput, null,
    new Date("2026-07-14T09:00:00.000Z"));
  const newer = createRecord({ code: "000300", name: "沪深300" }, savedInput, null,
    new Date("2026-07-14T10:00:00.000Z"));
  const replacement = createRecord({ code: "510500", name: "中证500ETF南方" },
    { ...savedInput, startPrice: "8.8" }, null,
    new Date("2026-07-14T11:00:00.000Z"));

  const records = upsertRecord(upsertRecord([older], newer), replacement);
  assert.deepEqual(Array.from(records, (record) => record.code), ["510500", "000300"]);
  assert.equal(records[0].name, "中证500ETF南方");
  assert.equal(records[0].input.startPrice, "8.8");
});

test("migrates version one records while skipping damaged data", () => {
  const { parseStore } = loadStrategyStore();
  const legacy = {
    version: 1,
    symbol: "港芯",
    savedAt: "2026-07-14T10:00:00.000Z",
    input: { ...savedInput, feePct: "0", profitRetentionMultiple: 0 },
  };

  assert.deepEqual(JSON.parse(JSON.stringify(parseStore("not json"))), {
    records: [], skippedCount: 1,
  });
  const parsed = JSON.parse(JSON.stringify(parseStore(JSON.stringify({
    version: 1,
    records: [
      legacy,
      { ...legacy, symbol: "" },
      { ...legacy, symbol: "bad-price", input: { ...legacy.input, startPrice: "garbage" } },
    ],
  }))));
  assert.equal(parsed.skippedCount, 2);
  assert.deepEqual(parsed.records[0], {
    version: 2,
    code: "",
    name: "港芯",
    symbol: "港芯",
    savedAt: legacy.savedAt,
    input: legacy.input,
    valuationSnapshot: null,
  });
});

test("removes one saved code and serializes a version two envelope", () => {
  const { createRecord, removeRecord, serializeStore } = loadStrategyStore();
  const record = createRecord({ code: "510500", name: "中证500ETF南方" }, savedInput, null,
    new Date("2026-07-14T10:00:00.000Z"));
  assert.deepEqual(Array.from(removeRecord([record], " 510500 ")), []);
  assert.equal(serializeStore([record]), JSON.stringify({ version: 2, records: [record] }));
});

test("loads and saves the version two strategy envelope through the API", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => url === "/api/strategies"
        ? { version: 2, records: [] }
        : { version: 2, records: [{ code: "510500" }] },
    };
  };
  const client = loadPersistence().createClient(fetchImpl);

  assert.deepEqual(
    JSON.parse(JSON.stringify(await client.load())),
    { version: 2, records: [] },
  );
  await client.save({ version: 2, records: [] });
  assert.equal(calls[1].options.method, "PUT");
  assert.equal(calls[1].options.headers["Content-Type"], "application/json");
});

test("surfaces public strategy API errors", async () => {
  const client = loadPersistence().createClient(async () => ({
    ok: false,
    json: async () => ({
      error: {
        code: "STRATEGY_STORE_WRITE_FAILED",
        message: "策略文件保存失败",
      },
    }),
  }));

  await assert.rejects(
    () => client.save({ version: 2, records: [] }),
    /策略文件保存失败/,
  );
});

test("builds an ordered same-browser migration chain from available ports", () => {
  const { buildMigrationUrl } = loadPersistence();

  const url = buildMigrationUrl(
    [
      { port: 52341, available: true },
      { port: 55018, available: true },
    ],
    "http://127.0.0.1:18765/",
  );

  assert.match(url, /^http:\/\/localhost:52341\/\?migrate=1/);
  assert.match(decodeURIComponent(url), /remaining=55018/);
  assert.match(
    decodeURIComponent(url),
    /return=http:\/\/127\.0\.0\.1:18765\//,
  );
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

test("contains the agreed local form and result regions", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  for (const id of [
    "grid-form",
    "instrument-code",
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
  assert.match(html, /fetchImpl\(`\/api\/valuation\?code=/);
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
    createExportFilename("510500", "  中证/500:ETF  ", new Date(2026, 6, 14, 9, 8, 7)),
    "510500-中证-500-ETF-网格策略-20260714-090807.csv",
  );
  assert.equal(
    createExportFilename("000905", "", new Date(2026, 6, 14, 9, 8, 7)),
    "000905-网格策略-20260714-090807.csv",
  );
});

test("exports a thermometer snapshot before pressure rows", () => {
  const { buildGridCsv } = loadExporter();
  const { calculateGrid } = loadCalculator();
  const input = {
    startPrice: 1, stepPct: 5, maxDropPct: 5, fundingMode: "perGrid",
    amount: 10_000, feePct: 0, profitRetentionMultiple: 0,
  };
  const csv = buildGridCsv(input, calculateGrid(input), {
    ...valuationSnapshot,
    isSnapshot: true,
  });

  assert.ok(csv.indexOf("估值辅助,数值") < csv.indexOf("压力测试,数值"));
  assert.match(csv, /标的代码,510500/);
  assert.match(csv, /标的名称,中证500ETF南方/);
  assert.match(csv, /指数温度,76\.00/);
  assert.match(csv, /估值区间,偏高/);
  assert.match(csv, /快照状态,历史快照，不是最新数据/);
});

test("exports PE and PB percentiles independently and handles no valuation", () => {
  const { buildGridCsv } = loadExporter();
  const { calculateGrid } = loadCalculator();
  const input = {
    startPrice: 1, stepPct: 5, maxDropPct: 5, fundingMode: "perGrid",
    amount: 10_000, feePct: 0, profitRetentionMultiple: 0,
  };
  const result = calculateGrid(input);
  const snapshot = {
    version: 1, code: "000300", name: "沪深300", instrumentType: "index",
    trackedIndex: { code: "000300", name: "沪深300" },
    source: "historical_percentile", asOf: "2026-07-14",
    queriedAt: "2026-07-15T10:00:00+08:00", cached: false,
    thermometer: null,
    percentiles: {
      pe: { currentValue: 12.3, percentilePct: 40, startDate: "2016-07-14", endDate: "2026-07-14", sampleCount: 2400 },
      pb: { currentValue: 1.4, percentilePct: 30, startDate: "2016-07-14", endDate: "2026-07-14", sampleCount: 2398 },
    },
    warnings: [], isSnapshot: false,
  };

  const csv = buildGridCsv(input, result, snapshot);
  const emptyCsv = buildGridCsv(input, result, null);

  assert.match(csv, /当前 PE,12\.30/);
  assert.match(csv, /PE 历史分位,40\.00%/);
  assert.match(csv, /PE 统计区间,2016-07-14 至 2026-07-14/);
  assert.match(csv, /当前 PB,1\.40/);
  assert.match(csv, /PB 历史分位,30\.00%/);
  assert.match(csv, /PB 样本数,2398/);
  assert.match(emptyCsv, /估值数据,暂无估值数据/);
});

test("renders and exports missing thermometer percentages as unavailable", () => {
  const { buildView } = loadValuation();
  const { buildValuationRows, serializeCsv } = loadExporter();
  const snapshot = {
    ...valuationSnapshot,
    thermometer: {
      ...valuationSnapshot.thermometer,
      intrinsicReturnPct: null,
      dividendYieldPct: null,
    },
  };

  const view = buildView(snapshot);
  const csv = serializeCsv(buildValuationRows(snapshot));

  assert.equal(view.metrics.find((item) => item.label === "内在收益率").value, "--");
  assert.equal(view.metrics.find((item) => item.label === "股息率").value, "--");
  assert.match(csv, /内在收益率,--/);
  assert.match(csv, /股息率,--/);
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

test("places a compact non-advisory valuation panel before parameters", () => {
  const html = fs.readFileSync(htmlPath, "utf8");
  const valuation = html.indexOf('id="valuation-panel"');
  const parameters = html.indexOf('id="parameter-title"');

  assert.ok(valuation > 0 && valuation < parameters);
  assert.match(html, /id="instrument-code"[^>]*inputmode="numeric"[^>]*maxlength="6"/);
  assert.match(html, /id="valuation-status"[^>]*aria-live="polite"/);
  assert.match(html, /id="valuation-retry"/);
  assert.match(html, /\.valuation-query[\s\S]*min-height:\s*44px/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*?\.valuation-query[^}]*grid-template-columns:\s*1fr/);
  assert.doesNotMatch(html, /建议开启|暂不建议|信号不一致|可考虑开启/);
  assert.doesNotMatch(html, /id="symbol-name"/);
});

test("sanitizes valuation codes and schedules only complete codes", () => {
  const timers = [];
  const valuation = loadValuation({
    setTimeout: (callback, delay) => {
      timers.push({ callback, delay });
      return timers.length;
    },
    clearTimeout: () => {},
  });
  const states = [];
  const controller = valuation.createController({
    fetchImpl: async () => ({ ok: true, json: async () => ({ code: "510500" }) }),
    onState: (state) => states.push(state),
  });

  assert.equal(valuation.sanitizeCode("51a05-00"), "510500");
  controller.input("51050");
  assert.equal(timers.length, 0);
  assert.equal(states.at(-1).kind, "empty");
  controller.input("510500");
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 400);
});

test("ignores stale valuation responses when a newer code wins", async () => {
  const requests = [];
  const fetchImpl = (url) => new Promise((resolve) => requests.push({ url, resolve }));
  const states = [];
  const valuation = loadValuation();
  const controller = valuation.createController({
    fetchImpl,
    onState: (state) => states.push(state),
  });

  const first = controller.query("510500");
  const second = controller.query("000300");
  requests[1].resolve({ ok: true, json: async () => ({ code: "000300", name: "沪深300" }) });
  await second;
  requests[0].resolve({ ok: true, json: async () => ({ code: "510500", name: "中证500ETF" }) });
  await first;

  assert.equal(states.at(-1).kind, "success");
  assert.equal(states.at(-1).data.code, "000300");
});

test("builds separate thermometer and PE/PB valuation views", () => {
  const { buildView } = loadValuation();
  const thermometer = buildView({
    code: "510500",
    name: "中证500ETF南方",
    trackedIndex: { code: "000905", name: "中证500" },
    source: "youzhiyouxing",
    asOf: "2026-07-14",
    thermometer: {
      temperature: 76,
      valuationBand: "偏高",
      intrinsicReturnPct: 4.42,
      dividendYieldPct: 1.53,
    },
    percentiles: null,
    warnings: [],
  });
  const percentiles = buildView({
    code: "000300",
    name: "沪深300",
    trackedIndex: { code: "000300", name: "沪深300" },
    source: "historical_percentile",
    asOf: "2026-07-14",
    thermometer: null,
    percentiles: {
      pe: { currentValue: 12.3, percentilePct: 40, startDate: "2016-07-14", endDate: "2026-07-14", sampleCount: 2400 },
      pb: { currentValue: 1.4, percentilePct: 30, startDate: "2016-07-14", endDate: "2026-07-14", sampleCount: 2400 },
    },
    warnings: [],
  });

  assert.deepEqual(Array.from(thermometer.metrics, (item) => item.label), [
    "标的", "跟踪指数", "指数温度", "估值区间", "内在收益率", "股息率",
  ]);
  assert.deepEqual(Array.from(percentiles.metrics, (item) => item.label), [
    "标的", "跟踪指数", "当前 PE", "PE 历史分位", "当前 PB", "PB 历史分位",
  ]);
  assert.equal(percentiles.sourceLabel, "历史 PE/PB 分位");
});

test("loads saved valuation snapshots before refreshing valid codes", () => {
  const html = fs.readFileSync(htmlPath, "utf8");

  assert.match(html, /record\.valuationSnapshot[\s\S]*kind:\s*"snapshot"/);
  assert.match(html, /valuationController\.query\(record\.code\)/);
  assert.match(html, /历史策略未保存代码，请补充 6 位代码/);
  assert.match(html, /currentValuation\?\.isSnapshot/);
});
