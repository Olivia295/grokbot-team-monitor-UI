"""Host status collector: same facts and formatting as the grok-bot dashboard."""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.host_status import SERVICES, collect, port_up, tcp_latency_ms  # noqa: E402
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
    def test_default_port_is_8080(self):
        self.assertEqual(PORT, 8080)

    def test_collect_matches_dashboard_formulas(self):
        def probe(port: int):
            return 1.2 if port in (8888, 8080) else None

        data = collect(
            generated_at="2026-10-22 12:00:00 UTC",
            read_text=_read_text,
            disk_usage=_disk,
            run=_run,
            probe=probe,
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
            [
                ("JupyterLab", 8888, True, 1.2),
                ("Dashboard", 8080, True, 1.2),
                ("Blog", 4000, False, None),
            ],
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

    def test_services_list_matches_dashboard(self):
        self.assertEqual(SERVICES, (("JupyterLab", 8888), ("Dashboard", 8080), ("Blog", 4000)))

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
        try:
            with mock.patch("backend.server.collect_host_status", return_value=sample):
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
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
