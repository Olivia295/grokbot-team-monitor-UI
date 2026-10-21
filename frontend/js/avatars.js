// Avatar art kit. Every bot is a small, soft character assembled from interchangeable parts:
// body shape, color, eyes, mouth, hat, held item and outfit. The default look is derived from the
// bot's Grok avatar and its role; anyone can override any part from the settings page.
// Coordinates: feet at (0, 0), body roughly 56 wide and 60 tall, head-and-body in one piece.

const LINE = "#3b3a4a";
const AV = {
  shapes: ["round", "bean", "square", "cloud", "drop", "ghost", "cat", "bear", "bunny"],
  colors: {
    peach: ["#ffd2bf", "#f7a98c", "#e88466"],
    tangerine: ["#ffd29e", "#f9ad5c", "#e08a35"],
    lemon: ["#fff0a8", "#ffd75e", "#e6b53a"],
    matcha: ["#d7efb3", "#a7d77c", "#7fb455"],
    mint: ["#c9f2e4", "#86dcc0", "#55b99a"],
    sky: ["#cfe8ff", "#8cc6f7", "#5b9fdc"],
    ocean: ["#c3d3ff", "#7d97ef", "#5a72d0"],
    lavender: ["#e6dcff", "#bba6f4", "#9480db"],
    grape: ["#ecc8f5", "#c88ae0", "#a666c2"],
    sakura: ["#ffe0ea", "#f8a9c2", "#e17f9f"],
    cocoa: ["#ead2c1", "#c69c80", "#a07759"],
    charcoal: ["#8d90a3", "#5c6075", "#3f4256"],
    cloud: ["#ffffff", "#e5e8ef", "#bfc5d2"],
  },
  eyes: ["dot", "sparkle", "happy", "sleepy", "wink", "glasses"],
  mouths: ["smile", "cat", "open", "tiny", "o"],
  hats: ["none", "crown", "beanie", "cap", "headphones", "bow", "sprout", "wizard", "beret", "halo", "antenna", "party"],
  items: ["none", "laptop", "book", "pencil", "magnifier", "mug", "bulb", "dice", "clipboard", "brush"],
  outfits: ["none", "scarf", "bowtie", "tie", "lanyard", "apron"],
};
AV.colorNames = Object.keys(AV.colors);

// Where the top of each body sits, so hats land on the head.
const SHAPE_TOP = { round: -55, bean: -62, square: -57, cloud: -56, drop: -54, ghost: -60, cat: -56, bear: -56, bunny: -56 };
const GROK_SHAPES = { pebble: "round", squircle: "square", blob: "round", cloud: "cloud", drop: "drop", bean: "bean" };
const GROK_COLORS = { yellow: "lemon", black: "charcoal", violet: "lavender", purple: "grape", blue: "sky", green: "matcha", red: "peach", orange: "tangerine", pink: "sakura", teal: "mint", gray: "cloud", white: "cloud" };
const ROLE_PARTS = [
  [/notion|journal|笔记|档案|管家|ledger|archiv|wiki/, { item: "book", outfit: "tie" }],
  [/x search|search|情报|scout|侦察|trending|research/, { item: "magnifier", hat: "cap" }],
  [/codex|code|github|代码|engineer/, { item: "laptop", hat: "headphones" }],
  [/content|forge|draft|写作|编辑|writer|quill|editor|echo/, { item: "pencil", outfit: "scarf" }],
  [/idea|prism|灵感|想法|spark|brainstorm/, { hat: "sprout", item: "bulb" }],
  [/willow|mage|psych|心灵|法师/, { hat: "wizard" }],
  [/spaceship|pilot|博客|副驾驶/, { hat: "antenna", outfit: "lanyard" }],
  [/morning|brief|早报|晨间|radar|news/, { item: "mug", hat: "beanie" }],
  [/deep dive|深挖|dive|deepsea|analyst/, { eyes: "glasses", item: "clipboard" }],
  [/serendipity|意外|sidequest|活动/, { item: "dice", hat: "party" }],
  [/eggbot|母体|designs.*bots|atlas|lead|指挥/, { hat: "crown", outfit: "bowtie" }],
  [/grok bot|参谋|concierge|前台|desk/, { hat: "headphones", outfit: "lanyard" }],
  [/pixel|design|设计|art/, { hat: "beret", item: "brush" }],
];

function hashOf(text) {
  let hash = 2166136261;
  for (const char of String(text)) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619) >>> 0;
  return hash;
}

function defaultLook(agent) {
  const seed = hashOf(agent.id || agent.name || "bot");
  const look = {
    // Grok's own avatar names, or catalog names straight from an event log.
    shape: GROK_SHAPES[agent.avatarShape] || (AV.shapes.includes(agent.avatarShape) ? agent.avatarShape : AV.shapes[seed % AV.shapes.length]),
    color: GROK_COLORS[agent.avatarColor] || (AV.colors[agent.avatarColor] ? agent.avatarColor : AV.colorNames[(seed >>> 5) % AV.colorNames.length]),
    eyes: ["dot", "sparkle", "dot", "happy"][(seed >>> 9) % 4],
    mouth: AV.mouths[(seed >>> 12) % AV.mouths.length],
    hat: "none",
    item: "none",
    outfit: "none",
  };
  const text = `${agent.originalName || agent.name || ""} ${agent.title || ""} ${agent.roleLine || ""}`.toLowerCase();
  const role = ROLE_PARTS.find(([pattern]) => pattern.test(text));
  if (role) Object.assign(look, role[1]);
  else look.hat = ["none", "sprout", "bow", "antenna"][(seed >>> 15) % 4];
  return look;
}
function lookFor(agent, override) {
  const look = { ...defaultLook(agent), ...(agent.look || {}), ...(override || {}) };
  if (!AV.colors[look.color]) look.color = "sky";
  if (!AV.shapes.includes(look.shape)) look.shape = "round";
  return look;
}

// One shared set of gradients for every avatar on the page.
function ensureAvatarDefs() {
  if (document.getElementById("avatar-defs")) return;
  const defs = Object.entries(AV.colors).map(([name, [light, base]]) =>
    `<linearGradient id="av-${name}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${base}"/></linearGradient>`).join("");
  const holder = document.createElement("div");
  holder.innerHTML = `<svg id="avatar-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>${defs}</defs></svg>`;
  document.body.prepend(holder.firstChild);
}

function bodyPath(shape) {
  switch (shape) {
    case "bean": return '<rect x="-23" y="-62" width="46" height="58" rx="23"/>';
    case "square": return '<rect x="-26" y="-57" width="52" height="53" rx="20"/>';
    case "cloud": return '<path d="M-22 -4C-33 -4-36 -20-26 -26C-29 -42-12 -51-3 -44C2 -59 26 -56 26 -38C36 -36 36 -18 27 -14C30 -6 22 -4 16 -4Z"/>';
    case "drop": return '<path d="M0 -60C13 -46 28 -36 28 -22C28 -9 16 -4 0 -4C-16 -4-28 -9-28 -22C-28 -36-13 -46 0 -60Z"/>';
    case "ghost": return '<path d="M-26 -4V-34C-26 -50-14 -60 0 -60S26 -50 26 -34V-4L19 -9 13 -4 6.5 -9 0 -4-6.5 -9-13 -4-19 -9Z"/>';
    case "cat": return '<path d="M-24 -46L-22 -62-10 -53C-4 -55 4 -55 10 -53L22 -62 24 -46C28 -40 29 -32 29 -26 29 -12 17 -4 0 -4S-29 -12-29 -26C-29 -32-28 -40-24 -46Z"/>';
    case "bear": return '<circle cx="-18" cy="-50" r="8"/><circle cx="18" cy="-50" r="8"/><ellipse cx="0" cy="-28" rx="29" ry="25"/>';
    case "bunny": return '<rect x="-17" y="-80" width="11" height="32" rx="5.5" transform="rotate(-8 -11 -64)"/><rect x="6" y="-80" width="11" height="32" rx="5.5" transform="rotate(8 11 -64)"/><ellipse cx="0" cy="-28" rx="28" ry="25"/>';
    default: return '<ellipse cx="0" cy="-29" rx="29" ry="26"/>';
  }
}
function earInner(shape) {
  if (shape === "cat") return '<path d="M-21 -50l-1 -7 6 4zM21 -50l1 -7-6 4z" fill="#ffb3c6" opacity=".7"/>';
  if (shape === "bear") return '<circle cx="-18" cy="-50" r="4" fill="#ffb3c6" opacity=".6"/><circle cx="18" cy="-50" r="4" fill="#ffb3c6" opacity=".6"/>';
  if (shape === "bunny") return '<rect x="-14" y="-76" width="5" height="22" rx="2.5" fill="#ffb3c6" opacity=".6" transform="rotate(-8 -11 -64)"/><rect x="9" y="-76" width="5" height="22" rx="2.5" fill="#ffb3c6" opacity=".6" transform="rotate(8 11 -64)"/>';
  return "";
}

function eyesArt(kind, dark) {
  const ink = dark ? "#fbf8ff" : "#2b2d42";
  const glint = dark ? "#2b2d42" : "#fff";
  const pair = (rx, ry, glints = 1) => `<ellipse cx="-11" cy="-28" rx="${rx}" ry="${ry}" fill="${ink}"/><ellipse cx="11" cy="-28" rx="${rx}" ry="${ry}" fill="${ink}"/>`
    + `<circle cx="-9.6" cy="-30" r="1.5" fill="${glint}"/><circle cx="12.4" cy="-30" r="1.5" fill="${glint}"/>`
    + (glints > 1 ? `<circle cx="-12" cy="-26.4" r=".8" fill="${glint}"/><circle cx="10" cy="-26.4" r=".8" fill="${glint}"/>` : "");
  switch (kind) {
    case "sparkle": return `<g class="eyes">${pair(4.4, 5.4, 2)}</g>`;
    case "happy": return `<g class="eyes"><path d="M-15 -27q4 -5 8 0M7 -27q4 -5 8 0" fill="none" stroke="${ink}" stroke-width="2.4" stroke-linecap="round"/></g>`;
    case "sleepy": return `<g class="eyes"><path d="M-15 -28q4 3 8 0M7 -28q4 3 8 0" fill="none" stroke="${ink}" stroke-width="2.4" stroke-linecap="round"/></g>`;
    case "wink": return `<g class="eyes"><ellipse cx="-11" cy="-28" rx="3.4" ry="4.2" fill="${ink}"/><circle cx="-9.8" cy="-29.6" r="1.3" fill="${glint}"/><path d="M7 -27q4 -4.5 8 0" fill="none" stroke="${ink}" stroke-width="2.4" stroke-linecap="round"/></g>`;
    case "glasses": return `<g class="eyes">${pair(2.8, 3.4)}</g><g class="specs"><circle cx="-11" cy="-28" r="7" fill="#ffffff55" stroke="${LINE}" stroke-width="1.8"/><circle cx="11" cy="-28" r="7" fill="#ffffff55" stroke="${LINE}" stroke-width="1.8"/><path d="M-4 -28h8" stroke="${LINE}" stroke-width="1.8"/></g>`;
    default: return `<g class="eyes">${pair(3.4, 4.2)}</g>`;
  }
}
function mouthArt(kind, dark) {
  const ink = dark ? "#fbf8ff" : "#2b2d42";
  switch (kind) {
    case "cat": return `<path d="M-4.5 -18q2.25 2.6 4.5 0q2.25 2.6 4.5 0" fill="none" stroke="${ink}" stroke-width="1.8" stroke-linecap="round"/>`;
    case "open": return `<path d="M-3.6 -19.5h7.2q-.4 5-3.6 5t-3.6 -5z" fill="${ink}"/><path d="M-2 -15.8q2 -1.8 4 0" fill="#ff8fa3"/>`;
    case "tiny": return `<ellipse cx="0" cy="-17.5" rx="1.6" ry="1.2" fill="${ink}"/>`;
    case "o": return `<ellipse cx="0" cy="-17.5" rx="2.2" ry="2.6" fill="none" stroke="${ink}" stroke-width="1.6"/>`;
    default: return `<path d="M-4 -18.5q4 3.8 8 0" fill="none" stroke="${ink}" stroke-width="1.8" stroke-linecap="round"/>`;
  }
}

const L = `stroke="${LINE}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"`;
function hatArt(kind, top) {
  const t = top;
  switch (kind) {
    case "crown": return `<g class="hat"><path d="M-12 ${t + 3}l-3 -13 8 6 7 -10 7 10 8 -6-3 13z" fill="#ffd75e" ${L}/><circle cx="0" cy="${t - 1}" r="2.2" fill="#f8a9c2"/></g>`;
    case "beanie": return `<g class="hat"><path d="M-22 ${t + 10}c0 -16 10 -22 22 -22s22 6 22 22z" fill="#f8a9c2" ${L}/><rect x="-24" y="${t + 6}" width="48" height="8" rx="4" fill="#e17f9f" ${L}/><circle cx="0" cy="${t - 13}" r="5" fill="#fff" ${L}/></g>`;
    case "cap": return `<g class="hat"><path d="M-20 ${t + 8}c0 -14 8 -19 20 -19s20 5 20 19z" fill="#7d97ef" ${L}/><path d="M14 ${t + 8}h20c2 0 2 4 0 4h-20z" fill="#5a72d0" ${L}/><circle cx="0" cy="${t - 11}" r="2" fill="#fff"/></g>`;
    case "headphones": return `<g class="hat"><path d="M-25 -30c0 -34 50 -34 50 0" fill="none" stroke="${LINE}" stroke-width="3.2" stroke-linecap="round"/><rect x="-31" y="-36" width="10" height="15" rx="5" fill="#ff8fa3" ${L}/><rect x="21" y="-36" width="10" height="15" rx="5" fill="#ff8fa3" ${L}/></g>`;
    case "bow": return `<g class="hat"><path d="M12 ${t + 2}l-10 -7v12zM12 ${t + 2}l10 -7v12z" fill="#ff8fa3" ${L}/><circle cx="12" cy="${t + 2}" r="3" fill="#ffd2dc" ${L}/></g>`;
    case "sprout": return `<g class="hat sway"><path d="M0 ${t + 3}v-9" stroke="#7fb455" stroke-width="2.2" stroke-linecap="round"/><path d="M0 ${t - 5}c-2 -8-10 -8-12 -4 4 4 8 5 12 4zM0 ${t - 5}c2 -8 10 -8 12 -4-4 4-8 5-12 4z" fill="#a7d77c" ${L}/></g>`;
    case "wizard": return `<g class="hat"><path d="M-22 ${t + 8}h44c-3 -3-7 -4-9 -5l-11 -26c-1 -3-3 -3-4 0l-11 26c-3 1-7 2-9 5z" fill="#9480db" ${L}/><path d="M2 ${t - 6}l1.5 3 3.2.4-2.4 2.2.6 3.2-2.9 -1.5-2.9 1.5.6 -3.2-2.4 -2.2 3.2 -.4z" fill="#ffd75e"/></g>`;
    case "beret": return `<g class="hat"><path d="M-20 ${t + 6}c-2 -10 10 -15 22 -14s20 6 18 13c-8 3-30 4-40 1z" fill="#e88466" ${L}/><path d="M4 ${t - 8}v-4" stroke="${LINE}" stroke-width="2" stroke-linecap="round"/></g>`;
    case "halo": return `<g class="hat glow"><ellipse cx="0" cy="${t - 8}" rx="15" ry="4.5" fill="none" stroke="#ffd75e" stroke-width="3.4"/></g>`;
    case "antenna": return `<g class="hat"><path d="M0 ${t + 2}v-12" stroke="${LINE}" stroke-width="2"/><circle class="blinker" cx="0" cy="${t - 13}" r="4" fill="#ff8fa3" ${L}/></g>`;
    case "party": return `<g class="hat"><path d="M-9 ${t + 6}l9 -26 9 26z" fill="#86dcc0" ${L}/><path d="M-6 ${t - 2}l12 3M-3 ${t - 10}l7 2" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="0" cy="${t - 21}" r="3.4" fill="#ffd75e" ${L}/></g>`;
    default: return "";
  }
}
function itemArt(kind) {
  switch (kind) {
    case "laptop": return `<g class="prop"><path d="M-15 -3h30l4 4h-38z" fill="#e5e8ef" ${L}/><rect x="-12" y="-17" width="24" height="14" rx="3" fill="#5c6075" ${L}/><circle cx="0" cy="-10" r="2" fill="#86dcc0"/></g>`;
    case "book": return `<g class="prop"><path d="M14 -23l16 -4v18l-16 4z" fill="#7d97ef" ${L}/><path d="M17 -20l9 -2M17 -15l9 -2" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></g>`;
    case "pencil": return `<g class="prop scribble"><path d="M21 -6l11 -21 5 3-11 21-6 2z" fill="#ffd75e" ${L}/><path d="M32 -27l5 3 2-4-5-3z" fill="#ff8fa3" ${L}/></g>`;
    case "magnifier": return `<g class="prop swing"><path d="M28 -5l7 8" stroke="${LINE}" stroke-width="3.2" stroke-linecap="round"/><circle cx="23" cy="-11" r="8" fill="#e8f6ff" ${L} stroke-width="2.2"/><circle cx="20" cy="-14" r="2.2" fill="#fff"/></g>`;
    case "mug": return `<g class="prop"><path class="steam" d="M25 -32c-3 -4 3 -6 0 -10M31 -32c-3 -4 3 -6 0 -10" fill="none" stroke="#c9c2d6" stroke-width="1.7" stroke-linecap="round"/><rect x="20" y="-26" width="14" height="14" rx="4" fill="#fff" ${L}/><path d="M34 -22c5 0 5 7 0 7" fill="none" ${L}/></g>`;
    case "bulb": return `<g class="prop glow"><circle cx="27" cy="-24" r="10" fill="#fff3a8" opacity=".5"/><path d="M22 -21a6.5 6.5 0 1 1 10 0v3h-10z" fill="#fff3a8" ${L}/><path d="M24 -15h6" stroke="${LINE}" stroke-width="1.8" stroke-linecap="round"/></g>`;
    case "dice": return `<g class="prop tumble"><rect x="20" y="-22" width="13" height="13" rx="3.5" fill="#fff" ${L} transform="rotate(-12 26 -15)"/><circle cx="24" cy="-18" r="1.4" fill="#e17f9f"/><circle cx="29" cy="-13" r="1.4" fill="#e17f9f"/></g>`;
    case "clipboard": return `<g class="prop"><rect x="18" y="-28" width="16" height="21" rx="3" fill="#c69c80" ${L}/><rect x="21" y="-24" width="10" height="14" rx="1.5" fill="#fff"/><path d="M23 -20h6M23 -16h4" stroke="#8cc6f7" stroke-width="1.4" stroke-linecap="round"/><rect x="23" y="-30" width="6" height="4" rx="1.5" fill="#5c6075"/></g>`;
    case "brush": return `<g class="prop scribble"><path d="M22 -4l10 -20" stroke="#c69c80" stroke-width="3.4" stroke-linecap="round"/><path d="M31 -23l4 -8c1 -2 4 -1 3 1l-3 9z" fill="#f8a9c2" ${L}/></g>`;
    default: return "";
  }
}
function outfitArt(kind) {
  switch (kind) {
    case "scarf": return `<g class="outfit"><path d="M-20 -14q20 8 40 0v6q-20 8-40 0z" fill="#ff8fa3" ${L}/><path d="M10 -8l2 10 6 -1-2-11z" fill="#ff8fa3" ${L}/></g>`;
    case "bowtie": return `<g class="outfit"><path d="M0 -12l-9 -5v10zM0 -12l9 -5v10z" fill="#e17f9f" ${L}/><circle cx="0" cy="-12" r="2.4" fill="#f8a9c2" ${L}/></g>`;
    case "tie": return `<g class="outfit"><path d="M-3 -15h6l-1 3 3 11-5 4-5-4 3-11z" fill="#7d97ef" ${L}/></g>`;
    case "lanyard": return `<g class="outfit"><path d="M-12 -24l10 14M12 -24l-10 14" stroke="#5b9fdc" stroke-width="2"/><rect x="-6" y="-12" width="12" height="9" rx="2" fill="#fff" ${L}/><path d="M-3 -8h6" stroke="#5b9fdc" stroke-width="1.4"/></g>`;
    case "apron": return `<g class="outfit"><path d="M-14 -20h28v12q0 4-4 4h-20q-4 0-4-4z" fill="#fff" fill-opacity=".9" ${L}/><path d="M-6 -14h12" stroke="#f8a9c2" stroke-width="1.6" stroke-linecap="round"/></g>`;
    default: return "";
  }
}

const HEART = (x, y, s, cls) => `<path class="${cls}" transform="translate(${x} ${y}) scale(${s})" d="M0 3l-5 -4.6a3 3 0 0 1 5 -3.6 3 3 0 0 1 5 3.6z" fill="#ff8fa3"/>`;
const STATUS = `<g class="status" transform="translate(23 -68)">
  <g class="sb sb-executing"><circle r="10" fill="#fff" stroke="${LINE}" stroke-width="1.6"/><g class="gear"><path d="M0 -6.5l1.6 2.2 2.6 -.6.4 2.6 2.4 1.2-1.2 2.4 1.2 2.4-2.4 1.2-.4 2.6-2.6 -.6L0 6.5l-1.6 -2.2-2.6 .6-.4 -2.6-2.4 -1.2 1.2 -2.4-1.2 -2.4 2.4 -1.2.4 -2.6 2.6 .6z" fill="#8cc6f7" stroke="${LINE}" stroke-width="1.1"/><circle r="2" fill="#fff" stroke="${LINE}" stroke-width="1.1"/></g></g>
  <g class="sb sb-writing"><circle r="10" fill="#fff" stroke="${LINE}" stroke-width="1.6"/><path d="M-4.5 0l3 3 6 -6.5" fill="none" stroke="#2fa36b" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></g>
  <g class="sb sb-researching"><circle r="10" fill="#fff" stroke="${LINE}" stroke-width="1.6"/><circle class="d1" cx="-4" r="1.8" fill="${LINE}"/><circle class="d2" r="1.8" fill="${LINE}"/><circle class="d3" cx="4" r="1.8" fill="${LINE}"/></g>
  <g class="sb sb-syncing"><circle r="10" fill="#fff" stroke="${LINE}" stroke-width="1.6"/><rect x="-5.5" y="-4" width="11" height="8" rx="1.5" fill="#ffd75e" stroke="${LINE}" stroke-width="1.2"/><path d="M-5 -3.5l5 4 5 -4" fill="none" stroke="${LINE}" stroke-width="1.1"/></g>
  <g class="sb sb-error"><circle r="10" fill="#f0643c" stroke="${LINE}" stroke-width="1.6"/><path d="M0 -5v4.5" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cy="4.2" r="1.5" fill="#fff"/></g>
  <g class="sb sb-sleepy"><circle r="10" fill="#fff" stroke="${LINE}" stroke-width="1.6"/><text x="0" y="4" text-anchor="middle" font-size="11" font-weight="800" fill="#9480db">z</text></g>
</g>`;
const SPEECH = `<g class="speech" transform="translate(0 -88)"><path class="speech-box" d="" fill="#fff" stroke="${LINE}" stroke-width="1.6" stroke-linejoin="round"/><text class="speech-text" x="0" y="-12" text-anchor="middle"></text></g>`;

// A full creature with every state decoration present; CSS shows the ones for the current state.
function creatureSVG(agent, override) {
  const look = lookFor(agent, override);
  const [light, base, shade] = AV.colors[look.color];
  const dark = look.color === "charcoal";
  const seed = hashOf(agent.id || agent.name || "bot");
  const top = SHAPE_TOP[look.shape] ?? -56;
  const delay = `--blink:${-(seed % 5000) / 1000}s;--breathe:${-(seed % 3000) / 1000}s`;
  return `<g class="creature shape-${look.shape}" style="${delay}">
    <ellipse class="ground" cx="0" cy="0" rx="23" ry="4.5"/>
    <g class="bob">
      <g class="feet"><ellipse cx="-10" cy="-3.5" rx="7" ry="4.5" fill="${base}" stroke="${shade}" stroke-width="1.8"/><ellipse cx="10" cy="-3.5" rx="7" ry="4.5" fill="${base}" stroke="${shade}" stroke-width="1.8"/></g>
      <g class="arm arm-l"><ellipse cx="-27" cy="-19" rx="5.5" ry="6.5" fill="${base}" stroke="${shade}" stroke-width="1.8"/></g>
      <g class="arm arm-r"><ellipse cx="27" cy="-19" rx="5.5" ry="6.5" fill="${base}" stroke="${shade}" stroke-width="1.8"/></g>
      <g class="body" fill="url(#av-${look.color})" stroke="${shade}" stroke-width="2" stroke-linejoin="round">${bodyPath(look.shape)}</g>
      ${earInner(look.shape)}
      <ellipse cx="0" cy="-12" rx="15" ry="7.5" fill="${light}" opacity=".7"/>
      <ellipse cx="-12" cy="-44" rx="8" ry="4.5" fill="#fff" opacity=".45" transform="rotate(-24 -12 -44)"/>
      ${outfitArt(look.outfit)}
      <g class="face">${eyesArt(look.eyes, dark)}
        <ellipse class="cheek" cx="-19" cy="-20" rx="4.6" ry="2.8" fill="#ff8fa3" opacity=".45"/><ellipse class="cheek" cx="19" cy="-20" rx="4.6" ry="2.8" fill="#ff8fa3" opacity=".45"/>
        ${mouthArt(look.mouth, dark)}</g>
      ${hatArt(look.hat, top)}
      ${itemArt(look.item)}
      <g class="envelope-held"><rect x="-37" y="-29" width="19" height="14" rx="3" fill="#fff" ${L}/><path d="M-36 -28l8.5 6.5 8.5 -6.5" fill="none" stroke="${LINE}" stroke-width="1.5" stroke-linejoin="round"/></g>
      <path class="sweat" d="M25 -48c3 4 4 6 2 8s-5 0-4 -3z" fill="#8cc6f7" ${L}/>
    </g>
    ${STATUS}
    <g class="hearts">${HEART(-14, -72, 0.9, "h1")}${HEART(12, -78, 0.7, "h2")}</g>
    ${SPEECH}
  </g>`;
}

function personSVG() {
  return `<g class="creature person" style="--blink:-1.3s;--breathe:-0.4s">
    <ellipse class="ground" cx="0" cy="0" rx="22" ry="4.5"/>
    <g class="bob">
      <ellipse cx="-7" cy="-3.5" rx="6" ry="4" fill="#fff" ${L}/><ellipse cx="7" cy="-3.5" rx="6" ry="4" fill="#fff" ${L}/>
      <path d="M-16 -6c0 -16 6 -22 16 -22s16 6 16 22z" fill="#8cc6f7" ${L} stroke-width="2"/>
      <circle cx="0" cy="-45" r="19" fill="#ffe2cf" ${L} stroke-width="2"/>
      <path d="M-19 -45c-1 -15 9 -21 19 -21s21 6 19 21c-4 -6-8 -9-14 -10-2 4-8 6-14 6-5 0-8 2-10 4z" fill="#6b4a3d" ${L}/>
      <g class="eyes"><ellipse cx="-7.5" cy="-41" rx="3" ry="3.8" fill="#2b2d42"/><ellipse cx="7.5" cy="-41" rx="3" ry="3.8" fill="#2b2d42"/><circle cx="-6.4" cy="-42.6" r="1.2" fill="#fff"/><circle cx="8.6" cy="-42.6" r="1.2" fill="#fff"/></g>
      <ellipse cx="-13" cy="-35" rx="3.6" ry="2.4" fill="#ff8fa3" opacity=".4"/><ellipse cx="13" cy="-35" rx="3.6" ry="2.4" fill="#ff8fa3" opacity=".4"/>
      <path d="M-3.5 -34q3.5 3 7 0" fill="none" stroke="#2b2d42" stroke-width="1.7" stroke-linecap="round"/>
      <rect x="13" y="-21" width="11" height="11" rx="3" fill="#fff" ${L}/>
      <path class="steam" d="M16 -25c-2 -3 2 -5 0 -8M21 -25c-2 -3 2 -5 0 -8" fill="none" stroke="#c9c2d6" stroke-width="1.5" stroke-linecap="round"/>
    </g>
    ${SPEECH}
  </g>`;
}

function clockSVG() {
  return `<g class="creature clock" style="--blink:-2.2s;--breathe:-1.1s">
    <ellipse class="ground" cx="0" cy="0" rx="20" ry="4.5"/>
    <g class="bob">
      <path d="M-12 -5l-5 6M12 -5l5 6" stroke="${LINE}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="-15" cy="-53" r="7" fill="#ffd75e" ${L}/><circle cx="15" cy="-53" r="7" fill="#ffd75e" ${L}/>
      <circle cx="0" cy="-29" r="24" fill="url(#av-sky)" stroke="#5b9fdc" stroke-width="2"/>
      <circle cx="0" cy="-29" r="18" fill="#fff"/>
      <g class="hand-min"><path d="M0 -29v-12" stroke="${LINE}" stroke-width="2.2" stroke-linecap="round"/></g>
      <g class="hand-hour"><path d="M0 -29h8" stroke="#f0643c" stroke-width="2.6" stroke-linecap="round"/></g>
      <g class="eyes"><ellipse cx="-7.5" cy="-24" rx="2.2" ry="2.8" fill="#2b2d42"/><ellipse cx="7.5" cy="-24" rx="2.2" ry="2.8" fill="#2b2d42"/></g>
      <circle cx="0" cy="-29" r="2.3" fill="${LINE}"/>
    </g>
    ${SPEECH}
  </g>`;
}

// What flies on a handoff: a letter with little wings.
function planeSVG(color = "#5b9fdc") {
  return `<g class="letter"><g class="wing-l"><path d="M-9 -3c-8 -8-15 -6-16 -1 4 0 8 3 10 6z" fill="#fff" ${L}/></g><g class="wing-r"><path d="M9 -3c8 -8 15 -6 16 -1-4 0-8 3-10 6z" fill="#fff" ${L}/></g>
    <rect x="-11" y="-7" width="22" height="15" rx="3" fill="#fff" ${L} stroke-width="1.8"/><path d="M-10 -6l10 7 10 -7" fill="none" stroke="${LINE}" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cy="3" r="3.2" fill="${color}" ${L} stroke-width="1.1"/></g>`;
}

// A standalone <svg> avatar for lists and cards.
function avatarSVG(agent, size = 40, kind = "agent", override) {
  const art = kind === "you" ? personSVG() : kind === "automation" ? clockSVG() : creatureSVG(agent, override);
  return `<svg class="avatar" width="${size}" height="${size}" viewBox="-44 -98 88 104" aria-hidden="true">${art}</svg>`;
}

// A self-contained SVG document (gradients and the few CSS rules it needs inlined), for drawing
// avatars onto a canvas when exporting images and GIFs.
function avatarDocument(agent, size = 96, kind = "agent", state = "") {
  const defs = Object.entries(AV.colors).map(([name, [light, base]]) =>
    `<linearGradient id="av-${name}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${base}"/></linearGradient>`).join("");
  const style = ".sb,.hearts,.speech,.envelope-held,.sweat{display:none}.ground{fill:#1f2a3d1f}"
    + ".st-syncing .envelope-held,.st-syncing .sb-syncing,.st-error .sweat,.st-error .sb-error,.st-executing .sb-executing,.st-writing .sb-writing,.st-researching .sb-researching{display:block}";
  const art = kind === "you" ? personSVG() : kind === "automation" ? clockSVG() : creatureSVG(agent);
  const body = (state ? art.replace('class="creature ', `class="creature st-${state} `) : art)
    // Some parts repeat an attribute (shared stroke style plus an override). HTML keeps the first
    // one; XML refuses the file, so drop the repeats the same way before making an image of it.
    .replace(/<([a-zA-Z][\w:-]*)((?:\s+[\w:-]+="[^"]*")*)\s*(\/?)>/g, (match, tag, attrs, slash) => {
      const seen = new Set();
      const kept = [...attrs.matchAll(/\s+([\w:-]+)="[^"]*"/g)].filter(([, name]) => !seen.has(name) && seen.add(name)).map(([whole]) => whole);
      return `<${tag}${kept.join("")}${slash ? "/" : ""}>`;
    });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="-44 -98 88 104"><defs>${defs}</defs><style>${style}</style>${body}</svg>`;
}
function avatarImage(agent, size = 96, kind = "agent", state = "") {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(avatarDocument(agent, size, kind, state))}`;
  });
}

// Show a short line in a creature's speech bubble (empty text hides it).
function setSpeech(creature, text, dx = 0, dy = 0) {
  if (!creature) return;
  creature.querySelector(".speech")?.setAttribute("transform", `translate(${dx} ${-88 + dy})`);
  const box = creature.querySelector(".speech-box");
  const label = creature.querySelector(".speech-text");
  if (!box || !label) return;
  creature.classList.toggle("talking", Boolean(text));
  if (!text) return;
  label.textContent = text;
  const half = speechHalfWidth(text);
  box.setAttribute("d", `M${-half} -28h${half * 2}a8 8 0 0 1 8 8v8a8 8 0 0 1 -8 8H6l-6 6-6 -6H${-half}a8 8 0 0 1 -8 -8v-8a8 8 0 0 1 8 -8z`);
}

function speechHalfWidth(text) {
  let width = 16;
  for (const ch of String(text || "")) width += ch.charCodeAt(0) > 0x2e80 ? 12 : 6.6;
  return Math.max(20, width / 2);
}

// The Bot Office mark: a bot head inside an orbit with two teammates riding it.
// Monochrome on purpose so it sits well next to Grok's black-and-white look.
function logoSVG(size = 40) {
  return `<svg class="logo" width="${size}" height="${size}" viewBox="0 0 64 64" aria-hidden="true">
    <rect width="64" height="64" rx="18" fill="#0d0d0f"/>
    <rect x=".5" y=".5" width="63" height="63" rx="17.5" fill="none" stroke="#ffffff" stroke-opacity=".12"/>
    <g class="logo-orbit">
      <ellipse cx="32" cy="35" rx="27" ry="9.5" transform="rotate(-24 32 35)" fill="none" stroke="#ffffff" stroke-opacity=".38" stroke-width="1.6"/>
      <circle cx="56" cy="24" r="3.4" fill="#ffffff"/>
      <circle cx="8" cy="46" r="2.6" fill="#ffffff" fill-opacity=".7"/>
    </g>
    <path d="M32 21v-6" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
    <circle class="logo-beacon" cx="32" cy="12.5" r="3.4" fill="#ffffff"/>
    <rect x="16" y="21" width="32" height="26" rx="11" fill="#0d0d0f" stroke="#ffffff" stroke-width="3.2"/>
    <rect class="logo-eye" x="24.5" y="29" width="4" height="9" rx="2" fill="#ffffff"/>
    <rect class="logo-eye" x="35.5" y="29" width="4" height="9" rx="2" fill="#ffffff"/>
  </svg>`;
}
