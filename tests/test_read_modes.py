"""Internal (Grok Bot box) and external reading share one switch; remote hosts need the token."""

import json
import os
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import server, views  # noqa: E402
from backend.box_source import empty_box_cache  # noqa: E402
from backend.settings import clean  # noqa: E402


class ReadModeTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.pop(key, None) for key in ("BOT_OFFICE_INTERNAL", "GROK_COLLAB_DEMO", "GROK_COLLAB_EVENTS")}

    def tearDown(self):
        for key, value in self.saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value

    def test_auto_reads_the_box_only_when_on_one(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        self.assertTrue(views.use_box(clean({})))
        self.assertFalse(views.use_box(clean({"readMode": "external"})))
        os.environ["BOT_OFFICE_INTERNAL"] = "0"
        self.assertFalse(views.use_box(clean({})))
        self.assertFalse(views.use_box(clean({"readMode": "internal"})))  # not on a box: nothing to read

    def test_request_override_and_explicit_flags(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        self.assertFalse(views.use_box(clean({}), box=False))
        self.assertTrue(views.use_box(clean({"readMode": "external"}), box=True))
        os.environ["GROK_COLLAB_DEMO"] = "1"  # --demo wins over auto
        self.assertFalse(views.use_box(clean({})))

    def test_alerts_and_views_follow_the_setting(self):
        os.environ["BOT_OFFICE_INTERNAL"] = "1"
        with mock.patch("backend.views.load_box_cache", return_value=empty_box_cache()) as box:
            office = views.office_view(clean({}), 1_800_000_000_000)
        box.assert_called_once()
        self.assertEqual(office["source"]["kind"], "box")
        self.assertTrue(office["source"]["empty"])

    def test_read_mode_is_a_known_value(self):
        self.assertEqual(clean({"readMode": "sideways"})["readMode"], "auto")
        self.assertEqual(clean({"readMode": "internal"})["readMode"], "internal")


class RemoteHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = os.environ.get("BOT_OFFICE_ALLOWED_HOSTS")
        os.environ["BOT_OFFICE_ALLOWED_HOSTS"] = "box.example"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("BOT_OFFICE_ALLOWED_HOSTS", None)
        if cls.saved is not None:
            os.environ["BOT_OFFICE_ALLOWED_HOSTS"] = cls.saved

    def request(self, path, headers=None, method="GET", body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        result = (response.status, data, dict(response.getheaders()))
        conn.close()
        return result

    def test_allowed_host_needs_the_token(self):
        status, body, _ = self.request("/api/mode", {"Host": "box.example"})
        self.assertEqual(status, 401)
        self.assertTrue(json.loads(body)["tokenRequired"])
        status, body, _ = self.request("/", {"Host": "box.example"})
        self.assertEqual(status, 401)
        self.assertIn(b"token", body)
        status, _, _ = self.request("/api/events", {"Host": "box.example", "Content-Type": "application/json"},
                                    "POST", b'{"type":"ask","to":"x"}')
        self.assertEqual(status, 401)

    def test_token_link_sets_a_cookie_and_then_works(self):
        status, _, headers = self.request(f"/?token={server.TOKEN}&tv=1", {"Host": "box.example"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/?tv=1")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        status, body, _ = self.request("/api/mode", {"Host": "box.example", "Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("mode", json.loads(body))
        status, _, _ = self.request("/api/mode", {"Host": "box.example", "Authorization": f"Bearer {server.TOKEN}"})
        self.assertEqual(status, 200)
        status, _, _ = self.request("/api/mode", {"Host": "box.example", "Cookie": "bot_office_token=wrong"})
        self.assertEqual(status, 401)

    def test_loopback_needs_no_token_and_other_hosts_stay_out(self):
        self.assertEqual(self.request("/api/mode")[0], 200)
        self.assertEqual(self.request("/api/mode", {"Host": "evil.example"})[0], 403)
        status, _, _ = self.request(f"/?token={server.TOKEN}", {"Host": "evil.example"})
        self.assertNotEqual(status, 302)


if __name__ == "__main__":
    unittest.main()
