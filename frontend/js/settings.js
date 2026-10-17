// Settings page: every change saves straight to data/settings.json on this machine.

const PARTS = [
  ["shape", () => AV.shapes],
  ["color", () => AV.colorNames],
  ["eyes", () => AV.eyes],
  ["mouth", () => AV.mouths],
  ["hat", () => AV.hats],
  ["item", () => AV.items],
  ["outfit", () => AV.outfits],
];
let editing = null;
let part = "shape";
let previewState = "idle";
let savedTimer;

function flashSaved(ok = true) {
  const node = $("#saved");
  node.textContent = ok ? `✓ ${t("settings.saved")}` : t("settings.saveFailed");
  node.dataset.ok = String(ok);
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => (node.textContent = ""), 2200);
}
async function save(patch) {
  try {
    await saveSettings(patch);
    flashSaved(true);
  } catch {
    flashSaved(false);
  }
}

// ---------------------------------------------------------------- general / privacy / data

function fillControls() {
  for (const control of $$("[data-setting]")) {
    const value = S.settings[control.dataset.setting];
    if (control.type === "checkbox") control.checked = Boolean(value);
    else control.value = String(value ?? "");
  }
}
for (const control of $$("[data-setting]")) {
  control.addEventListener("change", async () => {
    const key = control.dataset.setting;
    let value = control.type === "checkbox" ? control.checked : control.value;
    if (control.hasAttribute("data-number")) value = Number(value);
    await save({ [key]: value });
    if (key === "language") render();
    if (key === "dataSource" || key === "supportDir" || key === "language") await loadOffice();
  });
}

let office = null;
async function loadOffice() {
  try {
    office = await getJson("/api/office");
    S.office = office;
  } catch {
    office = null;
  }
  renderSource();
  renderRooms();
  renderPicker();
  if (editing) renderEditor();
}
function renderSource() {
  const node = $("#source-status");
  if (!office) {
    node.textContent = t("pill.error");
    return;
  }
  const source = office.source;
  $("#supportDir").placeholder = source.supportDir || t("set.folderAuto");
  node.innerHTML = source.demo
    ? `🧪 ${esc(t("set.statusDemo"))}`
    : `✅ ${esc(t("set.statusGrok", { n: office.roster.length, path: source.supportDir }))}`;
}

// ---------------------------------------------------------------- rooms

function roomEntries() {
  const rooms = office?.allRooms || [];
  const settings = S.settings.rooms || {};
  return rooms
    .map((room, index) => ({ ...room, ...(settings[room.id] || {}), base: room.name, order: settings[room.id]?.order ?? index }))
    .sort((a, b) => a.order - b.order);
}
function renderRooms() {
  const list = $("#room-list");
  const rooms = roomEntries();
  if (!rooms.length) {
    list.innerHTML = `<li class="muted">${t("set.noRooms")}</li>`;
    return;
  }
  list.innerHTML = rooms.map((room, i) => `<li data-room="${esc(room.id)}">
      <span class="room-dot" style="background:var(${SECTION_VARS[i % SECTION_VARS.length]})"></span>
      <input type="text" maxlength="40" value="${esc(room.name && room.name !== room.base ? room.name : "")}" placeholder="${esc(roomName({ id: room.id, name: room.base }))}" aria-label="${esc(t("set.roomName"))}">
      <button type="button" data-move="-1" aria-label="${esc(t("set.up"))}" ${i === 0 ? "disabled" : ""}>↑</button>
      <button type="button" data-move="1" aria-label="${esc(t("set.down"))}" ${i === rooms.length - 1 ? "disabled" : ""}>↓</button>
      <label class="switch small"><input type="checkbox" data-room-hide ${room.hidden ? "" : "checked"}><span></span><b>${t("set.show")}</b></label>
    </li>`).join("");
}
function roomPatch(id, change) {
  const rooms = structuredClone(S.settings.rooms || {});
  rooms[id] = { ...(rooms[id] || {}), ...change };
  for (const key of Object.keys(rooms[id])) if (rooms[id][key] === "" || rooms[id][key] === false) delete rooms[id][key];
  return rooms;
}
$("#room-list").addEventListener("change", (event) => {
  const row = event.target.closest("[data-room]");
  if (!row) return;
  const id = row.dataset.room;
  if (event.target.matches("input[type=text]")) save({ rooms: roomPatch(id, { name: event.target.value.trim() }) });
  if (event.target.matches("[data-room-hide]")) save({ rooms: roomPatch(id, { hidden: !event.target.checked }) });
});
$("#room-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-move]");
  if (!button) return;
  const rooms = roomEntries();
  const index = rooms.findIndex((room) => room.id === button.closest("[data-room]").dataset.room);
  const target = index + Number(button.dataset.move);
  if (target < 0 || target >= rooms.length) return;
  [rooms[index], rooms[target]] = [rooms[target], rooms[index]];
  const next = structuredClone(S.settings.rooms || {});
  rooms.forEach((room, order) => (next[room.id] = { ...(next[room.id] || {}), order }));
  await save({ rooms: next });
  renderRooms();
});

// ---------------------------------------------------------------- bots & looks

function rosterBot(id) {
  return office?.roster.find((bot) => bot.id === id) || null;
}
function botAgent(id, look) {
  const bot = rosterBot(id) || { id, name: id };
  return { ...bot, originalName: bot.name, look: look ?? (S.settings.bots?.[id]?.look || {}) };
}
function renderPicker() {
  const picker = $("#bot-picker");
  const bots = (office?.roster || []).filter((bot) => !bot.sidebarHidden);
  picker.innerHTML = bots.map((bot) => {
    const custom = S.settings.bots?.[bot.id] || {};
    return `<button type="button" class="pick ${editing === bot.id ? "active" : ""}" data-pick="${esc(bot.id)}">
      ${avatarSVG(botAgent(bot.id), 56)}<span>${esc(custom.alias || bot.name)}</span>${custom.hidden ? `<small>${t("set.hiddenTag")}</small>` : ""}</button>`;
  }).join("") || `<p class="muted">${t("set.noBots")}</p>`;
}
$("#bot-picker").addEventListener("click", (event) => {
  const button = event.target.closest("[data-pick]");
  if (!button) return;
  editing = button.dataset.pick;
  history.replaceState(null, "", `#bot=${encodeURIComponent(editing)}`);
  renderPicker();
  renderEditor();
  $("#editor").scrollIntoView({ behavior: "smooth", block: "nearest" });
});

function currentLook() {
  return lookFor(botAgent(editing));
}
function botPatch(change) {
  const bots = structuredClone(S.settings.bots || {});
  const entry = { ...(bots[editing] || {}), ...change };
  if (!entry.alias) delete entry.alias;
  if (!entry.hidden) delete entry.hidden;
  if (!entry.look || !Object.keys(entry.look).length) delete entry.look;
  if (Object.keys(entry).length) bots[editing] = entry;
  else delete bots[editing];
  return bots;
}
function renderEditor() {
  const editor = $("#editor");
  if (!editing || !rosterBot(editing)) {
    editor.hidden = true;
    return;
  }
  editor.hidden = false;
  const custom = S.settings.bots?.[editing] || {};
  $("#alias").value = custom.alias || "";
  $("#alias").placeholder = rosterBot(editing).name;
  $("#botHidden").checked = Boolean(custom.hidden);
  $("#preview").innerHTML = `<svg viewBox="-60 -110 120 120" width="220" height="220" aria-hidden="true">${creatureSVG(botAgent(editing))}</svg>`;
  $("#preview .creature").classList.add(`st-${previewState}`);
  $$("[data-preview]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.preview === previewState)));
  $("#part-tabs").innerHTML = PARTS.map(([key]) => `<button type="button" role="tab" data-part="${key}" aria-selected="${key === part}">${t(`part.${key}`)}</button>`).join("");
  const look = currentLook();
  const [, options] = PARTS.find(([key]) => key === part);
  $("#part-grid").innerHTML = options().map((option) => {
    const label = t(`asset.${part}.${option}`);
    return `<button type="button" class="part ${look[part] === option ? "on" : ""}" data-option="${option}" aria-pressed="${look[part] === option}" title="${esc(label)}">
      ${avatarSVG(botAgent(editing), 64, "agent", { [part]: option })}<span>${esc(label)}</span></button>`;
  }).join("");
}
$("#part-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[data-part]");
  if (!tab) return;
  part = tab.dataset.part;
  renderEditor();
});
$("#part-grid").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-option]");
  if (!button) return;
  const look = { ...(S.settings.bots?.[editing]?.look || {}), [part]: button.dataset.option };
  await save({ bots: botPatch({ look }) });
  renderEditor();
  renderPicker();
});
$$("[data-preview]").forEach((button) => button.addEventListener("click", () => {
  previewState = button.dataset.preview;
  renderEditor();
}));
$("#alias").addEventListener("change", async (event) => {
  await save({ bots: botPatch({ alias: event.target.value.trim() }) });
  renderPicker();
});
$("#botHidden").addEventListener("change", async (event) => {
  await save({ bots: botPatch({ hidden: event.target.checked }) });
  renderPicker();
});
$("#randomize").addEventListener("click", async () => {
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const look = Object.fromEntries(PARTS.map(([key, options]) => [key, pick(options())]));
  await save({ bots: botPatch({ look }) });
  renderEditor();
  renderPicker();
});
$("#resetLook").addEventListener("click", async () => {
  await save({ bots: botPatch({ look: {} }) });
  renderEditor();
  renderPicker();
});

function render() {
  fillControls();
  renderSource();
  renderRooms();
  renderPicker();
  renderEditor();
}

(async function boot() {
  ensureAvatarDefs();
  $("#brand-mascot").innerHTML = mascotSVG(50);
  await loadSettings();
  fillControls();
  const match = location.hash.match(/^#bot=(.+)$/);
  if (match) editing = decodeURIComponent(match[1]);
  await loadOffice();
  if (editing) setTimeout(() => $("#bots").scrollIntoView({ block: "start" }), 50);
})();
