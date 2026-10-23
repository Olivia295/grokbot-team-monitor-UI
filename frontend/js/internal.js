// Internal box panel: on-disk bot status, collaboration and real message counts.
// External mode leaves this hidden. The choice is saved as the readMode setting on the
// server, so alerts, the big screen and every open page read the same source.

// The online demo shows the panel as a labelled sample, built from the demo team.
const showsPanel = () => S.dataMode === "internal" || Boolean(STATIC);
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
  // Off a box there is nothing to switch to; on a box "external" would only be the demo team.
  // So the switch stays hidden, and only shows up to offer a retry when /api/mode fails.
  document.getElementById("mode-switch").hidden = !S.modeRequestFailed;
  const panel = document.getElementById("internal-panel");
  if (panel) panel.hidden = !showsPanel();
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

function tasksCell(bot, index) {
  if (bot.status === "不监控" || bot.status === "no-folder") return '<span class="muted">—</span>';
  const tasks = bot.recent_tasks || [];
  if (!tasks.length) return `<span class="muted">${esc(t("internal.tasks.none"))}</span>`;
  const label = t("internal.tasks.open", { name: bot.name });
  return `<button type="button" class="link-btn tasks-btn" data-tasks="${index}" aria-haspopup="dialog" aria-label="${esc(label)}">${esc(t("internal.tasks.count", { n: tasks.length }))} <span aria-hidden="true">›</span></button>`;
}
// Recent tasks open in a small window: date, then what was asked.
function openTasks(index) {
  const bot = S.internal?.bots?.[index];
  const dialog = $("#tasks-dialog");
  if (!bot || !dialog) return;
  const meta = [bot.label, bot.group].filter(Boolean).join(" · ");
  const items = (bot.recent_tasks || []).map((task) => {
    const match = String(task).match(/^(\d{4}-\d{2}-\d{2})\s+(.*)$/);
    return match
      ? `<li><time>${esc(match[1])}</time><span>${esc(match[2])}</span></li>`
      : `<li><span>${esc(task)}</span></li>`;
  }).join("");
  $("#tasks-body").innerHTML = `<header class="tasks-head">
      <h3 id="tasks-title">${esc(bot.name)}</h3>
      <p class="muted">${meta ? `<span>${esc(meta)}</span>` : ""}<span class="st-badge ${esc(statusClass(bot.status))}">${esc(statusLabel(bot.status))}</span></p>
    </header>
    ${bot.duty ? `<p class="tasks-duty">${esc(bot.duty)}</p>` : ""}
    <h4>${esc(t("internal.tasks.title"))}</h4>
    <ol class="tasks-list">${items}</ol>`;
  if (!dialog.open) dialog.showModal();
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
  // Folder-less and unmonitored bots are exceptions: only show them when there are some.
  const chips = stats.filter(([key, value]) => value || !/nofolder|unmonitored/.test(key)).map(([key, value]) => (
    `<div class="internal-stat"><b class="num">${esc(value ?? 0)}</b><span>${esc(t(key))}</span></div>`
  )).join("");
  const english = S.lang === "en" && summary.text_en;
  const zhNote = S.lang === "en" && !english ? `<p class="muted">${esc(t("internal.summary.zh"))}</p>` : "";
  return `<article class="card internal-card">
    <h3>${esc(t("internal.summary"))}</h3>
    <div class="internal-stats">${chips}</div>
    <p class="internal-summary">${esc((english ? summary.text_en : summary.text) || "")}</p>
    ${zhNote}
    <p class="muted internal-privacy">${esc(t("internal.privacy"))}</p>
  </article>`;
}

function tableCard(data) {
  const head = ["name", "label", "group", "status", "last", "files", "tasks"]
    .map((key) => `<th>${esc(t(`internal.col.${key}`))}</th>`).join("");
  const rows = (data.bots || []).map((bot, index) => {
    const quiet = bot.status === "不监控";
    const last = quiet || !bot.last_activity ? "—" : String(bot.last_activity).replace("T", " ").slice(0, 16);
    const files = quiet ? "—" : String(bot.files_modified_7d ?? 0);
    const title = bot.duty ? ` title="${esc(bot.duty)}"` : "";
    return `<tr>
      <td class="name"${title}>${esc(bot.name)}</td>
      <td>${esc(bot.label || "—")}</td>
      <td>${esc(bot.group || "—")}</td>
      <td><span class="st-badge ${esc(statusClass(bot.status))}">${esc(statusLabel(bot.status))}</span></td>
      <td>${esc(last)}</td>
      <td class="num">${esc(files)}</td>
      <td>${tasksCell(bot, index)}</td>
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
  // The box writes this note in Chinese; English readers get the same fact in English.
  const note = S.lang === "en" ? t("internal.usage.none") : (usage.note || t("internal.usage.none"));
  const counts = usage.counts || [];
  const max = counts.reduce((peak, item) => Math.max(peak, item.messages_7d || 0), 0);
  const bars = counts.length
    ? counts.map((item) => {
      const sent = item.messages_7d || 0;
      const width = !sent || !max ? 0 : Math.max(2, Math.min(100, Math.round(100 * sent / max)));
      const meta = t("internal.bar", { sent, received: item.received_7d || 0 });
      return `<div class="bar-row">
        <div class="bar-name">${esc(item.name)}</div>
        <div class="bar-track" role="presentation"><div class="bar-fill" style="width:${width}%"></div></div>
        <div class="bar-val">${esc(meta)}</div>
      </div>`;
    }).join("")
    : `<p class="muted">${esc(t("internal.edges.none"))}</p>`;
  const label = S.lang === "en" ? t("internal.counts.hint") : (usage.counts_label || t("internal.counts.hint"));
  return `<article class="card internal-card">
    <h3>${esc(t("internal.usage"))}</h3>
    <div class="quota-banner"><span class="quota-mark" aria-hidden="true">!</span><strong>${esc(note)}</strong></div>
    <div class="counts" role="img" aria-label="${esc(label)}">
      <p class="muted counts-label">${esc(label)}</p>
      ${bars}
    </div>
  </article>`;
}

function hostRetryHtml() {
  return `<p class="muted">${esc(t("host.error"))} <button type="button" class="retry" id="host-retry">${esc(t("request.retry"))}</button></p>`;
}

function hostFactsCard(data) {
  const rows = [
    [t("host.uptime"), data.uptime && data.uptime.text],
    [t("host.load"), (data.load || []).join(" ")],
    [t("host.memory"), data.memory && data.memory.text],
    [t("host.disk"), data.disk && data.disk.text],
    [t("host.tailscale"), data.tailscale],
  ].map(([label, value]) => `<tr><td>${esc(label)}</td><td>${esc(value || "—")}</td></tr>`).join("");
  return `<article class="card internal-card host-status">
    <table class="internal-table host-table host-facts"><tbody>${rows}</tbody></table>
    ${hostServicesTable(data)}
    ${hostPeersTable(data)}
  </article>`;
}

function hostServicesTable(data) {
  const head = ["service", "port", "status"].map((key) => `<th>${esc(t(`host.col.${key}`))}</th>`).join("");
  const rows = (data.services || []).map((svc) => (
    `<tr><td>${esc(svc.name)}</td><td>${esc(svc.port)}</td><td>${esc(svc.up ? t("host.up") : t("host.down"))}</td></tr>`
  )).join("");
  return `<h3>${esc(t("host.services"))}</h3>
    <div class="table-scroll"><table class="internal-table host-table">
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody>
    </table></div>`;
}

function hostPeersTable(data) {
  const head = ["host", "os", "online"].map((key) => `<th>${esc(t(`host.col.${key}`))}</th>`).join("");
  const peers = data.peers || [];
  const rows = peers.length
    ? peers.map((peer) => (
      `<tr><td>${esc(peer.host)}</td><td>${esc(peer.os)}</td><td>${esc(peer.online ? t("host.online") : t("host.offline"))}</td></tr>`
    )).join("")
    : `<tr><td colspan="3">${esc(t("host.nopeers"))}</td></tr>`;
  return `<h3>${esc(t("host.devices"))}</h3>
    <div class="table-scroll"><table class="internal-table host-table">
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody>
    </table></div>`;
}

function renderHostStatus() {
  const root = $("#host-status");
  const stamp = $("#host-stamp");
  if (!root) return;
  if (S.dataMode !== "internal") {
    if (stamp) stamp.textContent = "";
    return;
  }
  if (S.hostRequestFailed) {
    if (stamp) stamp.textContent = "";
    root.innerHTML = hostRetryHtml();
    return;
  }
  if (!S.hostStatus) {
    if (stamp) stamp.textContent = "";
    root.innerHTML = `<p class="muted">${esc(t("loading"))}</p>`;
    return;
  }
  if (stamp) stamp.textContent = `${S.hostStatus.generated_at} · ${t("host.refresh")}`;
  root.innerHTML = hostFactsCard(S.hostStatus);
}

let hostGen = 0;
async function refreshHostStatus() {
  const gen = ++hostGen;
  if (S.dataMode !== "internal") {
    renderHostStatus();
    return;
  }
  if (!S.hostStatus) renderHostStatus();
  const result = await fetchJson("api/host-status");
  if (gen !== hostGen || S.dataMode !== "internal") return;
  if (result.failed) {
    S.hostRequestFailed = true;
  } else {
    S.hostStatus = result.data;
    S.hostRequestFailed = false;
  }
  renderHostStatus();
}

function sbNa() {
  return t("board.na");
}
function sbAgo(iso) {
  const at = Date.parse(iso || "");
  if (!Number.isFinite(at)) return t("board.ago.now");
  const minutes = Math.max(0, Math.round((Date.now() - at) / 60000));
  if (minutes < 1) return t("board.ago.now");
  return t("board.ago.min", { n: minutes });
}
function sbClock(iso) {
  const match = String(iso || "").match(/T(\d{2}:\d{2})/);
  return match ? match[1] : "";
}
function sbLastActive(iso) {
  if (!iso) return sbNa();
  const match = String(iso).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (!match) return "—";
  const today = String((S.statusBoard && S.statusBoard.generated_at) || "").slice(0, 10);
  if (match[1] === today) return t("board.last.today", { time: match[2] });
  return t("board.last.at", { date: match[1].slice(5), time: match[2] });
}
function sbCompare(pct, periodKey) {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct))) return "";
  const period = t(periodKey);
  const n = Number(pct);
  if (n === 0) return t("board.compare.flat", { period });
  if (n > 0) return t("board.compare.up", { period, pct: Math.abs(n) });
  return t("board.compare.down", { period, pct: String(n) });
}
function sbCompareLine(kpi) {
  if (!kpi || !kpi.available) return sbNa();
  const compare = kpi.compare || {};
  const primary = sbCompare(compare.yesterday_pct, "board.period.day")
    || sbCompare(compare.week_pct, "board.period.week");
  return primary || sbNa();
}
function sbCompareHtml(kpi) {
  const text = sbCompareLine(kpi);
  const match = String(text).match(/^(.*?)([+\-]?\d+(?:\.\d+)?%)$/);
  if (!match) return esc(text);
  return `${esc(match[1])}<span class="num">${esc(match[2])}</span>`;
}
function sbValueHtml(kpi) {
  if (!kpi || !kpi.available || kpi.value === null || kpi.value === undefined) {
    return `<span class="num">${esc(sbNa())}</span>`;
  }
  if (kpi.id === "bots") {
    return `<span class="num">${esc(kpi.value)}/${esc(kpi.total ?? "—")}</span><span class="sb-unit">${esc(t("board.kpi.bots.unit"))}</span>`;
  }
  if (kpi.id === "host") {
    return `<span class="num">${esc(kpi.value)}</span>`;
  }
  return `<span class="num">${esc(kpi.value)}</span><span class="sb-unit">${esc(t(`board.kpi.${kpi.id}.unit`))}</span>`;
}
function sbDetail(kpi) {
  if (!kpi) return "";
  const meta = kpi.meta || {};
  const week = kpi.available ? sbCompare((kpi.compare || {}).week_pct, "board.period.week") : "";
  const extra = [];
  if (kpi.id === "bots" && kpi.available) extra.push(t("board.kpi.bots.detail", { active: meta.active ?? kpi.value, total: kpi.total ?? 0 }));
  if (kpi.id === "messages" && kpi.available) {
    const n = meta.messages_1h;
    if (n !== null && n !== undefined) extra.push(t("board.kpi.messages.detail", { n }));
  }
  if (kpi.id === "handoffs" && kpi.available) extra.push(t("board.kpi.handoffs.detail"));
  if (kpi.id === "reply" && kpi.available) extra.push(t("board.kpi.reply.detail", { n: meta.samples ?? 0 }));
  if (kpi.id === "host" && kpi.available) {
    const load = (meta.load || []).join(" ") || "—";
    extra.push(t("board.kpi.host.detail", { load, memory: meta.memory_text || "—" }));
  }
  if (kpi.id === "fail") extra.push(t("board.kpi.fail.detail"));
  if (week && sbCompare((kpi.compare || {}).yesterday_pct, "board.period.day")) extra.unshift(week);
  return extra.filter(Boolean).join(" · ");
}
function sbPill(kpi) {
  const status = !kpi || !kpi.available ? "none" : (kpi.status === "watch" ? "watch" : "ok");
  const label = status === "none" ? t("board.na") : t(status === "watch" ? "board.status.watch" : "board.status.ok");
  return `<span class="sb-pill ${status}">${esc(label)}</span>`;
}
function sbKpiCard(kpi) {
  const id = kpi && kpi.id ? kpi.id : "";
  return `<article class="sb-card" data-kpi="${esc(id)}">
    <div class="sb-card-top">
      <div class="sb-card-title">${esc(t(`board.kpi.${id}`))}
        <button type="button" class="sb-help" title="${esc(t(`board.kpi.${id}.hint`))}" aria-label="${esc(t(`board.kpi.${id}.hint`))}">?</button>
      </div>
      ${sbPill(kpi)}
    </div>
    <div class="sb-value">${sbValueHtml(kpi)}</div>
    <p class="sb-compare">${sbCompareHtml(kpi)}</p>
    <p class="sb-detail">${esc(sbDetail(kpi))}</p>
  </article>`;
}
function sbHourCells(values, fadeIndex) {
  const max = Math.max(1, ...(values || []).map((n) => Number(n) || 0));
  return (values || []).map((raw, index) => {
    const n = Number(raw) || 0;
    const on = n > 0;
    const fade = fadeIndex === index;
    const opacity = on ? Math.max(0.35, n / max) : "";
    const klass = `sb-cell${on ? " on" : ""}${fade ? " partial" : ""}`;
    const style = on ? ` style="opacity:${fade ? (Number(opacity) * 0.55).toFixed(2) : opacity}"` : "";
    const extra = fade && !on ? " style=\"opacity:.45\"" : style;
    return `<span class="${klass}"${extra} title="${esc(String(n))}"></span>`;
  }).join("");
}
function sbNiceMax(max) {
  if (max <= 1) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const n = Math.ceil(max / pow);
  const step = n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}
function sbChart(values, avg, labels, liveIndex) {
  const series = (values || []).map((n) => Number(n) || 0);
  const mean = (avg || []).map((n) => (n === null || n === undefined ? null : Number(n)));
  if (!series.length) return `<p class="muted">${esc(sbNa())}</p>`;
  const w = 640, h = 260, padL = 40, padR = 18, padT = 16, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const peak = sbNiceMax(Math.max(1, ...series, ...mean.map((n) => n || 0)));
  const xAt = (i) => padL + (series.length === 1 ? innerW / 2 : i * innerW / (series.length - 1));
  const yAt = (v) => padT + innerH * (1 - v / peak);
  const line = series.map((v, i) => `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
  const avgPts = mean.map((v, i) => (v === null || Number.isNaN(v) ? null : `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`));
  const avgLine = avgPts.filter(Boolean).length === mean.length ? avgPts.join(" ") : "";
  const yTicks = [0, peak / 2, peak].map((v) => {
    const y = yAt(v);
    return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="currentColor" opacity=".08"/>
      <text x="${padL - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="currentColor" opacity=".55">${esc(String(v % 1 ? v.toFixed(1) : v))}</text>`;
  }).join("");
  const xTicks = series.map((_, i) => {
    if (i % 3 !== 0 && i !== series.length - 1) return "";
    return `<text x="${xAt(i).toFixed(1)}" y="${h - 12}" text-anchor="middle" font-size="11" fill="currentColor" opacity=".55">${esc((labels && labels[i]) || "")}</text>`;
  }).join("");
  const live = liveIndex >= 0 && liveIndex < series.length
    ? `<circle cx="${xAt(liveIndex).toFixed(1)}" cy="${yAt(series[liveIndex]).toFixed(1)}" r="5" fill="none" stroke="#2f7fd8" stroke-width="2"/>`
    : "";
  return `<svg class="sb-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(t("board.chart.title"))}">
    ${yTicks}
    ${avgLine ? `<polyline fill="none" stroke="currentColor" stroke-opacity=".45" stroke-width="1.6" stroke-dasharray="5 5" points="${avgLine}"/>` : ""}
    <polyline fill="none" stroke="#2f7fd8" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" points="${line}"/>
    ${live}
    ${xTicks}
  </svg>
  <div class="sb-chart-legend">
    <span><i></i>${esc(t("board.chart.series"))}</span>
    <span><i class="avg"></i>${esc(t(S.boardWindow === "7d" ? "board.chart.avg7" : "board.chart.avg"))}</span>
    ${liveIndex >= 0 ? `<span class="sb-live">${esc(t("board.chart.live"))}</span>` : ""}
  </div>`;
}
function sbCurrentHour(data) {
  const label = ((data.messages && data.messages.hour_labels_24) || []).slice(-1)[0];
  const hour = Number(label);
  return Number.isFinite(hour) ? hour : 23;
}
function sbBotsTable(data) {
  const win7 = S.boardWindow === "7d";
  const hoursKey = win7 ? "hours_7d" : "hours_24";
  const fadeIndex = win7 ? sbCurrentHour(data) : 23;
  const head = `<tr>
    <th>${esc(t("board.col.bot"))}</th>
    <th>${esc(t("board.col.group"))}</th>
    <th>${esc(t("board.col.last"))}</th>
    <th>${esc(t(win7 ? "board.col.hours7" : "board.col.hours"))}</th>
  </tr>`;
  const rows = (data.bots || []).map((bot) => {
    const note = bot.unmonitored ? ` title="${esc(t("board.unmonitored"))}"` : "";
    const cells = bot[hoursKey] || [];
    const fade = win7 ? fadeIndex : cells.length - 1;
    return `<tr>
      <td class="name"${note}>${esc(bot.name)}</td>
      <td>${esc(bot.group || "—")}</td>
      <td>${esc(sbLastActive(bot.last_active))}</td>
      <td><div class="sb-hours" aria-hidden="true">${sbHourCells(cells, fade)}</div></td>
    </tr>`;
  }).join("");
  return `<article class="card sb-section">
    <div class="sb-section-head"><h3>${esc(t("board.bots.title"))}</h3></div>
    <p class="sb-legend">${esc(t("board.bots.note"))}</p>
    <div class="table-scroll"><table class="sb-table">
      <thead>${head}</thead><tbody>${rows}</tbody>
    </table></div>
  </article>`;
}
function sbChartCard(data) {
  const series = data.messages || {};
  const win7 = S.boardWindow === "7d";
  let values = null, avg = null, labels = [];
  if (series.available) {
    if (win7) {
      values = series.hours_7d;
      avg = series.hours_7d_prev_avg;
      labels = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
    } else {
      values = series.hours_24;
      avg = series.hours_24_avg7;
      labels = series.hour_labels_24 || [];
    }
  }
  const liveIndex = series.available ? (win7 ? sbCurrentHour(data) : (values || []).length - 1) : -1;
  const body = series.available
    ? sbChart(values, avg, labels, liveIndex)
    : `<p class="muted">${esc(sbNa())}</p>`;
  return `<article class="card sb-section sb-chart-wrap">
    <div class="sb-section-head">
      <h3>${esc(t("board.chart.title"))} <button type="button" class="sb-help" title="${esc(t("board.chart.hint"))}" aria-label="${esc(t("board.chart.hint"))}">?</button></h3>
    </div>
    ${body}
  </article>`;
}
function sbServices(data) {
  const rows = (data.services || []).map((svc) => {
    const up = !!svc.up;
    const latency = svc.latency_ms === null || svc.latency_ms === undefined ? sbNa() : t("board.svc.ms", { n: svc.latency_ms });
    return `<tr>
      <td>${esc(svc.name)}</td>
      <td class="num">${esc(svc.port)}</td>
      <td>${esc(up ? t("board.svc.up") : t("board.svc.down"))}</td>
      <td>${esc(up ? latency : sbNa())}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="4" class="muted">${esc(sbNa())}</td></tr>`;
  return `<article class="card sb-section">
    <div class="sb-section-head">
      <h3>${esc(t("board.svc.title"))} <button type="button" class="sb-help" title="${esc(t("board.svc.note"))}" aria-label="${esc(t("board.svc.note"))}">?</button></h3>
      ${sbPill({ available: (data.services || []).length > 0, status: (data.services || []).some((s) => s.up) ? "ok" : "watch" })}
    </div>
    <div class="table-scroll"><table class="sb-table">
      <thead><tr>
        <th>${esc(t("board.svc.name"))}</th><th>${esc(t("board.svc.port"))}</th>
        <th>${esc(t("board.svc.reach"))}</th><th>${esc(t("board.svc.latency"))}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </article>`;
}
function sbBanner(data) {
  const ok = !!(data.overall && data.overall.ok);
  const time = sbClock(data.generated_at) || "—";
  return `<div class="sb-banner${ok ? "" : " warn"}">
    <div class="sb-banner-left"><span class="sb-dot" aria-hidden="true"></span><h2 id="status-board-title">${esc(t(ok ? "board.ok" : "board.alert"))}</h2></div>
    <div class="sb-banner-right">
      <b>${esc(t("board.updated", { time, ago: sbAgo(data.generated_at) }))}</b>
      <span>${esc(t("board.refresh", { n: data.refresh_seconds || 30 }))}</span>
    </div>
  </div>`;
}

function renderStatusBoard() {
  const root = $("#status-board");
  if (!root) return;
  if (S.dataMode !== "internal") {
    root.hidden = true;
    root.innerHTML = "";
    return;
  }
  root.hidden = false;
  if (S.statusBoardFailed && !S.statusBoard) {
    root.innerHTML = `<p class="muted">${esc(t("board.error"))} <button type="button" class="retry" id="board-retry">${esc(t("request.retry"))}</button></p>`;
    return;
  }
  if (!S.statusBoard) {
    root.innerHTML = `<p class="muted">${esc(t("loading"))}</p>`;
    return;
  }
  const data = S.statusBoard;
  const win = S.boardWindow === "7d" ? "7d" : "24h";
  const kpis = (data.kpis || []).map(sbKpiCard).join("");
  root.innerHTML = `${sbBanner(data)}
    <div class="sb-kpis">${kpis}</div>
    <div class="sb-section-head">
      <h3>${esc(t("board.details"))}</h3>
      <div class="segmented" role="group">
        <button type="button" data-board-window="24h" aria-pressed="${String(win === "24h")}">${esc(t("board.win.24h"))}</button>
        <button type="button" data-board-window="7d" aria-pressed="${String(win === "7d")}">${esc(t("board.win.7d"))}</button>
      </div>
    </div>
    <p class="sb-legend">${esc(t(win === "7d" ? "board.legend.7d" : "board.legend"))}</p>
    ${sbBotsTable(data)}
    <div class="sb-split">${sbChartCard(data)}${sbServices(data)}</div>`;
}

let boardGen = 0;
async function refreshStatusBoard() {
  const gen = ++boardGen;
  if (S.dataMode !== "internal") {
    renderStatusBoard();
    return;
  }
  if (!S.statusBoard) renderStatusBoard();
  const result = await fetchJson("api/status-board");
  if (gen !== boardGen || S.dataMode !== "internal") return;
  if (result.unavailable) {
    S.statusBoardFailed = false;
    S.statusBoard = null;
    renderStatusBoard();
    return;
  }
  if (result.failed) {
    S.statusBoardFailed = true;
  } else {
    S.statusBoard = result.data;
    S.statusBoardFailed = false;
  }
  renderStatusBoard();
}

function renderInternal() {
  const panel = $("#internal-panel");
  if (!panel) return;
  panel.hidden = !showsPanel();
  renderStatusBoard();
  renderHostStatus();
  if (!showsPanel()) return;
  $("#internal-title").textContent = t(STATIC ? "internal.titleDemo" : "internal.title");
  const intro = $("#internal-intro");
  if (intro) intro.hidden = !STATIC;
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
  body.innerHTML = summaryCard(S.internal) + tableCard(S.internal)
    + `<div class="internal-split">${edgesCard(S.internal)}${usageCard(S.internal)}</div>`;
}

async function refreshInternal() {
  const gen = ++internalGen;
  if (STATIC) {
    const result = await fetchJson("api/internal");
    if (result.ok) S.internal = result.data;
    S.internalRequestFailed = !result.ok && !S.internal;
    renderInternal();
    return;
  }
  if (S.dataMode !== "internal") {
    renderInternal();
    return;
  }
  refreshHostStatus();
  refreshStatusBoard();
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
  const tasks = event.target.closest("[data-tasks]");
  if (tasks) openTasks(Number(tasks.dataset.tasks));
  if (event.target.closest("#host-retry")) refreshHostStatus();
  if (event.target.closest("#board-retry")) refreshStatusBoard();
  const tog = event.target.closest("[data-board-window]");
  if (tog && (tog.dataset.boardWindow === "24h" || tog.dataset.boardWindow === "7d")) {
    S.boardWindow = tog.dataset.boardWindow;
    renderStatusBoard();
  }
});
$("#tasks-close")?.addEventListener("click", () => $("#tasks-dialog").close());
$("#tasks-dialog")?.addEventListener("click", (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });

bindModeSwitch();
