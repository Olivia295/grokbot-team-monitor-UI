// Shared state and helpers for every view and page.
const S = {
  settings: null,
  lang: "zh",
  office: null,
  flows: null,
  insights: null,
  hours: 24,
  filter: "all",
  view: "studio",
  side: "flows",
  hover: null,
  replay: null,
  ambient: true,
  dataMode: "external",
  modeInfo: null,
  modeRequestFailed: false,
  internal: null,
  internalError: false,
  internalRequestFailed: false,
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const SECTION_VARS = ["--c0", "--c1", "--c2", "--c3", "--c4"];
let REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
function cut(text, n) {
  const value = String(text || "");
  return value.length > n ? `${value.slice(0, n - 1)}…` : value;
}

// ---------------------------------------------------------------- settings

const DEFAULT_SETTINGS = {
  language: "auto", theme: "auto", hours: 24, ambient: true, motion: "full", privacy: false, refreshSeconds: 3,
  dataSource: "auto", supportDir: "", eventsPath: "", tvSeconds: 20, rooms: {}, bots: {},
  alerts: { enabled: false, desktop: true, error: true, awaiting: true, stuck: true, done: false, stuckMinutes: 10, cooldownMinutes: 15, quiet: false, quietFrom: 23, quietTo: 8, webhooks: [] },
};
async function getJson(url) {
  if (STATIC) return staticJson(url);
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
async function postJson(url, body) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
// Distinguishes "not on this box" (403 + internal_available false) from a broken request.
async function fetchJson(url) {
  if (STATIC) {
    try { return { ok: true, data: await staticJson(url) }; } catch { return { ok: false, failed: true }; }
  }
  let response;
  try {
    response = await fetch(url, { cache: "no-store" });
  } catch {
    return { ok: false, failed: true };
  }
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (response.status === 403 && data && data.internal_available === false) {
    return { ok: false, unavailable: true, data };
  }
  if (!response.ok) return { ok: false, failed: true, status: response.status, data };
  return { ok: true, data };
}
// Ask for exactly what the read-mode switch shows (the server falls back to the saved setting).
function withBox(url) {
  if (!S.modeInfo?.internal_available) return url;
  return url + (url.includes("?") ? "&" : "?") + `box=${S.dataMode === "internal" ? 1 : 0}`;
}
async function loadSettings() {
  try {
    S.settings = { ...structuredClone(DEFAULT_SETTINGS), ...(await getJson("api/settings")) };
  } catch {
    S.settings = structuredClone(DEFAULT_SETTINGS);
  }
  applySettings();
  return S.settings;
}
async function saveSettings(patch) {
  const next = { ...S.settings, ...patch };
  if (STATIC) {
    S.settings = next;
    try { localStorage.setItem(STATIC_KEY, JSON.stringify(next)); } catch { /* private window: keep it for this visit */ }
  } else {
    S.settings = await postJson("api/settings", next);
  }
  applySettings();
  return S.settings;
}

// ---------------------------------------------------------------- static site (GitHub Pages demo)
// The online demo has no server: scripts/build_pages.py bakes the demo team into JSON frames,
// 30 seconds apart. The page plays them in a loop and moves every timestamp up to the present,
// and applies settings (aliases, looks, rooms, privacy) here instead of on the server.

const STATIC = window.BOT_OFFICE_STATIC || null;
const STATIC_KEY = "bot-office.settings";
const staticFiles = new Map();
async function staticFile(path) {
  if (!staticFiles.has(path)) {
    staticFiles.set(path, fetch(`${STATIC.base}${path}`).then((response) => {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }));
    if (staticFiles.size > 40) staticFiles.delete(staticFiles.keys().next().value);
  }
  return structuredClone(await staticFiles.get(path));
}
function staticClock() {
  const elapsed = Math.max(0, Date.now() - STATIC.t0);
  const loop = STATIC.step * STATIC.frames;
  const loopIndex = Math.floor(elapsed / loop);
  return { loopIndex, shift: loopIndex * loop, frame: Math.min(STATIC.frames - 1, Math.floor((elapsed % loop) / STATIC.step)) };
}
function shiftTimes(value, shift, lo, hi) {
  if (Array.isArray(value)) return value.map((item) => shiftTimes(item, shift, lo, hi));
  if (value && typeof value === "object") {
    for (const key of Object.keys(value)) value[key] = shiftTimes(value[key], shift, lo, hi);
    return value;
  }
  return typeof value === "number" && value >= lo && value <= hi ? value + shift : value;
}
async function staticJson(url) {
  const [path, query = ""] = url.replace(/^\//, "").split("?");
  if (path === "api/settings") {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(STATIC_KEY) || "{}"); } catch { /* ignore */ }
    return { ...structuredClone(DEFAULT_SETTINGS), dataSource: "demo", ...saved };
  }
  if (path === "api/mode") return { internal_available: false, reason: "online demo", mode: "external", setting: "auto" };
  const lang = S.lang === "en" ? "en" : "zh";
  const { shift, frame } = staticClock();
  const loop = STATIC.step * STATIC.frames;
  if (path === "api/alerts") {
    // What the real alert rules found in the recording, this loop and the one before, up to now.
    const recorded = await staticFile(`${lang}/alerts.json`);
    const seen = [shift, shift - loop].flatMap((by) => recorded.map((alert) => ({ ...alert, id: `${alert.id}+${by}`, at: alert.at + by })));
    return { enabled: true, demo: true, alerts: seen.filter((alert) => alert.at <= Date.now()).sort((a, b) => b.at - a.at) };
  }
  if (path === "api/internal") return staticInternal(await staticFile(`${lang}/internal.json`), shift);
  let data;
  if (path === "api/office" || (path === "api/flows" && (new URLSearchParams(query).get("hours") || "24") === "24")) {
    const both = await staticFile(`${lang}/frame-${String(frame).padStart(3, "0")}.json`);
    data = path === "api/office" ? both.office : both.flows;
  } else if (path === "api/flows") {
    data = await staticFile(`${lang}/flows-${new URLSearchParams(query).get("hours") === "720" ? 720 : 168}.json`);
  } else if (path === "api/insights") {
    data = await staticFile(`${lang}/insights.json`);
  } else {
    throw new Error("404");
  }
  const day = 86400e3;
  shiftTimes(data, shift, STATIC.t0 - 90 * day, STATIC.t0 + STATIC.step * STATIC.frames + 10 * day);
  return staticView(path, data);
}
// The demo box panel keeps times in ms; turn them into the strings /api/internal sends.
function staticInternal(data, shift) {
  const local = (ms) => {
    const d = new Date(ms + shift);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  data.generated_at = local(Date.now() - shift);
  for (const bot of data.bots) {
    bot.last_activity = bot.last_activity_ms ? local(bot.last_activity_ms) : null;
    bot.recent_tasks = (bot.recent_tasks_ms || []).map(([ms, text]) => `${local(ms).slice(0, 10)} ${text}`);
  }
  return data;
}
// The same adjustments backend/views.py makes, for the static demo.
function staticView(path, data) {
  const settings = S.settings || DEFAULT_SETTINGS;
  const bots = settings.bots || {};
  const rooms = settings.rooms || {};
  const MASK = "•••";
  const alias = (id, name) => bots[id]?.alias || name;
  if (path === "api/office") {
    const hiddenRooms = new Set(Object.keys(rooms).filter((id) => rooms[id].hidden));
    data.wings = data.wings.filter((wing) => !hiddenRooms.has(wing.id))
      .map((wing, index) => ({ ...wing, name: rooms[wing.id]?.name || wing.name, order: rooms[wing.id]?.order ?? index }))
      .sort((a, b) => a.order - b.order);
    data.agents = data.agents.filter((agent) => !bots[agent.id]?.hidden && !hiddenRooms.has(agent.wingId)).map((agent) => {
      const wing = data.wings.find((item) => item.id === agent.wingId);
      const next = { ...agent, name: alias(agent.id, agent.originalName || agent.name), look: bots[agent.id]?.look || {}, wingName: wing ? wing.name : agent.wingName };
      if (settings.privacy) Object.assign(next, { snippet: agent.snippet && MASK, roleLine: agent.roleLine && MASK, detailParam: agent.detailParam && MASK });
      return next;
    });
    data.privacy = Boolean(settings.privacy);
  } else if (path === "api/flows") {
    for (const item of data.external) item.name = alias(item.id, item.name);
    if (settings.privacy) for (const flow of data.flows) {
      if (flow.trigger.text) flow.trigger.text = MASK;
      for (const step of flow.steps) step.text = step.text && MASK;
    }
  } else if (path === "api/insights") {
    for (const profile of data.profiles) {
      profile.name = alias(profile.id, profile.name);
      if (settings.privacy && profile.description) profile.description = MASK;
    }
    data.awards = data.awards.filter((award) => !bots[award.id]?.hidden);
    if (settings.privacy) for (const item of data.feed) if (item.kind !== "automation" && item.text) item.text = MASK;
  }
  return data;
}
function applySettings() {
  const settings = S.settings;
  S.lang = settings.language === "auto" ? (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en" : settings.language;
  document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
  if (settings.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = settings.theme;
  document.documentElement.dataset.motion = settings.motion;
  REDUCED = settings.motion === "off" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  S.ambient = settings.ambient && settings.motion !== "off";
  const themeButton = document.getElementById("theme");
  if (themeButton) {
    const dark = settings.theme === "auto" ? matchMedia("(prefers-color-scheme: dark)").matches : settings.theme === "dark";
    themeButton.innerHTML = icon(dark ? "sun" : "moon", 17);
  }
  translatePage();
  if (typeof syncModeChrome === "function") syncModeChrome();
}

// ---------------------------------------------------------------- formatting

function ago(ms) {
  if (!ms) return "—";
  const minutes = Math.max(0, Math.floor((Date.now() - ms) / 60000));
  if (minutes < 1) return t("time.now");
  if (minutes < 60) return t("time.minutes", { n: minutes });
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? t("time.hours", { n: hours }) : t("time.days", { n: Math.floor(hours / 24) });
}
function clock(ms) {
  const d = new Date(ms);
  const pad = (n) => String(n).padStart(2, "0");
  const today = new Date().toDateString() === d.toDateString();
  return `${today ? "" : `${d.getMonth() + 1}/${d.getDate()} `}${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function span(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return t("dur.s", { s });
  if (s < 3600) return s % 60 ? t("dur.ms", { m: Math.floor(s / 60), s: s % 60 }) : t("dur.m", { m: Math.floor(s / 60) });
  return t("dur.hm", { h: Math.floor(s / 3600), m: Math.round((s % 3600) / 60) });
}
function plus(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s >= 3600) return `+${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
  return `+${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function number(n) {
  if (S.lang === "zh" && n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)} 万`;
  if (S.lang !== "zh" && n >= 10000) return `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k`;
  return n.toLocaleString(S.lang === "zh" ? "zh-CN" : "en-US");
}
function windowLabel(hours) {
  return t(`window.${hours}`);
}

// ---------------------------------------------------------------- identities

function agentOf(id) {
  return S.office?.agents.find((agent) => agent.id === id) || null;
}
function profileOf(id) {
  return S.insights?.profiles.find((profile) => profile.id === id) || null;
}
function externalOf(id) {
  return S.flows?.external.find((item) => item.id === id) || null;
}
function nameOf(id) {
  if (id === "you") return t("who.you");
  if (id === "automation") return t("who.automation");
  return agentOf(id)?.name || externalOf(id)?.name || profileOf(id)?.name || t("who.external");
}
function roomName(wing) {
  if (!wing) return t("room.desk");
  if (wing.id === "__loose__" && !wing.name) return t("room.loose");
  return wing.name || t("room.unnamed");
}
function wingOf(agent) {
  return S.office?.wings.find((wing) => wing.id === agent?.wingId) || null;
}
function kindOf(id) {
  if (id === "you") return "you";
  if (id === "automation") return "automation";
  return "agent";
}
function lookAgent(id) {
  const agent = agentOf(id);
  if (agent) return agent;
  const look = S.settings?.bots?.[id]?.look;
  return { id, name: nameOf(id), look: look || {} };
}
function avatar(id, size = 32) {
  return avatarSVG(lookAgent(id), size, kindOf(id));
}
function sectionIndex(id) {
  const agent = agentOf(id);
  if (!agent || agent.wingId === "__door__") return -1;
  return S.office.wings.findIndex((wing) => wing.id === agent.wingId);
}
function colorVar(id) {
  if (id === "you" || id === "automation") return "var(--hall)";
  const agent = agentOf(id);
  if (!agent) return "var(--ext)";
  const index = sectionIndex(id);
  return index < 0 ? "var(--hall)" : `var(${SECTION_VARS[index % SECTION_VARS.length]})`;
}
function softVar(id) {
  const index = sectionIndex(id);
  if (!agentOf(id) || index < 0) return "var(--hall-soft)";
  return `var(${SECTION_VARS[index % SECTION_VARS.length]}-soft)`;
}
function isBusy(agent) {
  return agent && agent.state !== "idle";
}
function stateText(agent) {
  return t(`state.${agent?.state || "idle"}`);
}
function detailText(agent) {
  if (!agent) return "";
  return t(`detail.${agent.detail || "idle"}`, { name: agent.detailParam || t("who.teammate") });
}
function masked(text) {
  return text === "•••" ? t("privacy.hidden") : text;
}

// Game-style level from everything a bot has produced: each level needs a bit more than the last.
function levelOf(id) {
  const profile = profileOf(id);
  if (!profile) return null;
  const xp = profile.outputs + profile.handoffsIn;
  const level = Math.floor(Math.sqrt(xp / 3)) + 1;
  const floor = 3 * (level - 1) ** 2;
  const next = 3 * level ** 2;
  return { level, xp, progress: (xp - floor) / (next - floor), toNext: next - xp };
}

// ---------------------------------------------------------------- flows

function replaySteps(flow) {
  const steps = [];
  if (flow.trigger.kind !== "agent") {
    steps.push({ kind: "trigger", from: flow.trigger.agentId, to: flow.rootAgentId, at: flow.trigger.at || flow.startedAt, text: flow.trigger.text, depth: 0, traced: true });
  }
  return steps.concat(flow.steps);
}
function stepVerb(step) {
  if (step.kind === "trigger") return step.from === "you" ? t("verb.ask") : t("verb.wake");
  if (step.kind === "reply") return t("verb.reply");
  return t("verb.handoff");
}
function stepSentence(step) {
  if (step.kind === "trigger") return t(step.from === "you" ? "sentence.ask" : "sentence.wake", { to: nameOf(step.to) });
  if (step.kind === "reply") return t("sentence.reply", { from: nameOf(step.from) });
  return `${nameOf(step.from)} → ${nameOf(step.to)}`;
}
function stepText(step) {
  if (step.kind === "trigger" && step.from === "automation" && !step.text) return t("trigger.automation");
  return masked(step.text) || t("step.empty");
}
function triggerChip(flow) {
  if (flow.trigger.kind === "user") return `<span class="chip you">${t("chip.you")}</span>`;
  if (flow.trigger.kind === "automation") return `<span class="chip auto">⏰ ${t("chip.auto")}</span>`;
  return `<span class="chip">${t("chip.agent", { name: esc(nameOf(flow.trigger.agentId)) })}</span>`;
}
function flowAsk(flow) {
  if (flow.trigger.kind !== "automation") return masked(flow.trigger.text);
  const step = flow.steps.find((item) => item.kind === "handoff");
  return step ? `${nameOf(step.from)}：${masked(step.text)}` : t("trigger.automation");
}

// ---------------------------------------------------------------- tooltip
// Shown on hover, or on keyboard focus only. Any click, scroll, redraw or dialog hides it,
// so it can never be left stranded on screen.

let tipOwner = null;
function showTip(html, x, y, owner = null) {
  const tip = $("#tooltip");
  if (!tip) return;
  tipOwner = owner;
  tip.innerHTML = html;
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  tip.style.left = `${Math.max(8, Math.min(innerWidth - box.width - 8, x - box.width / 2))}px`;
  tip.style.top = `${y - box.height - 14 > 8 ? y - box.height - 14 : y + 20}px`;
}
function hideTip() {
  tipOwner = null;
  const tip = $("#tooltip");
  if (tip) tip.hidden = true;
}
addEventListener("pointerdown", hideTip, true);
addEventListener("scroll", hideTip, true);
addEventListener("blur", hideTip);
document.addEventListener("visibilitychange", hideTip);
document.addEventListener("pointermove", (event) => {
  if (tipOwner && (!tipOwner.isConnected || !tipOwner.contains(event.target))) {
    hideTip();
    if (S.hover && typeof setHover === "function") setHover(null);
  }
});
function agentTip(id) {
  const agent = agentOf(id);
  const profile = profileOf(id);
  const links = S.flows?.links || [];
  const out = links.filter((link) => link.from === id).reduce((n, link) => n + link.count, 0);
  const got = links.filter((link) => link.to === id).reduce((n, link) => n + link.count, 0);
  const level = levelOf(id);
  return `<b>${esc(nameOf(id))}</b>${agent?.title ? ` · ${esc(agent.title)}` : ""}${level ? ` · Lv${level.level}` : ""}
    ${agent ? `<div class="soft">${esc(roomName(wingOf(agent)))} · ${esc(stateText(agent))}${agent.state !== "idle" ? `：${esc(detailText(agent))}` : ""}</div>` : ""}
    ${agent?.roleLine ? `<div>${esc(masked(agent.roleLine))}</div>` : ""}
    <div class="soft">${t("tip.counts", { out, got })}${profile ? ` · ${S.office?.source?.box ? t("tip.outputs", { n: number(profile.outputs) }) : t("tip.chars", { n: number(profile.chars) })}` : ""}</div>`;
}

// ---------------------------------------------------------------- line icons
// A tiny stroke-icon set (24px grid) for chrome: tabs, headings, buttons.
const ICONS = {
  studio: '<path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-5h6v5M9 11h.01M15 11h.01"/>',
  network: '<circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M10.7 7.2 6.3 15.8M13.3 7.2l4.4 8.6M7.5 18h9"/>',
  timeline: '<path d="M4 6h10M4 12h16M4 18h7"/><circle cx="17" cy="6" r="2"/><circle cx="14" cy="18" r="2"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8 20h8M9 17h6"/>',
  insights: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  inbox: '<path d="M4 13 6.5 5h11L20 13M4 13v6h16v-6M4 13h5l1.5 2h3L15 13h5"/>',
  digest: '<path d="M5 4h11l3 3v13H5zM9 9h6M9 13h6M9 17h4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  grid: '<rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/>',
  team: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18.5 20a6.5 6.5 0 0 0-3-5.5"/>',
  bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.9 1.2-1.8-.5-1.1.2-2.2 1.4-2.2H17a4 4 0 0 0 4-4c0-5-4-10-9-10z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  arrowLeft: '<path d="M15 6l-6 6 6 6"/>',
  tv: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  flow: '<path d="M3 6h4c5 0 5 12 10 12h4M3 18h4c2.2 0 3.3-2.3 4.4-5M13.6 11C14.7 8.3 15.8 6 18 6h3"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  plug: '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
};
function icon(name, size = 16) {
  return `<svg class="ico" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
function paintIcons(root = document) {
  for (const node of root.querySelectorAll("[data-icon]")) node.innerHTML = icon(node.dataset.icon, Number(node.dataset.size) || 16);
}
