import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.collab import flows_from, office_from
from backend.grok_cache import encode_blob_name, load_cache
from backend.insights import insights_from

ACCOUNT = "user%40example.com"
NOW = 1_800_000_000_000
BOSS, SCOUT, WRITER, GHOST = "boss-id", "scout-id", "writer-id", "ghost-id"


def msg(entry_id, role, at, text, request, **extra):
    return {"kind": "message", "id": entry_id, "role": role, "timestampMs": at, "content": text,
            "requestId": request, "isStreaming": False, **extra}


def reply(entry_id, at, text, request):
    return {"kind": "send-message", "id": entry_id, "timestampMs": at, "requestId": request,
            "message": {"type": "text", "content": text}}


class CollabTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.support = Path(self.dir.name)
        persist = self.support / "sand-client-persistence"
        persist.mkdir()

        def put(suffix, value):
            key = f"sand.client.account.{ACCOUNT}.{suffix}"
            (persist / encode_blob_name(key)).write_text(json.dumps({"value": value}), encoding="utf-8")

        put("roster.last-roster", {"rows": [
            {"id": BOSS, "name": "Dr Eggbot", "description": "总调度\n更多"},
            {"id": SCOUT, "name": "X Search Bot"},
            {"id": WRITER, "name": "Content Forge"},
        ]})
        put("sidebar.last-sections", {"sections": [
            {"id": "hq", "name": "司令部", "agentIds": [BOSS]},
            {"id": "intel", "name": "情报中心", "agentIds": [SCOUT, WRITER]},
        ]})
        t = NOW - 10 * 60 * 1000
        # You ask the boss; boss hands to scout; scout passes to writer and to an unknown bot;
        # writer answers back to boss; boss replies to you.
        put(f"transcript.replicas.{BOSS}", {"entries": [
            msg("b1", "user", t, "帮我做一份周报", "r-boss"),
            msg("b2", "assistant", t + 1000, "去搜一下本周新闻", "r-boss", toAgent={"id": SCOUT, "name": "旧名字"}),
            msg("b3", "user", t + 61_000, "周报写好了", "r-boss2", fromAgent={"id": WRITER, "name": "Content Forge"}),
            reply("b4", t + 70_000, "周报在这里", "r-boss2"),
            msg("b5", "user", t + 100_000, "你好", "r-solo"),
            reply("b6", t + 101_000, "你好呀", "r-solo"),
        ]})
        put(f"transcript.replicas.{SCOUT}", {"entries": [
            msg("s1", "user", t + 1200, "去搜一下本周新闻", "r-scout", fromAgent={"id": BOSS, "name": "Dr Eggbot"}),
            msg("s2", "assistant", t + 30_000, "素材给你", "r-scout", toAgent={"id": WRITER, "name": "Content Forge"}),
            msg("s3", "assistant", t + 31_000, "顺便看看", "r-scout", toAgent={"id": GHOST, "name": "Sydney"}),
        ]})
        put(f"transcript.replicas.{WRITER}", {"entries": [
            msg("w1", "user", t + 30_300, "素材给你", "r-writer", fromAgent={"id": SCOUT, "name": "X Search Bot"}),
            msg("w2", "assistant", t + 60_000, "周报写好了", "r-writer", toAgent={"id": BOSS, "name": "Dr Eggbot"}),
        ]})

    def tearDown(self):
        self.dir.cleanup()

    def test_follows_handoffs_across_transcripts(self):
        data = flows_from(load_cache(self.support), NOW, 24)
        self.assertEqual(data["flowCount"], 1)
        flow = data["flows"][0]
        self.assertEqual(flow["trigger"]["kind"], "user")
        self.assertEqual(flow["trigger"]["text"], "帮我做一份周报")
        self.assertEqual(flow["participants"], ["you", BOSS, SCOUT, WRITER, GHOST])
        pairs = [(s["from"], s["to"], s["depth"]) for s in flow["steps"]]
        self.assertEqual(pairs, [(BOSS, SCOUT, 0), (SCOUT, WRITER, 1), (SCOUT, GHOST, 1), (WRITER, BOSS, 2), (BOSS, "you", 3)])
        self.assertEqual(flow["steps"][-1]["text"], "周报在这里")
        self.assertTrue(all(s["traced"] for s in flow["steps"][:2]))
        self.assertFalse(flow["steps"][2]["traced"])
        self.assertEqual(data["external"], [{"id": GHOST, "name": "Sydney"}])
        self.assertEqual(data["hub"]["id"], SCOUT)

    def test_counts_solo_turns_and_handoffs(self):
        data = flows_from(load_cache(self.support), NOW, 24)
        self.assertEqual(data["soloCount"], 1)
        self.assertEqual(data["handoffCount"], 4)

    def test_untraced_incoming_starts_a_flow_from_that_bot(self):
        cache = load_cache(self.support)
        entries, mtime = cache.transcripts[SCOUT]
        cache.transcripts[SCOUT] = ([e for e in entries if e["id"] != "s2"], mtime)
        data = flows_from(cache, NOW, 24)
        writer_flow = next(f for f in data["flows"] if f["rootAgentId"] == WRITER)
        self.assertEqual(writer_flow["trigger"]["kind"], "agent")
        self.assertEqual(writer_flow["trigger"]["agentId"], SCOUT)
        self.assertEqual(writer_flow["steps"][0]["from"], SCOUT)

    def test_window_drops_old_flows(self):
        data = flows_from(load_cache(self.support), NOW + 2 * 24 * 3600 * 1000, 24)
        self.assertEqual(data["flows"], [])

    def test_office_places_agents_by_section(self):
        office = office_from(load_cache(self.support), NOW)
        self.assertEqual([w["name"] for w in office["wings"]], ["司令部", "情报中心"])
        by_id = {a["id"]: a for a in office["agents"]}
        self.assertEqual(by_id[WRITER]["wingId"], "intel")
        self.assertEqual(by_id[WRITER]["slot"], 1)
        self.assertEqual(by_id[BOSS]["roleLine"], "总调度")
        self.assertEqual(by_id[BOSS]["state"], "idle")


    def test_insights_profiles_awards_and_feed(self):
        cache = load_cache(self.support)
        entries, mtime = cache.transcripts[BOSS]
        entries.append({"kind": "event", "id": "e1", "timestampMs": NOW - 1000,
                        "event": {"type": "automation-changed", "action": "created", "automationId": "a1", "automationName": "周报闹钟"}})
        data = insights_from(cache, NOW)
        boss = next(p for p in data["profiles"] if p["id"] == BOSS)
        self.assertEqual(boss["replies"], 2)
        self.assertEqual(boss["asks"], 2)
        self.assertEqual(boss["handoffsOut"], 1)
        self.assertEqual(boss["handoffsIn"], 1)
        self.assertEqual(boss["medianResponseMs"], 1000)  # only r-solo has a prompt and a reply in one turn
        self.assertEqual(boss["automations"], [{"name": "周报闹钟", "action": "created", "at": NOW - 1000, "active": True}])
        self.assertEqual({p["id"] for p in boss["partners"]}, {SCOUT, WRITER})
        keys = {award["key"]: award["id"] for award in data["awards"]}
        self.assertEqual(keys["scheduler"], BOSS)
        self.assertEqual(data["feed"][0]["kind"], "automation")
        self.assertEqual(sum(data["totals"]["hours"]), sum(p["outputs"] for p in data["profiles"]))


if __name__ == "__main__":
    unittest.main()
