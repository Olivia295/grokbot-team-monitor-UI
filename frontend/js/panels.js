// Everything around the stage: hero, awards, flow list, partners, feed, relay detail,
// insight cards, roster and the profile drawer.

function greeting() {
  const h = new Date().getHours();
  return t(h < 5 ? "greet.late" : h < 11 ? "greet.morning" : h < 14 ? "greet.noon" : h < 18 ? "greet.afternoon" : "greet.evening");
}

function renderHero() {
  const office = S.office;
  const flows = S.flows;
  const totals = S.insights?.totals;
  if (!office) return;
  const busy = office.agents.filter(isBusy);
  $("#greeting").textContent = `${greeting()} · ${t("hero.count", { n: office.agents.length })}`;
  const live = flows?.activeCount || 0;
  $("#hero-title").innerHTML = live ? t(live === 1 ? "hero.liveOne" : "hero.live", { n: `<em>${live}</em>` }) : busy.length ? esc(t("hero.busy", { n: busy.length })) : esc(t("hero.idle"));
  $("#tiles").innerHTML = [
    [flows?.flowCount ?? "—", t("tile.flows", { window: windowLabel(S.hours) })],
    [flows?.handoffCount ?? "—", t("tile.handoffs")],
    [totals ? number(totals.replies) : "—", t("tile.replies")],
    [totals ? number(totals.chars) : "—", t("tile.chars")],
  ].map(([value, text]) => `<div class="tile"><b>${value}</b><span>${esc(text)}</span></div>`).join("");
  renderHeroArt();
  const usage = office.usage;
  if (usage) {
    const left = Math.max(0, 100 - usage.percentUsed);
    const days = usage.nextResetMs ? Math.max(0, Math.ceil((usage.nextResetMs - Date.now()) / 86400e3)) : null;
    const level = left > 40 ? "" : left > 15 ? "low" : "empty";
    const r = 30;
    const dash = (2 * Math.PI * r * left) / 100;
    $("#fuel").innerHTML = `<h3>${icon("bolt")} ${t("fuel.title")}</h3>
      <div class="jar"><svg viewBox="0 0 76 76" role="img" aria-label="${esc(t("fuel.aria", { n: Math.round(left) }))}">
        <circle cx="38" cy="38" r="${r}" fill="none" stroke="var(--line)" stroke-width="8"/>
        <circle class="ring ${level}" cx="38" cy="38" r="${r}" fill="none" stroke-width="8" stroke-linecap="round" stroke-dasharray="${dash.toFixed(1)} 999" transform="rotate(-90 38 38)"/>
        <text x="38" y="43" text-anchor="middle" class="ring-text">${Math.round(left)}%</text></svg></div>
      <div class="big">${Math.round(left)}<small>% ${t("fuel.left")}</small></div>
      <p>${esc(usage.plan || "Grok")}${days == null ? "" : ` · ${days ? t("fuel.reset", { n: days }) : t("fuel.resetToday")}`}</p>
      <p>${t(left > 40 ? "fuel.ok" : left > 15 ? "fuel.low" : "fuel.empty")}</p>`;
  } else {
    $("#fuel").innerHTML = `<h3>${icon("bolt")} ${t("fuel.title")}</h3><p style="grid-column:1/-1">${t("fuel.none")}</p>`;
  }
}

function renderHeroArt() {
  const office = S.office;
  if (!office) return;
  const busy = office.agents.filter(isBusy);
  const cast = [...busy, ...office.agents.filter((agent) => !isBusy(agent)).sort((a, b) => b.lastActivityAt - a.lastActivityAt)].slice(0, 3);
  const signature = cast.map((agent) => agent.id + agent.state + JSON.stringify(agent.look)).join();
  const host = $("#hero-art");
  if (host.dataset.sig === signature) return;
  host.dataset.sig = signature;
  const spots = [[60, 128, 1], [135, 120, 1.15], [210, 128, 1]];
  host.innerHTML = `<svg viewBox="0 0 270 140"><ellipse cx="135" cy="128" rx="120" ry="12" fill="var(--ink)" opacity=".06"/>
    ${cast.map((agent, i) => `<g transform="translate(${spots[i][0]} ${spots[i][1]}) scale(${spots[i][2] * 0.95})">${creatureSVG(agent)}</g>`).join("")}</svg>`;
  cast.forEach((agent, i) => host.querySelectorAll(".creature")[i]?.classList.add(`st-${agent.state}`));
}

let headlineIndex = 0;
function feedSentence(item) {
  const b = (id, fallback) => `<b>${esc(id && nameOf(id) !== t("who.external") ? nameOf(id) : fallback || nameOf(id))}</b>`;
  if (item.kind === "handoff") return t("feed.handoff", { from: b(item.from), to: b(item.to, item.toName) });
  if (item.kind === "reply") return t("feed.reply", { from: b(item.from) });
  if (item.kind === "ask") return t("feed.ask", { to: b(item.to) });
  const action = ["created", "updated", "deleted", "enabled", "disabled"].includes(item.action) ? item.action : "updated";
  return t(`feed.auto.${action}`, { from: b(item.from), name: esc(item.text) });
}
function rotateHeadline() {
  const feed = S.insights?.feed || [];
  if (!feed.length) return;
  const item = feed[headlineIndex++ % Math.min(6, feed.length)];
  const node = $("#headline");
  node.classList.add("fade");
  setTimeout(() => {
    node.innerHTML = `${avatar(item.kind === "ask" ? item.to : item.from, 26)}<span>${feedSentence(item)} · <span class="muted">${ago(item.at)}</span></span>`;
    node.classList.remove("fade");
  }, REDUCED ? 0 : 350);
}

function awardBlurb(award) {
  const v = award.value;
  switch (award.key) {
    case "quickdraw": return t("award.quickdraw.blurb", { n: Math.max(1, Math.round(v / 1000)) });
    case "nightowl":
    case "earlybird": return t(`award.${award.key}.blurb`, { n: Math.round(v * 100) });
    case "newcomer": { const d = new Date(v); return t("award.newcomer.blurb", { date: `${d.getMonth() + 1}/${d.getDate()}` }); }
    case "chatterbox": return t("award.chatterbox.blurb", { n: number(v) });
    default: return t(`award.${award.key}.blurb`, { n: v });
  }
}
function renderAwards() {
  const awards = S.insights?.awards || [];
  if (S.insights?.totals.since) $("#awards-note").textContent = t("awards.note", { since: clock(S.insights.totals.since) });
  $("#awards").innerHTML = awards.map((award) => `<li><button type="button" class="award" data-profile="${esc(award.id)}"><span class="medal" aria-hidden="true">★</span>${avatar(award.id, 56)}<span><b>${award.emoji} ${esc(t(`award.${award.key}.label`))}</b><span class="who">${esc(nameOf(award.id))}</span><span class="why">${esc(awardBlurb(award))}</span></span></button></li>`).join("") || `<li class="muted">${t("awards.none")}</li>`;
}

// ---------------------------------------------------------------- flows & feed

function flowMatches(flow) {
  if (S.filter === "user") return flow.trigger.kind === "user";
  if (S.filter === "automation") return flow.trigger.kind === "automation";
  if (S.filter === "active") return flow.active;
  return true;
}
function chainMarkup(flow, limit = 8) {
  const ids = flow.participants.filter((id) => id !== "you" || flow.trigger.kind === "user");
  const shown = ids.slice(0, limit);
  const back = flow.steps.some((step) => step.kind === "reply") && !shown.includes("you");
  return `<span class="chain">${shown.map((id) => avatar(id, 30)).join("")}${back ? avatar("you", 30) : ""}${ids.length > limit ? `<span class="more">+${ids.length - limit}</span>` : ""}</span>`;
}
function renderFlowList() {
  if (!S.flows) return;
  const flows = S.flows.flows.filter(flowMatches);
  $("#flow-count").textContent = S.flows.flowCount ? `${S.flows.flowCount}` : "";
  const list = $("#flow-list");
  if (!flows.length) {
    if (S.office?.source?.box && S.office.source.empty) {
      list.innerHTML = `<li class="empty">${esc(t("box.empty"))}</li>`;
      return;
    }
    list.innerHTML = `<li class="empty">${t(S.filter === "all" ? "flows.none" : "flows.noneFiltered")}${S.hours < 720 ? `<br><button type="button" data-widen>${t("flows.widen")}</button>` : ""}</li>`;
    return;
  }
  list.innerHTML = flows.map((flow) => `<li><button type="button" class="flow-card ${ambient.flowId === flow.id ? "ambient" : ""}" data-flow="${flow.id}">
      <span class="meta">${flow.active ? `<span class="chip live">${t("chip.active")}</span>` : ""}${triggerChip(flow)}<span>${ago(flow.endedAt)}</span><span>· ${t("flows.handoffs", { n: flow.handoffCount })}</span><span>· ${span(flow.endedAt - flow.startedAt)}</span></span>
      <span class="ask">${esc(flowAsk(flow))}</span>
      ${chainMarkup(flow)}
    </button></li>`).join("");
}
function renderFeed() {
  const feed = S.insights?.feed || [];
  const icons = { handoff: "📨", reply: "💬", ask: "🙋", automation: "⏰" };
  $("#feed").innerHTML = feed.map((item) => `<li data-profile="${esc(item.kind === "ask" ? item.to : item.from)}">
      <span class="icon">${icons[item.kind]}</span>
      <div style="min-width:0"><div class="what">${feedSentence(item)}</div>${item.kind !== "automation" && item.text ? `<div class="text">${esc(masked(item.text))}</div>` : ""}<time>${ago(item.at)} · ${clock(item.at)}</time></div>
    </li>`).join("") || `<li class="empty">${esc(t(S.office?.source?.box && S.office.source.empty ? "box.empty" : "feed.none"))}</li>`;
}

function showFlowDetail(flow) {
  $("#side-list").hidden = true;
  $("#side-detail").hidden = false;
  $("#detail-meta").textContent = t("detail.meta", { start: clock(flow.startedAt), span: span(flow.endedAt - flow.startedAt) });
  const steps = S.replay.steps;
  const intro = flow.trigger.kind === "user" ? t("detail.youSaid") : flow.trigger.kind === "automation" ? t("detail.auto") : t("detail.agentStarted", { name: nameOf(flow.trigger.agentId) });
  $("#flow-detail").innerHTML = `
    <div class="ask-card"><small>${esc(intro)}</small>${esc(flowAsk(flow))}</div>
    <div class="cast">${flow.participants.map((id) => `<button type="button" ${kindOf(id) === "agent" ? `data-profile="${esc(id)}"` : "disabled"}>${avatar(id, 26)}${esc(nameOf(id))}</button>`).join("")}</div>
    <ol class="relay">${steps.map((step, i) => `<li data-step="${i}" style="--c:${colorVar(step.from)};margin-left:${Math.min(step.depth, 4) * 12}px">
        <div class="row"><span class="t">${plus((step.at || flow.startedAt) - flow.startedAt)}</span>${avatar(step.from, 26)}<span class="muted">→</span>${avatar(step.to, 26)}<span class="who"><b>${esc(nameOf(step.from))}</b> ${esc(stepVerb(step))} <b>${esc(nameOf(step.to))}</b></span></div>
        <div class="text">${esc(stepText(step))}</div>
        ${step.kind === "handoff" && !step.traced ? `<div class="note">${t("detail.untraced")}</div>` : ""}
      </li>`).join("")}</ol>`;
}
function hideFlowDetail() {
  $("#side-detail").hidden = true;
  $("#side-list").hidden = false;
  renderFlowList();
}
function paintRelay() {
  if (!S.replay) return;
  for (const li of $$("#flow-detail .relay li")) {
    const i = Number(li.dataset.step);
    li.classList.toggle("current", i === S.replay.index);
    li.classList.toggle("future", i > S.replay.index);
    if (i === S.replay.index && S.replay.playing) li.scrollIntoView({ block: "nearest", behavior: REDUCED ? "auto" : "smooth" });
  }
}

// ---------------------------------------------------------------- partners

function pairData() {
  const pairs = new Map();
  for (const link of S.flows?.links || []) {
    const [a, b] = [link.from, link.to].sort();
    const pair = pairs.get(`${a}|${b}`) || { a, b, ab: 0, ba: 0, lastAt: 0 };
    if (link.from === a) pair.ab += link.count; else pair.ba += link.count;
    pair.lastAt = Math.max(pair.lastAt, link.lastAt);
    pairs.set(`${a}|${b}`, pair);
  }
  const list = [...pairs.values()].map((pair) => ({ ...pair, total: pair.ab + pair.ba }));
  list.sort((x, y) => y.total - x.total || y.lastAt - x.lastAt);
  for (const pair of list) {
    for (const flow of S.flows.flows) {
      const steps = replaySteps(flow);
      const index = steps.findIndex((step) => step.kind === "handoff" && [step.from, step.to].sort().join("|") === `${pair.a}|${pair.b}`);
      if (index >= 0) {
        pair.flow = flow;
        pair.stepIndex = index;
        pair.quote = steps[index];
        break;
      }
    }
  }
  return list;
}
function renderPairs() {
  if (!S.flows) return;
  const pairs = pairData().slice(0, 20);
  const max = Math.max(1, ...pairs.map((pair) => Math.max(pair.ab, pair.ba)));
  $("#pairs-list").innerHTML = pairs.map((pair) => `<li class="pair">
      <div class="pair-head"><span class="duo">${avatar(pair.a, 34)}${avatar(pair.b, 34)}</span><span class="names">${esc(nameOf(pair.a))} ⇄ ${esc(nameOf(pair.b))}</span><span class="num">${pair.total}</span></div>
      <div class="pair-bars">
        <span>${esc(cut(nameOf(pair.a), 8))} →</span><span class="bar"><i style="width:${(pair.ab / max) * 100}%;background:${colorVar(pair.a)}"></i></span><b>${pair.ab}</b>
        <span>${esc(cut(nameOf(pair.b), 8))} →</span><span class="bar"><i style="width:${(pair.ba / max) * 100}%;background:${colorVar(pair.b)}"></i></span><b>${pair.ba}</b>
      </div>
      ${pair.quote ? `<div class="pair-quote">${esc(nameOf(pair.quote.from))}：${esc(cut(stepText(pair.quote), 70))}</div>` : ""}
      <div class="pair-foot"><span><span class="chip">${t(pair.ab && pair.ba ? "pairs.mutual" : "pairs.oneway")}</span> ${t("pairs.last", { when: ago(pair.lastAt) })}</span>${pair.flow ? `<button type="button" data-pair-replay="${pair.flow.id}" data-step="${pair.stepIndex}">${t("pairs.watch")} ▶</button>` : ""}</div>
    </li>`).join("") || `<li class="empty">${esc(t(S.office?.source?.box && S.office.source.empty ? "box.empty" : "flows.none"))}</li>`;
}

// ---------------------------------------------------------------- insight cards

function renderAttention() {
  if (!S.office) return;
  const items = [];
  for (const agent of S.office.agents) {
    if (agent.detail === "awaiting") items.push({ id: agent.id, icon: "💬", text: t("attn.awaiting", { name: agent.name }), weight: 3 });
    if (agent.state === "error") items.push({ id: agent.id, icon: "⚠️", text: t("attn.error", { name: agent.name }), weight: 4 });
    if (agent.unreadCount > 0) items.push({ id: agent.id, icon: "🔔", text: t("attn.unread", { name: agent.name, n: agent.unreadCount }), weight: 2 });
  }
  const stuck = (S.flows?.flows || []).filter((flow) => flow.active && Date.now() - flow.startedAt > 15 * 60e3);
  for (const flow of stuck) items.push({ flow: flow.id, icon: "⏳", text: t("attn.long", { what: cut(flowAsk(flow), 24) }), weight: 1 });
  items.sort((a, b) => b.weight - a.weight);
  $("#attention").innerHTML = items.length
    ? `<ul class="attn">${items.slice(0, 6).map((item) => `<li><button type="button" ${item.id ? `data-profile="${esc(item.id)}"` : `data-replay="${item.flow}"`}><span class="icon">${item.icon}</span>${item.id ? avatar(item.id, 30) : ""}<span>${esc(item.text)}</span></button></li>`).join("")}</ul>`
    : `<p class="all-good">✅ ${t("attn.none")}</p>`;
  $("#attention-count").textContent = items.length ? String(items.length) : "";
}

let digestDay = 0;
function renderDigest() {
  const digest = S.insights?.digest;
  if (!digest) return;
  const day = digest[digestDay];
  const other = digest[1 - digestDay];
  const delta = (a, b) => (b == null ? "" : a > b ? `<span class="up">▲ ${a - b}</span>` : a < b ? `<span class="down">▼ ${b - a}</span>` : "");
  const rows = [
    ["digest.outputs", day.outputs, other?.outputs],
    ["digest.handoffs", day.handoffs, other?.handoffs],
    ["digest.asks", day.asks, other?.asks],
    ["digest.bots", day.activeBots, other?.activeBots],
  ];
  $$("[data-digest]").forEach((button) => button.setAttribute("aria-pressed", String(Number(button.dataset.digest) === digestDay)));
  $("#digest").innerHTML = day.outputs + day.asks === 0 ? `<p class="muted">${t("digest.quiet")}</p>` : `
    <div class="digest-grid">${rows.map(([key, value, prev]) => `<div><b>${value}</b><span>${t(key)} ${delta(value, prev)}</span></div>`).join("")}</div>
    <ul class="digest-list">
      ${day.busiest ? `<li>${avatar(day.busiest.id, 26)}<span>${t("digest.busiest", { name: esc(nameOf(day.busiest.id)), n: day.busiest.count })}</span></li>` : ""}
      ${day.topPair ? `<li><span class="duo">${avatar(day.topPair.ids[0], 26)}${avatar(day.topPair.ids[1], 26)}</span><span>${t("digest.pair", { a: esc(nameOf(day.topPair.ids[0])), b: esc(nameOf(day.topPair.ids[1])), n: day.topPair.count })}</span></li>` : ""}
      ${day.first ? `<li><span class="icon">🕘</span><span>${t("digest.span", { from: clock(day.first), to: clock(day.last) })}</span></li>` : ""}
    </ul>`;
}
function digestMarkdown() {
  const day = S.insights.digest[digestDay];
  const title = t(digestDay ? "digest.mdYesterday" : "digest.mdToday");
  const lines = [`## ${title}`, "",
    `- ${t("digest.outputs")}: ${day.outputs}`, `- ${t("digest.handoffs")}: ${day.handoffs}`, `- ${t("digest.asks")}: ${day.asks}`, `- ${t("digest.bots")}: ${day.activeBots}`];
  if (day.busiest) lines.push(`- ${t("digest.busiestPlain", { name: nameOf(day.busiest.id), n: day.busiest.count })}`);
  if (day.topPair) lines.push(`- ${t("digest.pairPlain", { a: nameOf(day.topPair.ids[0]), b: nameOf(day.topPair.ids[1]), n: day.topPair.count })}`);
  if (day.first) lines.push(`- ${t("digest.span", { from: clock(day.first), to: clock(day.last) })}`);
  return lines.join("\n");
}

function renderRhythm() {
  const week = S.insights?.totals.week;
  if (!week) return;
  const max = Math.max(1, ...week.flat());
  const days = tList("weekdays");
  let peak = [0, 0];
  week.forEach((row, d) => row.forEach((n, h) => { if (n > week[peak[0]][peak[1]]) peak = [d, h]; }));
  const cell = 15;
  const left = 34;
  const top = 6;
  let svg = "";
  week.forEach((row, d) => {
    svg += `<text class="axis-label" x="${left - 6}" y="${top + d * (cell + 2) + 11}" text-anchor="end">${days[d]}</text>`;
    row.forEach((n, h) => {
      const level = n ? 0.15 + 0.85 * Math.sqrt(n / max) : 0;
      svg += `<rect class="heat" data-d="${d}" data-h="${h}" x="${left + h * (cell + 2)}" y="${top + d * (cell + 2)}" width="${cell}" height="${cell}" rx="3.5" fill="${n ? "var(--accent)" : "var(--card-2)"}" fill-opacity="${n ? level.toFixed(2) : 1}"/>`;
    });
  });
  for (const h of [0, 6, 12, 18, 23]) svg += `<text class="axis-label" x="${left + h * (cell + 2) + cell / 2}" y="${top + 7 * (cell + 2) + 10}" text-anchor="middle">${h}</text>`;
  const width = left + 24 * (cell + 2);
  const height = top + 7 * (cell + 2) + 16;
  $("#rhythm").innerHTML = `<svg class="chart heatmap" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t("rhythm.aria"))}">${svg}</svg>
    <div class="legend-row"><span>${t("rhythm.low")}</span><i class="ramp"></i><span>${t("rhythm.high")}</span><span class="peak">${max > 1 ? t("rhythm.peak", { day: days[peak[0]], h: peak[1] }) : ""}</span></div>`;
  $$("#rhythm .heat").forEach((node) => {
    node.addEventListener("pointerenter", (event) => {
      const d = Number(node.dataset.d);
      const h = Number(node.dataset.h);
      showTip(`<b>${days[d]} ${h}:00–${h + 1}:00</b><div>${t("rhythm.tip", { n: week[d][h] })}</div>`, event.clientX, event.clientY, node);
    });
    node.addEventListener("pointerleave", hideTip);
  });
}

function renderAutomations() {
  const profiles = S.insights?.profiles || [];
  const active = [];
  const gone = [];
  for (const profile of profiles) {
    for (const auto of profile.automations) (auto.active ? active : gone).push({ ...auto, id: profile.id });
  }
  active.sort((a, b) => b.at - a.at);
  $("#autos-count").textContent = active.length ? String(active.length) : "";
  $("#automations").innerHTML = active.length || gone.length ? `<ul class="autos board">${active.map((auto) => `<li><button type="button" data-profile="${esc(auto.id)}">${avatar(auto.id, 28)}<span class="auto-name">${esc(auto.name)}</span><span class="muted">${esc(nameOf(auto.id))}</span><time>${ago(auto.at)}</time></button></li>`).join("")}</ul>
    ${gone.length ? `<details class="gone-list"><summary>${t("autos.gone", { n: gone.length })}</summary><ul class="autos">${gone.map((auto) => `<li class="gone">${esc(auto.name)} · ${esc(nameOf(auto.id))}</li>`).join("")}</ul></details>` : ""}`
    : `<p class="muted">${t("autos.none")}</p>`;
}

// ---------------------------------------------------------------- roster

function miniBars(days, color) {
  const max = Math.max(1, ...days);
  return `<div class="mini-bars" style="--sec:${color}" role="img" aria-label="${esc(t("roster.bars"))}">${days.map((n) => `<i class="${n ? "" : "zero"}" style="height:${n ? Math.max(12, (n / max) * 100) : 8}%"></i>`).join("")}</div>`;
}
function renderRoster() {
  if (!S.office) return;
  const agents = [...S.office.agents].sort((a, b) => (sectionIndex(a.id) + 1) * 100 + a.slot - ((sectionIndex(b.id) + 1) * 100 + b.slot));
  $("#roster").innerHTML = agents.map((agent) => {
    const profile = profileOf(agent.id);
    const level = levelOf(agent.id);
    return `<button type="button" class="member" data-profile="${esc(agent.id)}" style="--sec-soft:${softVar(agent.id)};--sec:${colorVar(agent.id)}">
      ${avatarSVG(agent, 64)}
      <span style="min-width:0">
        <h3>${level ? `<span class="lv">Lv${level.level}</span> ` : ""}${esc(agent.name)}</h3>
        <span class="sub"><span class="dot" style="background:${colorVar(agent.id)}"></span>${esc(roomName(wingOf(agent)))}${agent.title ? ` · ${esc(agent.title)}` : ""}<span class="state ${isBusy(agent) ? "busy" : ""}">${esc(stateText(agent))}</span></span>
        ${profile ? miniBars(profile.days, colorVar(agent.id)) : ""}
        ${profile ? `<span class="nums">${t("roster.nums", { r: profile.replies, o: profile.handoffsOut, i: profile.handoffsIn })}</span>` : ""}
        ${level ? `<div class="xp" title="${esc(t("roster.xp", { xp: level.xp, next: level.toNext }))}"><i style="width:${Math.round(level.progress * 100)}%"></i></div>` : ""}
      </span>
    </button>`;
  }).join("");
  for (const card of $$("#roster .member")) card.querySelector(".creature")?.classList.add(`st-${agentOf(card.dataset.profile)?.state || "idle"}`);
}

// ---------------------------------------------------------------- profile drawer

function barChart(values, { color, labels, tip, height = 110, peakText }) {
  const width = 420;
  const top = 18;
  const bottom = 18;
  const gap = 2;
  const barW = (width - gap * (values.length - 1)) / values.length;
  const max = Math.max(1, ...values);
  const plotH = height - top - bottom;
  let bars = "";
  values.forEach((v, i) => {
    const h = v ? Math.max(3, (v / max) * plotH) : 0;
    const x = i * (barW + gap);
    const y = top + plotH - h;
    const r = Math.min(4, barW / 2, h);
    const d = h ? `M${x} ${top + plotH}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + barW - r}Q${x + barW} ${y} ${x + barW} ${y + r}V${top + plotH}Z` : "";
    bars += `<g class="bar-hit" data-i="${i}"><rect x="${x}" y="${top}" width="${barW + gap}" height="${plotH}" fill="transparent"/>${d ? `<path class="bar-mark" d="${d}" fill="${color}"/>` : ""}</g>`;
  });
  const peakX = values.indexOf(max) * (barW + gap) + barW / 2;
  const axis = labels.map(([i, text]) => `<text class="axis-label" x="${i * (barW + gap) + barW / 2}" y="${height - 4}" text-anchor="middle">${text}</text>`).join("");
  const svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(peakText || "")}">
    <path class="base" d="M0 ${top + plotH + 0.5}H${width}"/>${bars}${axis}
    ${Math.max(...values) && peakText ? `<text class="peak" x="${Math.min(width - 60, Math.max(60, peakX))}" y="${top - 5}" text-anchor="middle">${esc(peakText)}</text>` : ""}
  </svg>`;
  return { svg, bind: (root) => root.querySelectorAll(".bar-hit").forEach((node) => {
    node.addEventListener("pointerenter", (event) => showTip(tip(Number(node.dataset.i)), event.clientX, event.clientY, node));
    node.addEventListener("pointerleave", hideTip);
  }) };
}

function openProfile(id) {
  const agent = agentOf(id);
  const profile = profileOf(id);
  if (!agent && !profile) return;
  hideTip();
  const color = colorVar(id);
  const days = profile ? Math.max(1, Math.round((Date.now() - (profile.createdAt || profile.firstAt || Date.now())) / 86400e3)) : 0;
  const awards = (S.insights?.awards || []).filter((award) => award.id === id);
  const hours = profile?.hours || Array(24).fill(0);
  const hourChart = barChart(hours, {
    color, labels: [[0, "0"], [6, "6"], [12, "12"], [18, "18"], [23, "23"]],
    tip: (i) => `<b>${i}:00–${i + 1}:00</b><div>${t("profile.outputs", { n: hours[i] })}</div>`,
    peakText: profile?.peakHour != null ? t("profile.peak", { h: profile.peakHour }) : "",
  });
  const dayLabels = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(Date.now() - (13 - i) * 86400e3);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });
  const dayValues = profile?.days || Array(14).fill(0);
  const dayChart = barChart(dayValues, {
    color, labels: [[0, dayLabels[0]], [7, dayLabels[7]], [13, t("time.today")]],
    tip: (i) => `<b>${dayLabels[i]}</b><div>${t("profile.outputs", { n: dayValues[i] })}</div>`,
  });
  const partnerMax = Math.max(1, ...(profile?.partners || []).map((p) => p.count));
  const flows = (S.flows?.flows || []).filter((flow) => flow.participants.includes(id)).slice(0, 6);
  const level = levelOf(id);
  const tiles = profile ? [
    [profile.replies, t("profile.replies")], [profile.handoffsOut, t("profile.out")], [profile.handoffsIn, t("profile.in")],
    [number(profile.chars), t("profile.chars")], [profile.medianResponseMs != null ? span(profile.medianResponseMs) : "—", t("profile.speed")],
    [profile.automations.filter((a) => a.active).length, t("profile.autos")],
  ] : [];
  $("#profile-body").innerHTML = `
    <div class="p-hero" style="--sec-soft:${softVar(id)}"><span class="pedestal">${avatarSVG(lookAgent(id), 120)}</span><div style="min-width:0">
      <h2 id="profile-name">${esc(nameOf(id))}</h2>
      <div class="sub">${agent?.title ? `<span class="p-title">${esc(agent.title)}</span>` : ""}<span class="dot" style="background:${color}"></span>${esc(agent ? roomName(wingOf(agent)) : t("profile.notInOffice"))}${days ? ` · ${t("profile.days", { n: days })}` : ""}</div>
      <div class="sub">${agent ? `<span class="state ${isBusy(agent) ? "busy" : ""}">${esc(stateText(agent))}</span> ${esc(detailText(agent))}` : ""}${agent?.lastActivityAt ? ` · ${t("profile.last", { when: ago(agent.lastActivityAt) })}` : ""}</div>
      ${level ? `<div class="p-xp"><span class="lv">Lv${level.level}</span><div class="xp"><i style="width:${Math.round(level.progress * 100)}%"></i></div><span>${t("profile.toNext", { n: level.toNext })}</span></div>` : ""}
      <a class="btn-link" href="/settings#bot=${encodeURIComponent(id)}">🎨 ${t("profile.customize")}</a>
    </div></div>
    <div class="p-inner">
    ${profile?.description ? `<p class="p-desc" id="p-desc">${esc(masked(profile.description))}</p><button type="button" class="ghost" id="p-more">${t("profile.more")}</button>` : ""}
    ${awards.length ? `<div class="p-section"><div class="badges">${awards.map((a) => `<span>${a.emoji} ${esc(t(`award.${a.key}.label`))} · ${esc(awardBlurb(a))}</span>`).join("")}</div></div>` : ""}
    ${tiles.length ? `<div class="p-tiles">${tiles.map(([v, label]) => `<div><b>${v}</b><span>${esc(label)}</span></div>`).join("")}</div>` : ""}
    <div class="p-section"><h3>${t("profile.hours")}</h3><div id="chart-hours">${hourChart.svg}</div></div>
    <div class="p-section"><h3>${t("profile.twoWeeks")}</h3><div id="chart-days">${dayChart.svg}</div></div>
    ${profile?.partners.length ? `<div class="p-section"><h3>${t("profile.partners")}</h3><ol class="partners" style="--sec:${color}">${profile.partners.map((p) => `<li>${avatar(p.id, 30)}<span class="name">${esc(nameOf(p.id))}</span><span class="track-bar"><i style="width:${(p.count / partnerMax) * 100}%"></i></span><b>${p.count}</b></li>`).join("")}</ol></div>` : ""}
    ${profile?.automations.length ? `<div class="p-section"><h3>${t("profile.autosTitle")}</h3><ul class="autos">${profile.automations.map((a) => `<li class="${a.active ? "" : "gone"}">⏰ ${esc(a.name)}<time>${a.active ? "" : `${t("autos.deleted")} · `}${ago(a.at)}</time></li>`).join("")}</ul></div>` : ""}
    ${flows.length ? `<div class="p-section"><h3>${t("profile.flows")}</h3><ul class="p-flows">${flows.map((flow) => `<li><button type="button" data-replay="${flow.id}">${triggerChip(flow)} ${esc(cut(flowAsk(flow), 46))} <span class="muted">· ${ago(flow.endedAt)}</span></button></li>`).join("")}</ul></div>` : ""}
    </div>`;
  hourChart.bind($("#chart-hours"));
  dayChart.bind($("#chart-days"));
  $("#p-more")?.addEventListener("click", (event) => {
    const open = $("#p-desc").classList.toggle("open");
    event.target.textContent = t(open ? "profile.less" : "profile.more");
  });
  $("#profile-body .p-hero .creature")?.classList.add(`st-${agent?.state || "idle"}`);
  const dialog = $("#profile");
  if (!dialog.open) dialog.showModal();
}

// ---------------------------------------------------------------- live toasts

function showToast(step) {
  const box = $("#toasts");
  const node = document.createElement("div");
  node.className = "toast";
  node.style.setProperty("--c", colorVar(step.from));
  node.innerHTML = `${avatar(step.from, 34)}<div style="min-width:0"><b>${esc(stepSentence(step))}</b><span>${esc(cut(stepText(step), 60))}</span></div>`;
  box.prepend(node);
  while (box.children.length > 3) box.lastElementChild.remove();
  setTimeout(() => {
    node.classList.add("out");
    setTimeout(() => node.remove(), 320);
  }, 5200);
}
