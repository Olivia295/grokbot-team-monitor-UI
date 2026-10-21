#!/usr/bin/env python3
"""Build the online demo for GitHub Pages into site/ (no server needed to view it).

    python3 scripts/build_pages.py            # writes site/
    python3 -m http.server -d site 8000       # preview at http://127.0.0.1:8000

The demo team is recorded as JSON frames 30 seconds apart over half an hour, in both
languages. The page plays the frames in a loop and shifts every timestamp to the present,
so the online demo always looks live. See STATIC in frontend/js/common.js.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import demo, views  # noqa: E402
from backend.settings import clean  # noqa: E402

SITE = ROOT / "site"
STEP_MS = 30 * 1000
FRAMES = 60
REPO = "https://github.com/Olivia295/grokbot-teamwork-UI"


def write(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    return len(data.encode("utf-8"))


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
        for index in range(FRAMES):
            at = t0 + index * STEP_MS
            total += write(out / f"frame-{index:03d}.json", {
                "office": views.office_view(settings, at),
                "flows": views.flows_view(24, settings, at),
            })
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
        path.write_text(html.replace(marker, tag + marker, 1), encoding="utf-8")
    print(f"Built {SITE.relative_to(ROOT)}/ · {FRAMES} frames × 2 languages · {total / 1e6:.1f} MB of data")


if __name__ == "__main__":
    main()
