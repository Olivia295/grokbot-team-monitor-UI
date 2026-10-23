// Guided tour: one spotlight at a time over the real page, with Back / Next / Skip.
// The online demo starts it on a first visit; everywhere else it only opens from the ? button.

const TOUR_KEY = "bot-monitor.tour";
// A step with a tab opens that tab under the studio before pointing at something in it.
const TOUR_STEPS = [
  { target: "#connection", key: "mode" },
  { target: ".strip", key: "hero" },
  { target: ".stage", key: "stage" },
  { target: "#side-list", key: "relays" },
  { target: "#page-tabs", key: "tabs" },
  { target: "#tab-overview .insight", key: "insights", tab: "overview" },
  { target: "#bottleneck-card", key: "neck", tab: "collab" },
  // The demo keeps the box table behind the Team tab's switch, so point at the switch there.
  { target: "#internal-panel", demo: "#team-view", key: "box", tab: "team" },
  { target: ".bell-wrap", key: "alerts" },
  { target: 'a[href="settings.html"].icon-btn', key: "settings" },
];
const tour = { index: -1, steps: [], last: null, tab: null };

function tourVisible(node) {
  return node && !node.closest("[hidden]") && node.getClientRects().length > 0;
}
const stepTarget = (step) => (STATIC && step.demo) || step.target;
function tourTarget(step) {
  const node = document.querySelector(step.box || stepTarget(step));
  return tourVisible(node) ? node : null;
}
// Shown, or only waiting behind its tab.
function tourAvailable(step) {
  const node = document.querySelector(stepTarget(step));
  if (!node || (step.tab && typeof tabAvailable === "function" && !tabAvailable(step.tab))) return false;
  const panel = step.tab ? $(`#tab-${step.tab}`) : null;
  for (let at = node; at && at !== document.body; at = at.parentElement) if (at.hidden && at !== panel) return false;
  return true;
}
function startTour() {
  tour.steps = TOUR_STEPS.filter(tourAvailable);
  if (!tour.steps.length) return;
  tour.last = document.activeElement;
  tour.tab = S.tab;
  if (!$("#tour")) {
    document.body.insertAdjacentHTML("beforeend", `<div class="tour" id="tour" hidden>
      <div class="tour-spot" id="tour-spot"></div>
      <div class="tour-card card" id="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text" tabindex="-1">
        <p class="tour-count muted" id="tour-count"></p>
        <h3 id="tour-title"></h3>
        <p id="tour-text"></p>
        <div class="tour-actions">
          <button type="button" class="ghost" id="tour-skip"></button>
          <span class="spacer"></span>
          <button type="button" class="small-btn" id="tour-back"></button>
          <button type="button" class="primary-btn" id="tour-next"></button>
        </div>
      </div>
    </div>`);
    $("#tour-skip").addEventListener("click", () => endTour());
    $("#tour-back").addEventListener("click", () => showTourStep(tour.index - 1));
    $("#tour-next").addEventListener("click", () => (tour.index >= tour.steps.length - 1 ? endTour() : showTourStep(tour.index + 1)));
    $("#tour").addEventListener("click", (event) => { if (event.target.id === "tour" || event.target.id === "tour-spot") endTour(); });
  }
  $("#tour").hidden = false;
  document.body.classList.add("touring");
  addEventListener("keydown", tourKeys, true);
  addEventListener("resize", placeTour);
  addEventListener("scroll", placeTour, true);
  showTourStep(0);
}
function showTourStep(index) {
  if (index < 0 || index >= tour.steps.length) return;
  tour.index = index;
  const step = tour.steps[index];
  const prefix = STATIC && t(`tour.${step.key}.demo`) !== `tour.${step.key}.demo` ? ".demo" : "";
  $("#tour-count").textContent = t("tour.count", { n: index + 1, total: tour.steps.length });
  $("#tour-title").textContent = t(`tour.${step.key}.title`);
  $("#tour-text").textContent = t(`tour.${step.key}${prefix}`);
  $("#tour-skip").textContent = t("tour.skip");
  $("#tour-back").textContent = t("tour.back");
  $("#tour-back").hidden = index === 0;
  $("#tour-next").textContent = index === tour.steps.length - 1 ? t("tour.done") : t("tour.next");
  if (step.tab && S.tab !== step.tab) selectTab(step.tab);
  const node = tourTarget(step);
  node?.scrollIntoView({ block: "center", behavior: REDUCED ? "auto" : "smooth" });
  placeTour();
  // Scrolling settles over a few frames; place again once it has.
  for (const wait of REDUCED ? [0] : [420, 900]) setTimeout(placeTour, wait);
  $("#tour-card").focus({ preventScroll: true });
}
function placeTour() {
  if (tour.index < 0) return;
  const node = tourTarget(tour.steps[tour.index]);
  const spot = $("#tour-spot");
  const card = $("#tour-card");
  if (!node) return;
  const pad = 8;
  const r = node.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const top = Math.max(4, r.top - pad);
  const left = Math.max(4, r.left - pad);
  const width = Math.min(vw - 8, r.width + pad * 2);
  const height = Math.min(innerHeight - 8 - top, r.bottom + pad - top);
  Object.assign(spot.style, { top: `${top}px`, left: `${left}px`, width: `${width}px`, height: `${Math.max(24, height)}px` });
  // Phones: the card is a sheet at the bottom. Wider screens: beside the spotlight, below or above it.
  if (vw < 640) {
    Object.assign(card.style, { top: "", left: "", bottom: "12px" });
    return;
  }
  const cw = Math.min(380, vw - 32);
  const ch = card.offsetHeight || 200;
  if (r.height > innerHeight * 0.55) {
    // A tall area: keep its top (titles, tabs) in view and park the card in the bottom corner.
    Object.assign(card.style, { top: `${innerHeight - ch - 20}px`, left: `${vw - cw - 20}px`, bottom: "" });
    return;
  }
  let y = r.bottom + pad + 12;
  if (y + ch > innerHeight - 12) y = r.top - pad - 12 - ch;
  if (y < 12) y = Math.max(12, Math.min(innerHeight - ch - 12, r.top + 12));
  const x = Math.max(16, Math.min(vw - cw - 16, r.left));
  Object.assign(card.style, { top: `${y}px`, left: `${x}px`, bottom: "" });
}
function tourKeys(event) {
  if (event.key === "Escape") { event.preventDefault(); endTour(); }
  else if (event.key === "ArrowRight") { event.preventDefault(); $("#tour-next").click(); }
  else if (event.key === "ArrowLeft" && tour.index > 0) { event.preventDefault(); showTourStep(tour.index - 1); }
  else if (event.key === "Tab") {
    // Keep focus inside the card while it's open.
    const items = [...$("#tour-card").querySelectorAll("button:not([hidden])")];
    const at = items.indexOf(document.activeElement);
    event.preventDefault();
    items[(at + (event.shiftKey ? -1 : 1) + items.length) % items.length]?.focus();
  }
}
function endTour() {
  if (tour.index < 0) return;
  tour.index = -1;
  $("#tour").hidden = true;
  document.body.classList.remove("touring");
  removeEventListener("keydown", tourKeys, true);
  removeEventListener("resize", placeTour);
  removeEventListener("scroll", placeTour, true);
  try { localStorage.setItem(TOUR_KEY, "seen"); } catch { /* private window: it may show again next visit */ }
  if (tour.tab && S.tab !== tour.tab) selectTab(tour.tab);
  (tour.last && document.contains(tour.last) ? tour.last : $("#tour-btn"))?.focus({ preventScroll: true });
}
function tourSeen() {
  try { return localStorage.getItem(TOUR_KEY) === "seen"; } catch { return false; }
}

$("#tour-btn")?.addEventListener("click", startTour);
