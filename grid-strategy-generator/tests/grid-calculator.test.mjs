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
