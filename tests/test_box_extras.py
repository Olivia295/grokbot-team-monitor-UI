"""Box reading from files that already exist: dispatch format, roster extras, profiles, status hints."""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import server  # noqa: E402
from backend.box_source import HIDDEN_TITLE, dispatch_sections, handoff_title, load_box_cache, load_messages, status_hints  # noqa: E402
from backend.collab import flows_from, office_from  # noqa: E402
from backend.internal_box import (  # noqa: E402
    build, is_forbidden, is_secret_name, log_runs, make_config, parse_roster_extras, read_log, schedule_status, slugify,
)

GROK, FORGE, SHIP, MORNING = "g-1", "f-1", "s-1", "m-1"
WORDS = "HER-OWN-WORDS-9f3a"
DESC = "PROFILE-INSTRUCTIONS-9f3a"

ROSTER = """# Bot 名册

## 一、名单

| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |
| --- | --- | --- | --- | --- |
| Grok Bot | 参谋长 | g-1 | 分派 | 聊天 |
| Content Forge | 写作 | f-1 | 写稿 | 派活 |
| Spaceship Co-Pilot | 飞船副驾 | s-1 | 博客 | 聊天 |
| Morning Bridge | 晨报 | m-1 | 晨报 | 每天 |

### 侧栏分组
| 分组 | 成员 |
| --- | --- |
| 司令部 | Grok Bot、Content Forge |
| 前线 | Spaceship Co-Pilot、Morning Bridge |

### 已删除
| 名字 | 什么时候 |
| --- | --- |
| Old Helper | 2026-10-01 |

### 旧名对照（看到旧名时按右边理解，新写的东西一律用新名）
| 旧名 | 新名 |
| --- | --- |
| Forge、Writer Bot | Content Forge |

### 共享电脑 /workspace
| 文件夹 | 谁的 | 放什么 |
| --- | --- | --- |
| `/workspace/ship/` | Spaceship Co-Pilot | 博客 |
| `/workspace/shared/` | Grok Bot、Content Forge | 共用 |

## 三、推送时间表（悉尼时间）
| 时间 | bot | 推什么 |
| --- | --- | --- |
| 07:30 | Morning Bridge | 晨报 |
| 每周日 20:00 | Content Forge | 周报 |

### 各 bot 的日志（Morning Bridge 每天读）
| bot | 日志 |
| --- | --- |
| Morning Bridge | `news-log.md`、log.md |

## 七、改动记录
| 日期 | 改了什么 |
| --- | --- |
| 2026-10-18 | 改名 Forge → Content Forge |
| 2026-10-20 | 加了推送时间表 |
"""

RUN_TABLE = """| 日期时间（悉尼） | 任务 | Codex 轮数 | 重来 | 结果 |
| --- | --- | --- | --- | --- |
| 2026-10-20 14:10 | 写首页 | 3 | 1 | 完成 |
| 2026-10-21 09:05 | 修 bug | 5 | 2 | 失败 |
| 2026-10-21 16:04 | 加测试 | 2 | - | 完成 |
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _db(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, agent_id TEXT, entry_id TEXT, role TEXT,"
               " timestamp_ms INTEGER, body TEXT, seq INTEGER, in_main_chat INTEGER)")
    db.executemany("INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


class Box(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "ws"
        self.agent = self.root / "agent-data"
        self.now = int(time.time() * 1000)
        _write(self.ws / "roster.md", ROSTER)
        _write(self.ws / "grok-bot" / "dispatch-log.md", "| 日期 | 任务 | bot | 状态 |\n| --- | --- | --- | --- |\n")
        _write(self.ws / "ship" / "log.md", "- 2026-10-21 与 Forge 对稿\n")
        _write(self.ws / "ship" / "inbox" / "log.md", "SHIP-INBOX-9f3a")
        _write(self.ws / "morning-bridge" / "news-log.md", "2026-10-21 | 三条新闻\n")
        _write(self.ws / "morning-bridge" / "map.md", "NOT-A-LOG-9f3a")
        _write(self.ws / "content-forge" / "log.md", RUN_TABLE)
        _write(self.ws / "content-forge" / "reforge-log.md", "- 2026-10-21 重写开头\n")
        for agent_id, profile in {
            FORGE: {"name": "Content Forge", "title": "写作", "description": DESC, "avatarShape": "pebble", "avatarColor": "violet", "harness": "codex"},
            "x-9": {"name": "SSH to Grok via Tailscale", "description": DESC, "avatarShape": "squircle", "avatarColor": "gray"},
        }.items():
            _write(self.agent / "agents" / agent_id / "profile.json", json.dumps(profile, ensure_ascii=False))
        self.config = make_config(self.ws, roster=self.ws / "roster.md", agent_data=self.agent, home=self.root / "home")

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, rows):
        _db(self.agent / "search-index.db", rows)
        config = make_config(self.ws, roster=self.ws / "roster.md", agent_data=self.agent, home=self.root / "home")
        return config, load_box_cache(config)


class DispatchFormatTest(Box):
    def test_only_my_understanding_becomes_the_title(self):
        self.assertEqual(dispatch_sections(f"她的原话：{WORDS}\n我的理解：整理本周新闻"), (True, "整理本周新闻"))
        self.assertEqual(dispatch_sections(f"【我的理解】先查资料\n【她的原话】{WORDS}"), (True, "先查资料"))
        self.assertEqual(dispatch_sections(f"**她的原话**: {WORDS}"), (True, None))
        self.assertEqual(handoff_title(f"她的原话：{WORDS}"), HIDDEN_TITLE)
        self.assertEqual(dispatch_sections("普通的一句话"), (False, None))

    def test_dispatch_messages_are_handoffs_from_the_dispatcher(self):
        t = self.now - 600_000
        config, cache = self.load([
            (FORGE, "f1", "user", t, f"她的原话：{WORDS}\n我的理解：写一篇发布会稿子", 1, 0),
            (FORGE, "f2", "assistant", t + 60_000, "SECRET-REPLY-9f3a", 2, 0),
            (SHIP, "s1", "user", t + 1000, f"Grok Bot：她的原话 {WORDS}；我的理解：检查博客链接", 1, 0),
            (SHIP, "s2", "user", t + 2000, "Forge 这段帮我看看", 2, 0),
            (GROK, "g1", "user", t + 3000, f"她的原话：{WORDS}", 1, 1),
        ])
        flows = flows_from(cache, self.now, 24)
        legs = {(s["from"], s["to"]): s for f in flows["flows"] for s in f["steps"] if s["kind"] == "handoff"}
        self.assertEqual(legs[(GROK, FORGE)]["text"], "写一篇发布会稿子")
        self.assertEqual(legs[(GROK, FORGE)]["waitMs"], 60_000)
        self.assertEqual(legs[(GROK, SHIP)]["text"], "检查博客链接")
        self.assertIn((FORGE, SHIP), legs)  # old name "Forge" → Content Forge
        blob = json.dumps([cache.transcripts, flows], ensure_ascii=False)
        self.assertNotIn(WORDS, blob)
        self.assertNotIn("SECRET-REPLY", blob)
        # The dispatcher's own chat with you is not a handoff to itself.
        self.assertNotIn((GROK, GROK), legs)


class RosterExtrasTest(Box):
    def test_tables_are_understood(self):
        names = ["Grok Bot", "Content Forge", "Spaceship Co-Pilot", "Morning Bridge"]
        extras = parse_roster_extras(ROSTER, names)
        self.assertEqual(extras["aliases"], {"Forge": "Content Forge", "Writer Bot": "Content Forge"})
        self.assertEqual(extras["folders"], {"Spaceship Co-Pilot": "ship"})  # the shared folder has two owners
        self.assertEqual(extras["logs"], {"Morning Bridge": ["news-log.md", "log.md"]})
        self.assertEqual([(i["bot"], i["time"], i["days"]) for i in extras["schedule"]],
                         [("Morning Bridge", "07:30", None), ("Content Forge", "20:00", [6])])
        self.assertEqual(extras["deleted"], ["Old Helper"])
        self.assertEqual(extras["changes"][0]["date"], "2026-10-20")
        self.assertEqual(slugify("Spaceship Co-Pilot"), "spaceship-copilot")

    def test_folders_logs_and_private_dirs(self):
        _db(self.agent / "search-index.db", [])
        payload = build(self.config)
        bots = {bot["name"]: bot for bot in payload["bots"]}
        self.assertTrue(bots["Spaceship Co-Pilot"]["folder"].endswith("ship"))
        self.assertIn("news-log.md", bots["Morning Bridge"]["logs"])
        self.assertIn("reforge-log.md", bots["Content Forge"]["logs"])
        self.assertEqual(bots["Content Forge"]["runs"], {"runs": 3, "retries": 3, "failures": 1, "last": "2026-10-21 16:04", "avg_rounds": 3.3})
        self.assertEqual(bots["Content Forge"]["engine"], "codex")
        self.assertIn(("Spaceship Co-Pilot", "Content Forge", "mention"), {(e["source"], e["target"], e["kind"]) for e in payload["edges"]})
        self.assertEqual(payload["dispatcher"], "Grok Bot")
        self.assertEqual(payload["deleted"], ["Old Helper"])
        blob = json.dumps(payload, ensure_ascii=False)
        for secret in ("SHIP-INBOX-9f3a", "NOT-A-LOG-9f3a", DESC):
            self.assertNotIn(secret, blob)
        self.assertTrue(is_forbidden(self.ws / "ship" / "inbox" / "log.md", self.config))
        with self.assertRaises(Exception):
            read_log(self.ws / "morning-bridge" / "map.md", self.config)

    def test_log_runs_need_a_run_table(self):
        self.assertIsNone(log_runs("- 2026-10-21 普通日志\n"))
        self.assertEqual(log_runs(RUN_TABLE)["failures"], 1)


class ScheduleTest(Box):
    def test_done_missed_upcoming(self):
        now = datetime(2026, 10, 21, 12, 0).astimezone()
        morning = now.replace(hour=7, minute=40)
        _db(self.agent / "search-index.db", [(MORNING, "m1", "assistant", int(morning.timestamp() * 1000), "x", 1, 1)])
        schedule = [
            {"bot": "Morning Bridge", "time": "07:30", "days": None, "what": "晨报"},
            {"bot": "Content Forge", "time": "08:00", "days": None, "what": ""},
            {"bot": "Content Forge", "time": "20:00", "days": None, "what": ""},
            {"bot": "Content Forge", "time": "20:00", "days": [6], "what": "周报"},
        ]
        ids = {"Morning Bridge": MORNING, "Content Forge": FORGE}
        states = [item["state"] for item in schedule_status(schedule, ids, self.config, now)]
        self.assertEqual(states, ["done", "missed", "upcoming", "not-today"])  # 2026-10-21 is a Wednesday


class ProfilesAndHintsTest(Box):
    def test_avatars_titles_and_never_instructions(self):
        _config, cache = self.load([(FORGE, "f1", "assistant", self.now - 1000, "hi", 1, 1)])
        rows = {row["id"]: row for row in cache.roster}
        self.assertEqual((rows[FORGE]["avatarShape"], rows[FORGE]["avatarColor"]), ("pebble", "violet"))
        self.assertEqual(rows["x-9"]["name"], "SSH to Grok via Tailscale")
        self.assertNotIn(DESC, json.dumps(cache.roster, ensure_ascii=False))

    def test_status_hints(self):
        now = self.now
        rows = [
            (FORGE, "a", "user", now - 600_000, "", 1, 1), (FORGE, "b", "assistant", now - 300_000, "", 2, 1),
            (SHIP, "c", "user", now - 30 * 60_000, "", 1, 0),
            (GROK, "d", "user", now - 60_000, "", 1, 1),
            (MORNING, "e", "assistant", now - 2 * 86400_000, "", 1, 1),
        ]
        self.assertEqual(status_hints(rows, now), {FORGE: "yourturn", SHIP: "pending"})
        _config, cache = self.load(rows)
        office = office_from(cache, now)
        details = {agent["id"]: agent["detail"] for agent in office["agents"]}
        self.assertEqual(details[FORGE], "yourturn")
        self.assertEqual(details[SHIP], "pending")


class SecretsCacheAndSettingsTest(Box):
    def test_secret_names(self):
        for name in ("box-secrets.json", "host-secrets.json", "chrome-cookie-seed.json", "store.db", "store.db-wal",
                     "auth.json", "api_token.txt", "id_rsa", "server.pem", ".env", "db-password.md"):
            self.assertTrue(is_secret_name(name), name)
        for name in ("log.md", "news-log.md", "profile.json", "search-index.db", "roster.md"):
            self.assertFalse(is_secret_name(name), name)

    def test_new_rows_in_the_wal_are_picked_up(self):
        db = self.agent / "search-index.db"
        _db(db, [(FORGE, "a", "user", self.now, "hi", 1, 1)])
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE messages SET seq = seq")  # first write creates the -wal / -shm files
        conn.commit()
        self.assertEqual(len(load_messages(db, {"willow"})), 1)
        self.assertEqual(len(load_messages(db, {"willow"})), 1)  # served from memory
        conn.execute("INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,?)",
                     (FORGE, "b", "assistant", self.now + 1, "yo", 2, 1))
        conn.commit()
        self.assertEqual(len(load_messages(db, {"willow"})), 2)
        conn.close()

    def test_settings_inside_the_workspace_are_flagged(self):
        with mock.patch.dict(os.environ, {"GROK_COLLAB_SETTINGS": str(self.ws / "app" / "data" / "settings.json")}), \
                mock.patch("backend.server.DEFAULT_WORKSPACE", self.ws):
            self.assertTrue(server.settings_in_workspace())
        with mock.patch.dict(os.environ, {"GROK_COLLAB_SETTINGS": str(self.root / "home" / ".config" / "s.json")}), \
                mock.patch("backend.server.DEFAULT_WORKSPACE", self.ws):
            self.assertFalse(server.settings_in_workspace())


if __name__ == "__main__":
    unittest.main()
