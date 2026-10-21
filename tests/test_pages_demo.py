"""The online demo: sample alerts and box panel built from the demo team, the tour, the tasks window."""

import importlib.util
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import alerts, demo, views  # noqa: E402
from backend.settings import clean  # noqa: E402

spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts" / "build_pages.py")
build_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_pages)

DEMO_NAMES = {bot[2] for bot in demo.BOTS}


class DemoAlertsTest(unittest.TestCase):
    def test_real_rules_find_waiting_and_stuck(self):
        now = int(time.time() * 1000)
        settings = clean({"dataSource": "demo", "language": "en"})
        frames = [(at, views.office_view(settings, at), views.flows_view(24, settings, at))
                  for at in (now, now + 30_000, now + 60_000)]
        found = build_pages.demo_alerts(frames, "en")
        kinds = {item["kind"] for item in found}
        self.assertIn("awaiting", kinds)
        self.assertIn("stuck", kinds)
        self.assertTrue(all(item["demo"] for item in found))
        self.assertEqual(len({item["key"] for item in found}), len(found), "each condition alerts once")
        self.assertEqual([item["at"] for item in found], sorted((item["at"] for item in found), reverse=True))
        stuck = next(item for item in found if item["kind"] == "stuck")
        self.assertEqual(stuck["title"], alerts.render({"kind": "stuck", "params": {"to": "Pixel", "sender": "Atlas", "minutes": 1}}, "en")[0])


class DemoBoxPanelTest(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time() * 1000)
        self.payload = build_pages.demo_internal(demo.demo_cache(self.now, "en"), self.now, "en")

    def test_same_shape_as_the_box(self):
        payload = self.payload
        self.assertTrue(payload["demo"])
        self.assertEqual(payload["usage"]["counts_label"], build_pages.internal_box.COUNTS_LABEL)
        self.assertFalse(payload["usage"]["available"])
        for key in ("text", "text_en", "active", "recent", "idle"):
            self.assertIn(key, payload["summary"])
        self.assertEqual({bot["name"] for bot in payload["bots"]}, DEMO_NAMES)
        self.assertTrue(all(edge["source"] in DEMO_NAMES and edge["target"] in DEMO_NAMES for edge in payload["edges"]))

    def test_counts_come_from_the_demo_records(self):
        cache = demo.demo_cache(self.now, "en")
        since = self.now - 7 * 86400 * 1000
        rows = {row["name"]: row for row in self.payload["usage"]["counts"]}
        for agent in cache.roster:
            entries = [e for e in cache.transcripts[agent["id"]][0] if since <= e["timestampMs"] <= self.now]
            received = sum(1 for e in entries if e.get("role") == "user")
            self.assertEqual(rows[agent["name"]]["received_7d"], received, agent["name"])

    def test_recent_tasks_are_unique_and_capped(self):
        for bot in self.payload["bots"]:
            texts = [text for _ms, text in bot["recent_tasks_ms"]]
            self.assertLessEqual(len(texts), 5)
            self.assertEqual(len(texts), len(set(texts)), bot["name"])

    def test_front_desk_has_a_group(self):
        concierge = next(bot for bot in self.payload["bots"] if bot["name"] == "Concierge")
        self.assertEqual(concierge["group"], "Front desk")


class DemoDataTest(unittest.TestCase):
    def test_a_handoff_is_left_hanging(self):
        now = int(time.time() * 1000)
        flows = views.flows_view(24, clean({"dataSource": "demo", "language": "en"}), now)
        hanging = [flow for flow in flows["flows"] if flow["steps"] and flow["steps"][-1]["kind"] == "handoff"
                   and flow["steps"][-1].get("waitMs") is None and now - flow["steps"][-1]["at"] > 10 * 60 * 1000]
        self.assertTrue(hanging)


class TourAndTasksWindowTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
        self.tour = (ROOT / "frontend" / "js" / "tour.js").read_text(encoding="utf-8")
        self.internal = (ROOT / "frontend" / "js" / "internal.js").read_text(encoding="utf-8")

    def test_wired_into_the_page(self):
        self.assertIn('id="tour-btn"', self.html)
        self.assertIn('<script src="js/tour.js"></script>', self.html)
        self.assertLess(self.html.index("js/tour.js"), self.html.index("js/main.js"))
        self.assertIn('id="tasks-dialog"', self.html)
        self.assertIn("showModal", self.internal)
        self.assertNotIn("<details><summary>", self.internal)

    def test_every_step_has_copy_in_both_languages(self):
        keys = re.findall(r'key: "(\w+)"', self.tour)
        self.assertGreaterEqual(len(keys), 8)
        for key in keys:
            for suffix in (".title", ""):
                self.assertEqual(self.i18n.count(f'"tour.{key}{suffix}":'), 2, f"tour.{key}{suffix}")

    def test_demo_labels_say_not_real(self):
        self.assertIn('"pill.static": "在线演示 · 不是真实数据"', self.i18n)
        self.assertIn('"internal.titleDemo": "Grok Bot box panel · demo sample"', self.i18n)


if __name__ == "__main__":
    unittest.main()
