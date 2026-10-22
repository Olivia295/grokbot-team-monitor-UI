import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.collab import flows_from, office_from
from backend.demo import demo_cache
from backend.grok_cache import Cache
from backend.insights import insights_from
from backend.settings import SettingsError, clean, load_settings, save_settings
from backend.views import flows_view, insights_view, office_view

NOW = 1_800_000_000_000


class SettingsTest(unittest.TestCase):
    def test_clean_keeps_known_values_and_drops_junk(self):
        data = clean({
            "language": "en", "theme": "neon", "hours": 168, "privacy": True, "refreshSeconds": 1,
            "rooms": {"r1": {"name": "  Art   Room ", "hidden": True, "order": 2, "x": 1}},
            "bots": {"b1": {"alias": "Boss", "look": {"hat": "crown", "shape": "<script>", "evil": "x"}}},
            "unknown": 1,
        })
        self.assertEqual(data["language"], "en")
        self.assertEqual(data["theme"], "auto")
        self.assertEqual(data["hours"], 168)
        self.assertEqual(data["refreshSeconds"], 3)
        self.assertEqual(data["rooms"], {"r1": {"name": "Art Room", "hidden": True, "order": 2}})
        self.assertEqual(data["bots"], {"b1": {"alias": "Boss", "look": {"hat": "crown"}}})
        self.assertNotIn("unknown", data)
        with self.assertRaises(SettingsError):
            clean([])

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GROK_COLLAB_SETTINGS"] = str(Path(tmp) / "nested" / "settings.json")
            try:
                save_settings({"language": "zh", "ambient": False})
                self.assertFalse(load_settings()["ambient"])
                self.assertEqual(json.loads(Path(os.environ["GROK_COLLAB_SETTINGS"]).read_text())["language"], "zh")
            finally:
                del os.environ["GROK_COLLAB_SETTINGS"]


class DemoTest(unittest.TestCase):
    def test_demo_team_has_rooms_relays_and_a_live_one(self):
        cache = demo_cache(NOW, "en")
        office = office_from(cache, NOW)
        self.assertEqual([wing["name"] for wing in office["wings"]], ["Command", "Studio", "Intel"])
        self.assertEqual(sum(1 for agent in office["agents"] if agent["wingId"] == "__door__"), 1)
        flows = flows_from(cache, NOW, 168)
        self.assertGreater(flows["flowCount"], 20)
        self.assertGreater(flows["handoffCount"], 50)
        # Ninety seconds into a two-minute bucket the live relay has started handing off.
        later = NOW + 90_000
        recent = flows_from(demo_cache(later, "en"), later, 24)
        self.assertGreaterEqual(recent["activeCount"], 1)
        insights = insights_from(cache, NOW)
        self.assertTrue(insights["awards"])
        self.assertEqual(len(insights["digest"]), 2)
        self.assertEqual(len(insights["totals"]["week"]), 7)

    def test_demo_is_stable_within_a_bucket(self):
        # History does not reshuffle between refreshes; only the live relay grows.
        a = flows_from(demo_cache(NOW, "zh"), NOW, 168)
        b = flows_from(demo_cache(NOW + 30_000, "zh"), NOW + 30_000, 168)
        self.assertLessEqual({f["id"] for f in a["flows"]}, {f["id"] for f in b["flows"]})


class ViewsTest(unittest.TestCase):
    def setUp(self):
        self._internal = os.environ.get("BOT_OFFICE_INTERNAL")
        os.environ["BOT_OFFICE_INTERNAL"] = "0"
        self.settings = {
            "dataSource": "demo", "language": "en", "privacy": False,
            "rooms": {"demo-studio": {"name": "Art Room", "order": -1}, "demo-intel": {"hidden": True}},
            "bots": {"demo-atlas": {"alias": "Boss", "look": {"hat": "beanie"}}, "demo-echo": {"hidden": True}},
        }

    def tearDown(self):
        if self._internal is None:
            os.environ.pop("BOT_OFFICE_INTERNAL", None)
        else:
            os.environ["BOT_OFFICE_INTERNAL"] = self._internal

    def test_rooms_and_bots_follow_settings(self):
        office = office_view(self.settings, NOW)
        self.assertEqual([wing["name"] for wing in office["wings"]], ["Art Room", "Command"])
        names = {agent["id"]: agent for agent in office["agents"]}
        self.assertEqual(names["demo-atlas"]["name"], "Boss")
        self.assertEqual(names["demo-atlas"]["look"], {"hat": "beanie"})
        self.assertNotIn("demo-echo", names)
        self.assertNotIn("demo-scout", names)  # in the hidden room
        self.assertTrue(office["source"]["demo"])
        flows = flows_view(168, self.settings, NOW)
        self.assertIn("demo-echo", {item["id"] for item in flows["external"]})

    def test_privacy_mode_blanks_every_text(self):
        settings = {**self.settings, "privacy": True}
        flows = flows_view(168, settings, NOW)
        texts = {step["text"] for flow in flows["flows"] for step in flow["steps"] if step["text"]}
        self.assertEqual(texts, {"•••"})
        insights = insights_view(settings, NOW)
        self.assertTrue(all(item["text"] in ("", "•••") for item in insights["feed"] if item["kind"] != "automation"))
        office = office_view(settings, NOW)
        self.assertTrue(all(agent["snippet"] in ("", "•••") for agent in office["agents"]))

    def test_bots_without_a_group_get_their_own_room(self):
        cache = Cache(support=Path("x"), roster=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}],
                      sections=[], pinned=["c"])
        office = office_from(cache, NOW)
        self.assertEqual([wing["id"] for wing in office["wings"]], ["__loose__"])
        self.assertEqual({agent["id"]: agent["wingId"] for agent in office["agents"]}, {"a": "__loose__", "b": "__loose__", "c": "__door__"})


if __name__ == "__main__":
    unittest.main()
