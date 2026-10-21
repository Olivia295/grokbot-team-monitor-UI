// Big-screen mode for an office TV (?tv=1 or /tv) and a chrome-less stream overlay (?overlay=1).
//   ?tv=1&rotate=30&views=studio,stars,track,neck   rotate views every 30 s
//   ?overlay=1&view=studio                           transparent background, stage only (OBS browser source)

const TV = (() => {
  const params = new URLSearchParams(location.search);
  const overlay = params.get("overlay") === "1";
  const active = overlay || params.get("tv") === "1" || /\/tv\/?$/.test(location.pathname);
  const allowed = ["studio", "stars", "track", "neck"];
  const views = (params.get("views") || (overlay ? params.get("view") || "studio" : "studio,stars,track,neck"))
    .split(",").map((item) => item.trim()).filter((item) => allowed.includes(item));
  return { active, overlay, views: views.length ? views : ["studio"], rotate: Number(params.get("rotate")) || 0, index: 0, nextAt: 0, idleTimer: 0 };
})();

function initTV() {
  if (!TV.active) return;
  document.body.classList.add(TV.overlay ? "overlay" : "tv");
  if (!TV.overlay) {
    $("#tv-bar").hidden = false;
    $("#tv-ticker").hidden = false;
    $("#tv-logo").innerHTML = logoSVG(30);
    $("#tv-title").textContent = t("app.title");
    $("#tv-full").addEventListener("click", () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen?.().catch(() => {});
    });
    // Hide the cursor when nobody is touching the mouse.
    addEventListener("pointermove", () => {
      document.body.classList.remove("tv-still");
      clearTimeout(TV.idleTimer);
      TV.idleTimer = setTimeout(() => document.body.classList.add("tv-still"), 3000);
    });
    setInterval(tvClock, 1000);
    tvClock();
  }
  S.ambient = true;
  const seconds = TV.rotate || S.settings.tvSeconds || 20;
  TV.rotate = Math.max(5, seconds);
  showTVView(TV.views[0]);
  TV.nextAt = Date.now() + TV.rotate * 1000;
  if (TV.views.length > 1) setInterval(tickTV, 1000);
}
function showTVView(view) {
  document.body.classList.toggle("tv-neck", view === "neck");
  if (view !== "neck" && view !== S.view) setView(view);
  if (view === "neck") renderBottleneck();
  if (!TV.overlay) $("#tv-view").textContent = view === "neck" ? t("neck.title") : t(`view.${view}`);
}
function tickTV() {
  if (Date.now() < TV.nextAt || S.replay) return;
  // Let a live handoff finish before switching away.
  if (typeof beat !== "undefined" && beat && beat.source === "live") return;
  TV.index = (TV.index + 1) % TV.views.length;
  showTVView(TV.views[TV.index]);
  TV.nextAt = Date.now() + TV.rotate * 1000;
}
function tvClock() {
  const now = new Date();
  $("#tv-clock").textContent = now.toLocaleTimeString(S.lang === "zh" ? "zh-CN" : "en-US", { hour: "2-digit", minute: "2-digit" });
}
function renderTV() {
  if (!TV.active || TV.overlay) return;
  const agents = S.office?.agents || [];
  const busy = agents.filter(isBusy).length;
  const live = S.flows?.activeCount || 0;
  const today = S.insights?.digest?.[0];
  $("#tv-kpis").innerHTML = [
    [live, t("tv.live")], [busy, t("tv.busy")], [today ? today.handoffs : 0, t("tv.today")],
  ].map(([value, label]) => `<span><b>${value}</b>${esc(label)}</span>`).join("");
  const feed = (S.insights?.feed || []).slice(0, 12);
  const items = feed.map((item) => `<span class="tick">${avatar(item.kind === "ask" ? item.to : item.from, 22)}${feedSentence(item)}<time>${ago(item.at)}</time></span>`).join("");
  const track = $("#tv-track");
  const sig = feed.map((item) => item.at).join(",");
  if (track.dataset.sig !== sig) {
    track.dataset.sig = sig;
    // Two copies so the marquee loops seamlessly.
    track.innerHTML = items + items;
    track.style.setProperty("--ticker", `${Math.max(30, feed.length * 6)}s`);
  }
}
