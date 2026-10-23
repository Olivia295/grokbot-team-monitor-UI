"""Event adapter, bottlenecks, alerts, ingest endpoint and the static site build."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import server  # noqa: E402
from backend.alerts import AlertWatcher, detect, in_quiet_hours, render, webhook_request  # noqa: E402
from backend.collab import flows_from, office_from  # noqa: E402
from backend.demo import demo_cache  # noqa: E402
from backend.events import append_events, events_cache, parse_ts, read_events  # noqa: E402
from backend.settings import clean  # noqa: E402

NOW = 1_800_000_000_000
MIN = 60_000


def write_events(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


RUN = [
    {"type": "bot", "id": "planner", "name": "Planner", "team": "Core", "shape": "cat", "color": "sky"},
    {"type": "bot", "id": "coder", "name": "Coder", "team": "Build"},
    {"type": "ask", "to": "planner", "text": "Fix the login bug", "run": "r1", "ts": NOW - 20 * MIN},
    {"type": "handoff", "from": "planner", "to": "coder", "text": "Please fix it", "run": "r1", "ts": NOW - 19 * MIN},
    {"type": "error", "bot": "coder", "text": "tests failed", "run": "r1", "ts": NOW - 18 * MIN},
    {"type": "handoff", "from": "planner", "to": "coder", "text": "Try again", "run": "r1", "ts": NOW - 17 * MIN},
    {"type": "handoff", "from": "coder", "to": "planner", "text": "Fixed", "run": "r1", "ts": NOW - 15 * MIN},
    {"type": "reply", "from": "planner", "text": "Login bug fixed", "run": "r1", "ts": NOW - 14 * MIN},
]


class EventsTest(unittest.TestCase):
    def test_timestamps_in_seconds_ms_or_iso(self):
        self.assertEqual(parse_ts(1_800_000_000, 0), 1_800_000_000_000)
        self.assertEqual(parse_ts(1_800_000_000_123, 0), 1_800_000_000_123)
        self.assertEqual(parse_ts("2027-01-15T08:00:00Z", 0), 1_800_000_000_000)
        self.assertEqual(parse_ts("2027-01-15T16:00:00+08:00", 0), 1_800_000_000_000)
        self.assertEqual(parse_ts("not a date", 7), 7)
        self.assertEqual(parse_ts(True, 7), 7)

    def test_event_log_becomes_rooms_flows_and_bottlenecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            write_events(path, RUN)
            with path.open("a") as handle:
                handle.write("not json\n{\"type\": \"mystery\"}\n")
            self.assertEqual(len(read_events(path, NOW)), len(RUN))
            cache = events_cache(path, NOW)
        self.assertEqual(cache.source, "events")
        self.assertEqual([s["name"] for s in cache.sections], ["Core", "Build"])
        office = office_from(cache, NOW)
        self.assertEqual({a["id"]: a["wingName"] for a in office["agents"]}, {"planner": "Core", "coder": "Build"})
        self.assertEqual(next(a for a in office["agents"] if a["id"] == "planner")["avatarShape"], "cat")
        flows = flows_from(cache, NOW, 24)
        self.assertEqual(flows["flowCount"], 1)
        flow = flows["flows"][0]
        self.assertEqual(flow["trigger"]["kind"], "user")
        self.assertEqual([s["kind"] for s in flow["steps"]], ["handoff", "handoff", "handoff", "reply"])
        first, retry, back, _ = flow["steps"]
        self.assertTrue(first["failed"])
        self.assertTrue(retry["retry"])
        self.assertEqual(retry["waitMs"], 2 * MIN)  # coder answered two minutes after the retry
        self.assertTrue(flow["failed"])
        neck = flows["bottleneck"]
        self.assertEqual(neck["handoffs"], 3)
        self.assertEqual(neck["failures"], 1)
        self.assertEqual(neck["retries"], 1)
        self.assertIn({"from": "you", "to": "planner", "count": 1}, flows["sources"])
        self.assertIn({"from": "planner", "to": "you", "count": 1}, flows["sources"])

    def test_status_events_drive_live_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            write_events(path, [
                {"type": "status", "bot": "a", "state": "working", "ts": NOW - MIN},
                {"type": "status", "bot": "b", "state": "waiting", "ts": NOW - MIN},
                {"type": "status", "bot": "c", "state": "error", "ts": NOW - MIN},
            ])
            office = office_from(events_cache(path, NOW), NOW)
        states = {a["id"]: (a["state"], a["detail"]) for a in office["agents"]}
        self.assertEqual(states["a"], ("executing", "replying"))
        self.assertEqual(states["b"], ("idle", "awaiting"))
        self.assertEqual(states["c"][0], "error")
        self.assertTrue(office["appOnline"])

    def test_append_only_writes_known_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "events.jsonl"
            self.assertEqual(append_events(path, [{"type": "handoff", "from": "a", "to": "b", "_x": 1}, {"type": "nope"}, "x"]), 1)
            line = json.loads(path.read_text().strip())
        self.assertNotIn("_x", line)
        self.assertIn("ts", line)


class AlertsTest(unittest.TestCase):
    def config(self, **extra):
        return clean({"alerts": {"enabled": True, **extra}})["alerts"]

    def test_detects_errors_waiting_and_stuck_handoffs(self):
        office = {"agents": [
            {"id": "a", "name": "Ada", "state": "error", "detail": "error", "snippet": "boom"},
            {"id": "b", "name": "Bo", "state": "idle", "detail": "awaiting", "snippet": ""},
        ]}
        flows = {"external": [], "flows": [{"id": "f1", "handoffCount": 1, "steps": [
            {"kind": "handoff", "from": "a", "to": "b", "at": NOW - 20 * MIN, "traced": True, "failed": False, "waitMs": None, "text": "please"},
        ]}]}
        found = detect(office, flows, self.config(stuckMinutes=10), NOW)
        self.assertEqual(sorted(item["kind"] for item in found), ["awaiting", "error", "stuck"])
        stuck = next(item for item in found if item["kind"] == "stuck")
        title, body = render(stuck, "en")
        self.assertEqual(title, "Bo hasn't picked up Ada's handoff")
        self.assertIn("20 min", body)
        self.assertEqual(detect(office, flows, self.config(stuckMinutes=30), NOW)[-1]["kind"], "awaiting")

    def test_watcher_baselines_then_alerts_once(self):
        settings = clean({"dataSource": "demo", "language": "en", "alerts": {"enabled": True}})
        watcher = AlertWatcher("http://127.0.0.1:8080")
        sent = []
        self.assertEqual(watcher.scan(settings, NOW, send=lambda alert, config: sent.append(alert)), [])
        # Same conditions again: nothing new.
        self.assertEqual(watcher.scan(settings, NOW + 1000, send=lambda alert, config: sent.append(alert)), [])
        self.assertEqual(sent, [])
        # Switching a kind on starts a fresh baseline instead of replaying old matches.
        more = clean({"dataSource": "demo", "language": "en", "alerts": {"enabled": True, "done": True}})
        self.assertEqual(watcher.scan(more, NOW + 2000, send=lambda alert, config: sent.append(alert)), [])

    def test_quiet_hours_wrap_midnight(self):
        from datetime import datetime
        config = {"quiet": True, "quietFrom": 23, "quietTo": 8}
        self.assertTrue(in_quiet_hours(config, datetime(2027, 1, 1, 2)))
        self.assertFalse(in_quiet_hours(config, datetime(2027, 1, 1, 12)))
        self.assertFalse(in_quiet_hours({**config, "quiet": False}, datetime(2027, 1, 1, 2)))

    def test_webhook_payloads(self):
        alert = {"kind": "error", "title": "Ada ran into a problem", "body": "boom", "url": "http://127.0.0.1:8080",
                 "openLabel": "Open", "at": NOW, "bot": "a", "flowId": None}
        slack = json.loads(webhook_request({"kind": "slack", "url": "https://h/s"}, alert)[1])
        self.assertIn("*Ada ran into a problem*", slack["text"])
        feishu = json.loads(webhook_request({"kind": "feishu", "url": "https://h/f", "secret": "s"}, alert)[1])
        self.assertEqual(feishu["msg_type"], "text")
        self.assertIn("sign", feishu)
        url, body = webhook_request({"kind": "dingtalk", "url": "https://h/d?access_token=x", "secret": "s"}, alert)
        self.assertIn("&timestamp=", url)
        self.assertIn("[Bot Monitoring Room]", json.loads(body)["text"]["content"])
        generic = json.loads(webhook_request({"kind": "generic", "url": "https://h/g"}, alert)[1])
        self.assertEqual(generic["source"], "bot-monitor")

    def test_settings_reject_unsafe_webhooks(self):
        hooks = clean({"alerts": {"webhooks": [
            {"kind": "slack", "url": "https://hooks.slack.com/services/x"},
            {"kind": "slack", "url": "http://example.com/plain-http"},
            {"kind": "slack", "url": "https://bad url"},
            {"kind": "weird", "url": "http://localhost:9000/hook"},
        ]}})["alerts"]["webhooks"]
        self.assertEqual([hook["url"] for hook in hooks], ["https://hooks.slack.com/services/x", "http://localhost:9000/hook"])
        self.assertEqual(hooks[1]["kind"], "generic")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["GROK_COLLAB_SETTINGS"] = str(Path(cls.tmp.name) / "settings.json")
        os.environ["GROK_COLLAB_EVENTS"] = str(Path(cls.tmp.name) / "events.jsonl")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("GROK_COLLAB_SETTINGS", None)
        os.environ.pop("GROK_COLLAB_EVENTS", None)
        cls.tmp.cleanup()

    def post(self, path, payload, headers=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, None

    def test_scripts_can_post_events_and_see_them(self):
        status, body = self.post("/api/events", [
            {"type": "ask", "to": "alpha", "text": "hello"},
            {"type": "handoff", "from": "alpha", "to": "beta", "text": "over to you"},
        ])
        self.assertEqual((status, body["written"]), (200, 2))
        with urllib.request.urlopen(self.base + "/api/office") as response:
            office = json.loads(response.read())
        self.assertEqual(office["source"]["kind"], "events")
        self.assertEqual(sorted(a["id"] for a in office["agents"]), ["alpha", "beta"])

    def test_foreign_pages_cannot_post(self):
        status, _ = self.post("/api/events", {"type": "ask", "to": "x"}, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.post("/api/settings", {"language": "en"})  # no Origin: not the page
        self.assertEqual(status, 403)
        request = urllib.request.Request(self.base + "/api/events", data=b"type=ask", method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)

    def test_alerts_endpoint(self):
        with urllib.request.urlopen(self.base + "/api/alerts") as response:
            data = json.loads(response.read())
        self.assertEqual(data, {"enabled": False, "alerts": []})


class StaticSiteTest(unittest.TestCase):
    def test_demo_frames_keep_history_fixed(self):
        anchor = NOW - NOW % (10 * MIN)
        a = flows_from(demo_cache(anchor, "en", anchor_ms=anchor), anchor, 168)
        b = flows_from(demo_cache(anchor + 5 * MIN, "en", anchor_ms=anchor), anchor + 5 * MIN, 168)
        old = {flow["id"] for flow in a["flows"] if anchor - 6 * 24 * 60 * MIN < flow["endedAt"] < anchor - 30 * MIN}
        self.assertTrue(old)
        self.assertTrue(old <= {flow["id"] for flow in b["flows"]})


if __name__ == "__main__":
    unittest.main()
