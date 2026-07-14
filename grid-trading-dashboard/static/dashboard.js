(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const reportNode = byId("initial-report");
  const stateNode = byId("initial-state");
  const errorNode = byId("initial-error");
  const refreshButton = byId("refresh-button");
  const positionSelector = byId("position-selector");
  const statusMessage = byId("status-message");
  const chartElement = byId("performance-chart");
  const metricsPanel = byId("metrics-panel");
  const tableBody = document.querySelector("#grid-summary tbody");
  const chartSummary = byId("chart-summary");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let chart = null;

  const metricDefinitions = [
    ["持仓收益率", "position_return", "percent", true],
    ["XIRR年化", "xirr", "percent", true],
    ["现距建仓涨跌", "current_change", "percent", true],
    ["距建仓最大跌幅", "max_decline_from_build", "percent", true],
    ["距历史最高跌幅", "decline_from_all_time_high", "percent", true],
    ["提款次数", "withdrawal_count", "count", false],
    ["单品仓位", "position_percentage", "percent", false],
    ["运行天数", "running_days", "days", false],
    ["建仓日期", "build_date", "date", false],
    ["XIRR计算日", "calculation_date", "date", false],
  ];

  const parseJson = (node) => {
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (_error) {
      return null;
    }
  };

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const formatNumber = (value, digits = 2) => new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

  function formatMetric(value, type) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    if (type === "percent") return `${formatNumber(value * 100)}%`;
    if (type === "count") return `${value}`;
    if (type === "days") return `${value}`;
    return String(value);
  }

  function showStatus(message, tone = "error") {
    statusMessage.textContent = message || "";
    statusMessage.className = `status-message ${tone === "warning" ? "warning" : ""}`;
    statusMessage.hidden = !message;
  }

  function renderMetrics(metrics = {}) {
    metricsPanel.replaceChildren();
    metricDefinitions.forEach(([label, key, type, signed]) => {
      const card = document.createElement("div");
      card.className = "metric-card";
      const value = metrics[key];
      const tone = signed && typeof value === "number"
        ? (value > 0 ? "positive" : value < 0 ? "negative" : "")
        : "";
      card.innerHTML = `
        <span class="metric-label">${escapeHtml(label)}</span>
        <span class="metric-value ${tone}">${escapeHtml(formatMetric(value, type))}</span>
      `;
      metricsPanel.append(card);
    });
  }

  function renderGrid(rows = []) {
    tableBody.replaceChildren();
    if (!rows.length) {
      const row = tableBody.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 6;
      cell.className = "empty-cell";
      cell.textContent = "暂无已完成的网格交易";
      return;
    }
    rows.forEach((item) => {
      const row = tableBody.insertRow();
      const values = [
        item.grid_id,
        item.completed_cycles,
        formatNumber(item.sold_quantity, 0),
        `¥${formatNumber(item.realized_profit)}`,
        formatMetric(item.return_rate, "percent"),
        item.average_holding_days === null ? "—" : formatNumber(item.average_holding_days, 1),
      ];
      values.forEach((value) => {
        const cell = row.insertCell();
        cell.textContent = value;
      });
    });
  }

  function markerTimestamp(chartDate, kind) {
    return `${chartDate}T${kind === "买入" ? "06:00:00" : "18:00:00"}`;
  }

  function formatAxisDate(value) {
    const day = new Date(value);
    if (Number.isNaN(day.getTime())) return String(value).slice(0, 10);
    const month = String(day.getMonth() + 1).padStart(2, "0");
    const date = String(day.getDate()).padStart(2, "0");
    return `${day.getFullYear()}-${month}-${date}`;
  }

  function markerData(markers, kind) {
    return markers
      .filter((marker) => marker.kind === kind)
      .map((marker) => ({
        value: [markerTimestamp(marker.chart_date, kind), marker.value],
        trade: marker,
        label: { formatter: `${kind === "买入" ? "买" : "卖"} ${marker.grid_id}` },
      }));
  }

  function tooltipFormatter(params) {
    const items = Array.isArray(params) ? params : [params];
    const date = items[0]?.axisValue || items[0]?.value?.[0] || "";
    const lines = [`<strong>${escapeHtml(formatAxisDate(date))}</strong>`];
    items.forEach((item) => {
      if (item.data?.trade) {
        const trade = item.data.trade;
        lines.push(
          `${escapeHtml(trade.kind)} ${escapeHtml(trade.grid_id)}：` +
          `${formatNumber(trade.quantity, 0)} 股 @ ${formatNumber(trade.price)}`
        );
      } else if (Array.isArray(item.value)) {
        lines.push(`${escapeHtml(item.seriesName)}：${formatMetric(item.value[1], "percent")}`);
      }
    });
    return lines.join("<br>");
  }

  function renderChart(report) {
    if (!window.echarts) {
      showStatus("图表组件未加载，请确认 static/vendor/echarts.min.js 存在。", "error");
      return;
    }
    if (!chart) chart = window.echarts.init(chartElement, null, { renderer: "canvas" });
    const buyMarkers = markerData(report.markers || [], "买入");
    const sellMarkers = markerData(report.markers || [], "卖出");
    chart.setOption({
      animation: !reduceMotion,
      backgroundColor: "#000",
      color: ["#8b93a3", "#d11f35", "#ff1f1f", "#00ef62"],
      grid: { left: 46, right: 46, top: 70, bottom: 64, containLabel: true },
      legend: {
        bottom: 12,
        textStyle: { color: "#e5e7eb", fontFamily: "Microsoft YaHei" },
        itemWidth: 28,
        itemHeight: 10,
        data: ["价格", "成本", "买入", "卖出"],
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: "rgba(8,10,13,.96)",
        borderColor: "#e5e7eb",
        textStyle: { color: "#f4f4f5" },
        formatter: tooltipFormatter,
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: "#7a818d" } },
        axisLabel: {
          color: "#bac0ca",
          rotate: 42,
          hideOverlap: true,
          formatter: formatAxisDate,
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        position: "right",
        axisLabel: { color: "#d2d6dd", formatter: (value) => `${(value * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: "#262a31", type: "dotted" } },
      },
      dataZoom: [
        { type: "inside", filterMode: "none" },
        { type: "slider", bottom: 36, height: 12, borderColor: "#343942", textStyle: { color: "#8f96a3" } },
      ],
      series: [
        {
          name: "价格",
          type: "line",
          showSymbol: false,
          sampling: "lttb",
          lineStyle: { width: 1, color: "#8b93a3" },
          data: (report.price_points || []).map((point) => [point.date, point.value]),
        },
        {
          name: "成本",
          type: "line",
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1.5, color: "#d11f35", type: "dashed" },
          data: (report.cost_points || []).map((point) => [point.date, point.value]),
        },
        {
          name: "买入",
          type: "scatter",
          symbol: "circle",
          symbolSize: 11,
          itemStyle: { color: "#ff1f1f" },
          label: { show: true, position: "top", color: "#ff9d9d", fontSize: 9 },
          data: buyMarkers,
          z: 5,
        },
        {
          name: "卖出",
          type: "scatter",
          symbol: "circle",
          symbolSize: 11,
          itemStyle: { color: "#00ef62" },
          label: { show: true, position: "top", color: "#7affac", fontSize: 9 },
          data: sellMarkers,
          z: 5,
        },
      ],
    }, true);
  }

  function renderReport(report) {
    if (!report) return;
    byId("chart-title").textContent = `【${report.stock_name || report.stock_code}】${report.title}`;
    byId("chart-subtitle").textContent = `数据源：固定 Excel · 日线不复权 · ${report.stock_code}`;
    byId("market-as-of").textContent = `行情日期 ${report.market_as_of || report.metrics?.calculation_date || "—"}`;
    renderMetrics(report.metrics);
    renderGrid(report.grid_rows);
    renderChart(report);
    const metrics = report.metrics || {};
    chartSummary.textContent =
      `${report.stock_name || report.stock_code}从${metrics.build_date || "建仓日"}` +
      `至${metrics.calculation_date || "计算日"}的价格与成本走势；` +
      `图中含${(report.markers || []).length}个买卖标记。`;
    if (report.warning) showStatus(report.warning, "warning");
    else showStatus("");
  }

  function renderPositions(positions = [], selectedFileId = null) {
    if (!positionSelector) return;
    positionSelector.replaceChildren();
    positions.forEach((position) => {
      const option = document.createElement("option");
      option.value = position.file_id;
      option.selected = position.file_id === selectedFileId;
      option.disabled = Boolean(position.error);
      option.textContent = position.error
        ? `${position.file_id}（${position.error}）`
        : `${position.stock_code} · ${position.display_name}`;
      positionSelector.append(option);
    });
    positionSelector.disabled = !positions.some((position) => !position.error);
  }

  function renderState(state) {
    if (!state) return;
    renderPositions(state.positions, state.selected_file_id);
    renderReport(state.report);
  }

  function setLoading(isLoading) {
    refreshButton.disabled = isLoading;
    if (positionSelector) {
      positionSelector.disabled = isLoading || !positionSelector.options.length;
    }
    refreshButton.classList.toggle("is-loading", isLoading);
    refreshButton.querySelector(".refresh-label").textContent = isLoading ? "刷新中" : "刷新数据";
  }

  async function refreshReport() {
    setLoading(true);
    try {
      const response = await fetch("/api/refresh", { method: "POST" });
      const payload = await response.json();
      if (!payload.ok) {
        showStatus(payload.error || "刷新失败，请检查交易记录。", "error");
        return;
      }
      if (payload.report?.report) renderState(payload.report);
      else renderReport(payload.report);
    } catch (error) {
      showStatus(`刷新失败：${error.message}`, "error");
    } finally {
      setLoading(false);
    }
  }

  refreshButton.addEventListener("click", refreshReport);
  positionSelector?.addEventListener("change", async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/select-position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: positionSelector.value }),
      });
      const payload = await response.json();
      if (!response.ok) {
        showStatus(payload.error || "切换标的失败", "error");
        return;
      }
      renderState(payload);
    } catch (error) {
      showStatus(`切换标的失败：${error.message}`, "error");
    } finally {
      setLoading(false);
    }
  });
  let resizeTimer;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => chart?.resize(), 120);
  });

  const initialState = parseJson(stateNode);
  const initialReport = parseJson(reportNode);
  const initialError = parseJson(errorNode);
  if (initialState) renderState(initialState);
  else if (initialReport) renderReport(initialReport);
  else renderMetrics({});
  if (initialError) showStatus(initialError, "error");
})();
