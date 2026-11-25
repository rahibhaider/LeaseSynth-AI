const CHART_PALETTE = ["#5468FF", "#8B5CF6", "#34D399", "#F5A524", "#F2555A", "#38BDF8", "#FB7185", "#A78BFA"];
const RENT_TICK_FORMAT = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
});
const RENT_TOOLTIP_FORMAT = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

const CHART_DEFAULTS = {
  plugins: {
    legend: {
      labels: { color: "#93A1C2", font: { family: "Inter", size: 11 }, boxWidth: 12, padding: 14 },
    },
  },
  scales: {},
};

function createDashboardChart(canvasId, config, { metric, formatValue = formatNumber, horizontal = false, currency = false }) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  Chart.getChart(canvas)?.destroy();

  const card = canvas.closest(".chart-card");
  const heading = card.querySelector("h3");
  heading.id = `${canvasId}Heading`;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-labelledby", heading.id);

  card.querySelector(".chart-inspector")?.remove();
  card.querySelector(".chart-view")?.remove();
  const inspector = document.getElementById("chartInspectorTemplate").content.firstElementChild.cloneNode(true);
  card.append(inspector);

  const select = inspector.querySelector("select");
  const value = inspector.querySelector("strong");
  const description = inspector.querySelector(".chart-point-metric");
  const labelId = `${canvasId}PointLabel`;
  select.id = `${canvasId}Point`;
  select.setAttribute("aria-labelledby", `${heading.id} ${labelId}`);
  inspector.querySelector("label").id = labelId;
  inspector.querySelector("label").htmlFor = select.id;
  inspector.querySelector("output").setAttribute("for", select.id);
  description.textContent = metric;

  const { labels, datasets: [dataset] } = config.data;
  canvas.parentElement.hidden = labels.length === 0;
  if (!labels.length) {
    select.add(new Option("No data points", ""));
    select.disabled = true;
    value.textContent = "—";
    return;
  }

  labels.forEach((label, index) => select.add(new Option(label, index)));
  let selectedIndex = Math.max(0, dataset.data.findIndex((point) => point > 0));
  const setReadout = () => {
    select.value = String(selectedIndex);
    value.textContent = formatValue(dataset.data[selectedIndex]);
  };
  setReadout();

  function selectPoint(index, chart) {
    if (!Number.isInteger(index) || index === selectedIndex) return;
    selectedIndex = index;
    setReadout();
    chart.draw();
  }

  config.options.onClick = (_, elements, chart) => selectPoint(elements[0]?.index, chart);
  config.options.plugins.tooltip = {
    callbacks: { label: ({ raw }) => `${metric}: ${formatValue(raw)}` },
  };
  if (config.options.plugins.legend.position === "bottom") {
    config.options.plugins.legend.onClick = (_, item, legend) => selectPoint(item.index, legend.chart);
  }

  let viewEvents;
  config.plugins = [{
    id: "selectedPointMarker",
    afterDatasetsDraw(chart) {
      const point = chart.getDatasetMeta(0).data[selectedIndex];
      if (!point) return;
      const { x, y } = point.tooltipPosition();
      const { left, right, top, bottom } = chart.chartArea;
      if (x < left || x > right || y < top || y > bottom) return;
      const { ctx } = chart;
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#111A2C";
      ctx.strokeStyle = "#F2F5FF";
      ctx.lineWidth = 2;
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    },
    afterDestroy() {
      viewEvents?.abort();
    },
  }];

  const chart = new Chart(canvas, config);
  select.addEventListener("change", () => selectPoint(Number(select.value), chart));
  if (horizontal) {
    const controls = document.getElementById("chartViewTemplate").content.firstElementChild.cloneNode(true);
    controls.setAttribute("aria-labelledby", heading.id);
    canvas.parentElement.before(controls);
    viewEvents = bindHorizontalChartView(chart, controls, () => dataset.data[selectedIndex], currency);
  }
}

function bindHorizontalChartView(chart, controls, selectedValue, currency) {
  const { canvas } = chart;
  const wrap = canvas.parentElement;
  const events = new AbortController();
  const listener = { signal: events.signal };
  const buttons = Object.fromEntries(
    Array.from(controls.querySelectorAll("button"), (button) => [button.dataset.action, button]),
  );
  const { min, max } = chart.scales.x;
  const fullSpan = max - min;
  const minSpan = Math.min(fullSpan, currency ? fullSpan / 16 : Math.max(2, Math.ceil(fullSpan / 16)));
  let start = min;
  let span = fullSpan;

  function updateControls() {
    const zoomed = span < fullSpan;
    buttons.in.disabled = span <= minSpan;
    buttons.out.disabled = buttons.reset.disabled = !zoomed;
    buttons.left.disabled = !zoomed || start <= min;
    buttons.right.disabled = !zoomed || start >= max - span;
    wrap.classList.toggle("is-pannable", zoomed);
  }

  function setView(nextStart, nextSpan) {
    if (!currency) {
      nextStart = Math.round(nextStart);
      nextSpan = Math.round(nextSpan);
    }
    nextSpan = Math.max(minSpan, Math.min(fullSpan, nextSpan));
    nextStart = Math.max(min, Math.min(max - nextSpan, nextStart));
    if (nextStart === start && nextSpan === span) return;
    start = nextStart;
    span = nextSpan;
    chart.options.scales.x.min = span < fullSpan ? start : undefined;
    chart.options.scales.x.max = span < fullSpan ? start + span : undefined;
    chart.update("none");
    updateControls();
  }

  buttons.in.addEventListener("click", () => {
    const nextSpan = Math.max(minSpan, currency ? span / 2 : Math.floor(span / 2));
    const focus = Math.max(start, Math.min(start + span, selectedValue()));
    setView(focus - (focus - start) * nextSpan / span, nextSpan);
  }, listener);
  buttons.out.addEventListener("click", () => setView(start - span / 2, span * 2), listener);
  buttons.reset.addEventListener("click", () => setView(min, fullSpan), listener);
  buttons.left.addEventListener("click", () => setView(start - span / 2, span), listener);
  buttons.right.addEventListener("click", () => setView(start + span / 2, span), listener);
  updateControls();

  let drag;
  let dragged = false;
  canvas.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0) return;
    dragged = false;
    if (span === fullSpan) return;
    const { left, right, top, bottom } = chart.chartArea;
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    if (x < left || x > right || y < top || y > bottom) return;
    drag = { id: event.pointerId, x: event.clientX, start, unitsPerPixel: span / (right - left) };
  }, listener);
  canvas.addEventListener("pointermove", (event) => {
    if (event.pointerId !== drag?.id) return;
    const delta = event.clientX - drag.x;
    if (!dragged && Math.abs(delta) < 6) return;
    if (!dragged) {
      dragged = true;
      canvas.setPointerCapture(event.pointerId);
      wrap.classList.add("is-dragging");
    }
    setView(drag.start - delta * drag.unitsPerPixel, span);
  }, listener);

  function endDrag(event) {
    if (event.pointerId !== drag?.id) return;
    drag = undefined;
    wrap.classList.remove("is-dragging");
  }

  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) {
    canvas.addEventListener(event, endDrag, listener);
  }
  canvas.addEventListener("pointerleave", (event) => {
    if (!dragged) endDrag(event);
  }, listener);
  canvas.addEventListener("click", (event) => {
    if (!dragged) return;
    dragged = false;
    event.stopImmediatePropagation();
  }, { ...listener, capture: true });
  events.signal.addEventListener("abort", () => wrap.classList.remove("is-pannable", "is-dragging"));
  return events;
}

function _gridOptions() {
  return {
    ticks: { color: "#93A1C2", font: { family: "IBM Plex Mono", size: 11 } },
    grid: { color: "rgba(255,255,255,0.05)" },
    border: { color: "#243354" },
  };
}

function renderPie(canvasId, labels, values, { doughnut = false } = {}) {
  createDashboardChart(canvasId, {
    type: doughnut ? "doughnut" : "pie",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: CHART_PALETTE, borderColor: "#111A2C", borderWidth: values.length > 1 ? 2 : 0 }],
    },
    options: {
      ...CHART_DEFAULTS,
      maintainAspectRatio: false,
      plugins: { ...CHART_DEFAULTS.plugins, legend: { ...CHART_DEFAULTS.plugins.legend, position: "bottom" } },
    },
  }, { metric: "Leases" });
}

function renderBar(canvasId, labels, values, { horizontal = false, label = "", currency = false } = {}) {
  const valueAxis = horizontal ? "x" : "y";
  const categoryAxis = horizontal ? "y" : "x";
  const valueScale = _gridOptions();
  const categoryScale = _gridOptions();
  valueScale.beginAtZero = true;
  valueScale.ticks.maxTicksLimit = 6;
  categoryScale.grid.display = false;
  categoryScale.ticks.maxRotation = 0;
  if (horizontal) {
    categoryScale.grid.drawTicks = false;
    categoryScale.ticks.color = "#D6DFF3";
    categoryScale.ticks.font = { family: "system-ui", size: 12, weight: 600 };
    categoryScale.ticks.padding = 10;
    categoryScale.ticks.autoSkip = false;
  }
  if (currency) {
    valueScale.ticks.callback = (value) => RENT_TICK_FORMAT.format(value);
  } else {
    valueScale.ticks.precision = 0;
  }

  createDashboardChart(canvasId, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label, data: values, backgroundColor: "#5468FF", borderRadius: 4, maxBarThickness: 46 }],
    },
    options: {
      ...CHART_DEFAULTS,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      interaction: { mode: "nearest", axis: categoryAxis, intersect: false },
      layout: { padding: 4 },
      plugins: { legend: { display: false } },
      scales: { [categoryAxis]: categoryScale, [valueAxis]: valueScale },
    },
  }, {
    metric: label,
    formatValue: currency ? (value) => RENT_TOOLTIP_FORMAT.format(value) : formatNumber,
    horizontal,
    currency,
  });
}

function renderLine(canvasId, labels, values, { label = "" } = {}) {
  const valueScale = _gridOptions();
  valueScale.beginAtZero = true;
  valueScale.ticks.precision = 0;
  createDashboardChart(canvasId, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label,
          data: values,
          borderColor: "#8B5CF6",
          backgroundColor: "rgba(139,92,246,0.12)",
          fill: true,
          tension: 0,
          pointRadius: 2,
          pointBackgroundColor: "#8B5CF6",
        },
      ],
    },
    options: {
      ...CHART_DEFAULTS,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: { legend: { display: false } },
      scales: { x: _gridOptions(), y: valueScale },
    },
  }, { metric: label });
}

function renderHistogram(canvasId, labels, values) {
  renderBar(canvasId, labels, values, { label: "Leases" });
}
