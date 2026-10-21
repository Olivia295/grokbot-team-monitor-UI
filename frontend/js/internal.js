// Internal box panel: on-disk bot status, collaboration and an estimate chart.
// External mode leaves this hidden. The choice is remembered in localStorage.

const MODE_KEY = "botOffice.dataMode";
let internalGen = 0;

function readStoredMode() {
  try { return localStorage.getItem(MODE_KEY); } catch { return null; }
}
function writeStoredMode(mode) {
  try { localStorage.setItem(MODE_KEY, mode); } catch { /* private mode */ }
}
function chooseMode(available) {
  if (!available) return "external";
  return readStoredMode() === "external" ? "external" : "internal";
}

function syncModeChrome() {
  const internal = document.getElementById("mode-internal");
  const external = document.getElementById("mode-external");
  const note = document.getElementById("mode-note");
  if (!internal || !external || !S.modeInfo) return;
  const available = !!S.modeInfo.internal_available;
  const on = S.dataMode === "internal" && available;
  if (!available) S.dataMode = "external";
  internal.disabled = !available;
  external.disabled = false;
  internal.setAttribute("aria-pressed", String(on));
  external.setAttribute("aria-pressed", String(!on));
  if (!available) {
    note.hidden = false;
    note.textContent = t("mode.unavailable");
    internal.setAttribute("aria-describedby", "mode-note");
  } else {
    note.hidden = true;
    note.textContent = "";
    internal.removeAttribute("aria-describedby");
  }
  const panel = document.getElementById("internal-panel");
  if (panel) panel.hidden = S.dataMode !== "internal";
}

function bindModeSwitch() {
  const root = document.getElementById("mode-switch");
  if (!root || root.dataset.bound) return;
  root.dataset.bound = "1";
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-mode]");
    if (!button || button.disabled) return;
    setDataMode(button.dataset.mode);
  });
}

function setDataMode(mode, persist = true) {
  if (!S.modeInfo) return;
  if (mode !== "internal" && mode !== "external") return;
  if (mode === "internal" && !S.modeInfo.internal_available) return;
  const changed = S.dataMode !== mode;
  S.dataMode = mode;
  if (persist) writeStoredMode(mode);
  syncModeChrome();
  if (mode === "internal" && (changed || !S.internal)) refreshInternal();
  else renderInternal();
}

async function initDataMode() {
  bindModeSwitch();
  try {
    S.modeInfo = await getJson("/api/mode");
  } catch {
    S.modeInfo = { internal_available: false, reason: "" };
  }
  S.dataMode = chooseMode(!!S.modeInfo.internal_available);
  syncModeChrome();
}

function statusLabel(status) {
  if (status === "不监控") return t("internal.status.unmonitored");
  if (status === "active") return t("internal.status.active");
  if (status === "recent") return t("internal.status.recent");
  if (status === "idle") return t("internal.status.idle");
  if (status === "no-folder") return t("internal.status.nofolder");
  return status || "—";
}
function statusClass(status) {
  if (status === "不监控") return "unmonitored";
  return status || "idle";
}
function kindLabel(kind) {
  if (kind === "dispatch") return t("internal.kind.dispatch");
  if (kind === "mention") return t("internal.kind.mention");
  return kind || "—";
}
function formatGenerated(iso, zone) {
  const match = String(iso || "").match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  const when = match ? `${match[1]} ${match[2]}` : String(iso || "");
  return `${t("internal.generated", { time: when })}${zone ? ` · ${zone}` : ""}`;
}

function tasksCell(bot) {
  if (bot.status === "不监控" || bot.status === "no-folder") return '<span class="muted">—</span>';
  const tasks = bot.recent_tasks || [];
  if (!tasks.length) return `<span class="muted">${esc(t("internal.tasks.none"))}</span>`;
  const items = tasks.map((task) => `<li>${esc(task)}</li>`).join("");
  return `<details><summary>${esc(t("internal.tasks.count", { n: tasks.length }))}</summary><ul>${items}</ul></details>`;
}

function summaryCard(data) {
  const summary = data.summary || {};
  const stats = [
    ["internal.stat.active", summary.active],
    ["internal.stat.recent", summary.recent],
    ["internal.stat.idle", summary.idle],
    ["internal.stat.nofolder", summary.no_folder],
    ["internal.stat.unmonitored", summary.unmonitored],
  ];
  const chips = stats.map(([key, value]) => (
    `<div class="internal-stat"><b class="num">${esc(value ?? 0)}</b><span>${esc(t(key))}</span></div>`
  )).join("");
  const zhNote = S.lang === "en" ? `<p class="muted">${esc(t("internal.summary.zh"))}</p>` : "";
  return `<article class="card internal-card">
    <h3>${esc(t("internal.summary"))}</h3>
    <div class="internal-stats">${chips}</div>
    <p class="internal-summary">${esc(summary.text || "")}</p>
    ${zhNote}
    <p class="muted internal-privacy">${esc(t("internal.privacy"))}</p>
  </article>`;
}

function tableCard(data) {
  const head = ["name", "label", "group", "status", "last", "files", "tasks"]
    .map((key) => `<th>${esc(t(`internal.col.${key}`))}</th>`).join("");
  const rows = (data.bots || []).map((bot) => {
    const quiet = bot.status === "不监控";
    const last = quiet || !bot.last_activity ? "—" : String(bot.last_activity).replace("T", " ").slice(0, 16);
    const files = quiet ? "—" : String(bot.files_modified_7d ?? 0);
    const title = bot.duty ? ` title="${esc(bot.duty)}"` : "";
    return `<tr>
      <td class="name"${title}>${esc(bot.name)}</td>
      <td>${esc(bot.label || "—")}</td>
      <td>${esc(bot.group || "—")}</td>
      <td><span class="badge ${esc(statusClass(bot.status))}">${esc(statusLabel(bot.status))}</span></td>
      <td>${esc(last)}</td>
      <td class="num">${esc(files)}</td>
      <td>${tasksCell(bot)}</td>
    </tr>`;
  }).join("");
  return `<article class="card internal-card">
    <div class="table-scroll"><table class="internal-table">
      <thead><tr>${head}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </article>`;
}

function edgesCard(data) {
  const edges = data.edges || [];
  const head = ["source", "target", "kind", "weight"]
    .map((key) => `<th>${esc(t(`internal.edges.${key}`))}</th>`).join("");
  const rows = edges.length
    ? edges.map((edge) => (
      `<tr><td>${esc(edge.source)}</td><td>${esc(edge.target)}</td><td>${esc(kindLabel(edge.kind))}</td><td class="num">${esc(edge.weight)}</td></tr>`
    )).join("")
    : `<tr><td colspan="4" class="muted">${esc(t("internal.edges.none"))}</td></tr>`;
  return `<article class="card internal-card">
    <h3>${esc(t("internal.edges"))}</h3>
    <div class="table-scroll edge-scroll"><table class="internal-table">
      <thead><tr>${head}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </article>`;
}

function usageCard(data) {
  const usage = data.usage || {};
  const note = usage.note || t("internal.usage.none");
  const english = S.lang === "en" && note !== t("internal.usage.none")
    ? `<span class="quota-en">${esc(t("internal.usage.none"))}</span>` : "";
  const estimates = usage.estimates || [];
  const max = estimates.reduce((peak, item) => Math.max(peak, item.activity || 0), 0);
  const bars = estimates.length
    ? estimates.map((item) => {
      const width = !item.activity || !max ? 0 : Math.max(2, Math.min(100, Math.round(100 * item.activity / max)));
      const meta = t("internal.bar", {
        activity: item.activity ?? 0,
        share: item.share_pct ?? 0,
        logs: item.log_lines_7d ?? 0,
        files: item.files_modified_7d ?? 0,
      });
      return `<div class="bar-row">
        <div class="bar-name">${esc(item.name)}</div>
        <div class="bar-track" role="presentation"><div class="bar-fill" style="width:${width}%"></div></div>
        <div class="bar-val">${esc(meta)}</div>
      </div>`;
    }).join("")
    : `<p class="muted">${esc(t("internal.edges.none"))}</p>`;
  const chartLabel = `${t("internal.estimate")}. ${usage.estimate_label || t("internal.estimate.hint")}`;
  return `<article class="card internal-card">
    <h3>${esc(t("internal.usage"))}</h3>
    <div class="quota-banner"><span class="quota-mark" aria-hidden="true">!</span><strong>${esc(note)}</strong>${english}</div>
    <div class="estimate" role="img" aria-label="${esc(chartLabel)}">
      <div class="estimate-head"><span class="est-badge">${esc(t("internal.estimate"))}</span></div>
      <p class="muted estimate-label">${esc(usage.estimate_label || "")}</p>
      ${S.lang === "en" ? `<p class="muted">${esc(t("internal.estimate.hint"))}</p>` : ""}
      ${bars}
    </div>
  </article>`;
}

function renderInternal() {
  const panel = $("#internal-panel");
  if (!panel) return;
  panel.hidden = S.dataMode !== "internal";
  if (S.dataMode !== "internal") return;
  const body = $("#internal-body");
  const stamp = $("#internal-stamp");
  if (S.internalError) {
    if (stamp) stamp.textContent = "";
    body.innerHTML = `<p class="muted">${esc(t("internal.error"))}</p>`;
    return;
  }
  if (!S.internal) {
    if (stamp) stamp.textContent = "";
    body.innerHTML = `<p class="muted">${esc(t("loading"))}</p>`;
    return;
  }
  if (stamp) stamp.textContent = formatGenerated(S.internal.generated_at, S.internal.timezone);
  body.innerHTML = summaryCard(S.internal) + tableCard(S.internal)
    + `<div class="internal-split">${edgesCard(S.internal)}${usageCard(S.internal)}</div>`;
}

async function refreshInternal() {
  const gen = ++internalGen;
  if (S.dataMode !== "internal") {
    renderInternal();
    return;
  }
  if (!S.internal) {
    S.internalError = false;
    renderInternal();
  }
  try {
    const data = await getJson("/api/internal");
    if (gen !== internalGen || S.dataMode !== "internal") return;
    S.internal = data;
    S.internalError = false;
  } catch {
    if (gen !== internalGen || S.dataMode !== "internal") return;
    if (!S.internal) S.internalError = true;
  }
  renderInternal();
}

bindModeSwitch();
