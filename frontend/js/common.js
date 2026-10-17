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

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
async function loadSettings() {
  try {
    S.settings = await getJson("/api/settings");
  } catch {
    S.settings = { language: "auto", theme: "auto", hours: 24, ambient: true, motion: "full", privacy: false, refreshSeconds: 3, dataSource: "auto", supportDir: "", rooms: {}, bots: {} };
  }
  applySettings();
  return S.settings;
}
async function saveSettings(patch) {
  const next = { ...S.settings, ...patch };
  const response = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
  if (!response.ok) throw new Error(String(response.status));
  S.settings = await response.json();
  applySettings();
  return S.settings;
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
    themeButton.textContent = dark ? "☀️" : "🌙";
  }
  translatePage();
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
    <div class="soft">${t("tip.counts", { out, got })}${profile ? ` · ${t("tip.chars", { n: number(profile.chars) })}` : ""}</div>`;
}
