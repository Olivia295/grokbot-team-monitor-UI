// Tabs under the studio: Overview, Team, Collaboration and (on a Grok Bot box) Host.
// One panel at a time. The choice is remembered per browser and can be linked as #tab=team.

const TAB_KEY = "bot-monitor.tab";
const TAB_IDS = ["overview", "team", "collab", "host"];

function tabAvailable(id) {
  return id !== "host" || S.dataMode === "internal";
}
function currentTab() {
  const linked = location.hash.match(/^#tab=(\w+)$/)?.[1];
  let saved = null;
  try { saved = localStorage.getItem(TAB_KEY); } catch { /* private window */ }
  return [linked, saved, "overview"].find((id) => TAB_IDS.includes(id) && tabAvailable(id));
}
// Charts measure their box, so redraw what lives in a panel once it is visible.
function drawTab(id) {
  if (id === "overview") {
    if (typeof renderStatusBoard === "function") renderStatusBoard();
    if (typeof renderAttention === "function") renderAttention();
  } else if (id === "team") {
    if (typeof renderInternal === "function") renderInternal();
    if (typeof renderRoster === "function") renderRoster();
  } else if (id === "collab") {
    if (typeof renderBottleneck === "function") renderBottleneck();
    if (typeof renderInternal === "function") renderInternal();
  } else if (id === "host" && typeof renderHostStatus === "function") {
    renderHostStatus();
  }
}
function selectTab(id, { focus = false, link = false } = {}) {
  if (!TAB_IDS.includes(id) || !tabAvailable(id)) id = "overview";
  S.tab = id;
  for (const button of $$("#page-tabs [data-tab]")) {
    const on = button.dataset.tab === id;
    button.setAttribute("aria-selected", String(on));
    button.tabIndex = on ? 0 : -1;
    if (on && focus) button.focus();
  }
  for (const tab of TAB_IDS) {
    const panel = $(`#tab-${tab}`);
    if (panel) panel.hidden = tab !== id;
  }
  try { localStorage.setItem(TAB_KEY, id); } catch { /* private window */ }
  if (link) history.replaceState(null, "", `#tab=${id}`);
  drawTab(id);
}
// The Host tab only exists while reading a box; called whenever the read mode settles.
function syncTabs() {
  const host = $("#tab-btn-host");
  if (host) host.hidden = !tabAvailable("host");
  selectTab(S.tab && tabAvailable(S.tab) ? S.tab : currentTab());
}

$("#page-tabs")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (button) selectTab(button.dataset.tab, { link: true });
});
$("#page-tabs")?.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = $$("#page-tabs [data-tab]").filter((button) => !button.hidden);
  const at = tabs.findIndex((button) => button.dataset.tab === S.tab);
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (at + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  selectTab(tabs[next].dataset.tab, { focus: true, link: true });
});
addEventListener("hashchange", () => {
  const linked = location.hash.match(/^#tab=(\w+)$/)?.[1];
  if (linked && linked !== S.tab) selectTab(linked);
});
