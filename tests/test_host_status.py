"""Host status collector: same facts and formatting as the grok-bot dashboard."""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.host_status import KNOWN_SERVICES, SELF_NAME, collect, port_up, tcp_latency_ms  # noqa: E402
from backend.server import PORT  # noqa: E402


PROC = {
    "/proc/uptime": "90061.50 12345.00\n",
    "/proc/loadavg": "0.10 0.20 0.30 1/234 5678\n",
    "/proc/meminfo": "MemTotal:        2048000 kB\nMemFree:          100000 kB\nMemAvailable:     1024000 kB\n",
}

SS_LISTING = """
State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
LISTEN 0      4096         0.0.0.0:8888       0.0.0.0:*
LISTEN 0      4096       127.0.0.1:8080       0.0.0.0:*
LISTEN 0      4096       127.0.0.1:22         0.0.0.0:*
"""

TAILSCALE = {
    "BackendState": "Running",
    "Self": {
        "DNSName": "grok-bot.tail4e6403.ts.net.",
        "TailscaleIPs": ["100.64.0.2", "fd7a:115c::2"],
        "KeyExpiry": "2026-12-01T00:00:00Z",
    },
    "Peer": {
        "a": {"HostName": "phone", "OS": "iOS", "Online": True},
        "b": {"HostName": "laptop", "OS": "macOS", "Online": False},
    },
}


def _read_text(path: str) -> str:
    return PROC[path]


def _disk(_path: str):
    return SimpleNamespace(used=5 * 2**30, total=20 * 2**30, free=15 * 2**30)


def _run(cmd: str) -> str:
    if cmd == "ss -ltn":
        return SS_LISTING
    if cmd == "tailscale status --json":
        return json.dumps(TAILSCALE)
    raise AssertionError(f"unexpected command: {cmd}")


class HostStatusTest(unittest.TestCase):
    def test_default_port_is_10000(self):
        self.assertEqual(PORT, 10000)

    def test_collect_matches_dashboard_formulas(self):
        def probe(port: int):
            return 1.2 if port in (8888, 8080) else None

        data = collect(
            generated_at="2026-10-22 12:00:00 UTC",
            read_text=_read_text,
            disk_usage=_disk,
            run=_run,
            probe=probe,
            own_port=8080,
        )
        self.assertEqual(data["generated_at"], "2026-10-22 12:00:00 UTC")
        self.assertEqual(data["refresh_seconds"], 30)
        self.assertEqual(data["uptime"]["text"], "1d 1h 1m")
        self.assertEqual(data["uptime"]["days"], 1)
        self.assertEqual(data["uptime"]["hours"], 1)
        self.assertEqual(data["uptime"]["minutes"], 1)
        self.assertEqual(data["load"], ["0.10", "0.20", "0.30"])
        self.assertEqual(data["memory"]["text"], "1000 / 2000 MiB used")
        self.assertEqual(data["disk"]["path"], "/home/box")
        self.assertEqual(data["disk"]["text"], "5 / 20 GiB used (15 GiB free)")
        self.assertEqual(
            data["tailscale"],
            "Running · grok-bot.tail4e6403.ts.net · 100.64.0.2 · key expires 2026-12-01T00:00:00Z",
        )
        self.assertEqual(
            [(s["name"], s["port"], s["up"], s["latency_ms"]) for s in data["services"]],
            # This app first, then only the known services that are listening.
            [(SELF_NAME, 8080, True, 1.2), ("JupyterLab", 8888, True, 1.2)],
        )
        self.assertEqual(
            [(p["host"], p["os"], p["online"]) for p in data["peers"]],
            [("phone", "iOS", True), ("laptop", "macOS", False)],
        )

    def test_tailscale_unavailable_and_no_peers(self):
        def run(cmd: str) -> str:
            if cmd == "ss -ltn":
                return SS_LISTING
            return "error: not found"

        data = collect(generated_at="now", read_text=_read_text, disk_usage=_disk, run=run, probe=lambda _p: None)
        self.assertEqual(data["tailscale"], "unavailable")
        self.assertEqual(data["peers"], [])

    def test_port_up_matches_ss_substring(self):
        self.assertTrue(port_up(8888, SS_LISTING))
        self.assertFalse(port_up(4000, SS_LISTING))
        self.assertFalse(port_up(80, "error: missing"))

    def test_known_services_are_the_old_dashboards(self):
        self.assertEqual(KNOWN_SERVICES, (("JupyterLab", 8888), ("MessageHub", 8090), ("Blog", 4000)))

    def test_service_urls_pass_through_and_are_validated(self):
        from backend.settings import clean
        cleaned = clean({"services": [
            {"name": "Jupyter", "port": 8888, "url": "https://grok-bot.tail4e6403.ts.net:8888/lab"},
            {"name": "Blog", "port": 4000, "url": "javascript:alert(1)"},
            {"name": "Hub", "port": 8090, "url": "http://x/<script>"},
        ]})["services"]
        self.assertEqual(cleaned[0]["url"], "https://grok-bot.tail4e6403.ts.net:8888/lab")
        self.assertNotIn("url", cleaned[1])
        self.assertNotIn("url", cleaned[2])
        data = collect(generated_at="now", read_text=_read_text, disk_usage=_disk, run=_run, probe=lambda _p: None,
                       services=cleaned, own_port=10000)
        by_name = {s["name"]: s for s in data["services"]}
        self.assertEqual(by_name["Jupyter"]["url"], "https://grok-bot.tail4e6403.ts.net:8888/lab")
        self.assertNotIn("url", by_name["Blog"])
        self.assertNotIn("url", by_name[SELF_NAME])

    def test_service_names_link_out(self):
        script = (Path(__file__).resolve().parents[1] / "frontend" / "js" / "internal.js").read_text(encoding="utf-8")
        self.assertIn("function serviceHref", script)
        self.assertIn("location.hostname}:${port}/", script)
        self.assertIn('target="_blank" rel="noopener noreferrer"', script)

    def test_settings_list_replaces_the_known_ones(self):
        data = collect(generated_at="now", read_text=_read_text, disk_usage=_disk, run=_run, probe=lambda _p: None,
                       services=[{"name": "Blog", "port": 4000}, {"name": "Jupyter", "port": 8888}], own_port=10000)
        self.assertEqual([(s["name"], s["port"], s["up"]) for s in data["services"]],
                         [(SELF_NAME, 10000, False), ("Blog", 4000, False), ("Jupyter", 8888, True)])

    def test_tcp_latency_open_and_closed_port(self):
        import socket

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            ms = tcp_latency_ms(port)
            self.assertIsNotNone(ms)
            self.assertGreaterEqual(ms, 0)
        finally:
            server.close()
        self.assertIsNone(tcp_latency_ms(port, timeout=0.2))

    def test_missing_proc_is_unavailable(self):
        def boom(_path: str) -> str:
            raise FileNotFoundError(_path)

        def no_disk(_path: str):
            raise OSError("no disk")

        data = collect(generated_at="now", read_text=boom, disk_usage=no_disk, run=lambda _c: "", probe=lambda _p: None)
        self.assertEqual(data["uptime"]["text"], "unavailable")
        self.assertEqual(data["load"], [])
        self.assertEqual(data["memory"]["text"], "unavailable")
        self.assertEqual(data["disk"]["text"], "unavailable")
        self.assertEqual(data["tailscale"], "unavailable")


class HostStatusApiTest(unittest.TestCase):
    def test_endpoint_is_local_json(self):
        from http.client import HTTPConnection
        from http.server import ThreadingHTTPServer
        import threading
        from backend.server import Handler

        class Quiet(Handler):
            def log_message(self, fmt, *args):
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        httpd.allow_reuse_address = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        sample = collect(
            generated_at="now",
            read_text=_read_text,
            disk_usage=_disk,
            run=_run,
            probe=lambda port: 0.5 if port in (8888, 8080) else None,
        )
        box = {"internal_available": True, "reason": ""}
        try:
            with mock.patch("backend.server.collect_host_status", return_value=sample), \
                    mock.patch("backend.server.mode_status", return_value=box):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/host-status")
                resp = conn.getresponse()
                body = json.loads(resp.read())
                kind = resp.getheader("Content-Type")
                status = resp.status
                conn.close()
            self.assertEqual(status, 200)
            self.assertIn("application/json", kind)
            self.assertEqual(body["uptime"]["text"], "1d 1h 1m")
            self.assertEqual(body["memory"]["text"], "1000 / 2000 MiB used")
            self.assertEqual(body["disk"]["text"], "5 / 20 GiB used (15 GiB free)")

            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/host-status", headers={"Host": "evil.example"})
            resp = conn.getresponse()
            forbidden = resp.status
            conn.close()
            self.assertEqual(forbidden, 403)

            # Off the box there is no host page: it says so instead of reading this machine.
            with mock.patch("backend.server.mode_status", return_value={"internal_available": False, "reason": "not a box"}):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/host-status")
                off_box = conn.getresponse().status
                conn.close()
            self.assertEqual(off_box, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
