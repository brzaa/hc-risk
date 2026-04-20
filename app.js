const state = {
  summary: null,
  chartModal: null,
};

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const currencyFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const CHART_COLORS = ["#9a5c39", "#61674b", "#c48a62", "#40667a", "#d4a37e", "#7c8162", "#b74b47", "#8a7e70"];

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return numberFormat.format(Number(value));
}

function formatDecimal(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function formatCurrency(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return currencyFormat.format(Number(value));
}

function titleCase(value) {
  if (!value) return "—";
  return String(value)
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
  return el;
}

function buildChartDetail(title, rows, eyebrow = "Selected point") {
  return { title, rows, eyebrow };
}

function renderChartDetail(root, selection, detailFormatter, fallbackText = "Click a point to inspect it.") {
  root.innerHTML = "";
  root.className = "chart-detail";

  if (!selection) {
    root.innerHTML = `
      <span class="chart-detail-eyebrow">Interactive chart</span>
      <strong class="chart-detail-title">${fallbackText}</strong>
      <span class="chart-detail-note">Click the chart background to open a larger view.</span>
    `;
    return;
  }

  const detail = detailFormatter
    ? detailFormatter(selection.point, selection.entry)
    : buildChartDetail(selection.entry.name || "Series", [
      ["X", String(selection.point.x)],
      ["Value", formatDecimal(selection.point.y)],
    ]);

  const eyebrow = document.createElement("span");
  eyebrow.className = "chart-detail-eyebrow";
  eyebrow.textContent = detail.eyebrow || "Selected point";

  const title = document.createElement("strong");
  title.className = "chart-detail-title";
  title.textContent = detail.title || selection.entry.name || "Series";

  const rows = document.createElement("div");
  rows.className = "chart-detail-rows";
  (detail.rows || []).forEach(([label, value]) => {
    rows.append(createMetricRow(label, value));
  });

  root.append(eyebrow, title, rows);
}

function setupChartModal() {
  if (state.chartModal) return state.chartModal;

  const overlay = document.createElement("div");
  overlay.className = "chart-modal hidden";
  overlay.innerHTML = `
    <div class="chart-modal-backdrop" data-role="chart-modal-close"></div>
    <div class="chart-modal-dialog" role="dialog" aria-modal="true" aria-label="Expanded chart">
      <div class="chart-modal-head">
        <div class="chart-modal-copy">
          <span class="panel-tag" data-role="chart-modal-eyebrow">Expanded Chart</span>
          <h3 data-role="chart-modal-title">Chart</h3>
          <p data-role="chart-modal-description"></p>
        </div>
        <button type="button" class="chart-modal-close" data-role="chart-modal-close" aria-label="Close chart">Close</button>
      </div>
      <div class="chart-modal-body" data-role="chart-modal-body"></div>
    </div>
  `;

  overlay.addEventListener("click", (event) => {
    if (event.target.dataset.role === "chart-modal-close") {
      closeChartModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.chartModal && !state.chartModal.root.classList.contains("hidden")) {
      closeChartModal();
    }
  });

  document.body.append(overlay);
  state.chartModal = {
    root: overlay,
    body: overlay.querySelector('[data-role="chart-modal-body"]'),
    title: overlay.querySelector('[data-role="chart-modal-title"]'),
    description: overlay.querySelector('[data-role="chart-modal-description"]'),
    eyebrow: overlay.querySelector('[data-role="chart-modal-eyebrow"]'),
  };
  return state.chartModal;
}

function closeChartModal() {
  const modal = setupChartModal();
  modal.root.classList.add("hidden");
  document.body.classList.remove("modal-open");
  modal.body.innerHTML = "";
}

function openChartModal(config) {
  const modal = setupChartModal();
  modal.title.textContent = config.title || "Expanded chart";
  modal.description.textContent = config.description || "Inspect the selected point and toggle visible series.";
  modal.eyebrow.textContent = config.eyebrow || "Expanded Chart";
  modal.body.innerHTML = "";
  modal.body.append(
    createLineChart(config.series, {
      ...config.options,
      viewWidth: 940,
      viewHeight: 500,
      expandable: false,
      interactive: true,
    }),
  );
  modal.root.classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function createMetricCard(label, value, note) {
  const card = document.createElement("article");
  card.className = "metric-card";
  card.innerHTML = `
    <span>${label}</span>
    <strong>${value}</strong>
    <span>${note}</span>
  `;
  return card;
}

function createMetricRow(label, value) {
  const row = document.createElement("div");
  row.className = "metric-row";
  row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
  return row;
}

function createResultTile(label, value, note) {
  const tile = document.createElement("div");
  tile.className = "result-tile";
  tile.innerHTML = `
    <span>${label}</span>
    <strong>${value}</strong>
    <small>${note}</small>
  `;
  return tile;
}

function createListRow(label, value) {
  const row = document.createElement("div");
  row.className = "list-row";
  row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
  return row;
}

function createBarRow(label, value, maxValue, note) {
  const numericValue = Number(value) || 0;
  const ratio = maxValue > 0 ? Math.max(0.04, numericValue / maxValue) : 0.04;
  const row = document.createElement("div");
  row.className = "bar-row";
  row.innerHTML = `
    <header>
      <span>${label}</span>
      <strong>${note}</strong>
    </header>
    <div class="bar-track">
      <div class="bar-fill" style="width:${Math.min(ratio * 100, 100)}%"></div>
    </div>
  `;
  return row;
}

function createStatusChip(label, state = "neutral") {
  const chip = document.createElement("span");
  chip.className = "status-chip";
  chip.dataset.state = state;
  chip.textContent = label;
  return chip;
}

function createPolicyBandCard(item) {
  const card = document.createElement("article");
  card.className = "policy-card";

  const header = document.createElement("div");
  header.className = "policy-card-head";

  const copy = document.createElement("div");
  copy.className = "policy-card-copy";
  copy.innerHTML = `
    <span class="policy-card-eyebrow">${item.decile_range}</span>
    <h3>${item.decision}</h3>
  `;

  header.append(copy, createStatusChip(item.decision, item.state || "neutral"));

  const rule = document.createElement("p");
  rule.className = "policy-card-body";
  rule.textContent = item.rule || "";

  const metrics = document.createElement("div");
  metrics.className = "policy-card-metrics";
  metrics.append(
    createMetricRow("Borrowers", formatNumber(item.borrowers)),
    createMetricRow("Share of Sample", formatPercent(item.share_of_sample, 1)),
    createMetricRow("Average PD", formatPercent(item.avg_prediction, 1)),
    createMetricRow("Observed Bad Rate", formatPercent(item.observed_default_rate, 1)),
    createMetricRow("Expected-Loss Proxy", formatCurrency(item.total_expected_loss_proxy)),
  );

  card.append(header, rule, metrics);
  return card;
}

function createTriggerCard(item) {
  const card = document.createElement("article");
  card.className = "policy-card";

  const header = document.createElement("div");
  header.className = "policy-card-head";

  const copy = document.createElement("div");
  copy.className = "policy-card-copy";
  copy.innerHTML = `
    <span class="policy-card-eyebrow">Trigger</span>
    <h3>${item.title}</h3>
  `;

  header.append(copy, createStatusChip(titleCase(item.state || "neutral"), item.state || "neutral"));

  const threshold = document.createElement("p");
  threshold.className = "policy-card-body";
  threshold.textContent = item.threshold || "";

  const metrics = document.createElement("div");
  metrics.className = "policy-card-metrics";
  metrics.append(
    createMetricRow("Current", item.current_value || "—"),
    createMetricRow("Action", item.action || "—"),
  );

  card.append(header, threshold, metrics);
  return card;
}

function createSignalCard(item, eyebrow = "Control") {
  const card = document.createElement("article");
  card.className = "signal-card";
  card.innerHTML = `
    <span class="signal-eyebrow">${eyebrow}</span>
    <h3>${item.title || "Untitled"}</h3>
    <p>${item.body || ""}</p>
  `;
  return card;
}

function createColumnChart(items, options = {}) {
  const {
    labelKey = "label",
    valueKey = "value",
    valueFormatter = formatNumber,
    colorScale = CHART_COLORS,
  } = options;
  const chart = document.createElement("div");
  chart.className = "column-chart";
  const maxValue = Math.max(...items.map((item) => Number(item[valueKey]) || 0), 1);

  items.forEach((item, index) => {
    const value = Number(item[valueKey]) || 0;
    const column = document.createElement("div");
    column.className = "column-item";
    column.innerHTML = `
      <span class="column-value">${valueFormatter(value)}</span>
      <div class="column-rail">
        <div class="column-bar" style="height:${Math.max((value / maxValue) * 100, 6)}%; background:${colorScale[index % colorScale.length]}"></div>
      </div>
      <span class="column-label">${item[labelKey]}</span>
    `;
    chart.append(column);
  });

  return chart;
}

function createGroupedMetricChart(items, metricKeys, options = {}) {
  const {
    seriesLabelKey = "dataset",
    valueFormatter = formatCurrency,
    showLegend = true,
  } = options;
  const chart = document.createElement("div");
  chart.className = "grouped-chart";
  const maxValue = Math.max(
    ...items.flatMap((item) => metricKeys.map((metric) => Number(item[metric.key]) || 0)),
    1,
  );

  metricKeys.forEach((metric) => {
    const group = document.createElement("div");
    group.className = "grouped-chart-group";

    const columns = document.createElement("div");
    columns.className = "grouped-columns";

    items.forEach((item, index) => {
      const value = Number(item[metric.key]) || 0;
      const column = document.createElement("div");
      column.className = "grouped-column";
      column.innerHTML = `
        <span class="grouped-value">${valueFormatter(value)}</span>
        <div class="grouped-rail">
          <div class="grouped-bar" style="height:${Math.max((value / maxValue) * 100, 6)}%; background:${CHART_COLORS[index % CHART_COLORS.length]}"></div>
        </div>
        <span class="grouped-series">${item[seriesLabelKey]}</span>
      `;
      columns.append(column);
    });

    const label = document.createElement("span");
    label.className = "grouped-label";
    label.textContent = metric.label;

    group.append(columns, label);
    chart.append(group);
  });

  const shell = document.createElement("div");
  shell.className = "chart-shell";
  shell.append(chart);
  if (showLegend) {
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    items.forEach((item, index) => {
      const chip = document.createElement("div");
      chip.className = "legend-chip";
      chip.innerHTML = `<span class="legend-swatch" style="background:${CHART_COLORS[index % CHART_COLORS.length]}"></span>${item[seriesLabelKey]}`;
      legend.append(chip);
    });
    shell.append(legend);
  }
  return shell;
}

function createRankedBarChart(items, options = {}) {
  const {
    labelKey = "feature",
    valueKey = "value",
    noteFormatter = (item) => formatPercent(item[valueKey], 1),
    valueFormatter = (value) => formatPercent(value, 1),
    color = "#9a5c39",
    maxItems = items.length,
  } = options;

  const chart = document.createElement("div");
  chart.className = "ranked-bar-chart";

  const rows = items.slice(0, maxItems);
  const maxValue = Math.max(...rows.map((item) => Number(item[valueKey]) || 0), 0.0001);

  rows.forEach((item) => {
    const value = Number(item[valueKey]) || 0;
    const row = document.createElement("div");
    row.className = "ranked-bar-row";
    row.style.setProperty("--ranked-bar-width", `${Math.max((value / maxValue) * 100, 4)}%`);
    row.style.setProperty("--ranked-bar-color", color);
    row.innerHTML = `
      <div class="ranked-bar-meta">
        <span class="ranked-bar-label">${titleCase(item[labelKey] ?? item.label ?? "Item")}</span>
        <strong class="ranked-bar-value">${valueFormatter(value)}</strong>
      </div>
      <div class="ranked-bar-rail">
        <div class="ranked-bar-fill"></div>
      </div>
      <span class="ranked-bar-note">${noteFormatter(item)}</span>
    `;
    chart.append(row);
  });

  return chart;
}

function createIntervalChart(items, options = {}) {
  const {
    labelKey = "feature",
    valueKey = "iv",
    lowerKey = "iv_ci_lower",
    upperKey = "iv_ci_upper",
    color = "#9a5c39",
    scaleFormatter = (value) => formatDecimal(value, 2),
    valueFormatter = (value) => formatDecimal(value, 3),
    noteFormatter = null,
    maxItems = items.length,
  } = options;

  const rows = items.slice(0, maxItems);
  const maxValue = Math.max(...rows.map((item) => Number(item[upperKey] ?? item[valueKey]) || 0), 0.001);

  const shell = document.createElement("div");
  shell.className = "interval-chart";

  const scale = document.createElement("div");
  scale.className = "interval-scale";
  [0, 0.5, 1].forEach((ratio) => {
    const tick = document.createElement("span");
    tick.textContent = scaleFormatter(maxValue * ratio);
    scale.append(tick);
  });
  shell.append(scale);

  rows.forEach((item) => {
    const value = Number(item[valueKey]) || 0;
    const lower = Number(item[lowerKey] ?? value) || 0;
    const upper = Number(item[upperKey] ?? value) || 0;
    const row = document.createElement("div");
    row.className = "interval-row";
    row.style.setProperty("--interval-color", color);
    row.title = noteFormatter ? noteFormatter(item) : "";

    const left = `${Math.max((lower / maxValue) * 100, 0)}%`;
    const width = `${Math.max(((upper - lower) / maxValue) * 100, 0.8)}%`;
    const point = `${Math.max((value / maxValue) * 100, 0)}%`;

    const note = noteFormatter ? `<span class="interval-note">${noteFormatter(item)}</span>` : "";
    row.innerHTML = `
      <div class="interval-copy">
        <span class="interval-label">${titleCase(item[labelKey] ?? "Metric")}</span>
        ${note}
      </div>
      <div class="interval-rail">
        <div class="interval-band" style="left:${left}; width:${width}"></div>
        <div class="interval-point" style="left:${point}"></div>
      </div>
      <strong class="interval-value">${valueFormatter(value)}</strong>
    `;
    shell.append(row);
  });

  return shell;
}

function linePath(points, xPosition, yPosition, stepped = false) {
  if (!points.length) return "";
  let path = `M ${xPosition(points[0].x)} ${yPosition(points[0].y)}`;
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1];
    const point = points[index];
    const x = xPosition(point.x);
    const y = yPosition(point.y);
    if (stepped) {
      path += ` L ${x} ${yPosition(prev.y)} L ${x} ${y}`;
    } else {
      path += ` L ${x} ${y}`;
    }
  }
  return path;
}

function createLineChart(series, options = {}) {
  const {
    stepped = false,
    xLabels = null,
    xTickFormatter = (value) => String(value),
    yTickFormatter = (value) => formatPercent(value, 0),
    showLegend = true,
    showDots = true,
    minY = 0,
    maxY = null,
    interactive = true,
    expandable = true,
    title = "Chart",
    description = "Click a point to inspect it. Click the chart to enlarge it.",
    eyebrow = "Interactive chart",
    detailFormatter = null,
    legendMode = series.length > 1 ? "isolate" : "none",
    viewWidth = 640,
    viewHeight = 320,
  } = options;

  const shell = document.createElement("div");
  shell.className = `chart-shell${interactive ? " chart-shell-interactive" : ""}${expandable ? " chart-shell-expandable" : ""}`;

  let activeSeries = new Set(series.map((entry, index) => entry.name || `Series ${index + 1}`));
  let selected = null;

  const shellToolbar = document.createElement("div");
  shellToolbar.className = "chart-toolbar";
  shellToolbar.innerHTML = `<span class="chart-hint">${description}</span>`;
  if (expandable) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chart-expand";
    button.textContent = "Expand";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openChartModal({
        title,
        description,
        eyebrow,
        series,
        options: {
          ...options,
          legendMode,
          title,
          description,
          eyebrow,
        },
      });
    });
    shellToolbar.append(button);
  }
  if (interactive || expandable) {
    shell.append(shellToolbar);
  }

  const svg = svgEl("svg", { viewBox: `0 0 ${viewWidth} ${viewHeight}`, class: "line-chart-svg", role: "img" });
  const padding = { top: 18, right: 18, bottom: 48, left: 48 };
  const innerWidth = viewWidth - padding.left - padding.right;
  const innerHeight = viewHeight - padding.top - padding.bottom;

  const allPoints = series.flatMap((entry) => entry.points);
  if (!allPoints.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<p>No chart data available.</p>";
    shell.append(empty);
    return shell;
  }

  const orderedX = xLabels
    ? [...xLabels]
    : [...new Set(allPoints.map((point) => point.x))];
  const xIndex = new Map(orderedX.map((value, index) => [value, index]));
  const xPosition = (xValue) => {
    const index = xIndex.get(xValue) ?? 0;
    if (orderedX.length === 1) return padding.left + innerWidth / 2;
    return padding.left + (index / (orderedX.length - 1)) * innerWidth;
  };

  const detailRoot = document.createElement("div");
  detailRoot.className = "chart-detail";
  const legend = document.createElement("div");
  legend.className = "chart-legend";

  function selectPoint(seriesName, pointIndex) {
    const entry = series.find((candidate, index) => (candidate.name || `Series ${index + 1}`) === seriesName);
    if (!entry || !entry.points?.[pointIndex]) return;
    selected = {
      entry,
      point: entry.points[pointIndex],
      seriesName,
      pointIndex,
    };
    render();
  }

  function render() {
    svg.innerHTML = "";
    const visibleSeries = series.filter((entry, index) => activeSeries.has(entry.name || `Series ${index + 1}`));
    const visiblePoints = visibleSeries.flatMap((entry) => entry.points);
    const yValues = visiblePoints.map((point) => Number(point.y) || 0);
    const resolvedMaxY = maxY === null ? Math.max(...yValues, minY + 1e-6) : Math.max(Number(maxY), minY + 1e-6);
    const minYAxis = Math.min(minY, ...yValues);
    const yPosition = (yValue) => {
      const ratio = (Number(yValue) - minYAxis) / Math.max(resolvedMaxY - minYAxis, 1e-6);
      return padding.top + innerHeight - ratio * innerHeight;
    };

    [0, 0.33, 0.66, 1].forEach((ratio) => {
      const yValue = minYAxis + (resolvedMaxY - minYAxis) * ratio;
      const y = yPosition(yValue);
      svg.append(
        svgEl("line", {
          x1: padding.left,
          y1: y,
          x2: viewWidth - padding.right,
          y2: y,
          class: "grid-line",
        }),
      );
      const text = svgEl("text", {
        x: padding.left - 10,
        y: y + 4,
        "text-anchor": "end",
        class: "chart-axis-label",
      });
      text.textContent = yTickFormatter(yValue);
      svg.append(text);
    });

    orderedX.forEach((value, index) => {
      const x = xPosition(value);
      svg.append(
        svgEl("line", {
          x1: x,
          y1: padding.top + innerHeight,
          x2: x,
          y2: padding.top + innerHeight + 6,
          class: "axis-tick",
        }),
      );
      const text = svgEl("text", {
        x,
        y: viewHeight - 16,
        "text-anchor": "middle",
        class: "chart-axis-label",
      });
      text.textContent = xTickFormatter(value, index);
      svg.append(text);
    });

    svg.append(
      svgEl("line", {
        x1: padding.left,
        y1: padding.top + innerHeight,
        x2: viewWidth - padding.right,
        y2: padding.top + innerHeight,
        class: "axis-line",
      }),
    );

    visibleSeries.forEach((entry, index) => {
      const seriesName = entry.name || `Series ${index + 1}`;
      const color = entry.color || CHART_COLORS[index % CHART_COLORS.length];
      const normalizedPoints = entry.points.map((point) => ({ ...point, x: point.x, y: Number(point.y) || 0 }));

      svg.append(
        svgEl("path", {
          d: linePath(normalizedPoints, xPosition, yPosition, stepped),
          fill: "none",
          stroke: color,
          "stroke-width": selected?.seriesName === seriesName ? "3.6" : "3",
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          opacity: selected && selected.seriesName !== seriesName ? "0.34" : "1",
        }),
      );

      normalizedPoints.forEach((point, pointIndex) => {
        const isSelected = selected?.seriesName === seriesName && selected?.pointIndex === pointIndex;
        if (showDots) {
          svg.append(
            svgEl("circle", {
              cx: xPosition(point.x),
              cy: yPosition(point.y),
              r: isSelected ? 5.5 : 3.5,
              fill: color,
              opacity: selected && selected.seriesName !== seriesName ? "0.45" : "1",
            }),
          );
        }
        if (interactive) {
          const hit = svgEl("circle", {
            cx: xPosition(point.x),
            cy: yPosition(point.y),
            r: isSelected ? 11 : 9,
            fill: "transparent",
            stroke: isSelected ? color : "transparent",
            "stroke-width": isSelected ? "2.4" : "0",
            "data-chart-point": "true",
            class: "chart-hit",
          });
          hit.addEventListener("click", (event) => {
            event.stopPropagation();
            selected = { entry, point, seriesName, pointIndex };
            render();
          });
          svg.append(hit);
        }
      });
    });

    renderChartDetail(detailRoot, selected, detailFormatter);

    if (showLegend && series.length > 1) {
      legend.innerHTML = "";
      series.forEach((entry, index) => {
        const seriesName = entry.name || `Series ${index + 1}`;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `legend-chip${activeSeries.has(seriesName) ? " legend-chip-active" : " legend-chip-muted"}`;
        chip.innerHTML = `<span class="legend-swatch" style="background:${entry.color || CHART_COLORS[index % CHART_COLORS.length]}"></span>${seriesName}`;
        if (legendMode !== "none") {
          chip.addEventListener("click", () => {
            const isOnlyVisible = activeSeries.size === 1 && activeSeries.has(seriesName);
            if (legendMode === "isolate") {
              activeSeries = isOnlyVisible
                ? new Set(series.map((candidate, candidateIndex) => candidate.name || `Series ${candidateIndex + 1}`))
                : new Set([seriesName]);
            } else {
              if (activeSeries.has(seriesName) && activeSeries.size > 1) {
                activeSeries.delete(seriesName);
              } else {
                activeSeries.add(seriesName);
              }
            }
            if (selected && !activeSeries.has(selected.seriesName)) {
              selected = null;
            }
            render();
          });
        }
        legend.append(chip);
      });
    }
  }

  if (interactive || expandable) {
    svg.addEventListener("click", (event) => {
      if (event.target?.getAttribute?.("data-chart-point") === "true") return;
      if (expandable) {
        openChartModal({
          title,
          description,
          eyebrow,
          series,
          options: {
            ...options,
            legendMode,
            title,
            description,
            eyebrow,
          },
        });
      }
    });
  }

  shell.selectChartPoint = selectPoint;
  shell.append(svg);
  if (interactive) shell.append(detailRoot);
  if (showLegend && series.length > 1) shell.append(legend);

  render();
  return shell;
}

function createLadderCard(item, tone) {
  const card = document.createElement("article");
  card.className = "ladder-card";
  const points = (item.points || []).map((point) => ({
    x: point.bucket,
    y: Number(point.default_rate) || 0,
    bucket: point.bucket,
    count: point.count,
  }));
  const first = points[0]?.y ?? null;
  const last = points[points.length - 1]?.y ?? null;

  const header = document.createElement("div");
  header.className = "ladder-card-header";
  header.innerHTML = `
    <h3>${item.display_name}</h3>
    <p>Default rate ladder across ordered risk buckets.</p>
  `;

  const chart = createLineChart(
    [
      {
        name: item.display_name,
        color: tone,
        points: points.map((point) => ({ x: point.bucket, y: point.y })),
      },
    ],
    {
      xLabels: points.map((point) => point.bucket),
      xTickFormatter: (_, index) => String(index + 1),
      yTickFormatter: (value) => formatPercent(value, 0),
      showLegend: false,
      minY: 0,
      title: item.display_name,
      description: "Click a bucket point to inspect it, or click the chart to open a larger view.",
      detailFormatter: (point) =>
        buildChartDetail(item.display_name, [
          ["Bucket", point.bucket],
          ["Default Rate", formatPercent(point.y, 1)],
          ["Observations", formatNumber(point.count)],
        ], "Selected bucket"),
    },
  );

  const bucketStrip = document.createElement("div");
  bucketStrip.className = "bucket-strip";
  points.forEach((point, index) => {
    const bucket = document.createElement("button");
    bucket.type = "button";
    bucket.className = "bucket-pill";
    bucket.innerHTML = `<span>${index + 1}</span><strong>${point.bucket}</strong>`;
    bucket.addEventListener("click", () => chart.selectChartPoint(item.display_name, index));
    bucketStrip.append(bucket);
  });

  const meta = document.createElement("div");
  meta.className = "ladder-meta";
  meta.append(
    createMetricRow("First Bucket", formatPercent(first, 1)),
    createMetricRow("Last Bucket", formatPercent(last, 1)),
  );

  card.append(header, chart, bucketStrip, meta);
  return card;
}

function renderHero(summary) {
  document.getElementById("hero-subtitle").textContent = summary.headline.subtitle;
  const container = document.getElementById("hero-metrics");
  container.innerHTML = "";
  const topRiskDecile = (summary.scorecard?.score_deciles || []).find((item) => Number(item.score_decile) === 10);
  container.append(
    createMetricCard("Portfolio Default Rate", formatPercent(summary.portfolio.default_rate), "Observed train bad rate"),
    createMetricCard("Scorecard ROC AUC", formatDecimal(summary.scorecard.roc_auc), "Explainable policy-facing scorecard"),
    createMetricCard(
      "Max Feature PSI",
      formatDecimal(summary.governance?.max_feature_psi, 3),
      summary.governance?.max_psi_feature
        ? `Largest train/test drift on ${titleCase(summary.governance.max_psi_feature)}`
        : "Top monitored drift feature",
    ),
    createMetricCard(
      "Top Risk Decile Bad Rate",
      formatPercent(topRiskDecile?.observed_default_rate, 1),
      "Observed bad rate in D10 of the scorecard sample",
    ),
  );
}

function renderAnalysis(summary) {
  const metrics = document.getElementById("analysis-metrics");
  metrics.innerHTML = "";
  metrics.append(
    createMetricRow("ROC AUC", formatDecimal(summary.analysis.roc_auc)),
    createMetricRow("PR AUC", formatDecimal(summary.analysis.pr_auc)),
    createMetricRow("KS", formatDecimal(summary.analysis.ks)),
    createMetricRow("Train Rows", formatNumber(summary.portfolio.train_rows)),
  );

  const topPredictors = document.getElementById("top-predictors");
  topPredictors.innerHTML = "";
  summary.analysis.top_numeric_predictors.forEach((item) => {
    topPredictors.append(createListRow(item.feature, formatDecimal(item.univariate_auc)));
  });

  const drift = document.getElementById("drift-features");
  drift.innerHTML = "";
  drift.append(createListRow("Adversarial AUC", formatDecimal(summary.drift.adversarial_auc)));
  summary.drift.top_drift_features.slice(0, 6).forEach((item) => {
    drift.append(createListRow(item.feature, formatDecimal(item.absolute_coefficient)));
  });
}

function renderLifecycle(summary) {
  const bands = document.getElementById("policy-bands");
  if (bands) {
    bands.innerHTML = "";
    (summary.strategy?.policy_bands || []).forEach((item) => {
      bands.append(createPolicyBandCard(item));
    });
  }

  const triggers = document.getElementById("policy-triggers");
  if (triggers) {
    triggers.innerHTML = "";
    (summary.strategy?.policy_triggers || []).forEach((item) => {
      triggers.append(createTriggerCard(item));
    });
  }
}

function renderAnalysisPlots(summary) {
  const plots = summary?.analysis_plots ?? {};

  const targetRoot = document.getElementById("target-distribution-chart");
  if (targetRoot) {
    targetRoot.innerHTML = "";
    targetRoot.append(
      createColumnChart(plots.target_distribution || [], {
        valueKey: "value",
        labelKey: "label",
        valueFormatter: formatNumber,
        colorScale: ["#61674b", "#b74b47"],
      }),
    );
  }

  const portfolioRoot = document.getElementById("portfolio-profile-chart");
  if (portfolioRoot) {
    portfolioRoot.innerHTML = "";
    portfolioRoot.append(
      createGroupedMetricChart(plots.portfolio_profile || [], [
        { key: "avg_income", label: "Income" },
        { key: "avg_credit", label: "Credit" },
        { key: "avg_annuity", label: "Annuity" },
      ], {
        showLegend: false,
      }),
    );
  }

  const capacityRoot = document.getElementById("capacity-ladders");
  if (capacityRoot) {
    capacityRoot.innerHTML = `<div class="ladder-heading"><h3>Capacity Signals</h3><p>Cash-flow and balance-sheet strain proxies.</p></div>`;
    const capacityGrid = document.createElement("div");
    capacityGrid.className = "ladder-grid";
    (plots.capacity_ladders || []).forEach((item) => {
      capacityGrid.append(createLadderCard(item, "#9a5c39"));
    });
    capacityRoot.append(capacityGrid);
  }

  const willingnessRoot = document.getElementById("willingness-ladders");
  if (willingnessRoot) {
    willingnessRoot.innerHTML = `<div class="ladder-heading"><h3>Willingness Signals</h3><p>Behavioral and historical repayment proxies.</p></div>`;
    const willingnessGrid = document.createElement("div");
    willingnessGrid.className = "ladder-grid";
    (plots.willingness_ladders || []).forEach((item) => {
      willingnessGrid.append(createLadderCard(item, "#40667a"));
    });
    willingnessRoot.append(willingnessGrid);
  }

  const vintageRoot = document.getElementById("vintage-chart");
  if (vintageRoot) {
    vintageRoot.innerHTML = "";
    const vintageSeries = (plots.vintage_curves || []).map((curve, index) => ({
      name: `${curve.cohort} · ${formatNumber(curve.loan_count)} loans`,
      color: CHART_COLORS[index % CHART_COLORS.length],
      points: (curve.points || []).map((point) => ({
        x: point.month_on_book,
        y: point.cumulative_default_rate,
      })),
    }));
    vintageRoot.append(
      createLineChart(vintageSeries, {
        xLabels: Array.from({ length: 12 }, (_, index) => index + 1),
        xTickFormatter: (value) => `M${value}`,
        yTickFormatter: (value) => formatPercent(value, 1),
        showLegend: true,
        minY: 0,
        title: "Vintage Analysis",
        description: "Click a cohort chip to isolate it. Click any point to inspect month-on-book performance.",
        legendMode: "isolate",
        detailFormatter: (point, entry) =>
          buildChartDetail(entry.name, [
            ["Month on Book", `M${point.x}`],
            ["Cumulative Default Rate", formatPercent(point.y, 3)],
          ], "Selected cohort point"),
      }),
    );
  }

  const survivalRoot = document.getElementById("survival-chart");
  if (survivalRoot) {
    survivalRoot.innerHTML = "";
    const survivalPoints = (plots.survival_curve || []).map((point) => ({
      x: point.month_on_book,
      y: point.survival_probability,
      n_at_risk: point.n_at_risk,
      events: point.events,
    }));
    const minSurvival = Math.min(...survivalPoints.map((point) => point.y), 0.999);
    survivalRoot.append(
      createLineChart(
        [
          {
            name: "Loan Survival",
            color: "#61674b",
            points: survivalPoints,
          },
        ],
        {
          stepped: true,
          xLabels: Array.from({ length: 13 }, (_, index) => index),
          xTickFormatter: (value) => `${value}`,
          yTickFormatter: (value) => formatPercent(value, 2),
          showLegend: false,
          showDots: false,
          minY: Math.max(minSurvival - 0.0012, 0.994),
          maxY: 1.0,
          title: "Survival Curve",
          description: "Click a month to inspect the survival step, or open the larger view for closer reading.",
          detailFormatter: (point) =>
            buildChartDetail("Loan Survival", [
              ["Month on Book", point.x],
              ["Survival Probability", formatPercent(point.y, 3)],
              ["At Risk", formatNumber(point.n_at_risk)],
              ["Events", formatNumber(point.events)],
            ], "Selected survival step"),
        },
      ),
    );
  }

  const specialValues = document.getElementById("special-values");
  if (specialValues) {
    specialValues.innerHTML = "";
    (plots.special_values || []).forEach((item) => {
      let rendered = formatNumber(item.value);
      if (item.kind === "percent") rendered = formatPercent(item.value, 1);
      if (item.kind === "currency") rendered = formatCurrency(item.value);
      specialValues.append(createListRow(item.item, rendered));
    });
  }

  const missingWatch = document.getElementById("missingness-watch");
  if (missingWatch) {
    missingWatch.innerHTML = "";
    const maxMissing = Math.max(...(plots.missing_top || []).map((item) => Number(item.missing_fraction) || 0), 0.01);
    (plots.missing_top || []).forEach((item) => {
      missingWatch.append(
        createBarRow(titleCase(item.feature), item.missing_fraction, maxMissing, formatPercent(item.missing_fraction, 1)),
      );
    });
  }

  const missingChart = document.getElementById("missingness-chart");
  if (missingChart) {
    missingChart.innerHTML = "";
    missingChart.append(
      createRankedBarChart(plots.missing_top || [], {
        labelKey: "feature",
        valueKey: "missing_fraction",
        color: "#40667a",
        maxItems: 6,
        valueFormatter: (value) => formatPercent(value, 1),
        noteFormatter: (item) => `${formatPercent(item.missing_fraction, 1)} missing share`,
      }),
    );
  }
}

function renderModels(summary) {
  const results = document.getElementById("scorecard-results");
  if (results) {
    const monitoring = summary.scorecard.monitoring_sample_rows || {};
    const topRiskDecile = (summary.scorecard.score_deciles || []).find((item) => Number(item.score_decile) === 10);
    const highRiskLoss = (summary.scorecard.score_deciles || [])
      .filter((item) => Number(item.score_decile) >= 8)
      .reduce((total, item) => total + (Number(item.total_expected_loss_proxy) || 0), 0);
    results.innerHTML = "";
    results.append(
      createResultTile("ROC AUC", formatDecimal(summary.scorecard.roc_auc), "Discrimination of the explainable scorecard"),
      createResultTile("KS", formatDecimal(summary.scorecard.ks), "Separation between good and bad borrowers"),
      createResultTile("PR AUC", formatDecimal(summary.scorecard.pr_auc), "Precision-recall quality on the bad class"),
      createResultTile("Brier", formatDecimal(summary.scorecard.brier), "Probability calibration error"),
      createResultTile(
        "Mean Calibration Gap",
        formatPercent(summary.scorecard.calibration_mean_absolute_gap, 1),
        "Average absolute gap between predicted and observed bad rate across score bins",
      ),
      createResultTile(
        "Worst Calibration Bin",
        formatPercent(summary.scorecard.calibration_max_gap, 1),
        summary.scorecard.worst_calibration_bin?.label
          ? `Largest miss in ${summary.scorecard.worst_calibration_bin.label}`
          : "Largest observed calibration miss",
      ),
      createResultTile(
        "Top Decile Bad Rate",
        formatPercent(topRiskDecile?.observed_default_rate, 1),
        "Observed bad rate in the riskiest score decile",
      ),
      createResultTile(
        "High-Risk EL Proxy",
        formatCurrency(highRiskLoss),
        "Expected-loss proxy in deciles D8-D10 using a 45% LGD assumption",
      ),
      createResultTile("Selected Features", formatNumber(summary.scorecard.selected_feature_count), "Final features retained by the scorecard"),
      createResultTile("Train Monitoring Sample", formatNumber(monitoring.train), "Rows used for train-side PSI diagnostics"),
      createResultTile("Test Monitoring Sample", formatNumber(monitoring.test), "Rows used for test-side PSI diagnostics"),
    );
  }

  const comparison = document.getElementById("model-comparison");
  if (comparison) {
    comparison.innerHTML = "";
    const comparisonNotes = {
      analysis_baseline: "Simple baseline for portfolio context",
      explainable_scorecard: "Primary operating model",
      leaderboard_ensemble: "Benchmark challenger",
    };
    Object.entries(summary.model_comparison).forEach(([name, metrics]) => {
      const row = document.createElement("div");
      row.className = "comparison-row";
      row.innerHTML = `
        <div class="comparison-copy">
          <span>${titleCase(name)}</span>
          <small>${comparisonNotes[name] || "Model comparison"}</small>
        </div>
        <div class="comparison-stats">
          <div class="comparison-stat">
            <span>AUC</span>
            <strong>${formatDecimal(metrics.roc_auc)}</strong>
          </div>
          <div class="comparison-stat">
            <span>PR</span>
            <strong>${formatDecimal(metrics.pr_auc)}</strong>
          </div>
          <div class="comparison-stat">
            <span>KS</span>
            <strong>${formatDecimal(metrics.ks)}</strong>
          </div>
          <div class="comparison-stat">
            <span>Brier</span>
            <strong>${formatDecimal(metrics.brier)}</strong>
          </div>
        </div>
      `;
      comparison.append(row);
    });
  }

  const topIv = summary.scorecard.top_iv;
  const ivMax = Math.max(...topIv.map((item) => Number(item.iv || 0)), 0.01);
  const scorecardFeatures = document.getElementById("scorecard-features");
  scorecardFeatures.innerHTML = "";
  topIv.forEach((item) => {
    scorecardFeatures.append(
      createBarRow(item.feature, item.iv, ivMax, `IV ${formatDecimal(item.iv)} · ${item.binning_strategy}`),
    );
  });

  const topPsi = summary.scorecard.top_psi;
  const psiMax = Math.max(...topPsi.map((item) => Number(item.psi_train_test || 0)), 0.01);
  const psiWatchlist = document.getElementById("psi-watchlist");
  psiWatchlist.innerHTML = "";
  topPsi.forEach((item) => {
    psiWatchlist.append(
      createBarRow(item.feature, item.psi_train_test, psiMax, `PSI ${formatDecimal(item.psi_train_test)}`),
    );
  });

  const diagnostics = document.getElementById("scorecard-diagnostics");
  if (diagnostics) {
    diagnostics.innerHTML = "";

    const grid = document.createElement("div");
    grid.className = "diagnostics-grid";

    const ivCard = document.createElement("div");
    ivCard.className = "diagnostic-card";
    ivCard.innerHTML = `
      <div class="plot-header">
        <h3>IV Strength</h3>
        <p>Point estimate with bootstrap confidence interval for the highest-value scorecard features.</p>
      </div>
    `;
    ivCard.append(
      createIntervalChart(summary.scorecard.top_iv || [], {
        valueKey: "iv",
        lowerKey: "iv_ci_lower",
        upperKey: "iv_ci_upper",
        color: "#9a5c39",
        maxItems: 6,
        noteFormatter: (item) => `p-value ${formatDecimal(item.iv_permutation_p_value, 3)}`,
      }),
    );

    const psiCard = document.createElement("div");
    psiCard.className = "diagnostic-card";
    psiCard.innerHTML = `
      <div class="plot-header">
        <h3>PSI Drift</h3>
        <p>Train-versus-test drift with uncertainty bounds for the most sensitive monitored features.</p>
      </div>
    `;
    psiCard.append(
      createIntervalChart(summary.scorecard.top_psi || [], {
        valueKey: "psi_train_test",
        lowerKey: "psi_ci_lower",
        upperKey: "psi_ci_upper",
        color: "#40667a",
        maxItems: 6,
        valueFormatter: (value) => formatDecimal(value, 3),
        noteFormatter: (item) => `missing ${formatPercent(item.test_missing_share, 1)} test / ${formatPercent(item.train_missing_share, 1)} train`,
      }),
    );

    const monitoringCard = document.createElement("div");
    monitoringCard.className = "diagnostic-card diagnostic-card-span";
    monitoringCard.innerHTML = `
      <div class="plot-header">
        <h3>Bin Monitoring</h3>
        <p>The largest PSI components come from coverage and bucket-share changes, not just raw value drift.</p>
      </div>
    `;
    monitoringCard.append(
      createRankedBarChart(summary.scorecard.bin_monitoring || [], {
        labelKey: "feature",
        valueKey: "psi_component",
        color: "#61674b",
        maxItems: 6,
        valueFormatter: (value) => formatDecimal(value, 3),
        noteFormatter: (item) =>
          `${titleCase(item.label)} · expected ${formatPercent(item.expected_share, 1)} / actual ${formatPercent(item.actual_share, 1)}`,
      }),
    );

    grid.append(ivCard, psiCard, monitoringCard);
    diagnostics.append(grid);
  }

  const calibrationChart = document.getElementById("calibration-chart");
  if (calibrationChart) {
    calibrationChart.innerHTML = "";
    const bins = summary.scorecard.calibration_bins || [];
    calibrationChart.append(
      createLineChart(
        [
          {
            name: "Average PD",
            color: "#40667a",
            points: bins.map((item) => ({ x: item.label, y: item.avg_prediction, count: item.count })),
          },
          {
            name: "Observed Bad Rate",
            color: "#b74b47",
            points: bins.map((item) => ({
              x: item.label,
              y: item.observed_default_rate,
              count: item.count,
              gap: item.gap,
            })),
          },
        ],
        {
          xLabels: bins.map((item) => item.label),
          yTickFormatter: (value) => formatPercent(value, 0),
          title: "Calibration Curve",
          description: "Compare the scorecard's predicted PD against the observed bad rate for each reported probability bin.",
          detailFormatter: (point, entry) =>
            buildChartDetail(entry.name, [
              ["Bin", point.x],
              ["Value", formatPercent(point.y, 1)],
              ["Sample", formatNumber(point.count)],
              ["Gap", point.gap === undefined ? "—" : formatPercent(point.gap, 1)],
            ], "Selected calibration bin"),
        },
      ),
    );
  }

  const decileChart = document.getElementById("bad-rate-decile-chart");
  if (decileChart) {
    decileChart.innerHTML = "";
    const deciles = summary.scorecard.score_deciles || [];
    decileChart.append(
      createLineChart(
        [
          {
            name: "Average PD",
            color: "#40667a",
            points: deciles.map((item) => ({ x: item.label, y: item.avg_prediction, borrowers: item.borrowers })),
          },
          {
            name: "Observed Bad Rate",
            color: "#9a5c39",
            points: deciles.map((item) => ({
              x: item.label,
              y: item.observed_default_rate,
              borrowers: item.borrowers,
              avg_credit: item.avg_credit,
            })),
          },
        ],
        {
          xLabels: deciles.map((item) => item.label),
          yTickFormatter: (value) => formatPercent(value, 0),
          title: "Bad Rate by Score Decile",
          description: "The score is translated into deciles so risk operations can compare average PD against the realized bad rate band by band.",
          detailFormatter: (point, entry) =>
            buildChartDetail(entry.name, [
              ["Decile", point.x],
              ["Value", formatPercent(point.y, 1)],
              ["Borrowers", formatNumber(point.borrowers)],
              ["Average Credit", point.avg_credit === undefined ? "—" : formatCurrency(point.avg_credit)],
            ], "Selected score decile"),
        },
      ),
    );
  }

  const expectedLossChart = document.getElementById("expected-loss-chart");
  if (expectedLossChart) {
    expectedLossChart.innerHTML = "";
    const deciles = [...(summary.scorecard.score_deciles || [])].sort(
      (left, right) => Number(right.total_expected_loss_proxy) - Number(left.total_expected_loss_proxy),
    );
    expectedLossChart.append(
      createRankedBarChart(deciles, {
        labelKey: "label",
        valueKey: "total_expected_loss_proxy",
        color: "#61674b",
        maxItems: deciles.length,
        valueFormatter: (value) => formatCurrency(value),
        noteFormatter: (item) =>
          `Bad rate ${formatPercent(item.observed_default_rate, 1)} · avg credit ${formatCurrency(item.avg_credit)} · loss share ${formatPercent(item.loss_share, 1)}`,
      }),
    );
  }
}

function renderGovernance(summary) {
  const proxyReview = document.getElementById("proxy-review");
  if (proxyReview) {
    proxyReview.innerHTML = "";
    (summary.governance?.proxy_notes || []).forEach((item) => {
      proxyReview.append(createSignalCard(item, "Proxy review"));
    });

    if ((summary.governance?.excluded_features || []).length) {
      proxyReview.append(
        createSignalCard(
          {
            title: "Explicit scorecard exclusions",
            body: summary.governance.excluded_features.join(", "),
          },
          "Excluded features",
        ),
      );
    }
  }

  const missingnessNotes = document.getElementById("missingness-notes");
  if (missingnessNotes) {
    missingnessNotes.innerHTML = "";
    (summary.governance?.missingness_notes || []).forEach((item) => {
      missingnessNotes.append(createSignalCard(item, "Missingness control"));
    });
  }

  const missingnessGovernance = document.getElementById("missingness-governance");
  if (missingnessGovernance) {
    missingnessGovernance.innerHTML = "";
    const items = summary.governance?.missingness_watch || [];
    const maxMissing = Math.max(...items.map((item) => Number(item.missing_fraction) || 0), 0.01);
    items.forEach((item) => {
      missingnessGovernance.append(
        createBarRow(
          titleCase(item.feature),
          item.missing_fraction,
          maxMissing,
          formatPercent(item.missing_fraction, 1),
        ),
      );
    });
  }

  const fraudSignals = document.getElementById("fraud-signals");
  if (fraudSignals) {
    fraudSignals.innerHTML = "";
    (summary.governance?.fraud_extension || []).forEach((item) => {
      fraudSignals.append(createSignalCard(item, "Fraud extension"));
    });
  }
}

function renderFeaturedBorrowers(summary) {
  const root = document.getElementById("featured-borrowers");
  if (!root) return;
  root.innerHTML = "";
  const ids = [
    ...summary.featured_borrowers.highest_scorecard_risk_train,
    ...summary.featured_borrowers.lowest_scorecard_risk_train,
    ...summary.featured_borrowers.sample_test_ids,
  ];
  [...new Set(ids)].forEach((id) => {
    const link = document.createElement("a");
    link.className = "borrower-chip";
    link.href = `/borrowers/${id}`;
    link.textContent = id;
    root.append(link);
  });
}

function renderDetailGrid(root, entries, formatter = (value) => value) {
  root.innerHTML = "";
  entries.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "detail-item";
    item.innerHTML = `<span>${label}</span><strong>${formatter(value)}</strong>`;
    root.append(item);
  });
}

function renderBorrower(payload) {
  const stage = document.getElementById("borrower-stage");
  stage.innerHTML = "";

  if (!payload || !payload.id) {
    stage.innerHTML = `<div class="empty-state"><p>Borrower not found in the prepared analysis bundle.</p></div>`;
    return;
  }

  const template = document.getElementById("borrower-template");
  const fragment = template.content.cloneNode(true);

  fragment.querySelector('[data-role="borrower-split"]').textContent = `${titleCase(payload.split)} Borrower`;
  fragment.querySelector('[data-role="borrower-title"]').textContent = `SK_ID_CURR ${payload.id}`;
  fragment.querySelector('[data-role="borrower-summary"]').textContent =
    payload.target === null || payload.target === undefined
      ? "This borrower lives in the test set, so the site shows the predicted risk path and modeled reasons without an observed target."
      : `Observed target: ${payload.target}. This drilldown connects the raw borrower profile, credit activity, reason codes, and modeled risk outputs.`;
  fragment.querySelector('[data-role="scorecard-probability"]').textContent = formatPercent(payload.scorecard?.probability, 2);
  fragment.querySelector('[data-role="scorecard-score"]').textContent = formatNumber(payload.scorecard?.score);
  fragment.querySelector('[data-role="leaderboard-blend"]').textContent = formatPercent(payload.leaderboard?.blend, 2);

  renderDetailGrid(
    fragment.querySelector('[data-role="profile-grid"]'),
    [
      ["Contract Type", payload.profile?.contract_type],
      ["Income Type", payload.profile?.income_type],
      ["Education", payload.profile?.education],
      ["Housing", payload.profile?.housing_type],
      ["Family Status", payload.profile?.family_status],
      ["Income", payload.profile?.income_total],
      ["Credit", payload.profile?.credit_amount],
      ["Annuity", payload.profile?.annuity_amount],
      ["Goods Price", payload.profile?.goods_price],
      ["EXT_SOURCE_2", payload.profile?.ext_source_2],
    ],
    (value) => (typeof value === "number" && value > 1000 ? formatCurrency(value) : value ?? "—"),
  );

  renderDetailGrid(
    fragment.querySelector('[data-role="activity-grid"]'),
    [
      ["Bureau Rows", payload.activity?.bureau_rows],
      ["Active Loans", payload.activity?.active_loans],
      ["Previous Applications", payload.activity?.previous_rows],
      ["Previous Approved", payload.activity?.previous_approved],
      ["Previous Refused", payload.activity?.previous_refused],
      ["Installment Rows", payload.activity?.installment_rows],
      ["Late Rate", payload.activity?.installment_late_rate],
      ["Max Days Past Due", payload.activity?.installment_max_dpd],
      ["Bureau Total Debt", payload.activity?.bureau_total_debt],
      ["Bureau Total Overdue", payload.activity?.bureau_total_overdue],
    ],
    (value) => {
      if (typeof value === "number" && value > 1000) return formatCurrency(value);
      if (typeof value === "number" && value <= 1) return formatPercent(value, 1);
      return value ?? "—";
    },
  );

  const reasonsList = fragment.querySelector('[data-role="reasons-list"]');
  reasonsList.innerHTML = "";
  (payload.reasons || []).forEach((reason) => {
    const item = document.createElement("div");
    item.className = "reason-item";
    item.innerHTML = `
      <span>${reason.feature}</span>
      <strong>${formatDecimal(reason.contribution)}</strong>
      <span>Raw: ${reason.raw_value ?? "—"}</span>
      <span>Bin: ${reason.matched_bin ?? "—"}</span>
      <span>Points: ${reason.points ?? "—"}</span>
      <span>Bad Rate: ${reason.bad_rate === null || reason.bad_rate === undefined ? "—" : formatPercent(reason.bad_rate, 1)}</span>
    `;
    reasonsList.append(item);
  });

  renderDetailGrid(
    fragment.querySelector('[data-role="highlights-grid"]'),
    [
      ["Observed Target", payload.target],
      ["Scorecard Probability", payload.scorecard?.probability],
      ["Scorecard Score", payload.scorecard?.score],
      ["Stack Logit", payload.leaderboard?.stack_logit],
      ["Leaderboard Blend", payload.leaderboard?.blend],
      ["Primary Reason", payload.reasons?.[0]?.feature],
    ],
    (value) => {
      if (typeof value === "number" && value <= 1 && !Number.isInteger(value)) return formatPercent(value, 2);
      if (typeof value === "number") return formatNumber(value);
      return value ?? "—";
    },
  );

  stage.append(fragment);
}

async function loadBorrower(id) {
  const stage = document.getElementById("borrower-stage");
  stage.innerHTML = `<div class="empty-state"><p>Loading borrower ${id}...</p></div>`;
  try {
    const response = await fetch(`/api/borrower?id=${encodeURIComponent(id)}`);
    if (!response.ok) {
      throw new Error(`Lookup failed with status ${response.status}`);
    }
    const payload = await response.json();
    renderBorrower(payload);
  } catch (error) {
    stage.innerHTML = `<div class="empty-state"><p>${error.message}</p></div>`;
  }
}

function scrollToHashTarget() {
  const rawHash = window.location.hash;
  if (!rawHash || rawHash === "#") return;
  const targetId = decodeURIComponent(rawHash.slice(1));
  const target = document.getElementById(targetId);
  if (!target) return;

  const top = window.scrollY + target.getBoundingClientRect().top - 24;
  window.scrollTo({ top: Math.max(top, 0), behavior: "auto" });
}

function syncHashAfterRender() {
  if (!window.location.hash) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      scrollToHashTarget();
    });
  });
}

async function init() {
  const response = await fetch("./data/summary.json");
  const summary = await response.json();
  state.summary = summary;
  try {
    renderHero(summary);
  } catch (error) {
    console.error("renderHero failed", error);
  }
  try {
    renderAnalysis(summary);
  } catch (error) {
    console.error("renderAnalysis failed", error);
  }
  try {
    renderLifecycle(summary);
  } catch (error) {
    console.error("renderLifecycle failed", error);
  }
  try {
    renderAnalysisPlots(summary);
  } catch (error) {
    console.error("renderAnalysisPlots failed", error);
  }
  try {
    renderModels(summary);
  } catch (error) {
    console.error("renderModels failed", error);
  }
  try {
    renderGovernance(summary);
  } catch (error) {
    console.error("renderGovernance failed", error);
  }
  try {
    renderFeaturedBorrowers(summary);
  } catch (error) {
    console.error("renderFeaturedBorrowers failed", error);
  }

  syncHashAfterRender();
}

window.addEventListener("hashchange", () => {
  requestAnimationFrame(() => {
    scrollToHashTarget();
  });
});

init().catch((error) => {
  document.getElementById("hero-subtitle").textContent = error.message;
});
