"""Box adapter: real transcripts for internal mode, never the demo team."""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.box_source import HIDDEN_TITLE, WILLOW_ID, load_box_cache, load_messages
from backend.internal_box import SYDNEY, make_config
from backend.server import Handler
from backend.views import flows_view, insights_view, office_view
from datetime import datetime

GROK = "f747fe8a-42b3-4549-952d-951887721c9b"
EGG = "ce01640f-ff42-4cac-9b87-35ac77fcf368"
SHIP = "5de8806d-518b-46bf-b0d2-965efedc1493"
SCOUT = "452c8175-1510-49dc-a538-cddd3f130d34"
SSH = "5990168b-750e-4ef5-8920-2614c36f33bc"

YOU_SECRET = "YOU-PRIVATE-BODY-9f3a"
ASSIST_SECRET = "ASSISTANT-SECRET-BODY-9f3a"
YOU_REPLY_SECRET = "ASSISTANT-TO-YOU-SECRET-9f3a"
WILLOW_SECRET = "WILLOW-SECRET-BODY-9f3a"
WILLOW_REPLY = "WILLOW-REPLY-SECRET-9f3a"
WILLOW_EDGE = "WILLOW-EDGE-SECRET-9f3a"
WILLOW_PROFILE = "WILLOW-PROFILE-SECRET-9f3a"
PROFILE_SECRET = "PROFILE-SECRET-DESC-9f3a"
FILE_SECRET = "SECRET-FILE-SHOULD-NOT-LOAD"
TAIL = "TAIL-SHOULD-NOT-SHOW-9f3a"
NOT_PREFIX = "LEAK-NOT-PREFIX-9f3a"
BOUNDARY = "LEAK-BOUNDARY-9f3a"
FEEL_LEAK = "FEEL-LEAK-9f3a"
MOOD_LEAK = "MOOD-LEAK-9f3a"
DISPATCH_HIDDEN = "心情类，已告诉 Willow"

SETTINGS = {"dataSource": "auto", "language": "zh", "privacy": False, "bots": {}, "rooms": {}}

ROSTER = """# roster

## 一、名单

| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |
| --- | --- | --- | --- | --- |
| Grok Bot | 参谋长 | f747fe8a-42b3-4549-952d-951887721c9b | 分派任务 | 聊天 |
| Dr Eggbot | 母体 | ce01640f-ff42-4cac-9b87-35ac77fcf368 | 维护名册 | 派活 |
| Spaceship Co-Pilot | 飞船副驾 | 5de8806d-518b-46bf-b0d2-965efedc1493 | 管博客 | 聊天 |
| Code Scout | AI 工具管家 | 452c8175-1510-49dc-a538-cddd3f130d34 | 找仓库 | 聊天 |
| Willow Mage | 心灵陪伴 | 0aae13ef-b790-4061-a6e8-1dc6d5e45803 | 陪伴 | 聊天 |

### 侧栏分组
| 分组 | 成员 |
| --- | --- |
| 司令部 | Grok Bot、Dr Eggbot |
| 前线部队 | Spaceship Co-Pilot、Code Scout |
| 休整营 | Willow Mage |
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _db(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            agent_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            role TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            body TEXT NOT NULL,
            seq INTEGER,
            in_main_chat INTEGER NOT NULL
        )"""
    )
    conn.executemany(
        "INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,1)",
        rows,
    )
    conn.commit()
    conn.close()


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


class BoxSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = int(time.time() * 1000)
        self._demo = os.environ.get("GROK_COLLAB_DEMO")

    def tearDown(self):
        if self._demo is None:
            os.environ.pop("GROK_COLLAB_DEMO", None)
        else:
            os.environ["GROK_COLLAB_DEMO"] = self._demo
        self.tmp.cleanup()

    def _config(self, messages, dispatch=None, profiles=None, roster=ROSTER, write_roster=True):
        roster_path = self.root / "roster.md"
        agent_data = self.root / "agent-data"
        home = self.root / "home"
        workspace = self.root / "ws"
        if write_roster:
            _write(roster_path, roster)
        if messages is not None:
            _db(agent_data / "search-index.db", messages)
        for agent_id, payload in (profiles or {}).items():
            folder = agent_data / "agents" / agent_id
            _write(folder / "profile.json", json.dumps(payload, ensure_ascii=False))
        config = make_config(workspace, roster=roster_path, agent_data=agent_data, home=home)
        if dispatch is not None:
            _write(config.dispatch_log, dispatch)
        return config

    def _load(self, config):
        with mock.patch("backend.box_source.default_config", return_value=config):
            cache = load_box_cache()
            office = office_view(SETTINGS, self.now, box=True)
            flows = flows_view(168, SETTINGS, self.now, box=True)
            insights = insights_view(SETTINGS, self.now, box=True)
        return cache, office, flows, insights

    def _dump(self, *values) -> str:
        return json.dumps(values, ensure_ascii=False)

    def test_sql_excludes_willow_and_opens_read_only(self):
        source = Path(__file__).resolve().parents[1].joinpath("backend", "box_source.py").read_text(encoding="utf-8")
        self.assertIn("mode=ro", source)
        self.assertIn("agent_id NOT IN", source)
        db = self.root / "search-index.db"
        _db(db, [
            (WILLOW_ID, "w", "user", self.now, WILLOW_SECRET, 1),
            (SCOUT, "s", "user", self.now, "hello", 1),
        ])
        rows = load_messages(db, {WILLOW_ID})
        self.assertEqual([row[0] for row in rows], [SCOUT])
        self.assertNotIn(WILLOW_SECRET, json.dumps(rows, ensure_ascii=False))

    def test_handoff_you_willow_sensitive_and_dispatch(self):
        ship_body = "Spaceship Co-Pilot please review the launch draft " + TAIL + ("x" * 40)
        mood_body = f"Dr Eggbot 今天心情很差不要外传 {MOOD_LEAK}"
        feel_body = f"Code Scout I feel awful {FEEL_LEAK}"
        you_body = f"帮我写周报 {YOU_SECRET} 不要显示"
        not_prefix = f"来自 Dr Eggbot {NOT_PREFIX}"
        boundary = f"Dr Eggbot2 is a different token {BOUNDARY}"
        egg_line = "\n  Dr Eggbot file the roster"
        today = datetime.fromtimestamp(self.now / 1000, SYDNEY).strftime("%Y-%m-%d")
        dispatch = (
            f"| {today} | 整理名册里的文件夹名字 | Dr Eggbot | 已交 |\n"
            f"| {today} | {DISPATCH_HIDDEN} | Willow Mage | 已交 |\n"
        )
        t = self.now - 60_000
        messages = [
            (SCOUT, "s-user", "user", t, ship_body, 1),
            (SCOUT, "s-asst", "assistant", t + 1000, ASSIST_SECRET, 2),
            (SCOUT, "s-you", "user", t + 2000, you_body, 3),
            (SCOUT, "s-you-asst", "assistant", t + 3000, YOU_REPLY_SECRET, 4),
            (SCOUT, "s-mid", "user", t + 4000, not_prefix, 5),
            (SCOUT, "s-bound", "user", t + 5000, boundary, 6),
            (SHIP, "p-mood", "user", t + 6000, mood_body, 1),
            (SHIP, "p-mood-asst", "assistant", t + 7000, "mood reply " + ASSIST_SECRET, 2),
            (SHIP, "p-feel", "user", t + 8000, feel_body, 3),
            (GROK, "g-egg", "user", t + 9000, egg_line, 1),
            (GROK, "g-willow", "user", t + 10000, f"Willow Mage please talk {WILLOW_EDGE}", 2),
            (GROK, "g-willow-asst", "assistant", t + 11000, "nope " + ASSIST_SECRET, 3),
            (WILLOW_ID, "w-user", "user", t, WILLOW_SECRET, 1),
            (WILLOW_ID, "w-asst", "assistant", t + 1000, WILLOW_REPLY, 2),
            (EGG, "e-you", "user", t, f"请看这个 {YOU_SECRET}", 1),
            (EGG, "e-asst", "assistant", t + 500, YOU_REPLY_SECRET, 2),
        ]
        config = self._config(
            messages,
            dispatch=dispatch,
            profiles={
                SSH: {"name": "SSH to Grok via Tailscale", "description": PROFILE_SECRET},
                WILLOW_ID: {"name": "Willow Mage", "description": WILLOW_PROFILE},
            },
        )
        _write(config.agent_data / "agents" / SSH / "secrets.json", FILE_SECRET)
        _write(config.agent_data / "agents" / SSH / "auth.json", FILE_SECRET)
        cache, office, flows, insights = self._load(config)
        blob = self._dump(cache.roster, cache.transcripts, office, flows, insights)

        self.assertFalse(cache.demo)
        self.assertTrue(cache.box)
        self.assertFalse(cache.empty)
        self.assertFalse(office["source"]["demo"])
        self.assertTrue(office["source"]["box"])
        self.assertFalse(office["source"]["empty"])

        expected = " ".join(ship_body.split())[:40]
        self.assertGreater(len(ship_body), 40)
        ship_legs = [step for flow in flows["flows"] for step in flow["steps"] if step["from"] == SHIP and step["to"] == SCOUT]
        self.assertEqual(len(ship_legs), 1)
        self.assertEqual(ship_legs[0]["kind"], "handoff")
        self.assertEqual(ship_legs[0]["text"], expected)
        self.assertLessEqual(len(ship_legs[0]["text"]), 40)
        self.assertNotIn(TAIL, ship_legs[0]["text"])
        scout_entries, _mtime = cache.transcript(SCOUT)
        ship_user = next(entry for entry in scout_entries if entry.get("fromAgent", {}).get("id") == SHIP)
        ship_reply = next(entry for entry in scout_entries if entry["role"] == "assistant" and entry["requestId"] == ship_user["requestId"])
        self.assertEqual(ship_reply["content"], "")
        scout_flow = next(flow for flow in flows["flows"] if any(step["from"] == SHIP and step["to"] == SCOUT for step in flow["steps"]))
        self.assertEqual([step["kind"] for step in scout_flow["steps"]], ["handoff"])

        egg_legs = [step for flow in flows["flows"] for step in flow["steps"] if step["from"] == EGG and step["to"] == GROK]
        self.assertEqual([step["text"] for step in egg_legs], ["Dr Eggbot file the roster"])

        for entries, _mtime in cache.transcripts.values():
            for entry in entries:
                if entry["role"] == "assistant" or (entry["role"] == "user" and "fromAgent" not in entry):
                    self.assertEqual(entry["content"], "")
                if entry.get("fromAgent"):
                    self.assertLessEqual(len(entry["content"]), 40)
        for text in _walk_strings([office, flows, insights]):
            self.assertNotIn(YOU_SECRET, text)
            self.assertNotIn(YOU_REPLY_SECRET, text)
            self.assertNotIn(ASSIST_SECRET, text)
        self.assertNotIn(YOU_SECRET, blob)
        self.assertNotIn(NOT_PREFIX, blob)
        self.assertNotIn(BOUNDARY, blob)
        self.assertFalse(any(step["from"] == EGG and NOT_PREFIX in step["text"] for flow in flows["flows"] for step in flow["steps"]))
        self.assertFalse(any(step["text"].startswith("Dr Eggbot2") for flow in flows["flows"] for step in flow["steps"]))

        hidden = [step for flow in flows["flows"] for step in flow["steps"] if step["from"] == EGG and step["to"] == SHIP]
        self.assertEqual([step["text"] for step in hidden], [HIDDEN_TITLE])
        feel = [step for flow in flows["flows"] for step in flow["steps"] if step["from"] == SCOUT and step["to"] == SHIP]
        self.assertEqual([step["text"] for step in feel], [HIDDEN_TITLE])
        for token in (MOOD_LEAK, FEEL_LEAK, "心情很差", "feel awful", DISPATCH_HIDDEN, "心情类"):
            self.assertNotIn(token, blob)

        dispatch_legs = [step for flow in flows["flows"] for step in flow["steps"] if step["from"] == GROK and step["to"] == EGG]
        self.assertEqual([step["text"] for step in dispatch_legs], ["整理名册里的文件夹名字"])

        self.assertNotIn(WILLOW_ID, cache.transcripts)
        for token in (WILLOW_SECRET, WILLOW_REPLY, WILLOW_EDGE, WILLOW_PROFILE, PROFILE_SECRET, FILE_SECRET):
            self.assertNotIn(token, blob)
        for link in flows["links"]:
            self.assertNotIn(WILLOW_ID, (link["from"], link["to"]))
        for flow in flows["flows"]:
            self.assertNotIn(WILLOW_ID, flow["participants"])
        willow = next(agent for agent in office["agents"] if agent["id"] == WILLOW_ID)
        self.assertEqual(willow["name"], "Willow Mage")
        self.assertEqual(willow["snippet"], "")
        self.assertEqual(willow["roleLine"], "")
        self.assertEqual(willow["title"], "")
        profile = next(item for item in insights["profiles"] if item["id"] == WILLOW_ID)
        self.assertEqual(profile["asks"], 0)
        self.assertEqual(profile["handoffsIn"], 0)
        self.assertEqual(profile["handoffsOut"], 0)
        self.assertEqual(profile["replies"], 0)
        self.assertEqual(sum(profile["hours"]), 0)
        self.assertEqual(profile["partners"], [])
        for item in insights["profiles"]:
            self.assertNotIn(WILLOW_ID, {partner["id"] for partner in item["partners"]})
        for item in insights["feed"]:
            self.assertNotIn(WILLOW_ID, (item.get("from"), item.get("to")))

        ssh = next(agent for agent in office["agents"] if agent["id"] == SSH)
        self.assertEqual(ssh["name"], "SSH to Grok via Tailscale")
        self.assertEqual(ssh["wingId"], "__loose__")
        self.assertEqual(ssh["roleLine"], "")

    def test_empty_internal_mode_does_not_fall_back_to_demo(self):
        os.environ["GROK_COLLAB_DEMO"] = "1"
        config = self._config(messages=None, profiles=None)
        with mock.patch("backend.views.demo_cache") as demo:
            cache, office, flows, insights = self._load(config)
            demo.assert_not_called()
        self.assertTrue(cache.box)
        self.assertTrue(cache.empty)
        self.assertFalse(cache.demo)
        self.assertFalse(office["source"]["demo"])
        self.assertTrue(office["source"]["box"])
        self.assertTrue(office["source"]["empty"])
        self.assertTrue(office["source"]["found"])
        names = {agent["name"] for agent in office["agents"]}
        self.assertIn("Grok Bot", names)
        self.assertNotIn("Atlas", names)
        self.assertNotIn("demo-atlas", {agent["id"] for agent in office["agents"]})
        self.assertEqual(flows["flows"], [])
        self.assertEqual(flows["flowCount"], 0)
        self.assertFalse(flows["source"]["demo"])
        self.assertTrue(insights["source"]["empty"])
        self.assertFalse(any(profile["id"].startswith("demo-") for profile in insights["profiles"]))

        missing = self._config(messages=None, write_roster=False)
        if missing.roster_path.exists():
            missing.roster_path.unlink()
        with mock.patch("backend.views.demo_cache") as demo:
            cache = load_box_cache(missing)
            with mock.patch("backend.box_source.default_config", return_value=missing):
                office = office_view(SETTINGS, self.now, box=True)
            demo.assert_not_called()
        self.assertFalse(cache.demo)
        self.assertTrue(cache.empty)
        self.assertEqual(cache.roster, [])
        self.assertFalse(office["source"]["demo"])
        self.assertTrue(office["source"]["empty"])
        self.assertEqual(office["agents"], [])

    def test_frontend_copy_separates_errors_and_empty_state(self):
        root = Path(__file__).resolve().parents[1]
        i18n = (root / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
        internal = (root / "frontend" / "js" / "internal.js").read_text(encoding="utf-8")
        main = (root / "frontend" / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn('"box.empty": "本机暂无协作记录"', i18n)
        self.assertIn('"box.empty": "No box collaboration records yet"', i18n)
        self.assertIn('"request.failed": "后端请求失败"', i18n)
        self.assertIn('"request.failed": "Backend request failed"', i18n)
        self.assertIn("request.retry", i18n)
        self.assertIn("result.failed", internal)
        self.assertIn("result.unavailable", internal)
        self.assertIn("mode.unavailable", internal)
        self.assertIn("mode-retry", internal)
        self.assertIn("withBox", main)
        self.assertIn("pill.demo", main)
        self.assertIn("source.demo", main)
        self.assertIn("box.empty", main)


class BoxApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def request(self, path):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        conn.close()
        return status, body

    def test_box_query_does_not_use_demo(self):
        saved = os.environ.get("GROK_COLLAB_DEMO")
        os.environ["GROK_COLLAB_DEMO"] = "1"
        try:
            status, body = self.request("/api/office")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["source"]["demo"])
            from backend.box_source import empty_box_cache
            with mock.patch("backend.views.load_box_cache", return_value=empty_box_cache()):
                status, body = self.request("/api/office?box=1")
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertFalse(payload["source"]["demo"])
            self.assertTrue(payload["source"]["box"])
            self.assertTrue(payload["source"]["empty"])
            self.assertNotIn("Atlas", {agent["name"] for agent in payload["agents"]})
            with mock.patch("backend.views.load_box_cache", return_value=empty_box_cache()):
                status, body = self.request("/api/flows?hours=24&box=1")
            self.assertEqual(status, 200)
            flows = json.loads(body)
            self.assertFalse(flows["source"]["demo"])
            self.assertEqual(flows["flows"], [])
        finally:
            if saved is None:
                os.environ.pop("GROK_COLLAB_DEMO", None)
            else:
                os.environ["GROK_COLLAB_DEMO"] = saved


if __name__ == "__main__":
    unittest.main()
