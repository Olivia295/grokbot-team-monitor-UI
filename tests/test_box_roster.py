"""Box reading for anyone's box: no roster needed, English rosters, private bots, roster drafts."""

import json
import os
import re
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import server  # noqa: E402
from backend.box_source import PRIVATE_HIDDEN, load_box_cache  # noqa: E402
from backend.collab import flows_from, office_from  # noqa: E402
from backend.internal_box import build, load_roster, make_config, mode_status, parse_roster_extras, roster_draft  # noqa: E402
from backend.views import _source  # noqa: E402

PLAN, WRITE, DIARY = "a-plan", "a-write", "a-diary"
INSTRUCTIONS = "SECRET-INSTRUCTIONS-9f3a"
DIARY_WORDS = "DIARY-WORDS-9f3a"

EN_ROSTER = """# Bot roster

## Bots

| Name | Label | id | The one thing it does | Trigger |
| --- | --- | --- | --- | --- |
| Planner | Lead | a-plan | Splits work | Chat |
| Writer | Copy | a-write | Writes | Planner |
| Diary | Companion | a-diary | Listens | Chat |

### Sidebar groups

| Group | Members |
| --- | --- |
| Core | Planner, Writer |
| Quiet | Diary |

### Old names

| Old name | New name |
| --- | --- |
| Scribe | Writer |

### Folders in /workspace

| Folder | Owner | What's in it |
| --- | --- | --- |
| `/workspace/copy/` | Writer | drafts |

## Push schedule (local time)

| Time | Bot | What |
| --- | --- | --- |
| weekdays 08:15 | Planner | stand-up |

## Bot Office privacy

| Bot | Rule |
| --- | --- |
| Diary | work only |
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _db(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, agent_id TEXT, entry_id TEXT, role TEXT, timestamp_ms INTEGER,"
               " body TEXT, seq INTEGER, in_main_chat INTEGER)")
    db.executemany("INSERT INTO messages (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat) VALUES (?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


class Box(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws, self.agent = self.root / "ws", self.root / "agent-data"
        self.now = int(time.time() * 1000)
        for agent_id, name, title, shape in ((PLAN, "Planner", "Lead", "pebble"), (WRITE, "Writer", "Copy", "cloud"),
                                             (DIARY, "Diary", "Companion", "drop")):
            _write(self.agent / "agents" / agent_id / "profile.json",
                   json.dumps({"name": name, "title": title, "avatarShape": shape, "avatarColor": "blue", "description": INSTRUCTIONS}))
        _write(self.ws / "planner" / "log.md", "- 2026-10-21 asked Scribe for a draft\n")
        _write(self.ws / "copy" / "log.md", "- 2026-10-21 drafted\n")
        _write(self.ws / "diary" / "log.md", f"- 2026-10-21 {DIARY_WORDS}\n")
        t = self.now - 600_000
        _db(self.agent / "search-index.db", [
            (WRITE, "w1", "user", t, "Original request: make it short\nMy understanding: draft the launch post", 1, 0),
            (WRITE, "w2", "assistant", t + 30_000, "done", 2, 0),
            (DIARY, "d1", "user", t + 1000, f"Planner here, {DIARY_WORDS}", 1, 0),
            (DIARY, "d2", "assistant", t + 2000, DIARY_WORDS, 2, 0),
            (PLAN, "p1", "user", t + 3000, "Diary says hi", 1, 0),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def config(self):
        return make_config(self.ws, roster=self.ws / "roster.md", agent_data=self.agent, home=self.root / "home")


class NoRosterTest(Box):
    def test_available_and_built_from_profiles(self):
        status = mode_status(self.config())
        self.assertTrue(status["internal_available"])
        self.assertFalse(status["roster"])
        cache = load_box_cache(self.config())
        self.assertTrue(cache.roster_missing)
        self.assertTrue(_source(cache)["rosterMissing"])
        rows = {row["id"]: row for row in cache.roster}
        self.assertEqual((rows[PLAN]["name"], rows[PLAN]["title"], rows[PLAN]["avatarShape"]), ("Planner", "Lead", "pebble"))
        office = office_from(cache, self.now)
        self.assertEqual({agent["wingId"] for agent in office["agents"]}, {"__loose__"})
        flows = flows_from(cache, self.now, 24)
        legs = {(s["from"], s["to"]) for f in flows["flows"] for s in f["steps"] if s["kind"] == "handoff"}
        self.assertIn((PLAN, DIARY), legs)  # name prefixes work without a roster
        self.assertNotIn(INSTRUCTIONS, json.dumps(cache.roster))

    def test_panel_without_roster(self):
        payload = build(self.config())
        self.assertEqual(payload["roster_source"], "profiles")
        bots = {bot["name"]: bot for bot in payload["bots"]}
        self.assertTrue(bots["Planner"]["folder"].endswith("planner"))
        self.assertNotIn(INSTRUCTIONS, json.dumps(payload))

    def test_nothing_on_the_box_is_unavailable(self):
        empty = self.root / "empty"
        (empty / "agent-data").mkdir(parents=True)
        config = make_config(empty / "ws", roster=empty / "ws" / "roster.md", agent_data=empty / "agent-data", home=empty)
        status = mode_status(config)
        self.assertFalse(status["internal_available"])
        self.assertIn("roster.md", status["reason"])


class EnglishRosterAndPrivacyTest(Box):
    def setUp(self):
        super().setUp()
        _write(self.ws / "roster.md", EN_ROSTER)
        # Whoever keeps dispatch-log.md is the dispatcher.
        _write(self.ws / "planner" / "dispatch-log.md", "| Date | Task | Bot | Status |\n| --- | --- | --- | --- |\n")

    def test_english_headings(self):
        bots, groups = load_roster(self.config())
        self.assertEqual([b["name"] for b in bots], ["Planner", "Writer", "Diary"])
        self.assertEqual(groups[0], {"name": "Core", "members": ["Planner", "Writer"]})
        extras = parse_roster_extras(EN_ROSTER, ["Planner", "Writer", "Diary"])
        self.assertEqual(extras["aliases"], {"Scribe": "Writer"})
        self.assertEqual(extras["folders"], {"Writer": "copy"})
        self.assertEqual(extras["schedule"][0]["days"], [0, 1, 2, 3, 4])
        self.assertEqual(extras["private"], ["Diary"])

    def test_private_bot_shows_work_only(self):
        cache = load_box_cache(self.config())
        self.assertFalse(cache.roster_missing)
        flows = flows_from(cache, self.now, 24)
        legs = {(s["from"], s["to"]): s["text"] for f in flows["flows"] for s in f["steps"] if s["kind"] == "handoff"}
        # A private bot's own messages are read without their text, so only handoffs *from* it
        # (seen in other bots' messages) are found, and their titles are the placeholder.
        self.assertNotIn((PLAN, DIARY), legs)
        self.assertEqual(legs[(DIARY, PLAN)], PRIVATE_HIDDEN)
        diary_entries, _ = cache.transcript(DIARY)
        self.assertTrue(all(entry.get("content") in ("", PRIVATE_HIDDEN) for entry in diary_entries))
        self.assertEqual(legs[(PLAN, WRITE)], "draft the launch post")  # dispatcher format in English
        payload = build(self.config())
        diary = next(bot for bot in payload["bots"] if bot["name"] == "Diary")
        self.assertTrue(diary["private"])
        self.assertIsNone(diary["folder"])
        self.assertEqual(diary["recent_tasks"], [])
        writer = next(bot for bot in payload["bots"] if bot["name"] == "Writer")
        self.assertTrue(writer["folder"].endswith("copy"))
        self.assertIn(("Planner", "Writer", "mention"), {(e["source"], e["target"], e["kind"]) for e in payload["edges"]})
        blob = json.dumps([cache.transcripts, flows, payload], ensure_ascii=False)
        self.assertNotIn(DIARY_WORDS, blob)
        self.assertNotIn("make it short", blob)


class DraftTest(Box):
    def test_draft_without_roster_reads_back(self):
        for language in ("zh", "en"):
            draft = roster_draft(self.config(), language)
            _write(self.ws / "roster.md", draft)
            bots, _groups = load_roster(self.config())
            self.assertEqual(sorted(b["name"] for b in bots), ["Diary", "Planner", "Writer"])
            self.assertIn("`/workspace/planner/`", draft)
            self.assertNotIn(INSTRUCTIONS, draft)
            (self.ws / "roster.md").unlink()

    def test_draft_keeps_roster_rows_and_adds_missing_bots(self):
        _write(self.ws / "roster.md", EN_ROSTER.replace("| Diary | Companion | a-diary | Listens | Chat |\n", ""))
        draft = roster_draft(self.config(), "en")
        self.assertIn("| Planner | Lead | a-plan | Splits work | Chat |", draft)
        self.assertIn("| Diary | Companion | a-diary |  | TODO |", draft)  # private: no duty text
        self.assertIn("| Scribe | Writer |", draft)
        self.assertIn("| weekdays 08:15 | Planner | stand-up |", draft)
        self.assertIn("| Core | Planner, Writer |", draft)

    def test_templates_parse(self):
        for name in ("roster.template.md", "roster.template.en.md"):
            text = (ROOT / "box" / name).read_text(encoding="utf-8")
            filled = re.sub(r"<(?:示例：|e\.g\. )?([^<>]*)>", r"\1", text)
            _write(self.ws / "roster.md", filled)
            bots, groups = load_roster(self.config())
            self.assertIn("Grok Bot", [b["name"] for b in bots], name)
            self.assertTrue(groups, name)
            extras = parse_roster_extras(filled, [b["name"] for b in bots])
            self.assertTrue(extras["schedule"], name)


class DraftEndpointTest(Box):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def get(self, path):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        conn.request("GET", path)
        response = conn.getresponse()
        result = (response.status, response.read().decode("utf-8"), response.getheader("Content-Type"))
        conn.close()
        return result

    def test_draft_download(self):
        with mock.patch.dict(os.environ, {"BOT_OFFICE_INTERNAL": "0"}):
            self.assertEqual(self.get("/api/roster-draft")[0], 403)
        with mock.patch.dict(os.environ, {"BOT_OFFICE_INTERNAL": "1"}), \
                mock.patch("backend.internal_box.default_config", return_value=self.config()):
            status, body, kind = self.get("/api/roster-draft?lang=en")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", kind)
        self.assertIn("## Bots", body)
        self.assertIn("| Writer | Copy | a-write |", body)


if __name__ == "__main__":
    unittest.main()
