# 图表同日标记与日期轴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同日买卖标记均可见，图表横坐标以完整年月日显示。

**Architecture:** 保持后端报告数据不变。`static/dashboard.js` 在渲染散点标记前，根据买卖方向向前或向后偏移半天，并给时间轴提供固定的日期格式化函数。

**Tech Stack:** JavaScript、ECharts、Node.js 内置测试执行器、pytest。

---

### Task 1: 为图表显示逻辑添加测试

**Files:**
- Create: `grid-trading-dashboard/tests/dashboard_js_test.mjs`
- Modify: `grid-trading-dashboard/static/dashboard.js`

- [ ] **Step 1: 编写失败测试**

```javascript
assert.equal(markerData([{ kind: "买入", chart_date: "2026-07-14", value: 0 }], "买入")[0].value[0], "2026-07-14T06:00:00");
assert.equal(markerData([{ kind: "卖出", chart_date: "2026-07-14", value: 0 }], "卖出")[0].value[0], "2026-07-14T18:00:00");
assert.equal(formatAxisDate("2026-07-14"), "2026-07-14");
```

- [ ] **Step 2: 运行测试确认失败**

Run: `node --test tests/dashboard_js_test.mjs`

Expected: FAIL，因为显示辅助函数尚未导出或尚未偏移标记时间。

- [ ] **Step 3: 最小实现**

```javascript
function markerDate(chartDate, kind) {
  return `${chartDate}T${kind === "买入" ? "06:00:00" : "18:00:00"}`;
}

function formatAxisDate(value) {
  return String(value).slice(0, 10);
}
```

在买卖标记的数据中使用 `markerDate`，并将 `formatAxisDate` 设置为 `xAxis.axisLabel.formatter`。

- [ ] **Step 4: 运行测试确认通过**

Run: `node --test tests/dashboard_js_test.mjs`

Expected: PASS。

- [ ] **Step 5: 运行回归检查并提交**

Run: `python -m pytest -q`

Expected: `40 passed`。

```bash
git add static/dashboard.js tests/dashboard_js_test.mjs
git commit -m "fix: separate same-day trade markers"
```
