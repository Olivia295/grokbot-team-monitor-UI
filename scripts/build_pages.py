#!/usr/bin/env python3
"""Build the online demo for GitHub Pages into site/ (no server needed to view it).

    python3 scripts/build_pages.py            # writes site/
    python3 -m http.server -d site 8000       # preview at http://127.0.0.1:8000

The demo team is recorded as JSON frames 30 seconds apart over half an hour, in both
languages. The page plays the frames in a loop and shifts every timestamp to the present,
so the online demo always looks live. See STATIC in frontend/js/common.js.

Two extras show what only a running copy can: alerts.json (the real alert rules run over
every frame) and internal.json (the Grok Bot box panel, built from the demo team's own
records). Both use the same shapes as /api/alerts and /api/internal, with times in ms.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import alerts, demo, internal_box, views  # noqa: E402
from backend.settings import clean  # noqa: E402

SITE = ROOT / "site"
STEP_MS = 30 * 1000
FRAMES = 60
REPO = "https://github.com/Olivia295/grokbot-team-monitor-UI"
ALERT_RULES = {"error": True, "awaiting": True, "stuck": True, "done": True, "stuckMinutes": 10}
DAY = 86400 * 1000


def write(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    return len(data.encode("utf-8"))


def demo_alerts(frames: list[tuple[int, dict, dict]], language: str) -> list[dict]:
    """What the alert watcher would have sent while the frames play, newest first."""
    seen: set[str] = set()
    out = []
    for at, office, flows in frames:
        for item in alerts.detect(office, flows, ALERT_RULES, at):
            if item["key"] in seen:
                continue
            seen.add(item["key"])
            title, body = alerts.render(item, language)
            out.append({"id": f"{item['key']}@{at}", "key": item["key"], "kind": item["kind"], "bot": item.get("bot"),
                        "flowId": item.get("flowId"), "title": title, "body": body, "at": at, "demo": True})
    return sorted(out, key=lambda alert: -alert["at"])


def _latest_unique(entries: list[dict], limit: int) -> list[list]:
    """The newest handoffs received, one per distinct ask, as [ms, text]."""
    out, seen = [], set()
    for entry in reversed(entries):
        if entry["content"] in seen:
            continue
        seen.add(entry["content"])
        out.append([entry["timestampMs"], entry["content"]])
        if len(out) == limit:
            break
    return out


def demo_internal(cache, now_ms: int, language: str = "zh") -> dict:
    """The Grok Bot box panel for the demo team, in the shape /api/internal returns.

    Everything comes from the demo team's records: last activity, handoffs received as
    recent tasks, who dispatches whom, and 7-day message counts. Times are in ms
    (``*_ms``) so the page can move them to the present.
    """
    groups = {bot_id: section["name"] for section in cache.sections for bot_id in section["agentIds"]}
    desk = "Front desk" if language == "en" else "前台"
    groups.update({bot_id: desk for bot_id in cache.pinned})
    since = now_ms - internal_box.WINDOW_DAYS * DAY
    now = datetime.fromtimestamp(now_ms / 1000, internal_box.SYDNEY)
    bots, measured = [], []
    edges: Counter = Counter()
    for row in cache.roster:
        entries = [entry for entry in cache.transcripts.get(row["id"], ([], 0))[0] if entry["timestampMs"] <= now_ms]
        recent = [entry for entry in entries if entry["timestampMs"] >= since]
        sent = sum(1 for entry in recent if entry.get("role") == "assistant" or entry["kind"] == "send-message")
        received = sum(1 for entry in recent if entry.get("role") == "user")
        last = max((entry["timestampMs"] for entry in entries), default=0)
        handed = [entry for entry in entries if entry.get("fromAgent")]
        for entry in recent:
            if entry.get("toAgent"):
                edges[(row["name"], entry["toAgent"]["name"])] += 1
        record = {
            "id": row["id"], "name": row["name"], "label": row.get("title", ""), "group": groups.get(row["id"], ""),
            "duty": row.get("description", ""),
            "status": internal_box.status_for(last / 1000 if last else None, now, True),
            "last_activity_ms": last or None,
            # The demo team has no folders; outputs stand in for files changed this week.
            "files_modified_7d": sent,
            "recent_tasks_ms": _latest_unique(handed, 5),
            "messages_7d": sent, "received_7d": received,
        }
        bots.append(record)
        measured.append(record)
    total = sum(item["messages_7d"] for item in measured) or 1
    ranking = sorted(measured, key=lambda item: (-item["messages_7d"], item["name"]))
    edge_rows = [{"source": a, "target": b, "kind": "dispatch", "weight": n} for (a, b), n in edges.most_common(12)]
    counts = Counter(bot["status"] for bot in bots)
    top_activity = [{"name": item["name"], "activity": item["messages_7d"], "share_pct": 0.0} for item in ranking[:3]]
    top_pairs = [{"source": row["source"], "target": row["target"], "weight": row["weight"], "dispatch": row["weight"], "mention": 0}
                 for row in edge_rows[:3]]
    text = internal_box.render_summary(now, counts, top_activity, top_pairs)
    text = "演示团队：" + text.split("：", 1)[1] if "：" in text else text
    busiest = ", ".join(f"{item['name']} ({item['activity']})" for item in top_activity)
    pairs = ", ".join(f"{row['source']} → {row['target']} ({row['weight']})" for row in top_pairs)
    text_en = (f"Demo team: files changed today for {counts.get('active', 0)} bots, in the last 3 days for "
               f"{counts.get('recent', 0)}, earlier for {counts.get('idle', 0)}. Most messages in 7 days: {busiest}. "
               f"Most dispatches: {pairs}. No quota data on this machine.")
    return {
        "generated_at_ms": now_ms, "timezone": "", "demo": True,
        "summary": {"text": text, "text_en": text_en, "active": counts.get("active", 0), "recent": counts.get("recent", 0),
                    "idle": counts.get("idle", 0), "no_folder": 0, "unmonitored": 0},
        "groups": sorted(set(groups.values())),
        "bots": bots,
        "edges": edge_rows,
        "usage": {"available": False, "note": internal_box.USAGE_NOTE, "counts_label": internal_box.COUNTS_LABEL,
                  "counts": [{"name": item["name"], "label": item["label"], "group": item["group"],
                              "messages_7d": item["messages_7d"], "received_7d": item["received_7d"],
                              "share_pct": round(100.0 * item["messages_7d"] / total, 1)} for item in ranking]},
    }


def main() -> None:
    now = int(time.time() * 1000)
    t0 = now - now % (10 * 60 * 1000)
    # Pin the demo history to one anchor so every frame shows the same past and only the
    # live relays move.
    views.demo_cache = lambda now_ms, language="zh": demo.demo_cache(now_ms, language, anchor_ms=t0)

    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "frontend", SITE)
    (SITE / ".nojekyll").write_text("")
    total = 0
    last = t0 + (FRAMES - 1) * STEP_MS
    for language in ("zh", "en"):
        settings = clean({"dataSource": "demo", "language": language})
        out = SITE / "data" / language
        frames = []
        for index in range(FRAMES):
            at = t0 + index * STEP_MS
            frame = {"office": views.office_view(settings, at), "flows": views.flows_view(24, settings, at)}
            frames.append((at, frame["office"], frame["flows"]))
            total += write(out / f"frame-{index:03d}.json", frame)
        total += write(out / "alerts.json", demo_alerts(frames, language))
        total += write(out / "internal.json", demo_internal(views.demo_cache(last, language), last, language))
        for hours in (168, 720):
            total += write(out / f"flows-{hours}.json", views.flows_view(hours, settings, last))
        total += write(out / "insights.json", views.insights_view(settings, last))

    config = {"t0": t0, "step": STEP_MS, "frames": FRAMES, "base": "data/", "repo": REPO}
    tag = f'<script>window.BOT_OFFICE_STATIC={json.dumps(config)}</script>\n  '
    for page in ("index.html", "settings.html"):
        path = SITE / page
        html = path.read_text(encoding="utf-8")
        marker = '<script src="js/i18n.js"></script>'
        if marker not in html:
            sys.exit(f"{page}: cannot find where to add the static config")
        html = html.replace(marker, tag + marker, 1)
        # A new build gets new URLs, so returning visitors never mix old scripts with new data.
        html = re.sub(r'((?:src|href)="(?:js/[\w-]+\.js|css/app\.css))"', rf'\1?v={t0}"', html)
        path.write_text(html, encoding="utf-8")
    print(f"Built {SITE.relative_to(ROOT)}/ · {FRAMES} frames × 2 languages · {total / 1e6:.1f} MB of data")


if __name__ == "__main__":
    main()
