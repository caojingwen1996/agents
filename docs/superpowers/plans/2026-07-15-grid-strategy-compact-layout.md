# Grid Strategy Compact Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the grid strategy page compact enough that a 1366 × 768 desktop viewport shows the top actions, full parameter panel, and full pressure-test panel without scrolling after generation.

**Architecture:** Keep the existing single-file offline application and all calculation/controller code. Move only the generate/save controls into a compact header, add dedicated parameter and pressure layout classes, and use CSS breakpoints to preserve the current mobile flow.

**Tech Stack:** Static HTML/CSS/JavaScript, Node.js built-in test runner, in-app browser acceptance testing.

---

## File map

- Modify `grid-strategy-generator/index.html`: compact header markup, action placement, panel-specific classes, desktop and responsive CSS.
- Modify `grid-strategy-generator/tests/grid-calculator.test.mjs`: structural and CSS contract tests for the compact layout.
- Reference `docs/superpowers/specs/2026-07-15-grid-strategy-compact-layout-design.md`: approved behavior and viewport acceptance criteria.

No new runtime files, dependencies, storage versions, or JavaScript modules are required.

### Task 1: Move primary actions into the compact header

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs:527-554`
- Modify: `grid-strategy-generator/index.html:280-352`

- [ ] **Step 1: Write the failing structural test**

Append this test after the existing saved-strategy sidebar test:

```js
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node --test --test-name-pattern "places generate and save actions" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because `.top-toolbar` and the external submit button do not exist.

- [ ] **Step 3: Replace the hero with the compact header**

Replace the current `<header class="hero">...</header>` with:

```html
<header class="top-toolbar">
  <div class="title-group">
    <p class="eyebrow">固定步长 · 网格策略 1.0</p>
    <h1>网格策略 1.0 生成器</h1>
    <p class="hero-copy">设置参数、检查资金压力，再制定每档买卖计划。</p>
  </div>
  <div class="top-actions" aria-label="策略操作">
    <button class="primary-button" type="submit" form="grid-form">生成网格计划</button>
    <button id="save-strategy-button" class="secondary-button" type="button" disabled>保存策略</button>
  </div>
</header>
```

Delete only the existing form action wrapper:

```html
<div class="form-actions">
  <button class="primary-button" type="submit">生成网格计划</button>
  <button id="save-strategy-button" class="secondary-button" type="button" disabled>保存策略</button>
</div>
```

Keep `#save-status` inside `#grid-form`, keep the step preset buttons beside the form, and keep `#export-csv-button` in `.plan-toolbar`.

- [ ] **Step 4: Run the structural test and full suite**

Run:

```powershell
node --test --test-name-pattern "places generate and save actions" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: the targeted test passes; the full suite reports 28 tests passed and 0 failed.

- [ ] **Step 5: Commit the action placement**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: move grid actions to compact header"
```

### Task 2: Compact the parameter and pressure panels

**Files:**
- Modify: `grid-strategy-generator/tests/grid-calculator.test.mjs:527-570`
- Modify: `grid-strategy-generator/index.html:40-275`
- Modify: `grid-strategy-generator/index.html:286-362`

- [ ] **Step 1: Write the failing compact-layout contract test**

Append:

```js
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node --test --test-name-pattern "defines compact desktop" grid-strategy-generator/tests/grid-calculator.test.mjs
```

Expected: FAIL because the dedicated panel classes and 4/6-column contracts do not exist.

- [ ] **Step 3: Add panel-specific markup classes**

Change only these opening tags/classes:

```html
<section class="panel parameter-panel" aria-labelledby="parameter-title">
...
<section class="panel pressure-panel" aria-labelledby="pressure-title">
...
<div id="pressure-summary" class="metric-grid pressure-grid"></div>
```

- [ ] **Step 4: Replace the large hero and generic form spacing with compact styles**

Use these values as the desktop contract:

```css
.page-shell {
  width: min(1480px, calc(100% - 24px));
  margin: 0 auto;
  padding: 14px 0 48px;
}
.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: var(--shadow);
}
.title-group { min-width: 0; }
.eyebrow { margin: 0 0 2px; font-size: 0.72rem; }
h1 { margin: 0; font-size: clamp(1.25rem, 2vw, 1.6rem); letter-spacing: -0.02em; }
.hero-copy { margin: 2px 0 0; color: var(--muted); font-size: 0.82rem; }
.top-actions { display: flex; flex: 0 0 auto; gap: 10px; }
.top-actions .primary-button { margin-top: 0; }
.app-layout { gap: 16px; }
.parameter-panel, .pressure-panel { margin-top: 12px; padding: 14px 16px; }
.parameter-panel .section-heading, .pressure-panel .section-heading { margin-bottom: 10px; }
.form-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px 12px; }
label { gap: 4px; }
.helper { font-size: 0.75rem; line-height: 1.35; }
input, select { min-height: 44px; padding: 8px 10px; }
.step-presets { gap: 8px; margin-top: 10px; }
.save-status { margin: 8px 0 0; }
.pressure-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
.pressure-grid .metric { padding: 9px 10px; border-radius: 10px; }
.pressure-grid .metric strong { margin-top: 2px; font-size: 0.98rem; }
```

Remove the now-unused `.form-actions` rules. Do not reduce the general body font below 16px and do not change calculation/result JavaScript.

- [ ] **Step 5: Add responsive fallbacks**

Add before the existing 900px/720px rules:

```css
@media (max-width: 1100px) {
  .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pressure-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
```

Update the 720px block to include:

```css
.top-toolbar { align-items: stretch; flex-direction: column; }
.top-actions { display: grid; grid-template-columns: 1fr 1fr; }
.top-actions .primary-button, .top-actions .secondary-button { width: 100%; }
.form-grid, .metric-grid { grid-template-columns: 1fr; }
```

Keep the existing table overflow container and sidebar stacking behavior.

- [ ] **Step 6: Run targeted and full tests**

Run:

```powershell
node --test --test-name-pattern "compact desktop|places generate and save actions" grid-strategy-generator/tests/grid-calculator.test.mjs
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check
```

Expected: 2 targeted layout tests pass; the full suite reports 29 tests passed and 0 failed; `git diff --check` prints nothing.

- [ ] **Step 7: Commit the compact styles**

```powershell
git add grid-strategy-generator/index.html grid-strategy-generator/tests/grid-calculator.test.mjs
git commit -m "feat: compact grid parameter and pressure panels"
```

### Task 3: Browser acceptance at desktop and mobile sizes

**Files:**
- Verify: `grid-strategy-generator/index.html`
- Verify: `grid-strategy-generator/tests/grid-calculator.test.mjs`

- [ ] **Step 1: Start the local static server**

Run from `grid-strategy-generator`:

```powershell
python -m http.server 8004 --bind 127.0.0.1
```

Expected: the tool is reachable at `http://127.0.0.1:8004/`.

- [ ] **Step 2: Verify the 1366 × 768 desktop contract**

Set the browser viewport to 1366 × 768, load the page, fill a valid plan, and click the unique “生成网格计划” button. Read these values in one page evaluation:

```js
({
  scrollY: window.scrollY,
  viewportBottom: window.innerHeight,
  toolbarBottom: document.querySelector('.top-toolbar').getBoundingClientRect().bottom,
  parameterBottom: document.querySelector('.parameter-panel').getBoundingClientRect().bottom,
  pressureBottom: document.querySelector('.pressure-panel').getBoundingClientRect().bottom,
  pressureVisible: document.querySelector('.pressure-panel').offsetParent !== null,
  pageOverflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
})
```

Acceptance:

- `scrollY === 0`
- `pressureBottom <= viewportBottom`
- `pageOverflows === false`
- toolbar, parameter panel, and pressure panel are visible
- save enables after generation and disables after a parameter edit
- export remains inside the result table panel

- [ ] **Step 3: Verify the 375px mobile contract**

Set the viewport to 375 × 812 and read:

```js
({
  pageOverflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  generateHeight: document.querySelector('[form="grid-form"]').getBoundingClientRect().height,
  saveHeight: document.querySelector('#save-strategy-button').getBoundingClientRect().height,
  inputMinHeight: Math.min(...[...document.querySelectorAll('input, select')].map(
    (element) => element.getBoundingClientRect().height,
  )),
  sidebarAboveTool: document.querySelector('.strategy-sidebar').getBoundingClientRect().top
    < document.querySelector('#tool-column').getBoundingClientRect().top,
})
```

Acceptance:

- `pageOverflows === false`
- generate/save/input heights are at least 44px
- `sidebarAboveTool === true`
- the table retains its own horizontal scroll container

- [ ] **Step 4: Check runtime errors and reset the viewport**

Inspect browser logs for `error` and `warn`; expect none. Reset the viewport override and stop the local server.

- [ ] **Step 5: Run final verification**

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check master...HEAD
git status --short --branch
```

Expected: 29 tests pass, no diff-check errors, and the feature worktree is clean.

### Task 4: Review and branch completion

**Files:**
- Review: `grid-strategy-generator/index.html`
- Review: `grid-strategy-generator/tests/grid-calculator.test.mjs`
- Review: `docs/superpowers/specs/2026-07-15-grid-strategy-compact-layout-design.md`

- [ ] **Step 1: Request code review**

Give the reviewer the base SHA, current HEAD, approved design file, layout implementation summary, and browser acceptance evidence. Fix all Critical and Important findings before proceeding.

- [ ] **Step 2: Re-run verification after review fixes**

```powershell
node --test grid-strategy-generator/tests/grid-calculator.test.mjs
git diff --check master...HEAD
git status --short --branch
```

Expected: all tests pass, no diff-check errors, and no uncommitted changes.

- [ ] **Step 3: Offer branch completion choices**

Use the finishing-a-development-branch workflow to offer local merge, push/PR, keep, or discard. Do not push or merge without the user's choice.
