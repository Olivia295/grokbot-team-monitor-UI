"""Every screen is real data: no automatic demo team, labelled read modes, data freshness."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import views  # noqa: E402
from backend.demo import demo_cache  # noqa: E402
from backend.events import events_cache  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class NoAutoDemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ("GROK_COLLAB_DEMO", "GROK_COLLAB_EVENTS", "GROK_BOT_SUPPORT"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_nothing_found_is_empty_not_demo(self):
        settings = {"dataSource": "auto", "supportDir": self.tmp.name}
        with mock.patch.object(views, "events_path", return_value=None), \
                mock.patch.object(views, "ingest_path", return_value=None):
            source = views.office_view(settings, box=False)["source"]
        self.assertFalse(source["demo"])
        self.assertFalse(source["found"])
        self.assertEqual(source["kind"], "grok")
        self.assertEqual(source["dataAt"], 0)

    def test_demo_only_when_asked(self):
        settings = {"dataSource": "demo", "supportDir": self.tmp.name}
        source = views.office_view(settings, box=False)["source"]
        self.assertTrue(source["demo"])


class FreshnessTest(unittest.TestCase):
    def test_events_report_when_the_log_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            log.write_text(json.dumps({"type": "ask", "to": "planner", "text": "hi"}) + "\n", encoding="utf-8")
            stamp = time.time() - 600
            os.utime(log, (stamp, stamp))
            cache = events_cache(log)
        self.assertEqual(cache.data_at, int(stamp * 1000))

    def test_demo_is_stamped_now(self):
        now = int(time.time() * 1000)
        self.assertEqual(demo_cache(now, "en").data_at, now)


class LabelsTest(unittest.TestCase):
    def setUp(self):
        self.i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
        self.stage = (ROOT / "frontend" / "js" / "stage.js").read_text(encoding="utf-8")
        self.main = (ROOT / "frontend" / "js" / "main.js").read_text(encoding="utf-8")

    def test_pill_says_internal_external_or_demo(self):
        for text in ('"pill.box": "内部读取 · Grok Bot 本机"', '"pill.online": "外部读取 · Grok Bot 应用在线"',
                     '"pill.none": "外部读取 · 没找到数据"', '"pill.demo": "演示数据 · 不是真实数据"',
                     '"pill.box": "Internal · Grok Bot box"', '"pill.none": "External · no data found"'):
            self.assertIn(text, self.i18n)
        self.assertNotIn("banner.demoAuto", self.i18n + self.main)
        self.assertIn("source.dataAt", self.main)

    def test_no_canned_speech(self):
        self.assertNotIn("speech.", self.i18n)
        self.assertNotIn("speech.", self.stage)
        for line in ("收到！", "谢谢～", "来杯咖啡", "Got it!", "Coffee?"):
            self.assertNotIn(line, self.i18n + self.stage)

    def test_file_activity_labels(self):
        self.assertIn('"internal.status.active": "今天有改动"', self.i18n)
        self.assertIn('"internal.status.recent": "3 天内有改动"', self.i18n)


if __name__ == "__main__":
    unittest.main()
