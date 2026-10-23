"""Internal status board: real counts only, no message bodies, Willow by name."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.internal_box import SYDNEY, WILLOW_ID, make_config  # noqa: E402
from backend.server import Handler  # noqa: E402
from backend.status_board import NA, build  # noqa: E402

GROK = "f747fe8a-42b3-4549-952d-951887721c9b"
MORNING = "f2441b1c-c90e-4590-a812-25de68bb10d6"
NOW = datetime(2026, 10, 23, 10, 41, tzinfo=SYDNEY)
NOW_MS = int(NOW.timestamp() * 1000)

ROSTER = """# roster

## 一、名单

| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |
| --- | --- | --- | --- | --- |
| Grok Bot | 参谋长 | f747fe8a-42b3-4549-952d-951887721c9b | 分派 | 聊天 |
| Morning Bridge | 信息主管 | f2441b1c-c90e-4590-a812-25de68bb10d6 | 晨报 | 每天 |
| Willow Mage | 心灵陪伴 | 0aae13ef-b790-4061-a6e8-1dc6d5e45803 | 陪伴 | 聊天 |

### 侧栏分组
| 分组 | 成员 |
| --- | --- |
| 司令部 | Grok Bot、Morning Bridge |
| 休整营 | Willow Mage |
"""

HOST = {
    "generated_at": "now",
    "refresh_seconds": 30,
    "uptime": {"text": "1d 1h 1m", "days": 1, "hours": 1, "minutes": 1, "seconds": 90061.0},
    "load": ["0.10", "0.20", "0.30"],
    "memory": {"used_mib": 1000, "total_mib": 2000, "text": "1000 / 2000 MiB used"},
    "services": [
        {"name": "JupyterLab", "port": 8888, "up": True, "latency_ms": 1.2},
        {"name": "Dashboard", "port": 8080, "up": True, "latency_ms": 0.8},
        {"name": "Blog", "port": 4000, "up": False, "latency_ms": None},
    ],
}

SECRETS = (
    "SECRET-BODY",
    "SECRET-HANDOFF",
    "SECRET-WILLOW",
    "SECRET-ASK",
    "SECRET-REPLY",
    "USER-PRIVATE-BODY",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _at(*, days=0, hours=0, minutes=0, seconds=0) -> int:
    stamp = NOW - timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return _ms(stamp)


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


def _kpis(payload: dict) -> dict:
    return {item["id"]: item for item in payload["kpis"]}


def _fixture_rows() -> list[tuple]:
    """Hand-counted fixture around 2026-10-23 10:41 Sydney.

    Last 15 minutes (10:26–10:41): 4 messages
      Grok assistant 10:30, Grok assistant 10:35, Morning user 10:38, Willow assistant 10:39
    Last hour (09:41–10:41): those 4 + Grok user 10:00 + Grok assistant 10:00:04 = 6
    Handoffs last 24h: 1 (Morning user starting with "Grok Bot" at 09:00)
    Reply samples: 4000ms (Grok 10:00), 5000ms (Morning 08:00), 3000ms (Grok yesterday 18:00) → median 4.0s
    Yesterday same 15 minutes: 2 messages. Days 2–7 same window: 2 each → 7-day avg 2, +100%
    """
    rows = [
        (GROK, "g-now-1", "assistant", _at(minutes=11), "SECRET-BODY 现在的回复", 10),
        (GROK, "g-now-2", "assistant", _at(minutes=6), "SECRET-BODY 另一条", 11),
        (MORNING, "m-now-u", "user", _at(minutes=3), "USER-PRIVATE-BODY 今天怎么样", 20),
        (WILLOW_ID, "w-now", "assistant", _at(minutes=2), "SECRET-WILLOW 不该出现", 1),
        (GROK, "g-hour-u", "user", _at(minutes=41), "SECRET-ASK 请看一下", 8),
        (GROK, "g-hour-a", "assistant", _at(minutes=41) + 4000, "SECRET-REPLY 好的", 9),
        (MORNING, "m-hand-u", "user", _at(hours=1, minutes=41), "Grok Bot 请准备晨报 SECRET-HANDOFF", 5),
        (MORNING, "m-hand-a", "assistant", _at(hours=1, minutes=41) + 30_000, "SECRET-BODY 已准备", 6),
        (MORNING, "m-reply-u", "user", _at(hours=2, minutes=41), "USER-PRIVATE-BODY 早报呢", 3),
        (MORNING, "m-reply-a", "assistant", _at(hours=2, minutes=41) + 5000, "SECRET-REPLY 在写", 4),
        (GROK, "g-yday-r-u", "user", _at(days=1, hours=16, minutes=41), "SECRET-ASK 昨天晚上", 1),
        (GROK, "g-yday-r-a", "assistant", _at(days=1, hours=16, minutes=41) + 3000, "SECRET-REPLY 收到", 2),
        (GROK, "g-yday-15", "assistant", _at(days=1, minutes=11), "SECRET-BODY 昨天同时段", 30),
        (MORNING, "m-yday-15", "assistant", _at(days=1, minutes=9), "SECRET-BODY 昨天同时段二", 31),
    ]
    seq = 100
    for day in range(2, 8):
        rows.append((GROK, f"g-w{day}a", "assistant", _at(days=day, minutes=11), "SECRET-BODY 周同时段", seq))
        rows.append((MORNING, f"m-w{day}a", "assistant", _at(days=day, minutes=9), "SECRET-BODY 周同时段二", seq + 1))
        seq += 2
    return rows


class StatusBoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved = os.environ.pop("BOT_OFFICE_INTERNAL", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("BOT_OFFICE_INTERNAL", None)
        else:
            os.environ["BOT_OFFICE_INTERNAL"] = self._saved
        self.tmp.cleanup()

    def _config(self, rows=None, roster=ROSTER, write_db=True):
        roster_path = self.root / "roster.md"
        agent = self.root / "agent-data"
        home = self.root / "home"
        workspace = self.root / "ws"
        _write(roster_path, roster)
        if write_db:
            _db(agent / "search-index.db", rows if rows is not None else _fixture_rows())
        return make_config(workspace, roster=roster_path, agent_data=agent, home=home)

    def _build(self, config, host=None):
        return build(config, now=NOW, host=host if host is not None else HOST)

    def test_counts_match_the_fixture(self):
        payload = self._build(self._config())
        kpis = _kpis(payload)
        self.assertEqual(kpis["bots"]["value"], 3)
        self.assertEqual(kpis["bots"]["total"], 3)
        self.assertEqual(kpis["bots"]["status"], "ok")
        self.assertEqual(kpis["messages"]["value"], 4)
        self.assertEqual(kpis["messages"]["meta"]["messages_1h"], 6)
        self.assertEqual(kpis["messages"]["compare"]["yesterday_pct"], 100.0)
        self.assertEqual(kpis["messages"]["compare"]["week_pct"], 100.0)
        self.assertEqual(kpis["handoffs"]["value"], 1)
        self.assertEqual(kpis["reply"]["value"], 4.0)
        self.assertEqual(kpis["reply"]["meta"]["samples"], 3)
        self.assertEqual(kpis["host"]["value"], "1d 1h 1m")
        self.assertEqual(kpis["host"]["status"], "ok")
        self.assertFalse(kpis["fail"]["available"])
        self.assertIsNone(kpis["fail"]["value"])
        self.assertTrue(payload["overall"]["ok"])
        self.assertEqual(payload["refresh_seconds"], 30)
        self.assertEqual(payload["timezone"], "Australia/Sydney")
        self.assertTrue(payload["generated_at"].startswith("2026-10-23T10:41:00"))

    def test_willow_is_name_and_counts_only(self):
        payload = self._build(self._config())
        willow = next(bot for bot in payload["bots"] if bot["name"] == "Willow Mage")
        self.assertEqual(willow["group"], "休整营")
        self.assertTrue(willow["unmonitored"])
        self.assertEqual(willow["messages_24h"], 1)
        self.assertIsNotNone(willow["last_active"])
        self.assertEqual(sum(willow["hours_24"]), 1)
        blob = json.dumps(payload, ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, blob)
        self.assertNotIn("请准备晨报", blob)
        self.assertNotIn("今天怎么样", blob)

    def test_hourly_cells_and_partial_current_hour(self):
        payload = self._build(self._config())
        series = payload["messages"]
        self.assertEqual(len(series["hours_24"]), 24)
        self.assertEqual(series["hour_labels_24"][-1], "10")
        self.assertTrue(series["partial_hour"])
        # Current hour 10:00–10:41 contains the 4 recent + Grok pair at 10:00 = 6.
        self.assertEqual(series["hours_24"][-1], 6)
        grok = next(bot for bot in payload["bots"] if bot["name"] == "Grok Bot")
        self.assertGreater(grok["hours_24"][-1], 0)
        # 7-day same-hour average for the current 15-min window is 2; hourly avg is computed per clock hour.
        self.assertEqual(len(series["hours_24_avg7"]), 24)
        self.assertTrue(all(isinstance(v, float) for v in series["hours_24_avg7"]))

    def test_missing_index_is_unavailable_not_zero(self):
        payload = self._build(self._config(write_db=False))
        kpis = _kpis(payload)
        self.assertFalse(kpis["bots"]["available"])
        self.assertIsNone(kpis["bots"]["value"])
        self.assertFalse(kpis["messages"]["available"])
        self.assertIsNone(kpis["messages"]["value"])
        self.assertFalse(kpis["handoffs"]["available"])
        self.assertFalse(kpis["reply"]["available"])
        self.assertFalse(payload["messages"]["available"])
        self.assertIsNone(payload["messages"]["hours_24"])
        self.assertEqual(kpis["host"]["value"], "1d 1h 1m")

    def test_reply_unavailable_without_pairs(self):
        rows = [(GROK, "only-a", "assistant", _at(minutes=5), "SECRET-BODY", 1)]
        payload = self._build(self._config(rows=rows))
        kpis = _kpis(payload)
        self.assertTrue(kpis["messages"]["available"])
        self.assertEqual(kpis["messages"]["value"], 1)
        self.assertFalse(kpis["reply"]["available"])
        self.assertIsNone(kpis["reply"]["value"])
        self.assertEqual(kpis["handoffs"]["value"], 0)

    def test_host_memory_watch_sets_overall_alert(self):
        host = json.loads(json.dumps(HOST))
        host["memory"] = {"used_mib": 1900, "total_mib": 2000, "text": "1900 / 2000 MiB used"}
        payload = self._build(self._config(), host=host)
        kpis = _kpis(payload)
        self.assertEqual(kpis["host"]["status"], "watch")
        self.assertFalse(payload["overall"]["ok"])

    def test_services_carry_latency(self):
        payload = self._build(self._config())
        rows = {(s["name"], s["port"], s["up"], s["latency_ms"]) for s in payload["services"]}
        self.assertEqual(
            rows,
            {
                ("JupyterLab", 8888, True, 1.2),
                ("Dashboard", 8080, True, 0.8),
                ("Blog", 4000, False, None),
            },
        )

    def test_yesterday_zero_baseline_is_not_a_percent(self):
        rows = [(GROK, "only", "assistant", _at(minutes=2), "SECRET-BODY", 1)]
        payload = self._build(self._config(rows=rows))
        kpis = _kpis(payload)
        self.assertEqual(kpis["messages"]["value"], 1)
        self.assertIsNone(kpis["messages"]["compare"]["yesterday_pct"])

    def test_na_constant_is_the_placeholder(self):
        self.assertEqual(NA, "暂无数据")


class QuietHandler(Handler):
    def log_message(self, fmt, *args):
        return


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True


class StatusBoardApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ReuseServer(("127.0.0.1", 0), QuietHandler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self._saved = os.environ.pop("BOT_OFFICE_INTERNAL", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("BOT_OFFICE_INTERNAL", None)
        else:
            os.environ["BOT_OFFICE_INTERNAL"] = self._saved

    def request(self, path, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        kind = resp.getheader("Content-Type")
        conn.close()
        return status, body, kind

    def test_status_board_is_local_json(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "0"
        status, body, kind = self.request("/api/status-board")
        self.assertEqual(status, 403)
        self.assertIn("application/json", kind)
        self.assertFalse(json.loads(body)["internal_available"])

        status, body, _kind = self.request("/api/status-board", {"Host": "evil.example"})
        self.assertEqual(status, 403)

        sample = build.__wrapped__ if hasattr(build, "__wrapped__") else {
            "generated_at": "2026-10-23T10:41:00+11:00",
            "timezone": "Australia/Sydney",
            "refresh_seconds": 30,
            "overall": {"ok": True, "reasons": []},
            "kpis": [],
            "bots": [],
            "messages": {"available": False},
            "services": [],
        }
        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        with mock.patch("backend.server.build_status_board", return_value=sample):
            status, body, kind = self.request("/api/status-board")
        self.assertEqual(status, 200)
        self.assertIn("application/json", kind)
        data = json.loads(body)
        self.assertEqual(data["refresh_seconds"], 30)
        self.assertIn("kpis", data)


class UiContractTest(unittest.TestCase):
    def test_board_is_wired_at_the_top_of_internal_panel(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        i18n = (root / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
        script = (root / "frontend" / "js" / "internal.js").read_text(encoding="utf-8")
        server = (root / "backend" / "server.py").read_text(encoding="utf-8")
        css = (root / "frontend" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="status-board"', html)
        self.assertLess(html.find('id="status-board"'), html.find('id="host-status"'))
        self.assertLess(html.find('id="internal-panel"'), html.find('class="hero"'))
        self.assertIn("api/status-board", script)
        self.assertIn('"/api/status-board"', server)
        self.assertIn("board.ok", i18n)
        self.assertIn("一切正常", i18n)
        self.assertIn("有异常", i18n)
        self.assertIn("暂无数据", i18n)
        self.assertIn("board.na", i18n)
        self.assertIn(".status-board", css)
        self.assertNotIn("cdn.", script)
        self.assertNotIn("cdn.", html)
        self.assertIn("Willow Mage", script + i18n + html)
        self.assertIn("data-board-window", script)


if __name__ == "__main__":
    unittest.main()
