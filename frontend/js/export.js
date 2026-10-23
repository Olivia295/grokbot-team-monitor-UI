// Export & share: a weekly report (Markdown or PNG) and an animated GIF of any relay.
// Everything is drawn on a canvas in the browser; nothing leaves the machine.

const EX = {
  bg: "#f7f7f8", card: "#ffffff", ink: "#0d0d0f", ink2: "#5b5d66", line: "#e6e6ea",
  accent: "#2F7FD8", warm: "#E0662E", green: "#1E9A68", violet: "#8A5BD6", rose: "#C9466B",
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
};
const PALETTE = [EX.accent, EX.warm, EX.green, EX.violet, EX.rose];

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
function stamp() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}
function shortDate(ms) {
  return new Date(ms).toLocaleDateString(S.lang === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric" });
}

// ---------------------------------------------------------------- weekly report data

function weekData() {
  const insights = S.insights;
  const week = insights.week || {};
  const days = insights.totals.days.slice(-7);
  const now = Date.now();
  const top = insights.profiles
    .filter((profile) => !profile.hidden && !S.settings.bots?.[profile.id]?.hidden)
    .map((profile) => ({ id: profile.id, outputs: profile.days.slice(-7).reduce((a, b) => a + b, 0) }))
    .filter((row) => row.outputs > 0)
    .sort((a, b) => b.outputs - a.outputs)
    .slice(0, 3);
  return {
    from: now - 6 * 86400e3, to: now, days,
    outputs: days.reduce((a, b) => a + b, 0),
    flows: week.flows || 0, handoffs: week.handoffs || 0,
    activeBots: insights.profiles.filter((profile) => profile.days.slice(-7).some(Boolean)).length,
    top, links: week.topLinks || [], neck: week.bottleneck || {}, hub: week.hub,
  };
}
function weekMarkdown() {
  const w = weekData();
  const lines = [
    `# ${t("week.mdTitle")} · ${shortDate(w.from)} – ${shortDate(w.to)}`, "",
    `- ${t("week.flows")}: **${w.flows}**`,
    `- ${t("digest.handoffs")}: **${w.handoffs}**`,
    `- ${t("digest.outputs")}: **${w.outputs}**`,
    `- ${t("digest.bots")}: **${w.activeBots}**`,
  ];
  if (w.neck.medianWaitMs != null) lines.push(`- ${t("neck.median")}: **${span(w.neck.medianWaitMs)}**`);
  lines.push("", `## ${t("week.daily")}`, "", "| " + w.days.map((_, i) => shortDate(w.from + i * 86400e3)).join(" | ") + " |", "|" + " --- |".repeat(7), "| " + w.days.join(" | ") + " |");
  if (w.top.length) {
    lines.push("", `## ${t("week.top")}`, "");
    w.top.forEach((row, i) => lines.push(`${i + 1}. ${nameOf(row.id)} — ${t("week.outputsN", { n: row.outputs })}`));
  }
  if (w.links.length) {
    lines.push("", `## ${t("week.pairs")}`, "");
    for (const link of w.links) lines.push(`- ${nameOf(link.from)} → ${nameOf(link.to)} ×${link.count}${link.avgWaitMs != null ? ` · ${t("neck.avgShort")} ${span(link.avgWaitMs)}` : ""}`);
  }
  if (w.neck.slowest || w.neck.handoffs) {
    lines.push("", `## ${t("neck.title")}`, "");
    if (w.neck.slowest) lines.push(`- ${t("neck.slowestLink")}: ${nameOf(w.neck.slowest.from)} → ${nameOf(w.neck.slowest.to)} (${span(w.neck.slowest.avgWaitMs)})`);
    if (w.neck.slowestBot) lines.push(`- ${t("neck.slowestBot")}: ${nameOf(w.neck.slowestBot.id)} (${span(w.neck.slowestBot.avgWaitMs)})`);
    lines.push(`- ${t("neck.failure")}: ${pct(w.neck.failureRate)} · ${t("neck.retry")}: ${pct(w.neck.retryRate)}`);
  }
  lines.push("", `_${t("week.footer")}_`);
  return lines.join("\n");
}
function pct(value) {
  return `${Math.round((value || 0) * 1000) / 10}%`;
}

// ---------------------------------------------------------------- canvas helpers

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function fitText(ctx, text, width) {
  const value = String(text || "");
  if (ctx.measureText(value).width <= width) return value;
  let low = 0;
  let high = value.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (ctx.measureText(`${value.slice(0, mid)}…`).width <= width) low = mid;
    else high = mid - 1;
  }
  return `${value.slice(0, low)}…`;
}
function wrapText(ctx, text, width, maxLines) {
  const lines = [];
  let line = "";
  // Split CJK per character and Latin per word.
  const tokens = String(text || "").match(/[⺀-鿿＀-￯]|[^\s⺀-鿿＀-￯]+|\s+/g) || [];
  for (const token of tokens) {
    const next = line + token;
    if (ctx.measureText(next).width > width && line.trim()) {
      lines.push(line.trim());
      line = token.trim() ? token : "";
      if (lines.length === maxLines) break;
    } else line = next;
  }
  if (lines.length < maxLines && line.trim()) lines.push(line.trim());
  if (lines.length === maxLines && tokens.join("").trim().length > lines.join("").length + 1) lines[maxLines - 1] = fitText(ctx, `${lines[maxLines - 1]}…`, width);
  return lines;
}
function drawLogo(ctx, x, y, size) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(size / 64, size / 64);
  ctx.fillStyle = EX.ink;
  roundRect(ctx, 0, 0, 64, 64, 18);
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 3.2;
  roundRect(ctx, 16, 21, 32, 26, 11);
  ctx.stroke();
  ctx.fillStyle = "#fff";
  roundRect(ctx, 24.5, 29, 4, 9, 2);
  ctx.fill();
  roundRect(ctx, 35.5, 29, 4, 9, 2);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(32, 12.5, 3.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(30.5, 14, 3, 7);
  ctx.restore();
}
async function avatarsFor(ids, size) {
  const images = new Map();
  await Promise.all(ids.map(async (id) => images.set(id, await avatarImage(lookAgent(id), size, kindOf(id)))));
  return images;
}

// ---------------------------------------------------------------- weekly PNG

async function weekPNG() {
  const w = weekData();
  const W = 1200;
  const H = 760;
  const scale = 2;
  const canvas = document.createElement("canvas");
  canvas.width = W * scale;
  canvas.height = H * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  const images = await avatarsFor(w.top.map((row) => row.id).concat(w.links.flatMap((link) => [link.from, link.to])), 120);
  ctx.fillStyle = EX.bg;
  ctx.fillRect(0, 0, W, H);

  drawLogo(ctx, 48, 40, 52);
  ctx.fillStyle = EX.ink;
  ctx.font = `800 30px ${EX.font}`;
  ctx.fillText(t("week.mdTitle"), 116, 68);
  ctx.fillStyle = EX.ink2;
  ctx.font = `500 16px ${EX.font}`;
  ctx.fillText(`${t("app.title")} · ${shortDate(w.from)} – ${shortDate(w.to)}`, 116, 92);

  // KPI tiles
  const kpis = [
    [w.flows, t("week.flows")], [w.handoffs, t("digest.handoffs")], [w.outputs, t("digest.outputs")],
    [w.activeBots, t("digest.bots")], [w.neck.medianWaitMs != null ? span(w.neck.medianWaitMs) : "—", t("neck.medianShort")],
  ];
  kpis.forEach(([value, label], i) => {
    const x = 48 + i * 224;
    ctx.fillStyle = EX.card;
    roundRect(ctx, x, 124, 208, 96, 18);
    ctx.fill();
    ctx.strokeStyle = EX.line;
    ctx.stroke();
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.font = `800 34px ${EX.font}`;
    ctx.fillText(fitText(ctx, String(value), 176), x + 18, 174);
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 15px ${EX.font}`;
    ctx.fillText(fitText(ctx, label, 176), x + 18, 202);
  });

  // Daily bars
  ctx.fillStyle = EX.card;
  roundRect(ctx, 48, 244, 664, 300, 20);
  ctx.fill();
  ctx.strokeStyle = EX.line;
  ctx.stroke();
  ctx.fillStyle = EX.ink;
  ctx.font = `700 18px ${EX.font}`;
  ctx.fillText(t("week.daily"), 72, 280);
  const peak = Math.max(1, ...w.days);
  w.days.forEach((value, i) => {
    const bw = 56;
    const x = 84 + i * 88;
    const h = Math.round((value / peak) * 170);
    ctx.fillStyle = i === w.days.length - 1 ? EX.accent : "#9cc3ee";
    roundRect(ctx, x, 494 - h, bw, Math.max(h, 3), 8);
    ctx.fill();
    ctx.fillStyle = EX.ink;
    ctx.font = `700 14px ${EX.font}`;
    ctx.textAlign = "center";
    ctx.fillText(String(value), x + bw / 2, 486 - h);
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 13px ${EX.font}`;
    ctx.fillText(shortDate(w.from + i * 86400e3), x + bw / 2, 518);
    ctx.textAlign = "left";
  });

  // Top bots
  ctx.fillStyle = EX.card;
  roundRect(ctx, 736, 244, 416, 300, 20);
  ctx.fill();
  ctx.strokeStyle = EX.line;
  ctx.stroke();
  ctx.fillStyle = EX.ink;
  ctx.font = `700 18px ${EX.font}`;
  ctx.fillText(t("week.top"), 760, 280);
  w.top.forEach((row, i) => {
    const y = 304 + i * 76;
    const image = images.get(row.id);
    if (image) ctx.drawImage(image, 760, y, 64, 64);
    ctx.fillStyle = EX.ink;
    ctx.font = `700 20px ${EX.font}`;
    ctx.fillText(fitText(ctx, `${["🥇", "🥈", "🥉"][i]} ${nameOf(row.id)}`, 300), 836, y + 30);
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 15px ${EX.font}`;
    ctx.fillText(t("week.outputsN", { n: row.outputs }), 836, y + 54);
  });
  if (!w.top.length) {
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 15px ${EX.font}`;
    ctx.fillText(t("digest.quiet"), 760, 320);
  }

  // Pairs + bottleneck
  ctx.fillStyle = EX.card;
  roundRect(ctx, 48, 568, 1104, 140, 20);
  ctx.fill();
  ctx.strokeStyle = EX.line;
  ctx.stroke();
  ctx.fillStyle = EX.ink;
  ctx.font = `700 18px ${EX.font}`;
  ctx.fillText(t("week.pairs"), 72, 602);
  w.links.slice(0, 3).forEach((link, i) => {
    const x = 72 + i * 260;
    const a = images.get(link.from);
    const b = images.get(link.to);
    if (a) ctx.drawImage(a, x, 616, 44, 44);
    if (b) ctx.drawImage(b, x + 34, 616, 44, 44);
    ctx.fillStyle = EX.ink;
    ctx.font = `700 15px ${EX.font}`;
    ctx.fillText(fitText(ctx, `${nameOf(link.from)} → ${nameOf(link.to)}`, 170), x + 86, 636);
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 13px ${EX.font}`;
    ctx.fillText(`×${link.count}${link.avgWaitMs != null ? ` · ${span(link.avgWaitMs)}` : ""}`, x + 86, 656);
  });
  ctx.fillStyle = EX.ink2;
  ctx.font = `500 14px ${EX.font}`;
  const neck = w.neck.slowest ? `${t("neck.slowestLink")}: ${nameOf(w.neck.slowest.from)} → ${nameOf(w.neck.slowest.to)} · ${span(w.neck.slowest.avgWaitMs)}` : "";
  ctx.fillText(fitText(ctx, [neck, `${t("neck.failure")} ${pct(w.neck.failureRate)}`, `${t("neck.retry")} ${pct(w.neck.retryRate)}`].filter(Boolean).join("   ·   "), 1056), 72, 690);

  ctx.fillStyle = "#9a9ca5";
  ctx.font = `500 13px ${EX.font}`;
  ctx.fillText(t("week.footer"), 48, 740);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

// ---------------------------------------------------------------- GIF encoder
// Plain GIF89a: one global 256-colour palette picked from the frames, LZW-compressed frames.

function buildPalette(frames) {
  const counts = new Uint32Array(32768);
  const sums = new Float64Array(32768 * 3);
  for (const frame of frames) {
    const data = frame.data;
    for (let i = 0; i < data.length; i += 4 * 7) {
      const key = ((data[i] >> 3) << 10) | ((data[i + 1] >> 3) << 5) | (data[i + 2] >> 3);
      counts[key]++;
      sums[key * 3] += data[i];
      sums[key * 3 + 1] += data[i + 1];
      sums[key * 3 + 2] += data[i + 2];
    }
  }
  const keys = [];
  for (let key = 0; key < 32768; key++) if (counts[key]) keys.push(key);
  keys.sort((a, b) => counts[b] - counts[a]);
  const palette = [];
  for (const key of keys) {
    const color = [sums[key * 3] / counts[key], sums[key * 3 + 1] / counts[key], sums[key * 3 + 2] / counts[key]].map(Math.round);
    // Skip colours almost identical to one we already have, so the 256 slots go further.
    if (palette.some((p) => Math.abs(p[0] - color[0]) + Math.abs(p[1] - color[1]) + Math.abs(p[2] - color[2]) < 10)) continue;
    palette.push(color);
    if (palette.length === 256) break;
  }
  while (palette.length < 256) palette.push([0, 0, 0]);
  return palette;
}
function makeMapper(palette) {
  const cache = new Int16Array(32768).fill(-1);
  return (r, g, b) => {
    const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
    let index = cache[key];
    if (index >= 0) return index;
    let best = 1e9;
    for (let i = 0; i < palette.length; i++) {
      const p = palette[i];
      const d = (p[0] - r) ** 2 * 2 + (p[1] - g) ** 2 * 4 + (p[2] - b) ** 2 * 3;
      if (d < best) { best = d; index = i; }
    }
    cache[key] = index;
    return index;
  };
}
function lzw(indices) {
  const minCode = 8;
  const clear = 256;
  const end = 257;
  const out = [];
  let codeSize = minCode + 1;
  let next = end + 1;
  let bits = 0;
  let acc = 0;
  let dict = new Map();
  const emit = (code) => {
    acc |= code << bits;
    bits += codeSize;
    while (bits >= 8) {
      out.push(acc & 255);
      acc >>>= 8;
      bits -= 8;
    }
  };
  emit(clear);
  let prefix = indices[0];
  for (let i = 1; i < indices.length; i++) {
    const k = indices[i];
    const key = prefix * 256 + k;
    const found = dict.get(key);
    if (found !== undefined) {
      prefix = found;
      continue;
    }
    emit(prefix);
    if (next < 4096) {
      dict.set(key, next++);
      if (next > 1 << codeSize && codeSize < 12) codeSize++;
    } else {
      emit(clear);
      dict = new Map();
      codeSize = minCode + 1;
      next = end + 1;
    }
    prefix = k;
  }
  emit(prefix);
  emit(end);
  if (bits > 0) out.push(acc & 255);
  return out;
}
async function encodeGIF(frames, width, height, onProgress) {
  const palette = buildPalette(frames.map((frame) => frame.image));
  const map = makeMapper(palette);
  const bytes = [];
  const push16 = (n) => bytes.push(n & 255, (n >> 8) & 255);
  bytes.push(...[..."GIF89a"].map((c) => c.charCodeAt(0)));
  push16(width);
  push16(height);
  bytes.push(0xf7, 0, 0); // global colour table, 256 entries
  for (const [r, g, b] of palette) bytes.push(r, g, b);
  bytes.push(0x21, 0xff, 11, ...[..."NETSCAPE2.0"].map((c) => c.charCodeAt(0)), 3, 1, 0, 0, 0); // loop forever
  for (let f = 0; f < frames.length; f++) {
    const { image, delay } = frames[f];
    bytes.push(0x21, 0xf9, 4, 0x04, delay & 255, (delay >> 8) & 255, 0, 0);
    bytes.push(0x2c);
    push16(0);
    push16(0);
    push16(width);
    push16(height);
    bytes.push(0);
    const data = image.data;
    const indices = new Uint8Array(width * height);
    for (let i = 0, p = 0; i < data.length; i += 4, p++) indices[p] = map(data[i], data[i + 1], data[i + 2]);
    const packed = lzw(indices);
    bytes.push(8);
    for (let i = 0; i < packed.length; i += 255) {
      const chunk = packed.slice(i, i + 255);
      bytes.push(chunk.length, ...chunk);
    }
    bytes.push(0);
    onProgress?.((f + 1) / frames.length);
    if (f % 4 === 3) await new Promise((resolve) => setTimeout(resolve));
  }
  bytes.push(0x3b);
  return new Blob([new Uint8Array(bytes)], { type: "image/gif" });
}

// ---------------------------------------------------------------- relay GIF

const GIF_W = 640;
const GIF_H = 360;
const GIF_STEPS = 14;

function envelope(ctx, x, y, angle, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = "#3b3a4a";
  ctx.lineWidth = 1.6;
  roundRect(ctx, -12, -8, 24, 16, 3);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-11, -7);
  ctx.lineTo(0, 1);
  ctx.lineTo(11, -7);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(0, 3, 3.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}
function gifLayout(ids) {
  const n = ids.length;
  const positions = new Map();
  const perRow = n > 6 ? Math.ceil(n / 2) : n;
  ids.forEach((id, i) => {
    const row = Math.floor(i / perRow);
    const col = i % perRow;
    const count = Math.min(perRow, n - row * perRow);
    const gap = Math.min(150, (GIF_W - 80) / count);
    const x = GIF_W / 2 + (col - (count - 1) / 2) * gap;
    const y = n > 6 ? 150 + row * 92 : 196;
    positions.set(id, { x, y, size: n > 6 ? 72 : 92 });
  });
  return positions;
}
function drawGifFrame(ctx, scene, stepIndex, progress, images) {
  const { flow, steps, positions } = scene;
  const step = steps[stepIndex];
  ctx.fillStyle = EX.bg;
  ctx.fillRect(0, 0, GIF_W, GIF_H);
  // Header
  drawLogo(ctx, 18, 14, 30);
  ctx.fillStyle = EX.ink;
  ctx.font = `800 15px ${EX.font}`;
  ctx.fillText(fitText(ctx, flowAsk(flow) || t("trigger.automation"), GIF_W - 150), 58, 30);
  ctx.fillStyle = EX.ink2;
  ctx.font = `500 11px ${EX.font}`;
  ctx.fillText(`${t("app.title")} · ${clock(flow.startedAt)} · ${t("flows.handoffs", { n: flow.handoffCount })}`, 58, 46);
  // Floor
  ctx.fillStyle = "#eceef2";
  roundRect(ctx, 16, 66, GIF_W - 32, 206, 18);
  ctx.fill();
  const from = positions.get(step.from);
  const to = positions.get(step.to);
  // Everyone
  for (const [id, pos] of positions) {
    const active = id === step.from || id === step.to;
    ctx.globalAlpha = active ? 1 : 0.45;
    const image = images.get(id);
    if (image) ctx.drawImage(image, pos.x - pos.size / 2, pos.y - pos.size * 0.8, pos.size, pos.size);
    ctx.globalAlpha = 1;
    ctx.fillStyle = active ? EX.ink : EX.ink2;
    ctx.font = `${active ? 700 : 500} 11px ${EX.font}`;
    ctx.textAlign = "center";
    ctx.fillText(fitText(ctx, nameOf(id), 110), pos.x, pos.y + pos.size * 0.28);
    ctx.textAlign = "left";
  }
  // The letter in flight
  if (from && to && progress < 1) {
    const cx = (from.x + to.x) / 2;
    const cy = Math.min(from.y, to.y) - 110;
    const q = (a, b, c, k) => (1 - k) ** 2 * a + 2 * (1 - k) * k * b + k ** 2 * c;
    const x = q(from.x, cx, to.x, progress);
    const y = q(from.y - 50, cy, to.y - 50, progress);
    ctx.strokeStyle = "#c9ccd6";
    ctx.setLineDash([4, 5]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y - 50);
    ctx.quadraticCurveTo(cx, cy, to.x, to.y - 50);
    ctx.stroke();
    ctx.setLineDash([]);
    envelope(ctx, x, y, (to.x - from.x) * 0.0008 * (1 - 2 * progress), PALETTE[stepIndex % PALETTE.length]);
  }
  // Caption
  ctx.fillStyle = EX.card;
  roundRect(ctx, 16, 282, GIF_W - 32, 60, 14);
  ctx.fill();
  ctx.strokeStyle = EX.line;
  ctx.stroke();
  ctx.fillStyle = EX.ink;
  ctx.font = `700 13px ${EX.font}`;
  const offset = plus((step.at || flow.startedAt) - flow.startedAt);
  ctx.fillText(fitText(ctx, `${offset}  ${stepSentence(step)}`, GIF_W - 70), 30, 304);
  if (progress >= 1) {
    ctx.fillStyle = EX.ink2;
    ctx.font = `500 12px ${EX.font}`;
    ctx.fillText(fitText(ctx, stepText(step), GIF_W - 70), 30, 326);
  }
  // Progress dots
  steps.forEach((_, i) => {
    ctx.fillStyle = i < stepIndex || (i === stepIndex && progress >= 1) ? EX.accent : i === stepIndex ? "#9cc3ee" : "#d8dae0";
    ctx.beginPath();
    ctx.arc(GIF_W - 24 - (steps.length - 1 - i) * 10, 46, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });
}
async function relayGIF(flow, onProgress) {
  const steps = replaySteps(flow).slice(0, GIF_STEPS);
  const ids = [];
  for (const step of steps) for (const id of [step.from, step.to]) if (!ids.includes(id)) ids.push(id);
  const images = await avatarsFor(ids, 128);
  const scene = { flow, steps, positions: gifLayout(ids) };
  const canvas = document.createElement("canvas");
  canvas.width = GIF_W;
  canvas.height = GIF_H;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const frames = [];
  const FLY = 9;
  steps.forEach((_, index) => {
    for (let f = 0; f < FLY; f++) {
      drawGifFrame(ctx, scene, index, f / FLY, images);
      frames.push({ image: ctx.getImageData(0, 0, GIF_W, GIF_H), delay: 7 });
    }
    drawGifFrame(ctx, scene, index, 1, images);
    frames.push({ image: ctx.getImageData(0, 0, GIF_W, GIF_H), delay: index === steps.length - 1 ? 300 : 170 });
  });
  return encodeGIF(frames, GIF_W, GIF_H, onProgress);
}

// ---------------------------------------------------------------- export dialog

function openExport(title) {
  const dialog = $("#export-dialog");
  $("#export-title").textContent = title;
  $("#export-preview").innerHTML = "";
  $("#export-status").textContent = t("export.working");
  $("#export-save").hidden = true;
  if (!dialog.open) dialog.showModal();
}
function finishExport(blob, filename) {
  const url = URL.createObjectURL(blob);
  $("#export-preview").innerHTML = `<img src="${url}" alt="">`;
  $("#export-status").textContent = t("export.ready", { size: `${Math.max(1, Math.round(blob.size / 1024))} KB` });
  const save = $("#export-save");
  save.href = url;
  save.download = filename;
  save.textContent = t("export.save");
  save.hidden = false;
}
async function exportRelayGIF(flow) {
  openExport(t("replay.gif"));
  try {
    const blob = await relayGIF(flow, (share) => ($("#export-status").textContent = t("export.progress", { n: Math.round(share * 100) })));
    finishExport(blob, `bot-monitor-relay-${flow.id}.gif`);
  } catch (error) {
    $("#export-status").textContent = t("export.failed");
    console.error(error);
  }
}
async function exportWeekPNG() {
  if (!S.insights) return;
  openExport(t("week.png"));
  try {
    finishExport(await weekPNG(), `bot-monitor-week-${stamp()}.png`);
  } catch (error) {
    $("#export-status").textContent = t("export.failed");
    console.error(error);
  }
}
function exportWeekMarkdown() {
  if (!S.insights) return;
  download(new Blob([weekMarkdown()], { type: "text/markdown;charset=utf-8" }), `bot-monitor-week-${stamp()}.md`);
}
