// Internal box panel: on-disk bot status, collaboration and an estimate chart.
// External mode leaves this hidden. The choice is saved as the readMode setting on the
// server, so alerts, the big screen and every open page read the same source.

const MODE_KEY = "botOffice.dataMode"; // where the first version kept it, per browser (localStorage)
let internalGen = 0;

function chooseMode(info) {
  if (!info.internal_available) return "external";
  return info.mode === "external" ? "external" : "internal";
}
// A choice saved by the first version in this browser moves into settings once.
async function adoptStoredMode() {
  let stored = null;
  try { stored = localStorage.getItem(MODE_KEY); localStorage.removeItem(MODE_KEY); } catch { /* private mode */ }
  if ((stored === "internal" || stored === "external") && S.settings.readMode === "auto") {
    try { await saveSettings({ readMode: stored }); } catch { /* keep auto */ }
    return stored;
  }
  return null;
}

function syncModeChrome() {
  const internal = document.getElementById("mode-internal");
  const external = document.getElementById("mode-external");
  const note = document.getElementById("mode-note");
  if (!internal || !external || !S.modeInfo) return;
  const available = !!S.modeInfo.internal_available && !S.modeRequestFailed;
  const on = S.dataMode === "internal" && available;
  if (!available) S.dataMode = "external";
  internal.disabled = !available;
  external.disabled = false;
  internal.setAttribute("aria-pressed", String(on));
  external.setAttribute("aria-pressed", String(!on));
  if (S.modeRequestFailed) {
    note.hidden = false;
    note.innerHTML = `${esc(t("request.failed"))} <button type="button" class="retry" id="mode-retry">${esc(t("request.retry"))}</button>`;
    internal.setAttribute("aria-describedby", "mode-note");
  } else if (!available) {
    note.hidden = false;
    note.textContent = t("mode.unavailable");
    internal.setAttribute("aria-describedby", "mode-note");
  } else {
    note.hidden = true;
    note.textContent = "";
    internal.removeAttribute("aria-describedby");
  }
  // Most people never run on a box: only show the switch where it can do something.
  document.getElementById("mode-switch").hidden = !available && !S.modeRequestFailed;
  const panel = document.getElementById("internal-panel");
  if (panel) panel.hidden = S.dataMode !== "internal";
}

function reloadOfficeViews() {
  if (typeof refreshOffice !== "function") return Promise.resolve();
  // A different source: don't replay its whole history as "just happened".
  if (typeof resetLive === "function") resetLive();
  return refreshOffice().then(() => Promise.all([
    typeof refreshFlows === "function" ? refreshFlows() : null,
    typeof refreshInsights === "function" ? refreshInsights() : null,
  ]));
}

function bindModeSwitch() {
  const root = document.getElementById("mode-switch");
  if (!root || root.dataset.bound) return;
  root.dataset.bound = "1";
  root.addEventListener("click", (event) => {
    if (event.target.closest("#mode-retry")) {
      initDataMode().then(() => reloadOfficeViews());
      return;
    }
    const button = event.target.closest("[data-mode]");
    if (!button || button.disabled) return;
    setDataMode(button.dataset.mode);
  });
}

function setDataMode(mode, persist = true) {
  if (!S.modeInfo || S.modeRequestFailed) return;
  if (mode !== "internal" && mode !== "external") return;
  if (mode === "internal" && !S.modeInfo.internal_available) return;
  const changed = S.dataMode !== mode;
  S.dataMode = mode;
  if (persist) saveSettings({ readMode: mode }).catch(() => {});
  syncModeChrome();
  if (changed) reloadOfficeViews();
  if (mode === "internal" && (changed || !S.internal)) refreshInternal();
  else renderInternal();
}

async function initDataMode() {
  bindModeSwitch();
  const adopted = await adoptStoredMode();
  const result = await fetchJson("api/mode");
  if (result.failed) {
    S.modeRequestFailed = true;
    S.modeInfo = { internal_available: false, reason: "", requestFailed: true };
    S.dataMode = "external";
  } else if (result.unavailable) {
    S.modeRequestFailed = false;
    S.modeInfo = { internal_available: false, reason: (result.data && (result.data.reason || result.data.error)) || "" };
    S.dataMode = "external";
  } else {
    S.modeRequestFailed = false;
    S.modeInfo = result.data || { internal_available: false, reason: "" };
    if (adopted) S.modeInfo.mode = adopted;
    S.dataMode = chooseMode(S.modeInfo);
  }
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
  if (bot.name === "Willow Mage") {
    const result = bot.last_result === "replied" ? t("handoff.replied")
      : bot.last_result === "no-reply" ? t("handoff.noreply") : "—";
    return `<span class="muted">${esc(t("willow.count", { n: bot.message_count ?? 0 }))} · ${esc(result)} · ${esc(t("willow.hidden"))}</span>`;
  }
  if (bot.status === "不监控" || bot.status === "no-folder") return '<span class="muted">—</span>';
  const runs = bot.runs
    ? `<div class="runs-line">${esc(t("internal.runs", { runs: bot.runs.runs, retries: bot.runs.retries, failures: bot.runs.failures }))}${bot.runs.avg_rounds != null ? ` · ${esc(t("internal.rounds", { n: bot.runs.avg_rounds }))}` : ""}</div>`
    : "";
  const tasks = bot.recent_tasks || [];
  if (!tasks.length) return `${runs}<span class="muted">${esc(t("internal.tasks.none"))}</span>`;
  const items = tasks.map((task) => `<li>${esc(task)}</li>`).join("");
  const logs = (bot.logs || []).length ? ` title="${esc(t("internal.logsRead", { files: bot.logs.join("、") }))}"` : "";
  return `${runs}<details${logs}><summary>${esc(t("internal.tasks.count", { n: tasks.length }))}</summary><ul>${items}</ul></details>`;
}

const SCHEDULE_STATES = { done: "active", waiting: "recent", upcoming: "idle", missed: "missed", "not-today": "no-folder" };
function scheduleCard(data) {
  const items = data.schedule || [];
  if (!items.length) return "";
  const head = ["time", "bot", "what", "today", "next"].map((key) => `<th>${esc(t(`internal.sched.${key}`))}</th>`).join("");
  const rows = items.map((item) => {
    const next = String(item.next || "").replace("T", " ").slice(5, 16);
    const at = item.at ? ` ${String(item.at).slice(11, 16)}` : "";
    return `<tr><td class="num">${esc(item.time)}</td><td class="name">${esc(item.bot)}</td><td>${esc(item.what || "—")}</td>
      <td><span class="st-badge ${SCHEDULE_STATES[item.state] || "idle"}">${esc(t(`internal.sched.${item.state}`))}${esc(at)}</span></td><td>${esc(next)}</td></tr>`;
  }).join("");
  return `<article class="card internal-card">
    <h3>${esc(t("internal.sched.title"))}</h3>
    <p class="muted">${esc(t("internal.sched.note"))}</p>
    <div class="table-scroll"><table class="internal-table compact"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
  </article>`;
}

function changesCard(data) {
  const changes = data.changes || [];
  const deleted = data.deleted || [];
  if (!changes.length && !deleted.length) return "";
  const list = changes.map((item) => `<li><time>${esc(item.date || "—")}</time><span>${esc(item.text)}</span></li>`).join("");
  return `<article class="card internal-card">
    <h3>${esc(t("internal.changes.title"))}</h3>
    ${list ? `<ul class="change-list">${list}</ul>` : ""}
    ${deleted.length ? `<p class="muted">${esc(t("internal.deleted", { names: deleted.join("、") }))}</p>` : ""}
  </article>`;
}

function settingsWarning(data) {
  if (!data.settingsInWorkspace) return "";
  return `<div class="quota-banner"><span class="quota-mark" aria-hidden="true">!</span><span>${esc(t("internal.settingsWarning"))}</span></div>`;
}

function summaryCard(data) {
  const summary = data.summary || {};
  const stats = [
    ["internal.stat.active", summary.active],
    ["internal.stat.recent", summary.recent],
    ["internal.stat.idle", summary.idle],
    ["internal.stat.nofolder", summary.no_folder],
  ];
  if (summary.unmonitored) stats.push(["internal.stat.unmonitored", summary.unmonitored]);
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
    const dutyTip = bot.name === "Willow Mage" || !bot.duty ? "" : ` title="${esc(bot.duty)}"`;
    return `<tr>
      <td class="name"${dutyTip}>${esc(bot.name)}</td>
      <td>${esc(bot.label || "—")}${bot.engine ? ` <span class="engine-tag">${esc(bot.engine)}</span>` : ""}</td>
      <td>${esc(bot.group || "—")}</td>
      <td><span class="st-badge ${esc(statusClass(bot.status))}">${esc(statusLabel(bot.status))}</span></td>
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
  if (S.internalRequestFailed) {
    if (stamp) stamp.textContent = "";
    body.innerHTML = `<p class="muted">${esc(t("request.failed"))} <button type="button" class="retry" id="internal-retry">${esc(t("request.retry"))}</button></p>`;
    return;
  }
  if (S.internalError) {
    if (stamp) stamp.textContent = "";
    body.innerHTML = `<p class="muted">${esc(t("internal.error"))} <button type="button" class="retry" id="internal-retry">${esc(t("request.retry"))}</button></p>`;
    return;
  }
  if (!S.internal) {
    if (stamp) stamp.textContent = "";
    body.innerHTML = `<p class="muted">${esc(t("loading"))}</p>`;
    return;
  }
  if (stamp) stamp.textContent = formatGenerated(S.internal.generated_at, S.internal.timezone);
  body.innerHTML = settingsWarning(S.internal) + summaryCard(S.internal) + tableCard(S.internal)
    + `<div class="internal-split">${scheduleCard(S.internal)}${changesCard(S.internal)}</div>`
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
  const result = await fetchJson("api/internal");
  if (gen !== internalGen || S.dataMode !== "internal") return;
  if (result.unavailable) {
    S.internalRequestFailed = false;
    S.internalError = false;
    S.modeInfo = { ...(S.modeInfo || {}), internal_available: false, reason: (result.data && result.data.error) || "" };
    S.dataMode = "external";
    syncModeChrome();
    renderInternal();
    reloadOfficeViews();
    return;
  }
  if (result.failed && result.status) {
    // The server answered but couldn't read the box (roster missing or unreadable).
    S.internalRequestFailed = false;
    S.internalError = !S.internal;
  } else if (result.failed) {
    S.internalRequestFailed = true;
    if (!S.internal) S.internalError = true;
  } else {
    S.internal = result.data;
    S.internalError = false;
    S.internalRequestFailed = false;
  }
  renderInternal();
}

document.addEventListener("click", (event) => {
  if (event.target.closest("#internal-retry")) refreshInternal();
});

bindModeSwitch();
