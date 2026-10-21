"""Internal box: availability override, Morning Bridge date lines, privacy."""

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

from backend.internal_box import (
    ESTIMATE_LABEL,
    USAGE_NOTE,
    PrivacyError,
    build,
    extract_entries,
    is_forbidden,
    iter_activity_files,
    make_config,
    mode_status,
    read_log,
)
from backend.server import Handler


ROSTER = """# roster

## 一、名单

| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |
| --- | --- | --- | --- | --- |
| Grok Bot | 参谋长 | g1 | 分派 | 聊天 |
| Dr Eggbot | 母体 | e1 | 名册 | 派活 |
| Morning Bridge | 信息主管 | m1 | 晨报 | 每天 |
| Notion Nexus | 管家 | n1 | Notion | 派活 |
| Willow Mage | 心灵陪伴 | w1 | WILLOW-DUTY-TEXT-9f3a | 聊天 |

### 侧栏分组
| 分组 | 成员 |
| --- | --- |
| 司令部 | Grok Bot、Dr Eggbot、Morning Bridge、Notion Nexus |
| 休整营 | Willow Mage |
"""

SECRETS = (
    "SECRET-INBOX",
    "SECRET-SNAP",
    "SECRET-RAW",
    "SECRET-DIARY",
    "SECRET-JOURNAL",
    "SECRET-AUTH",
    "SECRET-TOKEN",
    "SECRET-ENV",
    "SECRET-CODEX",
    "SECRET-GROK",
    "SECRET-WILLOW",
    "SECRET-DEEP",
    "WILLOW-DB-BODY-MARKER-9f3a",
    "WILLOW-DUTY-TEXT-9f3a",
)


class EnvCase(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("BOT_OFFICE_INTERNAL", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("BOT_OFFICE_INTERNAL", None)
        else:
            os.environ["BOT_OFFICE_INTERNAL"] = self._saved


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _symlink(src: Path, dst: Path, directory: bool = False) -> bool:
    try:
        os.symlink(src, dst, target_is_directory=directory)
    except (OSError, NotImplementedError):
        return False
    return True


def _sample(root: Path):
    """A fake box. Private dirs hold canaries that must never show up."""
    roster = root / "roster.md"
    agent = root / "agent-data"
    home = root / "home"
    box = root / "box"
    _write(roster, ROSTER)
    agent.mkdir()
    _write(home / ".codex" / "auth.json", "SECRET-CODEX")
    _write(home / ".grok" / "secret.md", "SECRET-GROK")

    grok = box / "grok-bot"
    _write(
        grok / "log.md",
        "- 2026-10-21 请 Morning Bridge 和 Notion Nexus 看一下，不要叫 Willow Mage\n",
    )
    _write(
        grok / "dispatch-log.md",
        "\n".join([
            "| 日期 | 任务 | bot | 状态 |",
            "| --- | --- | --- | --- |",
            "| 2026-10-21 | 晨报 | Morning Bridge | done |",
            "| 2026-10-21 | 名册 | Dr Eggbot | done |",
            "| 2026-10-21 | 陪伴 | Willow Mage | skip |",
            "",
        ]),
    )
    _symlink(home / ".grok" / "secret.md", grok / "grok-link.md")

    morning = box / "morning-bridge"
    _write(
        morning / "log.md",
        "\n".join([
            "# 晨间简报日志",
            "每天：日期 | 天气来源 | 事项条数",
            "2026-10-18（周日版）| BOM API 已读到 | 已交给 Grok Bot",
            "2026-10-19 只有日期开头，没有竖线",
            "2026-10-20 | 昨日简报",
            "2026-10-21 | 发出 约 07:36 | BOM API 已读到",
            "",
        ]),
    )

    nexus = box / "notion-nexus"
    _write(
        nexus / "log.md",
        "\n".join([
            "| 日期 | 事项 |",
            "| --- | --- |",
            "| 2026-10-21 | PUBLIC-TASK 整理库 |",
            "",
        ]),
    )
    _write(nexus / "public.md", "PUBLIC-FILE")
    _write(nexus / "auth.json", "SECRET-AUTH")
    _write(nexus / "session-token.txt", "SECRET-TOKEN")
    _write(nexus / ".env", "SECRET-ENV")
    _write(nexus / "周记.md", "SECRET-DIARY")
    _write(nexus / "我的日记.md", "SECRET-JOURNAL")
    _write(nexus / "inbox" / "log.md", "SECRET-INBOX")
    _write(nexus / "snapshots" / "log.md", "SECRET-SNAP")
    _write(nexus / "raw" / "log.md", "SECRET-RAW")
    _write(nexus / "notes" / "inside.md", "one level down")
    _write(nexus / "notes" / "deeper" / "too.md", "SECRET-DEEP")
    _symlink(nexus / "inbox", nexus / "leak", directory=True)
    _symlink(home / ".codex" / "auth.json", nexus / "seen.md")

    willow = box / "willow-private"
    _write(willow / "log.md", "2026-10-21 SECRET-WILLOW 不应该被读到\n")
    now_ms = int(time.time() * 1000)
    db_path = agent / "search-index.db"
    db = sqlite3.connect(db_path)
    db.execute(
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
    db.executemany(
        "INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,1)",
        [
            ("w1", "w-user", "user", now_ms - 2000, "WILLOW-DB-BODY-MARKER-9f3a", 1),
            ("w1", "w-asst", "assistant", now_ms - 1000, "WILLOW-DB-BODY-MARKER-9f3a reply", 2),
        ],
    )
    db.commit()
    db.close()
    config = make_config(
        box,
        roster=roster,
        agent_data=agent,
        home=home,
        extra_folders={"Willow Mage": willow},
    )
    return config, nexus, grok


def _names(folder: Path, config) -> list[str]:
    return sorted(Path(entry.path).name for entry in iter_activity_files(folder, config))


class ModeTest(EnvCase):
    def test_env_override_zero_forces_unavailable(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roster = root / "roster.md"
            roster.write_text("x", encoding="utf-8")
            agent = root / "agent-data"
            agent.mkdir()
            config = make_config(root / "ws", roster=roster, agent_data=agent, home=root / "home")
            status = mode_status(config)
        # The override wins even when this machine really is a Grok Bot box.
        self.assertFalse(mode_status()["internal_available"])
        self.assertFalse(status["internal_available"])
        self.assertEqual(status["reason"], "BOT_OFFICE_INTERNAL=0")

    def test_env_override_one_forces_available(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        missing = make_config(
            "/tmp/bot-office-does-not-exist",
            roster="/tmp/bot-office-does-not-exist/roster.md",
            agent_data="/tmp/bot-office-does-not-exist/agent-data",
            home="/tmp/bot-office-does-not-exist/home",
        )
        status = mode_status(missing)
        self.assertTrue(status["internal_available"])
        self.assertEqual(status["reason"], "BOT_OFFICE_INTERNAL=1")
        self.assertFalse(missing.roster_path.exists())
        self.assertFalse(missing.agent_data.exists())

    def test_detection_needs_roster_file_and_agent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roster = root / "roster.md"
            agent = root / "agent-data"
            roster.write_text("roster", encoding="utf-8")
            agent.write_text("not a directory", encoding="utf-8")
            config = make_config(root / "ws", roster=roster, agent_data=agent, home=root / "home")
            status = mode_status(config)
            self.assertFalse(status["internal_available"])
            self.assertIn("agent-data", status["reason"])

            agent.unlink()
            agent.mkdir()
            status = mode_status(config)
            self.assertTrue(status["internal_available"])
            self.assertIn("reason", status)

            roster.unlink()
            status = mode_status(config)
            self.assertFalse(status["internal_available"])
            self.assertIn("roster.md", status["reason"])

    def test_agent_data_symlink_to_a_directory_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roster = root / "roster.md"
            roster.write_text("roster", encoding="utf-8")
            real = root / "real-agent"
            real.mkdir()
            link = root / "agent-data"
            if not _symlink(real, link, directory=True):
                self.skipTest("symlinks are not available")
            config = make_config(root / "ws", roster=roster, agent_data=link, home=root / "home")
            self.assertTrue(mode_status(config)["internal_available"])


class ParseTest(EnvCase):
    def test_morning_bridge_date_lines_are_tasks(self):
        text = "\n".join([
            "# 晨间简报日志",
            "每天：日期 | 天气来源 | 事项条数",
            "2026-10-18（周日版）| BOM API 已读到",
            "2026-10-19 只有日期开头，没有竖线",
            "2026-10-21 | 发出 约 07:36 | BOM API 已读到",
            "| 日期 | 事项 |",
            "| --- | --- |",
            "| 2026-10-21 | 表格里的一条 |",
            "- 一条减号任务",
            "## 2026-10-20 日期标题",
            "## 不是日期的标题",
            "普通一句，中间才有 2026-10-21",
            "  2026-10-16 前面有空格",
        ])
        entries = extract_entries(text)
        self.assertIn("2026-10-18（周日版）| BOM API 已读到", entries)
        self.assertIn("2026-10-19 只有日期开头，没有竖线", entries)
        self.assertTrue(any(item.startswith("2026-10-21 | 发出") for item in entries))
        self.assertTrue(any("表格里的一条" in item for item in entries))
        self.assertIn("- 一条减号任务", entries)
        self.assertTrue(any(item.startswith("## 2026-10-20") for item in entries))
        self.assertFalse(any(item.startswith("每天") for item in entries))
        self.assertFalse(any(item.startswith("## 不是日期") for item in entries))
        self.assertFalse(any(item.startswith("普通一句") for item in entries))
        self.assertFalse(any(item.startswith("| ---") for item in entries))
        self.assertFalse(any(item.startswith("| 日期") for item in entries))
        self.assertTrue(any(item.startswith("2026-10-16") for item in entries))

        long_line = "2026-10-21 " + ("事" * 200)
        self.assertEqual(len(extract_entries(long_line)[0]), 160)

        with tempfile.TemporaryDirectory() as tmp:
            config, _nexus, _grok = _sample(Path(tmp))
            payload = build(config)
        morning = next(bot for bot in payload["bots"] if bot["name"] == "Morning Bridge")
        tasks = morning["recent_tasks"]
        self.assertTrue(tasks)
        self.assertTrue(tasks[0].startswith("2026-10-21"))
        self.assertTrue(any(task.startswith("2026-10-19 ") for task in tasks))
        self.assertTrue(any("周日版" in task for task in tasks))
        self.assertFalse(any(task.startswith("每天") for task in tasks))


class PrivacyTest(EnvCase):
    def test_willow_mage_metadata_only(self):
        source = Path(__file__).resolve().parents[1].joinpath("backend", "internal_box.py").read_text(encoding="utf-8")
        meta_sql = source.split('_WILLOW_META_SQL = """', 1)[1].split('"""', 1)[0]
        self.assertNotIn("body", meta_sql.lower())
        with tempfile.TemporaryDirectory() as tmp:
            config, _nexus, _grok = _sample(Path(tmp))
            payload = build(config)
        blob = json.dumps(payload, ensure_ascii=False)
        willow = next(bot for bot in payload["bots"] if bot["name"] == "Willow Mage")
        self.assertEqual(willow["label"], "心灵陪伴")
        self.assertEqual(willow["group"], "休整营")
        self.assertEqual(willow["status"], "active")
        self.assertNotEqual(willow["status"], "不监控")
        self.assertTrue(willow["last_activity"])
        self.assertEqual(willow["message_count"], 2)
        self.assertEqual(willow["last_result"], "replied")
        self.assertEqual(willow["files_modified_7d"], 0)
        self.assertEqual(willow["log_lines_7d"], 0)
        self.assertEqual(willow["recent_tasks"], [])
        self.assertIsNone(willow["folder"])
        self.assertFalse(willow["duty"])
        self.assertNotIn("SECRET-WILLOW", blob)
        self.assertNotIn("WILLOW-DB-BODY-MARKER-9f3a", blob)
        self.assertNotIn("WILLOW-DUTY-TEXT-9f3a", blob)
        self.assertNotIn("willow-private", blob)
        self.assertNotIn("不监控", blob)
        self.assertIn("Willow Mage", [item["name"] for item in payload["usage"]["estimates"]])
        egg = next(bot for bot in payload["bots"] if bot["name"] == "Dr Eggbot")
        self.assertEqual(egg["status"], "no-folder")

        def weight(source, target, kind):
            rows = [
                edge for edge in payload["edges"]
                if edge["source"] == source and edge["target"] == target and edge["kind"] == kind
            ]
            self.assertEqual(len(rows), 1, payload["edges"])
            return rows[0]["weight"]

        # Dispatch rows are also log lines, so Morning Bridge is mentioned and dispatched.
        self.assertEqual(weight("Grok Bot", "Morning Bridge", "dispatch"), 1)
        self.assertEqual(weight("Grok Bot", "Morning Bridge", "mention"), 2)
        self.assertEqual(weight("Grok Bot", "Notion Nexus", "mention"), 1)
        self.assertEqual(weight("Morning Bridge", "Grok Bot", "mention"), 1)
        self.assertEqual(weight("Grok Bot", "Dr Eggbot", "dispatch"), 1)
        self.assertEqual(weight("Grok Bot", "Willow Mage", "mention"), 2)
        self.assertEqual(weight("Grok Bot", "Willow Mage", "dispatch"), 1)

    def test_notion_nexus_private_dirs_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, nexus, grok = _sample(root)
            self.assertIn(os.path.abspath(nexus / "inbox"), config.forbidden_dirs)
            self.assertIn(os.path.abspath(nexus / "snapshots"), config.forbidden_dirs)
            self.assertIn(os.path.abspath(nexus / "raw"), config.forbidden_dirs)
            self.assertIn(os.path.abspath(root / "home" / ".codex"), config.forbidden_dirs)
            self.assertIn(os.path.abspath(root / "home" / ".grok"), config.forbidden_dirs)
            self.assertNotEqual(os.path.abspath(nexus / "inbox"), os.path.abspath("/workspace/notion-nexus/inbox"))

            self.assertTrue(is_forbidden(nexus / "inbox" / "log.md", config))
            self.assertTrue(is_forbidden(nexus / "snapshots" / "log.md", config))
            self.assertTrue(is_forbidden(nexus / "raw" / "log.md", config))
            with self.assertRaises(PrivacyError):
                list(iter_activity_files(nexus / "inbox", config))
            with self.assertRaises(PrivacyError):
                read_log(nexus / "inbox" / "log.md", config)
            with self.assertRaises(PrivacyError):
                read_log(nexus / "auth.json", config)
            with self.assertRaises(PrivacyError):
                read_log(nexus / "周记.md", config)

            private = {"inbox", "snapshots", "raw"}
            found = list(iter_activity_files(nexus, config))
            for entry in found:
                self.assertFalse(private.intersection(Path(entry.path).parts))
                self.assertNotIn("周记", entry.name)
                self.assertNotIn("日记", entry.name)
            self.assertEqual(
                sorted(Path(entry.path).name for entry in found),
                sorted([".env", "auth.json", "inside.md", "log.md", "public.md", "session-token.txt"]),
            )
            # The symlink into ~/.grok is not an activity file.
            self.assertEqual(_names(grok, config), ["dispatch-log.md", "log.md"])

            payload = build(config)
            blob = json.dumps(payload, ensure_ascii=False)
            for secret in SECRETS:
                self.assertNotIn(secret, blob)
            self.assertIn("PUBLIC-TASK", blob)
            nexus_bot = next(bot for bot in payload["bots"] if bot["name"] == "Notion Nexus")
            self.assertEqual(nexus_bot["files_modified_7d"], 6)
            self.assertTrue(any("PUBLIC-TASK" in task for task in nexus_bot["recent_tasks"]))
            self.assertEqual(payload["usage"]["available"], False)
            self.assertEqual(payload["usage"]["note"], USAGE_NOTE)
            self.assertEqual(payload["usage"]["estimate_label"], ESTIMATE_LABEL)
            self.assertTrue(payload["usage"]["estimate_label"].startswith("估算"))


class QuietHandler(Handler):
    def log_message(self, fmt, *args):
        return


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True


class ApiTest(EnvCase):
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

    def request(self, path, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        kind = resp.getheader("Content-Type")
        conn.close()
        return status, body, kind

    def test_mode_and_internal_are_local_json(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "0"
        status, body, kind = self.request("/api/mode")
        self.assertEqual(status, 200)
        self.assertIn("application/json", kind)
        data = json.loads(body)
        self.assertFalse(data["internal_available"])
        self.assertTrue(data["reason"])

        status, body, kind = self.request("/api/internal")
        self.assertEqual(status, 403)
        self.assertIn("application/json", kind)
        error = json.loads(body)
        self.assertIn("error", error)
        self.assertFalse(error["internal_available"])

        status, body, _kind = self.request("/api/mode", {"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("error", json.loads(body))

        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        status, body, _kind = self.request("/api/internal", {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertNotIn(b"estimates", body)

        sample = {"usage": {"note": USAGE_NOTE, "available": False}, "bots": []}
        with mock.patch("backend.server.build", return_value=sample):
            status, body, kind = self.request("/api/internal")
        self.assertEqual(status, 200)
        self.assertIn("application/json", kind)
        self.assertEqual(json.loads(body)["usage"]["note"], USAGE_NOTE)


class UiContractTest(unittest.TestCase):
    def test_switch_copy_and_endpoints_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        i18n = (root / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
        script = (root / "frontend" / "js" / "internal.js").read_text(encoding="utf-8")
        server = (root / "backend" / "server.py").read_text(encoding="utf-8")
        self.assertIn('data-mode="internal"', html)
        self.assertIn('data-mode="external"', html)
        self.assertIn('id="internal-panel"', html)
        self.assertIn("Grok Bot 本机读取", i18n)
        self.assertIn("Grok Bot box (internal)", i18n)
        self.assertIn('"mode.external": "外部读取"', i18n)
        self.assertIn('"mode.external": "External"', i18n)
        self.assertIn("未检测到 Grok Bot 本机环境，只能外部读取", i18n)
        self.assertIn("无真实限额/用量数据", i18n)
        self.assertIn('"internal.estimate": "估算"', i18n)
        self.assertIn('"internal.estimate": "Estimate"', i18n)
        self.assertIn("localStorage", script)
        self.assertIn("api/mode", script)
        self.assertIn("api/internal", script)
        self.assertIn('"/api/mode"', server)
        self.assertIn('"/api/internal"', server)


if __name__ == "__main__":
    unittest.main()
