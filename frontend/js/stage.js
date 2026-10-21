// The stage: three views of the same people (studio, stars, track) and one flight engine
// that throws paper planes between them, for live handoffs, ambient replays and step-by-step replay.
const SVGNS = "http://www.w3.org/2000/svg";
const ST = { W: 1200, H: 680, ROOM_Y: 16, ROOM_H: 520, HALL_Y: 552, FEET: 650 };
const FLY_MS = 1100;
const HOLD_MS = 1400;
const SW = 1200;
const SH = 680;
const PER_ROW = 3;

let studioSig = "";
let starsSig = "";
let starNodes = new Map();
let starLinks = [];
let ambient = { flowIndex: 0, visitIndex: 0, nextAt: 0, flowId: null, queue: [] };

function el(name, attrs = {}, html = "") {
  const node = document.createElementNS(SVGNS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (html) node.innerHTML = html;
  return node;
}
function viewSvg() {
  return S.view === "track" ? $("#track svg") : $(`#${S.view}`);
}

// ================================================================= studio

// Rooms flow three to a row; each row grows tall enough for its busiest room,
// so any number of groups and any number of bots per group still fit.
function deskColumns(width) {
  return Math.max(1, Math.min(6, Math.floor((width - 40) / 104)));
}
function membersOf(wing) {
  return S.office.agents.filter((agent) => agent.wingId === wing.id);
}
function studioRooms() {
  const wings = S.office.wings;
  const gap = 18;
  const rooms = [];
  let y = 16;
  for (let start = 0; start < Math.max(wings.length, 1); start += PER_ROW) {
    const row = wings.slice(start, start + PER_ROW);
    const count = Math.max(row.length, 1);
    const w = (ST.W - 40 - gap * (count - 1)) / count;
    const h = Math.max(520, ...row.map((wing) => {
      const n = membersOf(wing).length;
      const deskRows = Math.ceil(n / Math.min(Math.max(n, 1), deskColumns(w)));
      return 188 + Math.max(deskRows, 1) * 96 + 200;
    }));
    row.forEach((wing, i) => rooms.push({ wing, index: start + i, x: 20 + i * (w + gap), y, w, h }));
    y += h + 18;
  }
  ST.HALL_Y = y - 2;
  ST.FEET = ST.HALL_Y + 98;
  ST.H = ST.HALL_Y + 128;
  return rooms;
}
function studioGuests() {
  const linked = new Set();
  for (const link of S.flows?.links || []) linked.add(link.from).add(link.to);
  if (S.replay) S.replay.flow.participants.forEach((id) => linked.add(id));
  return (S.flows?.external || []).map((item) => item.id).filter((id) => linked.has(id)).slice(0, 3);
}
function studioDesks() {
  const desks = new Map();
  for (const room of studioRooms()) {
    const people = S.office.agents.filter((agent) => agent.wingId === room.wing.id).sort((a, b) => a.slot - b.slot);
    const cols = Math.min(Math.max(people.length, 1), deskColumns(room.w));
    people.forEach((agent, i) => {
      const row = Math.floor(i / cols);
      const inRow = Math.min(cols, people.length - row * cols);
      const col = i % cols;
      const cell = (room.w - 40) / cols;
      const offset = ((cols - inRow) * cell) / 2;
      desks.set(agent.id, { x: room.x + 20 + offset + cell * (col + 0.5), y: room.y + 188 + row * 96, room });
    });
  }
  S.office.agents.filter((agent) => agent.wingId === "__door__").forEach((agent, i) => {
    desks.set(agent.id, { x: 330 + i * 130, y: ST.FEET - 6, room: null });
  });
  return desks;
}
function studioPositions(base = false) {
  const desks = studioDesks();
  const map = new Map();
  for (const room of studioRooms()) {
    const idle = S.office.agents.filter((agent) => agent.wingId === room.wing.id && !isBusy(agent)).sort((a, b) => a.slot - b.slot);
    const perRow = idle.length > 3 ? Math.ceil(idle.length / Math.ceil(idle.length / Math.max(3, Math.floor(room.w / 80)))) : idle.length;
    idle.forEach((agent, i) => {
      const row = Math.floor(i / perRow);
      const inRow = row ? idle.length - perRow : perRow;
      const col = i % perRow;
      const left = room.x + 70 + (row ? 34 : 0);
      const width = room.w - 110 - (row ? 68 : 0);
      map.set(agent.id, { x: left + (width * (col + 0.5)) / inRow, y: room.y + room.h - (idle.length > 3 ? 110 - row * 82 : 64), mode: "lounge" });
    });
  }
  for (const agent of S.office.agents) {
    if (map.has(agent.id)) continue;
    const desk = desks.get(agent.id);
    map.set(agent.id, { x: desk.x, y: desk.y + 4, mode: desk.room ? "desk" : "frontdesk" });
  }
  map.set("you", { x: 112, y: ST.FEET, mode: "hall" });
  map.set("automation", { x: 250, y: ST.FEET, mode: "hall" });
  studioGuests().forEach((id, i) => map.set(id, { x: 1100 - i * 76, y: ST.FEET, mode: "hall" }));
  if (!base) for (const [id, spot] of visits) if (map.has(id)) map.set(id, spot);
  return map;
}

const OUT = 'stroke="#2a3347" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"';
function skyFor(hour) {
  const cloud = (x, y, s) => `<path transform="translate(${x} ${y}) scale(${s})" d="M-12 4a6 6 0 0 1 2 -11 8 8 0 0 1 15 -2 6 6 0 0 1 7 8 5 5 0 0 1 -2 5z" fill="#fff" opacity=".95"/>`;
  if (hour < 6 || hour >= 19) return { sky: "#34406b", body: `<circle cx="-22" cy="-8" r="6" fill="#fff3b0"/><circle cx="-19" cy="-10" r="5.5" fill="#34406b"/><circle class="tw-star" cx="10" cy="-10" r="1.4" fill="#fff"/><circle class="tw-star d2" cx="26" cy="4" r="1.2" fill="#fff"/><circle class="tw-star d3" cx="-4" cy="8" r="1" fill="#fff"/>` };
  if (hour < 8 || hour >= 17) return { sky: "#ffc9a3", body: `<circle cx="16" cy="6" r="9" fill="#ff9a6b"/>${cloud(-16, 2, 0.8)}` };
  return { sky: "#a7d4fb", body: `<circle cx="22" cy="-6" r="8" fill="#ffd36e"/>${cloud(-14, 4, 0.9)}` };
}
function plant(x, y, s = 1) {
  return `<g transform="translate(${x} ${y}) scale(${s})"><path d="M0 -14c-12 -6-15 -22-7 -28 5 9 9 15 7 28zM0 -14c10 -9 18 -11 22 -21-10 -1-20 7-22 21zM0 -14c-2 -14 2 -25 10 -31 2 12-2 21-10 31z" fill="#7cc48a" ${OUT} stroke-width="1.6"/>
    <path d="M-11 -15h22l-3 16a3 3 0 0 1 -3 2.5h-10a3 3 0 0 1 -3 -2.5z" fill="#e8a172" ${OUT}/></g>`;
}
function shelf(x, y) {
  const books = ["#2f7fd8", "#e0662e", "#1e9a68", "#8a5bd6", "#ffd36e", "#c9466b"];
  let html = `<rect x="${x}" y="${y}" width="78" height="56" rx="6" fill="#e9dcc6" ${OUT}/><path d="M${x + 3} ${y + 28}h72" ${OUT} stroke-width="1.6"/>`;
  for (let i = 0; i < 6; i++) html += `<rect x="${x + 7 + i * 10}" y="${y + 7 + (i % 3) * 2}" width="8" height="${19 - (i % 3) * 2}" rx="1.5" fill="${books[i]}" ${OUT} stroke-width="1.2"/>`;
  html += `<rect x="${x + 8}" y="${y + 35}" width="22" height="15" rx="2" fill="#fff" ${OUT} stroke-width="1.2"/><path d="M${x + 12} ${y + 41}h14M${x + 12} ${y + 45}h9" stroke="#9aa6b8" stroke-width="1.4" stroke-linecap="round"/><circle cx="${x + 54}" cy="${y + 43}" r="7" fill="#9fdcab" ${OUT} stroke-width="1.2"/><rect x="${x + 64}" y="${y + 36}" width="8" height="14" rx="2" fill="#8fc3f2" ${OUT} stroke-width="1.2"/>`;
  return html;
}
function deskArt(id, desk) {
  const agent = agentOf(id);
  const x = desk.x;
  const y = desk.y;
  const tint = desk.room ? `var(${SECTION_VARS[desk.room.index % SECTION_VARS.length]}-soft)` : "var(--hall-soft)";
  return `<g class="desk ${isBusy(agent) ? "on" : ""}" data-desk="${esc(id)}">
    <rect x="${x + 5}" y="${y - 36}" width="29" height="21" rx="4" fill="#3a4458" ${OUT} stroke-width="1.8"/>
    <rect class="screen" x="${x + 8}" y="${y - 33}" width="23" height="14" rx="2"/>
    <path d="M${x + 16} ${y - 15}h7v3h-7z" fill="#3a4458"/>
    <rect x="${x - 44}" y="${y - 16}" width="88" height="13" rx="5" fill="${tint}" ${OUT}/>
    <rect x="${x - 38}" y="${y - 4}" width="76" height="27" rx="6" fill="var(--desk-front)" ${OUT}/>
    <rect x="${x - 31}" y="${y + 2}" width="62" height="15" rx="4" fill="#fff" ${OUT} stroke-width="1.4"/>
    <text class="plate" x="${x}" y="${y + 13}" text-anchor="middle">${esc(cut(nameOf(id), 10))}</text>
    <rect x="${x - 35}" y="${y - 28}" width="11" height="12" rx="3" fill="#fff" ${OUT} stroke-width="1.6"/><path d="M${x - 24} ${y - 24}c4 0 4 6 0 6" fill="none" ${OUT} stroke-width="1.6"/>
  </g>`;
}
function rug(cx, cy, w, h, color) {
  return `<rect x="${cx - w / 2}" y="${cy - h / 2}" width="${w}" height="${h}" rx="${h / 2}" fill="${color}" ${OUT} stroke-width="1.8"/>
    <rect x="${cx - w / 2 + 9}" y="${cy - h / 2 + 8}" width="${w - 18}" height="${h - 16}" rx="${(h - 16) / 2}" fill="none" stroke="#fff" stroke-opacity=".75" stroke-width="2.2" stroke-dasharray="6 6"/>`;
}

function buildStudio() {
  const svg = $("#studio");
  const rooms = studioRooms();
  const desks = studioDesks();
  const sky = skyFor(new Date().getHours());
  let back = `<defs>
      <pattern id="planks" width="120" height="30" patternUnits="userSpaceOnUse"><rect width="120" height="30" fill="var(--floor)"/><path d="M0 29.5h120M60 0v15M0 15h120M20 15v15M100 15v15" stroke="var(--floor-line)" stroke-width="1.5"/></pattern>
    </defs><rect x="0" y="0" width="${ST.W}" height="${ST.H}" fill="url(#planks)"/>`;
  for (const room of rooms) {
    const varName = SECTION_VARS[room.index % SECTION_VARS.length];
    const color = `var(${varName})`;
    const soft = `var(${varName}-soft)`;
    const cx = room.x + room.w / 2;
    const signW = Math.min(room.w - 32, 210);
    back += `<g class="room">
      <rect x="${room.x}" y="${room.y}" width="${room.w}" height="${room.h}" rx="20" fill="var(--room-floor)" ${OUT} stroke-width="2.4"/>
      <path d="M${room.x} ${room.y + 128}V${room.y + 20}a20 20 0 0 1 20 -20H${room.x + room.w - 20}a20 20 0 0 1 20 20V${room.y + 128}z" fill="${soft}" ${OUT} stroke-width="2.4"/>
      <rect x="${room.x + 2}" y="${room.y + 120}" width="${room.w - 4}" height="8" fill="${color}" opacity=".55"/>
      <path d="M${room.x + 2} ${room.y + 128}H${room.x + room.w - 2}" stroke="#2a3347" stroke-width="2.4"/>
      <g transform="translate(${cx} ${room.y + 80})"><rect x="-46" y="-30" width="92" height="60" rx="8" fill="#fff" ${OUT} stroke-width="2.4"/><rect x="-40" y="-24" width="80" height="48" rx="4" class="window-sky" fill="${sky.sky}"/><g>${sky.body}</g><path d="M0 -24v48M-40 0h80" stroke="#fff" stroke-width="3"/></g>
      ${shelf(room.x + 18, room.y + 60)}
      ${plant(room.x + room.w - 36, room.y + 120, 1)}
      ${rug(cx, room.y + room.h - 72, room.w * 0.82, 120, soft)}
      <g transform="translate(${room.x + 30} ${room.y + room.h - 150})"><rect x="-14" y="-22" width="30" height="34" rx="8" fill="${soft}" ${OUT}/><rect x="-16" y="4" width="36" height="14" rx="6" fill="${color}" fill-opacity=".55" ${OUT}/></g>
      ${plant(room.x + room.w - 26, room.y + room.h - 20, 0.85)}
      <g transform="translate(${room.x + 14} ${room.y + 12})"><rect width="${signW}" height="32" rx="9" fill="${color}" ${OUT}/><rect x="3" y="3" width="${signW - 6}" height="12" rx="6" fill="#fff" opacity=".18"/><text class="room-label" x="12" y="21.5">${esc(cut(roomName(room.wing), 14))}</text><rect x="${signW - 74}" y="6" width="66" height="20" rx="10" fill="#fff" opacity=".92"/><text class="room-count" data-room-count="${esc(room.wing.id)}" x="${signW - 41}" y="20" text-anchor="middle"></text></g>
    </g>`;
  }
  back += `<g class="hall">
    <rect x="20" y="${ST.HALL_Y}" width="${ST.W - 40}" height="${ST.H - ST.HALL_Y - 8}" rx="20" fill="var(--hall-soft)" ${OUT} stroke-width="2.4"/>
    <g transform="translate(40 ${ST.HALL_Y + 24})"><rect width="44" height="90" rx="8" fill="#c9a37a" ${OUT} stroke-width="2.2"/><rect x="8" y="10" width="28" height="30" rx="4" fill="#a7d4fb" ${OUT} stroke-width="1.6"/><circle cx="35" cy="56" r="3" fill="#ffd36e" ${OUT} stroke-width="1.4"/></g>
    <g transform="translate(470 ${ST.HALL_Y + 14})"><rect width="200" height="58" rx="8" fill="#fff" ${OUT} stroke-width="2.2"/><rect x="0" y="0" width="200" height="16" rx="8" fill="var(--accent)"/><rect x="0" y="8" width="200" height="8" fill="var(--accent)"/><text class="board-title" x="100" y="12" text-anchor="middle">${esc(t("studio.board"))}</text><text class="board-text" id="board-1" x="14" y="34"></text><text class="board-text" id="board-2" x="14" y="50"></text><path d="M20 58v28M180 58v28" ${OUT} stroke-width="3"/></g>
    <g transform="translate(730 ${ST.HALL_Y + 40})"><rect x="0" y="20" width="130" height="44" rx="8" fill="var(--desk-front)" ${OUT} stroke-width="2.2"/><rect x="0" y="14" width="130" height="10" rx="4" fill="#e9dcc6" ${OUT}/><rect x="14" y="-18" width="34" height="34" rx="6" fill="#4d5466" ${OUT}/><circle cx="31" cy="-6" r="5" fill="#9fdcab"/><rect x="66" y="0" width="12" height="14" rx="3" fill="#fff" ${OUT} stroke-width="1.5"/><rect x="86" y="0" width="12" height="14" rx="3" fill="#fff" ${OUT} stroke-width="1.5"/></g>
    <text class="label small" x="795" y="${ST.HALL_Y + 120}" text-anchor="middle">${esc(t("studio.coffee"))}</text>
    ${plant(900, ST.HALL_Y + 104, 1)}
    <g transform="translate(${ST.W - 214} ${ST.HALL_Y + 22})"><path d="M0 90V20a20 20 0 0 1 20 -20h154a20 20 0 0 1 20 20v70" fill="none" stroke="#2a3347" stroke-opacity=".3" stroke-width="2.4" stroke-dasharray="6 6" stroke-linecap="round"/></g>
    <text class="label small" x="${ST.W - 117}" y="${ST.HALL_Y + 40}" text-anchor="middle" id="outside-label">${esc(t("studio.outside"))}</text>
  </g>`;
  let fronts = "";
  for (const [id, desk] of desks) fronts += deskArt(id, desk);
  svg.setAttribute("viewBox", `0 0 ${ST.W} ${ST.H}`);
  svg.innerHTML = `<g id="studio-back">${back}</g><g id="studio-links"></g><g id="studio-actors"></g><g id="studio-desks">${fronts}</g><g id="studio-fx"></g>`;
  for (const [id] of desks) $(`[data-desk="${CSS.escape(id)}"]`, svg)?.addEventListener("click", () => openProfile(id));
}

function studioIds() {
  return ["you", "automation", ...S.office.agents.map((agent) => agent.id), ...studioGuests()];
}
function actorArt(id) {
  const kind = kindOf(id);
  if (kind === "you") return personSVG();
  if (kind === "automation") return clockSVG();
  return creatureSVG(lookAgent(id));
}
function renderStudio() {
  const signature = JSON.stringify([S.office.wings, S.office.agents.map((a) => [a.id, a.wingId, a.slot, a.name, a.look]), studioGuests(), new Date().getHours(), S.lang]);
  if (signature !== studioSig) {
    buildStudio();
    studioSig = signature;
  }
  const svg = $("#studio");
  const positions = studioPositions();
  const layer = $("#studio-actors", svg);
  const ids = studioIds();
  const existing = new Map($$(".actor", layer).map((node) => [node.dataset.id, node]));
  for (const [id, node] of existing) if (!ids.includes(id)) node.remove();
  const cast = S.replay ? new Set(S.replay.flow.participants) : null;
  const neighbours = S.hover && !S.replay ? neighbourSet(S.hover) : null;
  for (const id of ids) {
    let node = existing.get(id);
    if (!node) {
      node = el("g", { class: "actor", "data-id": id, tabindex: "0", role: "button", "aria-label": nameOf(id) });
      node.innerHTML = `${actorArt(id)}<text class="label name" y="20" text-anchor="middle"></text>`;
      bindActor(node, id);
      layer.append(node);
    }
    const pos = positions.get(id);
    node.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
    const agent = agentOf(id);
    node.querySelector(".creature").classList.remove("st-idle", "st-writing", "st-researching", "st-executing", "st-syncing", "st-error");
    node.querySelector(".creature").classList.add(`st-${agent ? agent.state : "idle"}`);
    node.querySelector(".creature").classList.toggle("sleepy", Boolean(agent && !isBusy(agent) && Date.now() - agent.lastActivityAt > 2 * 3600e3));
    // A visiting bot hides its name tag (its speech bubble says who it is), so tags never pile up.
    node.classList.toggle("away", pos.mode === "lounge");
    node.classList.toggle("hall", pos.mode === "hall");
    node.classList.toggle("faded", Boolean((cast && !cast.has(id)) || (neighbours && !neighbours.has(id))));
    const level = kindOf(id) === "agent" ? levelOf(id) : null;
    node.querySelector(".name").textContent = id === "automation" ? t("who.automationShort") : `${level ? `Lv${level.level} ` : ""}${cut(nameOf(id), 9)}`;
  }
  // Keep actors sorted by depth so the ones in front overlap the ones behind.
  [...layer.children].sort((a, b) => positions.get(a.dataset.id).y - positions.get(b.dataset.id).y).forEach((node) => layer.append(node));
  for (const [id] of studioDesks()) $(`[data-desk="${CSS.escape(id)}"]`, svg)?.classList.toggle("on", isBusy(agentOf(id)));
  for (const room of studioRooms()) {
    const people = S.office.agents.filter((agent) => agent.wingId === room.wing.id);
    const busy = people.filter(isBusy).length;
    const label = $(`[data-room-count="${CSS.escape(room.wing.id)}"]`, svg);
    if (label) label.textContent = busy ? t("studio.countBusy", { n: people.length, busy }) : t("studio.count", { n: people.length });
  }
  $("#outside-label", svg)?.setAttribute("opacity", studioGuests().length ? 1 : 0);
  const board1 = $("#board-1", svg);
  if (board1 && S.flows) {
    const busy = S.office.agents.filter(isBusy).length;
    board1.textContent = t("studio.board1", { flows: S.flows.flowCount, handoffs: S.flows.handoffCount });
    $("#board-2", svg).textContent = S.flows.hub ? t("studio.board2hub", { busy, hub: cut(nameOf(S.flows.hub.id), 12) }) : t("studio.board2", { busy });
  }
  renderStudioLinks();
}
function renderStudioLinks() {
  const layer = $("#studio-links");
  if (!layer) return;
  let html = "";
  if (!S.replay) {
    const links = (S.flows?.links || []).filter((link) => S.hover ? link.from === S.hover || link.to === S.hover : Date.now() - link.lastAt < 15 * 60e3);
    for (const link of links) {
      const q = studioCurve(link.from, link.to);
      if (!q) continue;
      const cls = S.hover ? "link-hover" : "link-live";
      html += `<path class="${cls}" d="${qPath(q)}" stroke="${colorVar(link.from)}"/>`;
      if (S.hover) {
        const mid = qPoint(q, 0.5);
        html += `<text class="label" x="${mid.x}" y="${mid.y}" text-anchor="middle">${link.count}</text>`;
      }
    }
  }
  layer.innerHTML = html;
}
function studioAnchor(id) {
  const pos = studioPositions().get(id);
  return pos ? { x: pos.x, y: pos.y - 44 } : null;
}
function studioCurve(from, to) {
  const a = studioAnchor(from);
  const b = studioAnchor(to);
  if (!a || !b) return null;
  const dist = Math.hypot(b.x - a.x, b.y - a.y);
  const lift = Math.min(220, 50 + dist * 0.32);
  return { a, c: { x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - lift }, b };
}
function neighbourSet(id) {
  const set = new Set([id]);
  for (const link of S.flows?.links || []) {
    if (link.from === id) set.add(link.to);
    if (link.to === id) set.add(link.from);
  }
  return set;
}
function bindActor(node, id) {
  node.addEventListener("pointerenter", (event) => event.pointerType === "mouse" && setHover(id, node));
  node.addEventListener("pointerleave", () => S.hover === id && setHover(null));
  // Keyboard focus only: a mouse click (or the drawer handing focus back) must not pin a tooltip.
  node.addEventListener("focus", () => node.matches(":focus-visible") && setHover(id, node));
  node.addEventListener("blur", () => S.hover === id && setHover(null));
  node.addEventListener("click", () => {
    setHover(null);
    if (kindOf(id) === "agent") openProfile(id);
  });
  node.addEventListener("keydown", (event) => event.key === "Enter" && kindOf(id) === "agent" && openProfile(id));
}
function setHover(id, node) {
  if (S.hover === id && (id || !node)) {
    if (!id) hideTip();
    return;
  }
  S.hover = id;
  if (S.view === "studio") renderStudio();
  if (S.view === "stars") paintStarsFocus();
  if (!id || !node) return hideTip();
  const box = node.getBoundingClientRect();
  showTip(agentTip(id), box.left + box.width / 2, box.top, node);
}

// ================================================================= stars

function starIds() {
  const ids = ["you", ...S.office.agents.map((agent) => agent.id)];
  const linked = new Set();
  for (const link of S.flows?.links || []) linked.add(link.from).add(link.to);
  if ((S.flows?.flows || []).some((flow) => flow.trigger.kind === "automation")) ids.push("automation");
  for (const item of S.flows?.external || []) if (linked.has(item.id)) ids.push(item.id);
  if (S.replay) for (const id of S.replay.flow.participants) if (!ids.includes(id)) ids.push(id);
  return ids;
}
function layoutStars() {
  const ids = starIds();
  const wings = S.office.wings;
  const center = { x: 600, y: 330 };
  const anchors = new Map();
  const sectionAnchor = (index) => {
    const angle = (index / Math.max(wings.length, 1)) * Math.PI * 2 - Math.PI / 2 + Math.PI / wings.length;
    return { x: center.x + Math.cos(angle) * 360, y: center.y + Math.sin(angle) * 210 };
  };
  for (const id of ids) {
    const index = sectionIndex(id);
    anchors.set(id, index >= 0 ? sectionAnchor(index) : kindOf(id) === "agent" && !agentOf(id) ? { x: 1080, y: 600 } : center);
  }
  const nodes = ids.map((id) => {
    const anchor = anchors.get(id);
    const seed = hashOf(id);
    return { id, x: anchor.x + ((seed % 120) - 60), y: anchor.y + (((seed >> 8) % 120) - 60), ax: anchor.x, ay: anchor.y, vx: 0, vy: 0 };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const pairs = new Map();
  for (const link of S.flows?.links || []) {
    if (!byId.has(link.from) || !byId.has(link.to)) continue;
    const key = [link.from, link.to].sort().join("|");
    pairs.set(key, (pairs.get(key) || 0) + link.count);
  }
  const springs = [...pairs].map(([key, count]) => ({ a: byId.get(key.split("|")[0]), b: byId.get(key.split("|")[1]), count }));
  for (let step = 0; step < 320; step++) {
    const heat = 1 - step / 320;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const d2 = Math.max(dx * dx + dy * dy, 100);
        const force = 14000 / d2;
        const d = Math.sqrt(d2);
        dx /= d;
        dy /= d;
        a.vx -= dx * force; a.vy -= dy * force;
        b.vx += dx * force; b.vy += dy * force;
      }
    }
    for (const spring of springs) {
      const dx = spring.b.x - spring.a.x;
      const dy = spring.b.y - spring.a.y;
      const d = Math.hypot(dx, dy) || 1;
      const pull = (d - 150) * 0.004 * Math.log2(spring.count + 1);
      spring.a.vx += (dx / d) * pull; spring.a.vy += (dy / d) * pull;
      spring.b.vx -= (dx / d) * pull; spring.b.vy -= (dy / d) * pull;
    }
    for (const node of nodes) {
      node.vx += (node.ax - node.x) * 0.035;
      node.vy += (node.ay - node.y) * 0.035;
      if (node.id === "you") { node.vx = (center.x - node.x) * 0.5; node.vy = (center.y - node.y) * 0.5; }
      node.x = Math.max(70, Math.min(SW - 70, node.x + node.vx * heat));
      node.y = Math.max(80, Math.min(SH - 60, node.y + node.vy * heat));
      node.vx *= 0.6;
      node.vy *= 0.6;
    }
    // Keep bubbles from overlapping: each node needs room for itself and its name.
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = (b.y - a.y) * 0.8;
        const d = Math.hypot(dx, dy) || 1;
        if (d >= 96) continue;
        const push = (96 - d) / 2;
        const fixedA = a.id === "you";
        const fixedB = b.id === "you";
        if (!fixedA) { a.x -= (dx / d) * push * (fixedB ? 2 : 1); a.y -= (dy / d) * push * (fixedB ? 2 : 1); }
        if (!fixedB) { b.x += (dx / d) * push * (fixedA ? 2 : 1); b.y += (dy / d) * push * (fixedA ? 2 : 1); }
      }
    }
  }
  starNodes = byId;
  starLinks = (S.flows?.links || []).filter((link) => byId.has(link.from) && byId.has(link.to));
}
function starCurve(from, to) {
  const a = starNodes.get(from);
  const b = starNodes.get(to);
  if (!a || !b) return null;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const d = Math.hypot(dx, dy) || 1;
  const bend = Math.min(60, d * 0.16);
  const trim = 30;
  const c = { x: (a.x + b.x) / 2 + (dy / d) * bend, y: (a.y + b.y) / 2 - (dx / d) * bend };
  const toward = (p, q, r) => {
    const l = Math.hypot(q.x - p.x, q.y - p.y) || 1;
    return { x: p.x + ((q.x - p.x) / l) * r, y: p.y + ((q.y - p.y) / l) * r };
  };
  return { a: toward(a, c, trim), c, b: toward(b, c, trim) };
}
function renderStars() {
  const signature = JSON.stringify([starIds(), S.flows?.links.map((l) => [l.from, l.to, l.count]), S.office.wings, S.office.agents.map((a) => [a.id, a.look]), S.lang]);
  const svg = $("#stars");
  if (signature !== starsSig) {
    layoutStars();
    starsSig = signature;
    let html = '<g class="stars-bg">';
    for (let i = 0; i < 46; i++) {
      const seed = hashOf(`star${i}`);
      const s2 = 0.5 + (seed % 4) * 0.25;
      const shape = seed % 3 ? "M0 -5q.8 4.2 5 5q-4.2 .8-5 5q-.8 -4.2-5 -5q4.2 -.8 5 -5z" : "M0 3l-5 -4.6a3 3 0 0 1 5 -3.6 3 3 0 0 1 5 3.6z";
      html += `<path class="tw-star" style="animation-delay:${-(seed % 30) / 10}s" transform="translate(${seed % SW} ${(seed >> 11) % SH}) scale(${s2})" d="${shape}" opacity="${0.4 + (seed % 5) / 10}"/>`;
    }
    html += "</g>";
    S.office.wings.forEach((wing, i) => {
      const members = S.office.agents.filter((agent) => agent.wingId === wing.id).map((agent) => starNodes.get(agent.id)).filter(Boolean);
      if (!members.length) return;
      const cx = members.reduce((n, node) => n + node.x, 0) / members.length;
      const top = Math.min(...members.map((node) => node.y));
      html += `<text class="cluster-label" x="${cx}" y="${Math.max(24, top - 58)}" text-anchor="middle" fill="var(${SECTION_VARS[i % SECTION_VARS.length]})">${esc(roomName(wing))}</text>`;
    });
    html += '<g id="star-edges">';
    const pairs = new Map();
    for (const link of starLinks) {
      const key = [link.from, link.to].sort().join("|");
      pairs.set(key, (pairs.get(key) || 0) + link.count);
    }
    for (const [key, count] of pairs) {
      const [a, b] = key.split("|");
      const na = starNodes.get(a);
      const nb = starNodes.get(b);
      html += `<path class="edge" data-a="${esc(a)}" data-b="${esc(b)}" d="M${na.x} ${na.y}L${nb.x} ${nb.y}" stroke-width="${(1 + Math.sqrt(count) * 1.3).toFixed(1)}"/>`;
    }
    html += '</g><g id="star-particles"></g><g id="star-nodes">';
    for (const [id, node] of starNodes) {
      const index = sectionIndex(id);
      const ring = colorVar(id);
      const scale = kindOf(id) === "agent" ? 0.66 : 0.6;
      html += `<g class="node" data-id="${esc(id)}" tabindex="0" role="button" aria-label="${esc(nameOf(id))}" transform="translate(${node.x.toFixed(1)} ${node.y.toFixed(1)})">
        <circle class="halo" r="36" fill="${ring}"/><circle r="36" fill="none" stroke="${ring}" stroke-width="2.4" stroke-dasharray="${index < 0 ? "2 6" : "1 0"}" stroke-linecap="round" opacity=".7"/>
        <g transform="translate(0 22) scale(${scale})">${actorArt(id)}</g>
        <text class="label" y="52" text-anchor="middle">${esc(cut(nameOf(id), 16))}</text></g>`;
    }
    html += '</g><g id="stars-fx"></g>';
    svg.innerHTML = html;
    $$(".node", svg).forEach((node) => bindActor(node, node.dataset.id));
  }
  for (const node of $$(".node", svg)) {
    const agent = agentOf(node.dataset.id);
    const creature = node.querySelector(".creature");
    creature.classList.remove("st-idle", "st-writing", "st-researching", "st-executing", "st-syncing", "st-error");
    creature.classList.add(`st-${agent ? agent.state : "idle"}`);
  }
  paintStarsFocus();
}
function paintStarsFocus() {
  const svg = $("#stars");
  const focus = S.replay ? new Set(S.replay.flow.participants) : S.hover ? neighbourSet(S.hover) : null;
  for (const node of $$(".node", svg)) node.classList.toggle("dim", Boolean(focus && !focus.has(node.dataset.id)));
  for (const edge of $$(".edge", svg)) {
    const lit = !focus || (S.replay ? focus.has(edge.dataset.a) && focus.has(edge.dataset.b) : edge.dataset.a === S.hover || edge.dataset.b === S.hover);
    edge.classList.toggle("dim", !lit);
  }
}
function drawParticles(now) {
  const layer = $("#star-particles");
  if (!layer || S.view !== "stars") return;
  let html = "";
  for (const link of starLinks) {
    if (S.replay) break;
    if (S.hover && link.from !== S.hover && link.to !== S.hover) continue;
    const q = starCurve(link.from, link.to);
    if (!q) continue;
    const n = Math.min(6, Math.max(1, Math.round(Math.sqrt(link.count) * 1.4)));
    const period = 4200 - Math.min(2400, link.count * 80);
    for (let k = 0; k < n; k++) {
      const t = ((now / period) + k / n + (hashOf(link.from + link.to) % 100) / 100) % 1;
      const p = qPoint(q, t);
      html += `<path class="particle" transform="translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})" d="M0 2.6l-4.3 -4a2.6 2.6 0 0 1 4.3 -3.1 2.6 2.6 0 0 1 4.3 3.1z" fill="${colorVar(link.from)}" opacity="${Math.sin(Math.PI * t).toFixed(2)}"/>`;
    }
  }
  layer.innerHTML = html;
}

// ================================================================= track

function trackLanes() {
  if (S.replay) return S.replay.flow.participants;
  const ids = ["you"];
  const agents = [...S.office.agents].sort((a, b) => (sectionIndex(a.id) + 1) * 100 + a.slot - ((sectionIndex(b.id) + 1) * 100 + b.slot));
  ids.push(...agents.map((agent) => agent.id));
  if ((S.flows?.flows || []).some((flow) => flow.trigger.kind === "automation")) ids.push("automation");
  const linked = new Set();
  for (const link of S.flows?.links || []) linked.add(link.from).add(link.to);
  for (const item of S.flows?.external || []) if (linked.has(item.id)) ids.push(item.id);
  return ids;
}
const TRACK = { LANE: 34, TOP: 38, LEFT: 168 };
function laneLabel(id, y) {
  return `<g transform="translate(26 ${y + 13}) scale(.3)">${actorArt(id)}</g><text class="lane-name" x="46" y="${y + 4}">${esc(cut(nameOf(id), 14))}</text>`;
}
function renderTrack() {
  const box = $("#track");
  const width = Math.max(680, box.clientWidth || $("#stage-body").clientWidth);
  const lanes = trackLanes();
  const laneY = new Map(lanes.map((id, i) => [id, TRACK.TOP + i * TRACK.LANE + TRACK.LANE / 2]));
  if (S.replay) return renderSequence(box, width, lanes, laneY);
  const height = TRACK.TOP + lanes.length * TRACK.LANE + 16;
  const now = Date.now();
  const start = now - S.hours * 3600e3;
  const x = (ms) => TRACK.LEFT + ((ms - start) / (now - start)) * (width - TRACK.LEFT - 24);
  let html = "";
  lanes.forEach((id, i) => {
    const y = TRACK.TOP + i * TRACK.LANE;
    if (i % 2 === 0) html += `<rect class="lane-bg" x="0" y="${y}" width="${width}" height="${TRACK.LANE}" rx="6"/>`;
    html += laneLabel(id, y + TRACK.LANE / 2);
  });
  const tickMs = S.hours <= 24 ? 3 * 3600e3 : S.hours <= 168 ? 24 * 3600e3 : 5 * 24 * 3600e3;
  const first = Math.ceil(start / tickMs) * tickMs;
  for (let t = first; t <= now - tickMs * 0.25; t += tickMs) {
    const d = new Date(t);
    const label = S.hours <= 24 ? `${String(d.getHours()).padStart(2, "0")}:00` : `${d.getMonth() + 1}/${d.getDate()}`;
    html += `<path class="gridline" d="M${x(t)} ${TRACK.TOP - 6}V${height - 10}"/><text class="axis" x="${x(t)}" y="${TRACK.TOP - 12}" text-anchor="middle">${label}</text>`;
  }
  html += `<path class="now-line" d="M${x(now)} ${TRACK.TOP - 6}V${height - 10}"/><text class="axis" x="${x(now) - 4}" y="${TRACK.TOP - 12}" text-anchor="end" fill="var(--accent)">${esc(t("track.now"))}</text>`;
  for (const flow of [...(S.flows?.flows || [])].reverse()) {
    const color = colorVar(flow.rootAgentId);
    let paths = "";
    let dots = "";
    for (const step of replaySteps(flow)) {
      const y1 = laneY.get(step.from);
      const y2 = laneY.get(step.to);
      if (y1 == null || y2 == null) continue;
      const sx = x(step.at || flow.startedAt);
      paths += `<path d="M${sx.toFixed(1)} ${y1}Q${(sx + 16).toFixed(1)} ${(y1 + y2) / 2} ${sx.toFixed(1)} ${y2}" stroke="${color}"/>`;
      dots += `<circle cx="${sx.toFixed(1)}" cy="${y1}" r="3" fill="${color}" opacity=".6"/><circle cx="${sx.toFixed(1)}" cy="${y2}" r="4.2" fill="${color}"/>`;
    }
    html += `<g class="thread" data-flow="${flow.id}">${paths}${dots}</g>`;
  }
  box.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="${esc(t("view.track"))}">${html}<g id="track-fx"></g></svg>`;
  for (const thread of $$(".thread", box)) {
    const flow = S.flows.flows.find((item) => item.id === thread.dataset.flow);
    thread.addEventListener("mouseenter", (event) => {
      $$(".thread", box).forEach((other) => other.classList.toggle("dim", other !== thread));
      thread.classList.add("hot");
      showTip(`<b>${esc(cut(flowAsk(flow), 60))}</b><div class="soft">${clock(flow.startedAt)} · ${t("track.tip", { handoffs: flow.handoffCount, people: flow.participants.length })}</div>`, event.clientX, event.clientY, thread);
    });
    thread.addEventListener("mouseleave", () => {
      $$(".thread", box).forEach((other) => other.classList.remove("dim", "hot"));
      hideTip();
    });
    thread.addEventListener("click", () => startReplay(flow));
  }
}
function renderSequence(box, width, lanes, laneY) {
  const steps = S.replay.steps;
  const col = Math.max(64, (width - TRACK.LEFT - 30) / steps.length);
  const fullWidth = Math.max(width, TRACK.LEFT + col * steps.length + 30);
  const height = TRACK.TOP + lanes.length * TRACK.LANE + 20;
  let html = "";
  lanes.forEach((id, i) => {
    const y = TRACK.TOP + i * TRACK.LANE;
    if (i % 2 === 0) html += `<rect class="lane-bg" x="0" y="${y}" width="${fullWidth}" height="${TRACK.LANE}" rx="6"/>`;
    html += `<path class="lifeline" d="M${TRACK.LEFT - 10} ${y + TRACK.LANE / 2}H${fullWidth - 10}"/>` + laneLabel(id, y + TRACK.LANE / 2);
  });
  const start = S.replay.flow.startedAt;
  steps.forEach((step, i) => {
    const sx = TRACK.LEFT + col * (i + 0.5);
    const y1 = laneY.get(step.from);
    const y2 = laneY.get(step.to);
    const color = colorVar(step.from);
    const dir = y2 > y1 ? 1 : -1;
    html += `<g class="seq-step" data-step="${i}"><rect x="${sx - col / 2}" y="${TRACK.TOP}" width="${col}" height="${height - TRACK.TOP}" fill="transparent"/>
      <text class="seq-time" x="${sx}" y="${TRACK.TOP - 12}" text-anchor="middle">${plus((step.at || start) - start)}</text>
      <circle cx="${sx}" cy="${y1}" r="4" fill="${color}"/>
      <path class="arrow" d="M${sx} ${y1}V${y2 - dir * 6}" stroke="${color}"/>
      <path d="M${sx - 6} ${y2 - dir * 10}L${sx} ${y2 - dir * 2}L${sx + 6} ${y2 - dir * 10}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></g>`;
  });
  box.innerHTML = `<svg viewBox="0 0 ${fullWidth} ${height}" width="${fullWidth}" height="${height}" role="img" aria-label="${esc(t("track.sequence"))}">${html}<g id="track-fx"></g></svg>`;
  for (const node of $$(".seq-step", box)) node.addEventListener("click", () => { S.replay.playing = false; goToStep(Number(node.dataset.step)); });
  paintSequence();
}
function paintSequence() {
  if (!S.replay) return;
  for (const node of $$("#track .seq-step")) {
    const i = Number(node.dataset.step);
    node.classList.toggle("current", i === S.replay.index);
    node.classList.toggle("future", i > S.replay.index);
  }
}
function trackCurve(step, index) {
  const svg = $("#track svg");
  if (!svg || !S.replay) return null;
  const lanes = trackLanes();
  const width = Number(svg.getAttribute("width"));
  const col = Math.max(64, (Math.max(680, $("#track").clientWidth) - TRACK.LEFT - 30) / S.replay.steps.length);
  const sx = TRACK.LEFT + col * (index + 0.5);
  const y = (id) => TRACK.TOP + lanes.indexOf(id) * TRACK.LANE + TRACK.LANE / 2;
  if (lanes.indexOf(step.from) < 0 || lanes.indexOf(step.to) < 0 || !width) return null;
  return { a: { x: sx, y: y(step.from) }, c: { x: sx + 26, y: (y(step.from) + y(step.to)) / 2 }, b: { x: sx, y: y(step.to) } };
}

// ================================================================= flights

function qPath(q) {
  return `M${q.a.x.toFixed(1)} ${q.a.y.toFixed(1)}Q${q.c.x.toFixed(1)} ${q.c.y.toFixed(1)} ${q.b.x.toFixed(1)} ${q.b.y.toFixed(1)}`;
}
function qPoint(q, t) {
  const u = 1 - t;
  return { x: u * u * q.a.x + 2 * u * t * q.c.x + t * t * q.b.x, y: u * u * q.a.y + 2 * u * t * q.c.y + t * t * q.b.y };
}
function qAngle(q, t) {
  const dx = 2 * (1 - t) * (q.c.x - q.a.x) + 2 * t * (q.b.x - q.c.x);
  const dy = 2 * (1 - t) * (q.c.y - q.a.y) + 2 * t * (q.b.y - q.c.y);
  return (Math.atan2(dy, dx) * 180) / Math.PI;
}
function curveFor(step, index) {
  if (S.view === "studio") return studioCurve(step.from, step.to);
  if (S.view === "stars") return starCurve(step.from, step.to);
  return trackCurve(step, index);
}
function fxLayer() {
  return S.view === "studio" ? $("#studio-fx") : S.view === "stars" ? $("#stars-fx") : $("#track-fx");
}
function planeMarkup(q, t, color) {
  const p = qPoint(q, t);
  const angle = qAngle(q, t);
  const tilt = Math.max(-35, Math.min(35, angle > 90 || angle < -90 ? 180 + angle : angle));
  return `<g transform="translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) rotate(${(tilt * 0.6).toFixed(0)}) scale(1.1)">${planeSVG(color)}</g>`;
}
function creatureOf(id) {
  const scope = S.view === "studio" ? "#studio-actors" : S.view === "stars" ? "#star-nodes" : null;
  return scope ? $(`${scope} [data-id="${CSS.escape(id)}"] .creature`) : null;
}
function react(id, cls) {
  const creature = creatureOf(id);
  if (!creature) return;
  creature.classList.remove(cls);
  void creature.getBBox();
  creature.classList.add(cls);
  setTimeout(() => creature.classList.remove(cls), 800);
}
function say(id, text, other) {
  // When two bots talk side by side, push each bubble outward and stagger heights so both stay readable.
  let dx = 0;
  let dy = 0;
  if (other && S.view === "studio") {
    const map = studioPositions();
    const me = map.get(id);
    const them = map.get(other);
    if (me && them && Math.abs(me.x - them.x) < 200 && Math.abs(me.y - them.y) < 90) {
      dx = me.x <= them.x ? -46 : 46;
      dy = beat && id === beat.step.from ? -22 : 0;
    }
  }
  if (S.view === "studio" && text) {
    // Keep the bubble inside the scene.
    const me = studioPositions().get(id);
    const half = speechHalfWidth(text) + 10;
    if (me) dx = Math.max(12 + half - me.x, Math.min(ST.W - 12 - half - me.x, dx));
  }
  setSpeech(creatureOf(id), text, dx, dy);
}
function hushAll() {
  $$(".creature.talking").forEach((creature) => setSpeech(creature, ""));
}

// ================================================================= beats
// A beat is one interaction: the sender walks over (studio only), tosses the letter, both talk.

const WALK_MS = 1300;
const HOP_MS = 650;

let beat = null;
const visits = new Map();

function speakLine(text, from) {
  if (text === "•••") return "•••";
  if (isWillowPlaceholder(text)) return t("willow.hidden");
  let clean = String(text || "").replace(/^[^：:\s]{1,24}[：:]\s*/, "");
  const name = from ? nameOf(from) : "";
  for (let i = 0; i < 2 && name && clean.startsWith(name); i++) clean = clean.slice(name.length).replace(/^[\s：:，,]+/, "");
  return cut(clean || "…", 14);
}
function walkerOf(step) {
  if (step.kind === "visit") return step.from;
  if (step.from === "automation") return null;
  return step.from;
}
function spotNear(target, walker) {
  const base = studioPositions(true);
  const t = base.get(target);
  const home = base.get(walker);
  if (!t || !home) return null;
  const side = home.x <= t.x ? -1 : 1;
  const x = Math.max(60, Math.min(ST.W - 60, t.x + side * 60));
  return { x, y: t.y, mode: "visit" };
}
function startBeat(step, index, source, opts = {}) {
  const speed = S.replay?.speed || 1;
  const walker = S.view === "studio" ? walkerOf(step) : null;
  for (const id of [...visits.keys()]) if (id !== walker) visits.delete(id);
  let walkMs = 0;
  if (walker) {
    const spot = spotNear(step.to, walker);
    const current = visits.get(walker);
    if (spot) {
      walkMs = current && Math.hypot(current.x - spot.x, current.y - spot.y) < 4 ? 0 : WALK_MS;
      visits.set(walker, spot);
    }
  }
  const hopMs = step.kind === "visit" ? 0 : S.view === "studio" ? HOP_MS : FLY_MS;
  const text = step.text || "";
  const holdMs = source === "replay" ? HOLD_MS + Math.min(1800, text.length * 9) : 1900;
  hushAll();
  beat = { step, index, source, walkMs, hopMs, holdMs, phase: walkMs ? "walk" : hopMs ? "hop" : "hold", elapsed: 0, speed, ...opts };
  if (S.view === "studio") renderStudio();
  if (beat.phase === "hop") enterHop();
  if (beat.phase === "hold") enterHold();
  if (opts.jumpToHold) {
    beat.elapsed = walkMs + hopMs;
    beat.phase = "hold";
    enterHold();
  }
}
function enterHop() {
  const { step } = beat;
  react(step.from, "toss");
  if (step.from !== "automation") say(step.from, speakLine(step.text, step.from), step.to);
}
function enterHold() {
  const { step } = beat;
  react(step.to, "catch");
  if (step.kind === "visit") {
    say(step.from, step.lines[0], step.to);
    say(step.to, step.lines[1], step.from);
  } else {
    if (step.from !== "automation") say(step.from, speakLine(step.text, step.from), step.to);
    const acks = tList("speech.acks");
    const ack = step.kind === "reply" ? t("speech.thanks") : step.from === "automation" ? t("speech.alarm") : acks[Math.abs(Math.round(step.at || 0)) % acks.length];
    say(step.to, ack, step.from);
  }
  beat.onHold?.();
}
function tickBeat(delta) {
  if (!beat) return;
  if (beat.source === "replay" && !S.replay?.playing) return;
  beat.elapsed += delta * (beat.source === "replay" ? S.replay.speed : 1);
  if (beat.phase === "walk" && beat.elapsed >= beat.walkMs) {
    beat.phase = beat.hopMs ? "hop" : "hold";
    if (beat.phase === "hop") enterHop(); else enterHold();
  }
  if (beat.phase === "hop" && beat.elapsed >= beat.walkMs + beat.hopMs) {
    beat.phase = "hold";
    enterHold();
  }
  if (beat.phase === "hold" && beat.elapsed >= beat.walkMs + beat.hopMs + beat.holdMs) {
    const done = beat;
    beat = null;
    done.onDone?.();
  }
}
function endScene(delay = 900) {
  hushAll();
  setTimeout(() => {
    if (beat) return;
    visits.clear();
    if (S.view === "studio" && S.office) renderStudio();
  }, delay);
}
function beatFx() {
  if (!beat) return "";
  const { step, index } = beat;
  const q = curveFor(step, index);
  if (!q) return "";
  const color = colorVar(step.from);
  if (beat.phase === "hop") {
    const t = Math.min(1, (beat.elapsed - beat.walkMs) / beat.hopMs);
    const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
    return `<path class="trail" d="${qPath(q)}" stroke="${color}" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="${(1 - eased).toFixed(3)}"/>${planeMarkup(q, eased, color)}`;
  }
  if (beat.phase === "hold" && step.kind !== "visit") return `<path class="trail" d="${qPath(q)}" stroke="${color}" opacity=".45"/>`;
  return "";
}
function drawFx() {
  const layer = fxLayer();
  if (!layer) return;
  let html = "";
  if (S.replay) {
    S.replay.steps.forEach((step, i) => {
      if (i >= S.replay.index) return;
      const q = curveFor(step, i);
      if (q) html += `<path class="trail old" d="${qPath(q)}" stroke="${colorVar(step.from)}"/>`;
    });
  }
  layer.innerHTML = html + beatFx();
}

// ================================================================= replay

function startReplay(flow, index = 0) {
  stopAmbient();
  S.replay = { flow, steps: replaySteps(flow), index, playing: true, speed: S.replay?.speed || 1, typed: 0 };
  $("#replay-bar").hidden = false;
  $("#scrubber").hidden = false;
  $("#narration").classList.remove("idle");
  renderStage();
  showFlowDetail(flow);
  goToStep(index, "start");
  if (location.hash !== `#flow=${flow.id}`) history.replaceState(null, "", `#flow=${flow.id}`);
}
function stopReplay() {
  if (!S.replay) return;
  S.replay = null;
  beat = null;
  $("#replay-bar").hidden = true;
  $("#scrubber").hidden = true;
  idleNarration();
  hideFlowDetail();
  endScene(0);
  renderStage();
  ambient.nextAt = performance.now() + 3000;
  if (location.hash.startsWith("#flow=")) history.replaceState(null, "", location.pathname + location.search);
}
function goToStep(index, mode = "jump") {
  const replay = S.replay;
  if (!replay) return;
  replay.index = Math.max(0, Math.min(replay.steps.length - 1, index));
  replay.typed = 0;
  startBeat(replay.steps[replay.index], replay.index, "replay", {
    jumpToHold: mode === "jump" || REDUCED,
    onHold: () => { replay.typed = 0; paintReplay(); },
    onDone: () => {
      if (S.replay !== replay) return;
      if (replay.index < replay.steps.length - 1) goToStep(replay.index + 1, "next");
      else {
        replay.playing = false;
        paintReplay();
      }
    },
  });
  if (mode === "jump" || REDUCED) replay.typed = 9999;
  paintReplay();
}
function phaseOfReplay() {
  return beat && beat.source === "replay" ? beat.phase : "hold";
}
function paintReplay() {
  const replay = S.replay;
  if (!replay) return;
  const step = replay.steps[replay.index];
  $("#replay-title").innerHTML = `${esc(stepSentence(step))}<small>${t("replay.leg", { i: replay.index + 1, n: replay.steps.length })} · ${clock(step.at || replay.flow.startedAt)}</small>`;
  $("#replay-play").textContent = replay.playing ? "❚❚" : "▶";
  $("#replay-play").setAttribute("aria-label", replay.playing ? t("replay.pause") : t("replay.play"));
  $("#replay-speed").textContent = `${replay.speed}×`;
  $("#scrubber").innerHTML = replay.steps.map((s, i) => `<button type="button" class="${i < replay.index ? "done" : ""} ${i === replay.index ? "current" : ""}" data-step="${i}" title="${esc(stepSentence(s))}" aria-label="${esc(t("replay.jump", { i: i + 1 }))}"></button>`).join("") + `<span>${replay.index + 1}/${replay.steps.length}</span>`;
  paintNarration();
  paintSequence();
  paintRelay();
}
function paintNarration() {
  const replay = S.replay;
  if (!replay) return;
  const step = replay.steps[replay.index];
  const text = stepText(step);
  const phase = phaseOfReplay();
  const shown = phase === "hold" ? text.slice(0, Math.floor(replay.typed)) : "";
  const typing = phase === "hold" && shown.length < text.length;
  const waiting = phase === "walk" ? t("replay.walking", { name: nameOf(step.from) }) : phase === "hop" ? t("replay.passing") : "";
  $("#narration").innerHTML = `${avatar(step.from, 40)}<div style="min-width:0"><div class="who">${esc(nameOf(step.from))} <span class="muted">${esc(stepVerb(step))}</span> ${esc(nameOf(step.to))}</div><p>${esc(shown)}${typing ? '<span class="caret"></span>' : ""}${waiting ? `<span class="muted">${esc(waiting)}</span>` : ""}</p></div>`;
}
function tickReplayText(delta) {
  const replay = S.replay;
  if (!replay || !replay.playing || phaseOfReplay() !== "hold") return;
  const before = Math.floor(replay.typed);
  replay.typed += (delta * replay.speed) / 9;
  if (Math.floor(replay.typed) !== before) paintNarration();
}
let lastPhase = "";
function watchPhase() {
  const phase = S.replay ? phaseOfReplay() : "";
  if (phase !== lastPhase) {
    lastPhase = phase;
    if (S.replay) paintNarration();
  }
}

// ================================================================= ambient show, live events, partner visits

function idleNarration() {
  const node = $("#narration");
  node.classList.add("idle");
  node.textContent = S.ambient ? t("narration.idle") : t("narration.off");
}
function stopAmbient() {
  ambient.queue = [];
  ambient.flowId = null;
  if (beat && beat.source !== "replay") beat = null;
  $$(".flow-card.ambient").forEach((card) => card.classList.remove("ambient"));
  if (!S.replay) {
    idleNarration();
    endScene(0);
  }
}
function queueLive(steps, flow) {
  if (S.replay || S.view === "track") return;
  const items = steps.map((step) => ({ step, index: 0, source: "live", flow }));
  ambient.queue = [...items, ...ambient.queue.filter((item) => item.source === "live")];
  if (beat && beat.source === "ambient") beat = null;
}
function ambientCaption(item) {
  const { step } = item;
  const tag = item.source === "live" ? `<span class="chip live">${t("chip.live")}</span> ` : step.kind === "visit" ? `<span class="chip">${t("chip.visit")}</span> ` : `<span class="muted">${t("chip.ambient")} · </span>`;
  const sentence = step.kind === "visit" ? t("visit.sentence", { a: nameOf(step.from), b: nameOf(step.to) }) : stepSentence(step);
  const body = step.kind === "visit" ? t("visit.body", { n: step.count }) : cut(stepText(step), 90);
  $("#narration").classList.remove("idle");
  $("#narration").innerHTML = `${avatar(step.from, 36)}<div style="min-width:0"><div class="who">${tag}${esc(sentence)}</div><p>${esc(body)}</p></div>`;
}
function partnerVisit() {
  const pairs = new Map();
  for (const link of S.flows?.links || []) {
    if (!agentOf(link.from) || !agentOf(link.to)) continue;
    const key = [link.from, link.to].sort().join("|");
    pairs.set(key, (pairs.get(key) || 0) + link.count);
  }
  const ranked = [...pairs].sort((a, b) => b[1] - a[1]).slice(0, 6);
  if (!ranked.length) return null;
  const [key, count] = ranked[ambient.visitIndex++ % ranked.length];
  let [a, b] = key.split("|");
  if (isBusy(agentOf(a)) && !isBusy(agentOf(b))) [a, b] = [b, a];
  const chats = tList("speech.chats");
  const lines = chats[(ambient.visitIndex + count) % chats.length];
  return { kind: "visit", from: a, to: b, at: Date.now(), text: "", lines, count, depth: 0 };
}
function tickAmbient(now) {
  if (S.replay || document.hidden || S.view === "track") return;
  if (beat) return;
  if (ambient.queue.length) {
    const item = ambient.queue.shift();
    ambientCaption(item);
    startBeat(item.step, item.index, item.source, {
      onDone: () => {
        if (!ambient.queue.length) {
          endScene(600);
          setTimeout(() => !beat && !ambient.queue.length && !S.replay && idleNarration(), 2400);
          $$(".flow-card.ambient").forEach((card) => card.classList.remove("ambient"));
        }
      },
    });
    return;
  }
  if (!S.ambient || now < ambient.nextAt) return;
  ambient.round = (ambient.round || 0) + 1;
  if (S.view === "studio" && ambient.round % 3 === 0) {
    const visit = partnerVisit();
    if (visit) {
      ambient.queue = [{ step: visit, index: 0, source: "ambient" }];
      ambient.nextAt = now + 7000;
      return;
    }
  }
  const flows = (S.flows?.flows || []).slice(0, 8);
  if (!flows.length) return;
  const flow = flows[ambient.flowIndex++ % flows.length];
  ambient.queue = replaySteps(flow).slice(0, 6).map((step, i) => ({ step, index: i, source: "ambient" }));
  ambient.flowId = flow.id;
  $$(".flow-card").forEach((card) => card.classList.toggle("ambient", card.dataset.flow === flow.id));
  ambient.nextAt = now + 6000;
}

// ================================================================= frame loop

function renderStage() {
  if (!S.office) return;
  const boxEmpty = S.office.source?.box && S.office.source.empty;
  $("#stage-hint").textContent = S.replay ? "" : boxEmpty ? t("box.empty") : t(`hint.${S.view}`);
  if (S.view === "studio") renderStudio();
  if (S.view === "stars") renderStars();
  if (S.view === "track") renderTrack();
}
function setView(view) {
  S.view = view;
  if (beat && beat.source !== "replay") beat = null;
  ambient.queue = [];
  visits.clear();
  for (const name of ["studio", "stars", "track"]) $(`#${name}`).toggleAttribute("hidden", name !== view);
  $$("[data-view]").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.view === view)));
  hideTip();
  renderStage();
  if (S.replay) goToStep(S.replay.index, "jump");
  else idleNarration();
}
let lastFrame = performance.now();
function frame(now) {
  const delta = Math.min(100, now - lastFrame);
  lastFrame = now;
  if (S.office) {
    tickBeat(delta);
    tickReplayText(delta);
    watchPhase();
    tickAmbient(now);
    if (!REDUCED) drawParticles(now);
    drawFx();
  }
  requestAnimationFrame(frame);
}
