#!/usr/bin/env python3
"""Grok Collab Room server. Local only: binds to 127.0.0.1 and refuses foreign Host/Origin.

    python3 backend/server.py            # http://127.0.0.1:19200
    python3 backend/server.py --demo     # always show the demo team
    python3 backend/server.py --port 8080 --open
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.settings import SettingsError, load_settings, save_settings
from backend.views import flows_view, insights_view, office_view

HOST = "127.0.0.1"
PORT = 19200
VERSION = "0.3.0"
WINDOWS = {24, 168, 720}
MIME = {
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        if not self.path.startswith("/api/"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _local(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        try:
            hostname = urlsplit("//" + host).hostname
        except ValueError:
            return False
        return hostname in {"127.0.0.1", "localhost", "::1"} and (not origin or origin == "http://" + host)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        if path == "/health":
            self._json({"ok": True, "version": VERSION})
            return
        if path.startswith("/api/"):
            if not self._local():
                self._json({"error": "请从本机打开协作室。"}, status=403)
                return
            if path == "/api/office":
                self._json(office_view())
            elif path == "/api/insights":
                self._json(insights_view())
            elif path == "/api/flows":
                query = parse_qs(url.query, max_num_fields=4)
                try:
                    hours = int(query.get("hours", ["24"])[0])
                except ValueError:
                    hours = 24
                self._json(flows_view(hours if hours in WINDOWS else 24))
            elif path == "/api/settings":
                self._json(load_settings())
            else:
                self.send_error(404)
            return
        if path == "/":
            path = "/index.html"
        elif path == "/settings":
            path = "/settings.html"
        root = FRONTEND.resolve()
        candidate = (root / path.lstrip("/")).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(candidate.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/settings":
            self.send_error(404)
            return
        # Only the page served from this machine may change settings.
        if not self._local() or not self.headers.get("Origin"):
            self._json({"error": "forbidden"}, status=403)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if not 0 < length <= 256_000 or "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json({"error": "bad request"}, status=400)
            return
        try:
            saved = save_settings(json.loads(self.rfile.read(length).decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, SettingsError):
            self._json({"error": "invalid settings"}, status=400)
            return
        self._json(saved)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    if sys.version_info < (3, 9):
        sys.exit("Grok Collab Room needs Python 3.9 or newer.")
    parser = argparse.ArgumentParser(description="Grok Collab Room — a local office view of your Grok Bot team.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GROK_COLLAB_PORT", PORT)), help=f"port to listen on (default {PORT})")
    parser.add_argument("--demo", action="store_true", help="always show the built-in demo team")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    args = parser.parse_args()
    if args.demo:
        os.environ["GROK_COLLAB_DEMO"] = "1"
    try:
        server = ThreadingHTTPServer((HOST, args.port), Handler)
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, 10048):
            sys.exit(f"Port {args.port} is already in use. Is the room already open? Try --port {args.port + 1}.")
        raise
    url = f"http://{HOST}:{args.port}"
    print(f"Grok Collab Room {VERSION}  {url}{'  (demo)' if args.demo else ''}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
