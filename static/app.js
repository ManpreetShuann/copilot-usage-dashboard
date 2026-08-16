const range = document.querySelector("#range");
const trendMetric = document.querySelector("#trend-metric");
const projectSelect = document.querySelector("#project-select");
const sessionSearch = document.querySelector("#session-search");
const exportButton = document.querySelector("#export");
const viewTabs = document.querySelectorAll("[data-view-target]");
const errorBox = document.querySelector("#error");

const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const colors = ["#bb9af7", "#7aa2f7", "#2ac3de", "#7dcfff", "#9ece6a", "#e0af68", "#ff9e64", "#f7768e", "#ff007c", "#1abc9c"];
let latestPayload;

function setView(view) {
  document.querySelectorAll("[data-view]").forEach((element) => {
    element.hidden = element.dataset.view !== view;
  });
  viewTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.viewTarget === view);
  });
}

function formatNumber(value) {
  return number.format(Number(value || 0));
}

function formatTokens(value) {
  const amount = Number(value || 0);
  if (amount >= 1_000_000) return `${formatNumber(amount / 1_000_000)}M`;
  if (amount >= 1_000) return `${formatNumber(amount / 1_000)}K`;
  return integer.format(amount);
}

function niceTokenScaleMax(value) {
  const exponent = Math.floor(Math.log10(Math.max(value, 1)));
  const magnitude = 10 ** exponent;
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function formatAiu(value) {
  const amount = Number(value || 0) / 1_000_000_000;
  if (amount >= 1_000_000) return `${formatNumber(amount / 1_000_000)}M`;
  if (amount >= 1_000) return `${formatNumber(amount / 1_000)}K`;
  return formatNumber(amount);
}

function formatTokenComposition(tokens, aiu) {
  return `${formatTokens(tokens)} tokens · ${formatAiu(aiu)} AIU`;
}

function totalTokens(row) {
  return Number(row.input_tokens || 0)
    + Number(row.output_tokens || 0)
    + Number(row.reasoning_tokens || 0);
}

function projectNameFromPath(path) {
  const normalizedPath = String(path).replace(/[\\/]+$/, "");
  return normalizedPath.split(/[\\/]/).pop() || path;
}

function percentChange(current, previous) {
  if (!previous) return current ? "new" : "0%";
  const change = ((current - previous) / previous) * 100;
  return `${change >= 0 ? "+" : ""}${formatNumber(change)}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSummary(summary) {
  const cards = [
    ["AIU usage", formatAiu(summary.total_nano_aiu), "converted from nano AIU"],
    ["Requests", integer.format(summary.requests || 0), "requests"],
    ["Tokens", formatTokens(totalTokens(summary)), "input + output + reasoning"],
    ["Cache reads", formatTokens(summary.cache_read_tokens), "cache_read_tokens"],
    ["Cache writes", formatTokens(summary.cache_write_tokens), "cache_write_tokens"],
    ["Sessions", integer.format(summary.sessions || 0), "sessions"],
  ];
  document.querySelector("#summary").innerHTML = cards.map(([label, value, hint]) => `
    <article class="card">
      <p class="card-label">${label}</p>
      <strong>${value}</strong>
      <span>${hint}</span>
    </article>
  `).join("");
}

function renderAdvancedMetrics(summary, previous, rangeDays) {
  const cacheBase = Number(summary.input_tokens || 0) + Number(summary.cache_read_tokens || 0);
  const cacheRate = cacheBase ? (Number(summary.cache_read_tokens || 0) / cacheBase) * 100 : 0;
  const aiuPerRequest = summary.requests ? Number(summary.total_nano_aiu || 0) / summary.requests : 0;
  const forecastDays = rangeDays === "month"
    ? new Date().getUTCDate()
    : rangeDays === "today" ? 1 : Number(rangeDays);
  const forecast = forecastDays
    ? (Number(summary.total_nano_aiu || 0) / forecastDays) * 30
    : null;
  const cards = [
    ["Period change", previous ? percentChange(summary.total_nano_aiu, previous.total_nano_aiu) : "n/a", "AIU vs previous timeframe"],
    ["Cache efficiency", `${formatNumber(cacheRate)}%`, "cache reads / input + cache"],
    ["AIU per request", formatAiu(aiuPerRequest), "average request intensity"],
    ["30-day projection", forecast === null ? "n/a" : `${formatAiu(forecast)} AIU`, "based on selected timeframe"],
  ];
  document.querySelector("#advanced-metrics").innerHTML = cards.map(([label, value, hint]) => `
    <article class="metric-card">
      <p>${label}</p>
      <strong>${value}</strong>
      <span>${hint}</span>
    </article>
  `).join("");
}

function renderDonut(donutId, legendId, segments, centerValue, centerLabel) {
  const donut = document.querySelector(`#${donutId}`);
  const legend = document.querySelector(`#${legendId}`);
  const total = segments.reduce((sum, segment) => sum + Number(segment.value || 0), 0);
  if (!total) {
    donut.style.background = "var(--panel-raised)";
    donut.querySelector(".donut-center").innerHTML = `<strong>0</strong><span>${centerLabel}</span>`;
    legend.innerHTML = '<p class="muted empty">No usage data in this timeframe.</p>';
    return;
  }

  let cursor = 0;
  const stops = segments.map((segment, index) => {
    const start = cursor;
    cursor += (Number(segment.value || 0) / total) * 100;
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  });
  donut.style.background = `conic-gradient(${stops.join(", ")})`;
  donut.querySelector(".donut-center").innerHTML =
    `<strong>${centerValue}</strong><span>${centerLabel}</span>`;
  legend.innerHTML = segments.map((segment, index) => {
    const percentage = (Number(segment.value || 0) / total) * 100;
    return `
      <${segment.onClick ? "button" : "div"} class="legend-row${segment.onClick ? " legend-button" : ""}"${segment.onClick ? ` type="button" data-segment-index="${index}"` : ""}>
        <span class="legend-label"><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(segment.label)}</span>
        <b>${segment.legendValue ? `${escapeHtml(segment.legendValue)} · ` : ""}${formatNumber(percentage)}%</b>
      </${segment.onClick ? "button" : "div"}>
    `;
  }).join("");
  legend.querySelectorAll("[data-segment-index]").forEach((element) => {
    element.addEventListener("click", () => segments[Number(element.dataset.segmentIndex)].onClick());
  });

  const segmentAtPoint = (event) => {
    const bounds = donut.getBoundingClientRect();
    const x = event.clientX - (bounds.left + bounds.width / 2);
    const y = event.clientY - (bounds.top + bounds.height / 2);
    const angle = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360;
    const value = angle / 360 * total;
    let cursor = 0;
    return segments.find((segment) => {
      cursor += Number(segment.value || 0);
      return value < cursor;
    });
  };
  donut.onclick = (event) => {
    segmentAtPoint(event)?.onClick?.();
  };
  donut.onmousemove = (event) => {
    const segment = segmentAtPoint(event);
    if (!segment?.hoverValue) return;
    const percentage = (Number(segment.value || 0) / total) * 100;
    donut.querySelector(".donut-center").innerHTML =
      `<strong>${escapeHtml(segment.hoverValue)}</strong><span>${escapeHtml(segment.label)} · ${formatNumber(percentage)}%</span>`;
  };
  donut.onmouseleave = () => {
    donut.querySelector(".donut-center").innerHTML =
      `<strong>${centerValue}</strong><span>${centerLabel}</span>`;
  };
}

function modelCardId(model) {
  return `model-card-${String(model).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;
}

function focusModel(model) {
  setView("models");
  const card = document.querySelector(`#${modelCardId(model)}`);
  card?.scrollIntoView({ behavior: "smooth", block: "center" });
  card?.classList.add("focused");
  window.setTimeout(() => card?.classList.remove("focused"), 1400);
}

function renderInsights(summary, models) {
  renderDonut(
    "model-donut",
    "model-legend",
    models.map((model) => ({
      label: model.model,
      value: model.total_nano_aiu,
      hoverValue: `${formatAiu(model.total_nano_aiu)} AIU`,
      onClick: () => focusModel(model.model),
    })),
    formatAiu(summary.total_nano_aiu),
    "AIU",
  );
  renderDonut(
    "token-donut",
    "token-legend",
    [
      { label: "Input", value: summary.input_tokens, legendValue: formatTokenComposition(summary.input_tokens, summary.input_nano_aiu), hoverValue: formatTokenComposition(summary.input_tokens, summary.input_nano_aiu) },
      { label: "Output", value: summary.output_tokens, legendValue: formatTokenComposition(summary.output_tokens, summary.output_nano_aiu), hoverValue: formatTokenComposition(summary.output_tokens, summary.output_nano_aiu) },
      { label: "Reasoning", value: summary.reasoning_tokens, legendValue: formatTokenComposition(summary.reasoning_tokens, 0), hoverValue: formatTokenComposition(summary.reasoning_tokens, 0) },
    ],
    formatTokens(totalTokens(summary)),
    "request tokens",
  );
  const requestTokens = totalTokens(summary);
  const cacheReads = Number(summary.cache_read_tokens || 0);
  const cacheShare = requestTokens + cacheReads
    ? (cacheReads / (requestTokens + cacheReads)) * 100
    : 0;
  document.querySelector("#token-legend").insertAdjacentHTML("beforeend", `
    <div class="legend-row legend-note">
      <span class="legend-label"><i></i>Cache reads</span>
      <b>${formatTokenComposition(cacheReads, summary.cache_read_nano_aiu)} · ${formatNumber(cacheShare)}%</b>
    </div>
    <div class="legend-row legend-note">
      <span class="legend-label"><i></i>Cache writes</span>
      <b>${formatTokenComposition(summary.cache_write_tokens, summary.cache_write_nano_aiu)}</b>
    </div>
  `);
  renderDonut(
    "model-token-donut",
    "model-token-legend",
    models
      .map((model) => ({
        label: model.model,
        value: totalTokens(model),
        hoverValue: `${formatTokens(totalTokens(model))} tokens`,
        onClick: () => focusModel(model.model),
      }))
      .sort((left, right) => right.value - left.value),
    formatTokens(totalTokens(summary)),
    "tokens",
  );
}

function renderIntentBreakdown(intents) {
  const totalTurns = intents.reduce((sum, item) => sum + Number(item.turns || 0), 0);
  renderDonut(
    "intent-donut",
    "intent-legend",
    intents.map((item) => ({
      label: formatIntentLabel(item.intent),
      value: item.turns,
      legendValue: `${integer.format(item.turns)} turns`,
      hoverValue: `${integer.format(item.turns)} turns`,
    })),
    integer.format(totalTurns),
    "user turns",
  );
}

function formatIntentLabel(intent) {
  return String(intent).replaceAll("_", " ");
}

function renderModelCards(models, summary) {
  const totalAiu = Number(summary.total_nano_aiu || 0);
  const container = document.querySelector("#model-cards");
  container.innerHTML = models.length
    ? models.map((model, index) => {
      const share = totalAiu ? (Number(model.total_nano_aiu || 0) / totalAiu) * 100 : 0;
      return `
        <article id="${modelCardId(model.model)}" class="model-card">
          <div class="model-card-top">
            <span class="model-dot" style="background:${colors[index % colors.length]}"></span>
            <strong title="${escapeHtml(model.model)}">${escapeHtml(model.model)}</strong>
            <b>${formatNumber(share)}%</b>
          </div>
          <div class="share-track"><span style="width:${share}%;background:${colors[index % colors.length]}"></span></div>
          <div class="model-stats">
            <span><b>${formatAiu(model.total_nano_aiu)}</b> AIU</span>
            <span><b>${integer.format(model.requests)}</b> requests</span>
            <span><b>${formatTokens(totalTokens(model))}</b> tokens</span>
            <span><b>${formatTokens(model.input_tokens)}</b> input</span>
            <span><b>${formatTokens(model.output_tokens)}</b> output</span>
            <span><b>${formatTokens(model.reasoning_tokens)}</b> reasoning</span>
            <span><b>${formatTokens(model.cache_read_tokens)}</b> cache read</span>
            <span><b>${formatTokens(model.cache_write_tokens)}</b> cache write</span>
            <span><b>${formatNumber(model.avg_duration_ms)} ms</b> latency</span>
            <span><b>${formatNumber(model.output_generation_speed_tps)} tokens/s</b> generation</span>
          </div>
        </article>
      `;
    }).join("")
    : '<p class="muted empty">No model data in this timeframe.</p>';
}

function renderReasoningEfforts(efforts) {
  renderDonut(
    "effort-donut",
    "effort-legend",
    efforts.map((effort) => ({ label: effort.reasoning_effort, value: effort.total_nano_aiu })),
    formatAiu(efforts.reduce((sum, effort) => sum + Number(effort.total_nano_aiu || 0), 0)),
    "AIU",
  );
  document.querySelector("#reasoning-efforts").innerHTML = efforts.length
    ? efforts.map((effort) => `
      <tr>
        <td class="model-name">${escapeHtml(effort.reasoning_effort)}</td>
        <td>${integer.format(effort.requests)}</td>
        <td>${formatTokens(effort.reasoning_tokens)}</td>
        <td class="aiu">${formatAiu(effort.total_nano_aiu)}</td>
        <td>${formatNumber(effort.avg_duration_ms)} ms</td>
      </tr>
    `).join("")
    : '<tr><td colspan="5" class="empty">No reasoning-effort data in this timeframe.</td></tr>';
}

function renderModels(models) {
  document.querySelector("#models").innerHTML = models.length
    ? models.map((model) => `
      <tr>
        <td class="model-name">${escapeHtml(model.model)}</td>
        <td>${integer.format(model.requests)}</td>
        <td>${formatTokens(model.input_tokens)}</td>
        <td>${formatTokens(model.output_tokens)}</td>
        <td>${formatTokens(model.reasoning_tokens)}</td>
        <td>${formatTokens(model.cache_read_tokens)}</td>
        <td class="aiu">${formatAiu(model.total_nano_aiu)}</td>
        <td>${formatNumber(model.avg_duration_ms)} ms</td>
        <td>${formatNumber(model.output_generation_speed_tps)} tokens/s</td>
      </tr>
    `).join("")
    : emptyRow("No usage data in this timeframe.");
}

function renderHourly(hourly) {
  const container = document.querySelector("#hourly-heatmap");
  const byHour = new Map(hourly.map((row) => [Number(row.hour), row]));
  const max = Math.max(...hourly.map((row) => Number(row.requests || 0)), 1);
  container.innerHTML = Array.from({ length: 24 }, (_, hour) => {
    const row = byHour.get(hour);
    const requests = Number(row?.requests || 0);
    const intensity = requests ? 0.18 + (requests / max) * 0.82 : 0.05;
    const label = `${String(hour).padStart(2, "0")}:00`;
    return `<div class="heat-cell" style="background:rgba(122,162,247,${intensity})" title="${label}: ${integer.format(requests)} requests, ${formatAiu(row?.total_nano_aiu)} AIU"><span>${hour}</span></div>`;
  }).join("");
}

function renderPerformance(summary, reliability) {
  const container = document.querySelector("#performance");
  const finishContainer = document.querySelector("#finish-reasons");
  const stopRate = summary.requests
    ? (Number(summary.stop_requests || 0) / summary.requests) * 100
    : 0;
  const toolCallRate = summary.requests
    ? (Number(summary.tool_call_requests || 0) / summary.requests) * 100
    : 0;
  const finishRows = reliability.map((row) => `
    <div class="status-row">
      <span>${escapeHtml(row.finish_reason)}</span>
      <b>${integer.format(row.requests)}</b>
    </div>
  `).join("");
  finishContainer.innerHTML = finishRows || '<span class="muted">No finish data.</span>';
  container.innerHTML = `
    <div class="performance-stats">
      <div><span>Avg response time</span><b>${formatNumber(summary.avg_duration_ms)} ms</b></div>
      <div><span>Avg time to first token</span><b>${formatNumber(summary.avg_ttft_ms)} ms</b></div>
      <div><span>Avg inter-token latency</span><b>${formatNumber(summary.avg_inter_token_ms)} ms</b></div>
      <div><span>Output generation speed</span><b>${formatNumber(summary.output_generation_speed_tps)} tokens/s</b></div>
      <div><span>Requests</span><b>${integer.format(summary.requests)}</b></div>
      <div><span>Stop completions</span><b>${integer.format(summary.stop_requests)} · ${formatNumber(stopRate)}%</b></div>
      <div><span>Tool calls</span><b>${integer.format(summary.tool_call_requests)} · ${formatNumber(toolCallRate)}%</b></div>
      <div><span>Filtered requests</span><b>${integer.format(summary.filtered_requests)}</b></div>
    </div>
  `;
}

function renderProjectDetail(locations, locationModels) {
  const paths = [...new Set(locations.map((location) => location.path))];
  const selectedPath = projectSelect.value;
  const options = paths.map((path) =>
    `<option value="${escapeHtml(path)}">${escapeHtml(projectNameFromPath(path))}</option>`
  ).join("");
  projectSelect.innerHTML = options || '<option value="">No projects</option>';
  projectSelect.value = paths.includes(selectedPath) ? selectedPath : (paths[0] || "");
  const selected = projectSelect.value;
  const rows = locationModels.filter((row) => row.path === selected);
  const location = locations.find((row) => row.path === selected);
  document.querySelector("#project-detail").innerHTML = location
    ? `
      <div class="project-summary">
        <strong title="${escapeHtml(location.path)}">${escapeHtml(projectNameFromPath(location.path))}</strong>
        <span>${integer.format(location.requests)} requests · ${formatTokens(location.tokens)} tokens · ${formatAiu(location.total_nano_aiu)} AIU</span>
      </div>
      <div class="project-detail-grid">
        <div><span>Total tokens</span><b>${formatTokens(location.tokens)}</b></div>
        <div><span>Input tokens</span><b>${formatTokens(location.input_tokens)}</b></div>
        <div><span>Output tokens</span><b>${formatTokens(location.output_tokens)}</b></div>
        <div><span>Reasoning tokens</span><b>${formatTokens(location.reasoning_tokens)}</b></div>
        <div><span>Cache reads / writes</span><b>${formatTokens(location.cache_read_tokens)} / ${formatTokens(location.cache_write_tokens)}</b></div>
      </div>
      ${rows.map((row) => `
        <div class="project-model-row">
          <span>${escapeHtml(row.model)}</span>
          <b>${integer.format(row.requests)} · ${formatTokens(row.tokens)} tokens · ${formatAiu(row.total_nano_aiu)} AIU</b>
        </div>
      `).join("")}
    `
    : '<p class="muted empty">No project data in this timeframe.</p>';
}

function renderSessions(sessions, query = sessionSearch.value) {
  const container = document.querySelector("#sessions");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredSessions = sessions.filter((session) => {
    if (!normalizedQuery) return true;
    const modelNames = (session.model_metrics || []).map((model) => model.model).join(" ");
    return [
      session.summary,
      session.path,
      session.repository,
      session.models,
      session.session_id,
      session.first_activity,
      session.last_activity,
      modelNames,
    ].some((value) => String(value || "").toLowerCase().includes(normalizedQuery));
  });
  container.innerHTML = filteredSessions.length
    ? filteredSessions.map((session) => `
      <details class="session-item">
        <summary class="session-row">
          <div>
            <strong title="${escapeHtml(session.summary)}">${escapeHtml(session.summary)}</strong>
            <span>${escapeHtml(projectNameFromPath(session.path))} · ${integer.format(session.requests)} requests</span>
          </div>
          <b>${formatAiu(session.total_nano_aiu)} AIU</b>
        </summary>
        <div class="session-details">
          <div class="session-detail-grid">
            <div><span>Models</span><b title="${escapeHtml(session.models || "")}">${escapeHtml((session.models || "Unknown").split(",").join(", "))}</b></div>
            <div><span>Tool calls</span><b>${integer.format(session.tool_calls)}</b></div>
            <div><span>Total tokens</span><b>${formatTokens(session.tokens)}</b></div>
            <div><span>Input / output</span><b>${formatTokens(session.input_tokens)} / ${formatTokens(session.output_tokens)}</b></div>
            <div><span>Reasoning tokens</span><b>${formatTokens(session.reasoning_tokens)}</b></div>
            <div><span>Cache reads / writes</span><b>${formatTokens(session.cache_read_tokens)} / ${formatTokens(session.cache_write_tokens)}</b></div>
            <div><span>Avg response</span><b>${formatNumber(session.avg_duration_ms)} ms</b></div>
            <div><span>Generation speed</span><b>${formatNumber(session.output_generation_speed_tps)} tokens/s</b></div>
            <div><span>Active days</span><b>${integer.format(session.active_days)}</b></div>
            <div><span>Last activity</span><b>${escapeHtml(formatDate(session.last_activity))}</b></div>
          </div>
          <div class="session-models">
            <div class="session-model-heading">Usage by model</div>
            <div class="session-model-table">
              <div class="session-model-row session-model-header">
                <span>Model</span><span>Requests</span><span>Tokens</span><span>Tool calls</span><span>AIU</span>
              </div>
              ${(session.model_metrics || []).map((model) => `
                <div class="session-model-row">
                  <strong title="${escapeHtml(model.model)}">${escapeHtml(model.model)}</strong>
                  <span>${integer.format(model.requests)}</span>
                  <span>${formatTokens(model.tokens)}</span>
                  <span>${integer.format(model.tool_calls)}</span>
                  <b>${formatAiu(model.total_nano_aiu)}</b>
                </div>
              `).join("") || '<span class="muted">No model data.</span>'}
            </div>
          </div>
          <span class="session-path" title="${escapeHtml(session.path)}">${escapeHtml(session.repository)} · ${escapeHtml(session.path)}</span>
        </div>
      </details>
    `).join("")
    : `<p class="muted empty">${normalizedQuery ? "No matching sessions." : "No session data in this timeframe."}</p>`;
}

function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function renderDaily(daily) {
  const chart = document.querySelector("#trend-chart");
  const dailyBars = document.querySelector("#daily");
  if (!daily.length) {
    chart.innerHTML = '<p class="muted empty">No usage data in this timeframe.</p>';
    dailyBars.innerHTML = '<p class="muted empty">No usage data in this timeframe.</p>';
    return;
  }
  const dailyMax = niceTokenScaleMax(Math.max(...daily.map(totalTokens), 1));
  const scaleLabels = [4, 3, 2, 1, 0].map((level) => `
    <span>${formatTokens((dailyMax * level) / 4)}</span>
  `).join("");
  const bars = daily.map((row) => {
    const height = Math.max((totalTokens(row) / dailyMax) * 100, 2);
    const date = new Date(`${row.day}T00:00:00`).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
    return `
      <div class="bar-group" title="${row.day}: ${formatTokens(totalTokens(row))} tokens, ${formatAiu(row.total_nano_aiu)} AIU">
        <div class="bar" style="height: ${height}%"></div>
        <span>${date}</span>
      </div>
    `;
  }).join("");
  dailyBars.innerHTML = `
    <div class="histogram" role="img" aria-label="Daily token volume, scaled from zero to ${formatTokens(dailyMax)} tokens">
      <div class="histogram-axis" aria-hidden="true">${scaleLabels}</div>
      <div class="histogram-plot">
        <div class="histogram-grid" aria-hidden="true">
          <i></i><i></i><i></i><i></i><i></i>
        </div>
        <div class="histogram-bars">${bars}</div>
      </div>
    </div>
  `;
  const metric = trendMetric.value;
  const values = daily.map((row) => metric === "aiu"
    ? Number(row.total_nano_aiu || 0)
    : metric === "requests" ? Number(row.requests || 0) : totalTokens(row));
  const max = Math.max(...values, 1);
  const width = 1000;
  const height = 290;
  const padding = { top: 24, right: 20, bottom: 42, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const points = values.map((value, index) => {
    const x = daily.length === 1
      ? width / 2
      : padding.left + (index / (daily.length - 1)) * plotWidth;
    const y = padding.top + plotHeight - (value / max) * plotHeight;
    return { x, y, value, row: daily[index] };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${padding.left},${padding.top + plotHeight} ${line} ${width - padding.right},${padding.top + plotHeight}`;
  const grid = [0, 0.5, 1].map((ratio) => {
    const y = padding.top + plotHeight - ratio * plotHeight;
    const value = max * ratio;
    const label = metric === "aiu" ? formatAiu(value)
      : metric === "requests" ? integer.format(value) : formatTokens(value);
    return `<line x1="${padding.left}" x2="${width - padding.right}" y1="${y}" y2="${y}"></line><text x="${padding.left - 10}" y="${y + 4}" text-anchor="end">${label}</text>`;
  }).join("");
  const dots = points.map((point) =>
    `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${point.row.day}: ${formatTrendValue(point.value, metric)}</title></circle>`
  ).join("");
  const labels = points.filter((_, index) => daily.length <= 8 || index % Math.ceil(daily.length / 8) === 0)
    .map((point) => {
      const date = new Date(`${point.row.day}T00:00:00`).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
      return `<text x="${point.x}" y="${height - 10}" text-anchor="middle">${date}</text>`;
    }).join("");
  chart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Usage trend chart">
      <g class="chart-grid">${grid}</g>
      <polygon class="trend-area" points="${area}"></polygon>
      <polyline class="trend-line" points="${line}"></polyline>
      <g class="trend-dots">${dots}</g>
      <g class="chart-labels">${labels}</g>
    </svg>
  `;
  document.querySelector("#trend-caption").textContent =
    `${metricLabel(metric)} per day in the selected timeframe. Hover points for details.`;
}

function renderLocations(locations) {
  const container = document.querySelector("#locations");
  container.innerHTML = locations.length
    ? locations.map((location) => {
      const projectName = projectNameFromPath(location.path);
      return `
        <div class="repo-row">
          <div>
            <strong title="${escapeHtml(location.path)}">${escapeHtml(projectName)}</strong>
            <span>${escapeHtml(location.repository)} · ${integer.format(location.sessions)} sessions · ${integer.format(location.requests)} requests</span>
          </div>
          <b>${formatAiu(location.total_nano_aiu)} AIU</b>
        </div>
      `;
    }).join("")
    : '<p class="muted empty">No path data in this timeframe.</p>';
}

function metricLabel(metric) {
  return metric === "aiu" ? "Usage units" : metric === "requests" ? "Requests" : "Tokens";
}

function formatTrendValue(value, metric) {
  return metric === "aiu" ? `${formatAiu(value)} AIU`
    : metric === "requests" ? `${integer.format(value)} requests` : `${formatTokens(value)} tokens`;
}

function emptyRow(message) {
  return `<tr><td colspan="9" class="empty">${message}</td></tr>`;
}

function exportCsv() {
  if (!latestPayload) return;
  const rows = [
    ["model", "requests", "input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens", "cache_write_tokens", "total_nano_aiu", "avg_duration_ms"],
    ...latestPayload.models.map((model) => [
      model.model, model.requests, model.input_tokens, model.output_tokens,
      model.reasoning_tokens, model.cache_read_tokens, model.cache_write_tokens,
      model.total_nano_aiu, model.avg_duration_ms,
    ]),
  ];
  const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `copilot-usage-${range.value}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

async function load() {
  errorBox.hidden = true;
  try {
    const response = await fetch(`/api/metrics?range=${encodeURIComponent(range.value)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Unable to load metrics.");
    latestPayload = payload;
    window.latestDaily = payload.daily;
    renderSummary(payload.summary);
    renderAdvancedMetrics(payload.summary, payload.previous_summary, payload.range_days);
    renderInsights(payload.summary, payload.models);
    renderIntentBreakdown(payload.intent_breakdown);
    renderModelCards(payload.models, payload.summary);
    renderReasoningEfforts(payload.reasoning_efforts);
    renderModels(payload.models);
    renderDaily(payload.daily);
    renderHourly(payload.hourly);
    renderPerformance(payload.summary, payload.reliability);
    renderProjectDetail(payload.locations, payload.location_models);
    renderSessions(payload.sessions);
    renderLocations(payload.locations);
    document.querySelector("#updated").textContent =
      `Updated ${new Date(payload.generated_at).toLocaleString()}`;
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

range.addEventListener("change", load);
trendMetric.addEventListener("change", () => {
  if (window.latestDaily) renderDaily(window.latestDaily);
});
projectSelect.addEventListener("change", () => {
  if (latestPayload) renderProjectDetail(latestPayload.locations, latestPayload.location_models);
});
sessionSearch.addEventListener("input", () => {
  if (latestPayload) renderSessions(latestPayload.sessions, sessionSearch.value);
});
exportButton.addEventListener("click", exportCsv);
viewTabs.forEach((tab) => {
  tab.addEventListener("click", () => setView(tab.dataset.viewTarget));
});
setView("overview");
load();
