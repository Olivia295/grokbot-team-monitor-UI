// Dashboard: data polling and wiring.

// One place decides the status pill and banner for every source: online demo, demo team,
// Grok Bot box (internal mode), event log or the Grok Bot app cache.
function paintSource() {
  const pill = $("#connection");
  const banner = $("#banner");
  const source = S.office.source || {};
  const privacy = S.office.privacy ? `${esc(t("banner.privacy"))} <a href="settings.html">${t("banner.settings")}</a>` : "";
  let status = S.office.appOnline ? "ok" : "offline";
  let label = S.office.appOnline ? t("pill.online") : t("pill.offline");
  let note = privacy;
  if (STATIC) {
    [status, label] = ["demo", t("pill.static")];
    note = `${esc(t("banner.static"))} <a href="${esc(STATIC.repo)}" target="_blank" rel="noopener">${t("banner.repo")}</a>`;
  } else if (source.demo) {
    [status, label] = ["demo", t("pill.demo")];
    note = `${esc(t(S.settings.dataSource === "demo" ? "banner.demo" : "banner.demoAuto"))} <a href="settings.html#data">${t("banner.settings")}</a>`;
  } else if (source.box) {
    [status, label] = ["ok", t("pill.box")];
    if (source.empty) note = esc(t("box.empty"));
  } else if (source.kind === "events") {
    label = S.office.appOnline ? t("pill.events") : t("pill.eventsQuiet");
  }
  pill.dataset.status = status;
  pill.textContent = label;
  banner.hidden = !note;
  banner.innerHTML = note;
}
async function refreshOffice() {
  try {
    S.office = await getJson(withBox(`api/office?lang=${S.lang}`));
    paintSource();
    renderStage();
    renderHero();
    renderRoster();
    renderAttention();
    $("#freshness").textContent = t("foot.updated", { time: clock(Date.now()) });
  } catch {
    $("#connection").dataset.status = "error";
    $("#connection").textContent = t("pill.error");
  }
}
async function refreshFlows() {
  try {
    const hours = S.hours;
    const data = await getJson(withBox(`api/flows?hours=${hours}&lang=${S.lang}`));
    if (hours !== S.hours) return;
    const fresh = newSteps(data);
    S.flows = data;
    if (S.office) renderStage();
    renderHero();
    renderFlowList();
    renderPairs();
    renderAttention();
    renderBottleneck();
    renderTV();
    for (const { step } of fresh) showToast(step);
    if (fresh.length) queueLive(fresh.map((item) => item.step), fresh[0].flow);
  } catch {
    // The office poll reports connection trouble.
  }
}
async function refreshInsights() {
  try {
    const first = !S.insights;
    S.insights = await getJson(withBox(`api/insights?lang=${S.lang}`));
    renderHero();
    renderAwards();
    renderFeed();
    renderRoster();
    renderDigest();
    renderRhythm();
    renderAutomations();
    renderTV();
    if (first) rotateHeadline();
  } catch {
    // Same as above.
  }
}
let alertsSince = 0;
async function refreshAlerts() {
  try {
    S.alerts = await getJson("api/alerts");
    const fresh = S.alerts.alerts.filter((alert) => alert.at > alertsSince);
    if (alertsSince) fresh.slice(0, 3).reverse().forEach(showAlertToast);
    alertsSince = Math.max(alertsSince || Date.now() - 1000, ...S.alerts.alerts.map((alert) => alert.at));
    renderBell();
  } catch {
    // An older server without /api/alerts: leave the bell quiet.
  }
}
function renderAll() {
  renderStage();
  renderHero();
  renderAwards();
  renderFlowList();
  renderPairs();
  renderFeed();
  renderRoster();
  renderAttention();
  renderDigest();
  renderRhythm();
  renderAutomations();
  renderBottleneck();
  renderBell();
  renderTV();
  if (typeof renderInternal === "function") renderInternal();
  if (S.replay) {
    showFlowDetail(S.replay.flow);
    paintReplay();
  } else idleNarration();
}

// Handoffs that appear after the page opened become toasts and play live on the stage.
const seenSteps = new Set();
let seeded = false;
let staticLoop = -1;
function resetLive() {
  seenSteps.clear();
  seeded = false;
}
function newSteps(data) {
  const fresh = [];
  // The online demo loops its recording; start over quietly when it wraps around.
  if (STATIC && staticClock().loopIndex !== staticLoop) {
    staticLoop = staticClock().loopIndex;
    seenSteps.clear();
    seeded = false;
  }
  for (const flow of data.flows) {
    for (const step of flow.steps) {
      const key = `${step.from}|${step.to}|${step.at}|${step.kind}`;
      if (seenSteps.has(key)) continue;
      seenSteps.add(key);
      if (seeded && Date.now() - step.at < 10 * 60e3) fresh.push({ step, flow });
    }
  }
  seeded = true;
  return fresh.sort((a, b) => a.step.at - b.step.at).slice(-6);
}

// ---------------------------------------------------------------- events

function pressHours(hours) {
  S.hours = hours;
  $$("[data-hours]").forEach((other) => other.setAttribute("aria-pressed", String(Number(other.dataset.hours) === hours)));
}
$$("[data-hours]").forEach((button) => button.addEventListener("click", () => {
  pressHours(Number(button.dataset.hours));
  refreshFlows();
}));
$$("[data-view]").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
$$("[data-side]").forEach((tab) => tab.addEventListener("click", () => {
  S.side = tab.dataset.side;
  $$("[data-side]").forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
  $("#flows-pane").hidden = S.side !== "flows";
  $("#pairs-pane").hidden = S.side !== "pairs";
  $("#feed").hidden = S.side !== "feed";
}));
$$("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  S.filter = button.dataset.filter;
  $$("[data-filter]").forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
  renderFlowList();
}));
$$("[data-digest]").forEach((button) => button.addEventListener("click", () => {
  digestDay = Number(button.dataset.digest);
  renderDigest();
}));
$("#digest-copy").addEventListener("click", async (event) => {
  if (!S.insights) return;
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(digestMarkdown());
    button.textContent = t("digest.copied");
  } catch {
    button.textContent = t("digest.copyFailed");
  }
  setTimeout(() => (button.textContent = t("digest.copy")), 1800);
});
// Search & filters
let searchTimer;
$("#flow-q").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    S.query = event.target.value;
    renderFlowList();
  }, 120);
});
$("#flow-bot").addEventListener("change", (event) => {
  S.botFilter = event.target.value;
  renderFlowList();
});
function clearSearch() {
  S.query = "";
  S.botFilter = "";
  S.pairFilter = "";
  $("#flow-q").value = "";
  renderFlowList();
}
function showFlowsPane() {
  if (S.replay) stopReplay();
  $('[data-side="flows"]').click();
}
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-clear-search]")) clearSearch();
  const pair = event.target.closest("[data-pair-filter]");
  if (pair) {
    S.pairFilter = pair.dataset.pairFilter;
    showFlowsPane();
    renderFlowList();
    $(".side").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  }
});

// Alerts bell
$("#bell").addEventListener("click", (event) => {
  event.stopPropagation();
  const panel = $("#bell-panel");
  panel.hidden = !panel.hidden;
  $("#bell").setAttribute("aria-expanded", String(!panel.hidden));
  renderBell();
  if (!panel.hidden) {
    try { localStorage.setItem(SEEN_KEY, String(Date.now())); } catch { /* ignore */ }
    setTimeout(() => ($("#bell-dot").hidden = true), 600);
  }
});
document.addEventListener("click", (event) => {
  const panel = $("#bell-panel");
  if (!panel.hidden && !event.target.closest(".bell-wrap")) {
    panel.hidden = true;
    $("#bell").setAttribute("aria-expanded", "false");
  }
});

// Export & share
$("#week-md").addEventListener("click", exportWeekMarkdown);
$("#week-png").addEventListener("click", exportWeekPNG);
$("#replay-gif").addEventListener("click", () => S.replay && exportRelayGIF(S.replay.flow));
$("#replay-link").addEventListener("click", async (event) => {
  if (!S.replay) return;
  const button = event.currentTarget;
  const url = `${location.origin}${location.pathname}#flow=${S.replay.flow.id}`;
  try {
    await navigator.clipboard.writeText(url);
    showToastText(t("replay.linkCopied"));
  } catch {
    showToastText(url);
  }
  button.blur();
});
$("#export-close").addEventListener("click", () => $("#export-dialog").close());
$("#export-dialog").addEventListener("click", (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });

// Deep links: #flow=<id> opens that relay's replay.
async function openFlowFromHash() {
  const match = location.hash.match(/^#flow=([\w-]+)$/);
  if (!match || !S.flows) return;
  let flow = S.flows.flows.find((item) => item.id === match[1]);
  for (const hours of [168, 720]) {
    if (flow || S.hours >= hours) break;
    pressHours(hours);
    await refreshFlows();
    flow = S.flows.flows.find((item) => item.id === match[1]);
  }
  if (flow) {
    startReplay(flow);
    $(".stage").scrollIntoView({ block: "start" });
  } else {
    showToastText(t("replay.notFound"));
  }
}
addEventListener("hashchange", openFlowFromHash);

$("#ambient").addEventListener("change", (event) => {
  S.ambient = event.target.checked;
  if (!S.ambient) stopAmbient();
  else idleNarration();
});
$("#flow-list").addEventListener("click", (event) => {
  if (event.target.closest("[data-widen]")) {
    $(`[data-hours="${S.hours < 168 ? 168 : 720}"]`).click();
    return;
  }
  const card = event.target.closest("[data-flow]");
  const flow = card && S.flows.flows.find((item) => item.id === card.dataset.flow);
  if (flow) startReplay(flow);
});
document.addEventListener("click", (event) => {
  const profile = event.target.closest("[data-profile]");
  if (profile) openProfile(profile.dataset.profile);
  const replay = event.target.closest("[data-replay]");
  if (replay) {
    const flow = S.flows.flows.find((item) => item.id === replay.dataset.replay);
    if ($("#profile").open) $("#profile").close();
    if (flow) {
      startReplay(flow);
      $(".stage").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
    }
  }
});
$("#pairs-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-pair-replay]");
  const flow = button && S.flows.flows.find((item) => item.id === button.dataset.pairReplay);
  if (flow) startReplay(flow, Number(button.dataset.step));
});
$("#flow-detail").addEventListener("click", (event) => {
  const row = event.target.closest("[data-step]");
  if (row && S.replay && !event.target.closest("[data-profile]")) {
    S.replay.playing = false;
    goToStep(Number(row.dataset.step));
  }
});
$("#scrubber").addEventListener("click", (event) => {
  const button = event.target.closest("[data-step]");
  if (button && S.replay) {
    S.replay.playing = false;
    goToStep(Number(button.dataset.step));
  }
});
$("#detail-back").addEventListener("click", stopReplay);
$("#replay-exit").addEventListener("click", stopReplay);
$("#replay-prev").addEventListener("click", () => { S.replay.playing = false; goToStep(S.replay.index - 1); });
$("#replay-next").addEventListener("click", () => { S.replay.playing = false; goToStep(S.replay.index + 1); });
$("#replay-play").addEventListener("click", () => {
  const replay = S.replay;
  if (!replay.playing && replay.index === replay.steps.length - 1 && !beat) {
    replay.playing = true;
    goToStep(0, "start");
    return;
  }
  replay.playing = !replay.playing;
  paintReplay();
});
$("#replay-speed").addEventListener("click", () => {
  S.replay.speed = S.replay.speed === 1 ? 2 : S.replay.speed === 2 ? 4 : 1;
  paintReplay();
});
$("#profile-close").addEventListener("click", () => $("#profile").close());
$("#profile").addEventListener("click", (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });
// Closing the drawer hands focus back to whatever opened it; never let that re-open a tooltip.
$("#profile").addEventListener("close", hideTip);
document.addEventListener("keydown", (event) => {
  if (!S.replay || $("#profile").open || event.target.closest("input,textarea,select")) return;
  if (event.key === "Escape") stopReplay();
  else if (event.key === "ArrowRight") $("#replay-next").click();
  else if (event.key === "ArrowLeft") $("#replay-prev").click();
  else if (event.key === " " && !event.target.closest("button")) { event.preventDefault(); $("#replay-play").click(); }
});
$("#theme").addEventListener("click", async () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  try { await saveSettings({ theme: dark ? "light" : "dark" }); } catch { applySettings(); }
});
$("#lang").addEventListener("click", async () => {
  try { await saveSettings({ language: S.lang === "zh" ? "en" : "zh" }); } catch { /* keep current */ }
  studioSig = "";
  starsSig = "";
  refreshOffice().then(() => Promise.all([refreshFlows(), refreshInsights()])).then(renderAll);
});
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (S.view === "track") renderTrack();
    renderBottleneck();
  }, 150);
});

(async function boot() {
  ensureAvatarDefs();
  $("#brand-logo").innerHTML = logoSVG(40);
  paintIcons();
  await loadSettings();
  pressHours(S.settings.hours);
  $("#ambient").checked = S.ambient;
  idleNarration();
  requestAnimationFrame(frame);
  if (STATIC) {
    document.body.classList.add("static-demo");
    $("#tv-link").href = "?tv=1";
  }
  if (typeof initDataMode === "function") await initDataMode();
  await refreshOffice();
  const jobs = [refreshFlows(), refreshInsights(), refreshAlerts()];
  if (S.dataMode === "internal" && typeof refreshInternal === "function") jobs.push(refreshInternal());
  await Promise.all(jobs);
  initTV();
  renderTV();
  openFlowFromHash();
  const every = Math.max(2, S.settings.refreshSeconds) * 1000;
  setInterval(refreshOffice, every);
  setInterval(refreshFlows, Math.max(every * 2, 8000));
  setInterval(refreshInsights, 15000);
  setInterval(refreshAlerts, Math.max(every, 5000));
  setInterval(() => { if (S.dataMode === "internal") refreshInternal(); }, 20000);
  setInterval(rotateHeadline, 6000);
})();
