"""Box mode shows only what the box records: real reply and handoff counts, real avatars."""

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.box_source import load_box_cache  # noqa: E402
from backend.insights import insights_from  # noqa: E402
from backend.internal_box import make_config  # noqa: E402

ROSTER = """# roster

## 一、名单

| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |
| --- | --- | --- | --- | --- |
| Grok Bot | 参谋长 | g1 | 分派 | 聊天 |
| Morning Bridge | 晨报 | m1 | 晨报 | 每天 |
| Willow Mage | 心灵陪伴 | 0aae13ef-b790-4061-a6e8-1dc6d5e45803 | x | 聊天 |

### 侧栏分组
| 分组 | 成员 |
| --- | --- |
| 司令部 | Grok Bot、Morning Bridge |
"""


class BoxModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "roster.md").write_text(ROSTER, encoding="utf-8")
        agents = root / "agent-data" / "agents" / "m1"
        agents.mkdir(parents=True)
        (agents / "profile.json").write_text(json.dumps({"name": "Morning Bridge", "avatarShape": "cloud", "avatarColor": "pink",
                                                         "description": "SECRET-INSTRUCTIONS"}), encoding="utf-8")
        self.now = int(time.time() * 1000)
        t = self.now - 3600_000
        db = sqlite3.connect(root / "agent-data" / "search-index.db")
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, agent_id TEXT, entry_id TEXT, role TEXT, timestamp_ms INTEGER,"
                   " body TEXT, seq INTEGER, in_main_chat INTEGER)")
        db.executemany("INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,1)", [
            ("g1", "a", "user", t, "帮我看看今天的安排 SECRET-ASK", 1),            # you → Grok Bot
            ("g1", "b", "assistant", t + 90_000, "SECRET-REPLY", 2),               # Grok Bot answers you
            ("m1", "c", "user", t + 100_000, "Grok Bot 请准备晨报", 1),            # Grok Bot → Morning Bridge
            ("m1", "d", "assistant", t + 160_000, "SECRET-OUT", 2),
        ])
        db.commit()
        db.close()
        self.config = make_config(root / "ws", roster=root / "roster.md", agent_data=root / "agent-data", home=root / "home")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_are_real(self):
        cache = load_box_cache(self.config)
        data = insights_from(cache, self.now)
        profiles = {p["id"]: p for p in data["profiles"]}
        self.assertEqual(profiles["g1"]["replies"], 1)
        self.assertEqual(profiles["g1"]["medianResponseMs"], 90_000)
        self.assertEqual(profiles["g1"]["handoffsOut"], 1)
        self.assertEqual(profiles["m1"]["handoffsIn"], 1)
        self.assertEqual(data["totals"]["replies"], 1)
        # An hour ago is today, or yesterday just after midnight: count both days.
        days = data["digest"]
        self.assertEqual(days[0]["replies"] + days[1]["replies"], 1)
        self.assertEqual(days[0]["handoffs"] + days[1]["handoffs"], 1)
        kinds = {item["kind"] for item in data["feed"]}
        self.assertTrue({"reply", "handoff", "ask"} <= kinds)
        blob = json.dumps([cache.transcripts, data], ensure_ascii=False)
        for secret in ("SECRET-ASK", "SECRET-REPLY", "SECRET-OUT", "SECRET-INSTRUCTIONS"):
            self.assertNotIn(secret, blob)

    def test_profile_avatar(self):
        cache = load_box_cache(self.config)
        row = next(row for row in cache.roster if row["id"] == "m1")
        self.assertEqual((row["avatarShape"], row["avatarColor"]), ("cloud", "pink"))
        self.assertNotIn("SECRET-INSTRUCTIONS", json.dumps(cache.roster))


if __name__ == "__main__":
    unittest.main()
