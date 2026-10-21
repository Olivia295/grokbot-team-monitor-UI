#!/usr/bin/env python3
"""Bot Office server. Local only: binds to 127.0.0.1 and refuses foreign Host/Origin.

    python3 backend/server.py                      # http://127.0.0.1:19200
    python3 backend/server.py --demo               # always show the demo team
    python3 backend/server.py --events runs.jsonl  # any multi-agent system, see docs/events.md
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

try:  # installed package (pipx, uvx, Homebrew) or python -m backend.server
    from .alerts import AlertWatcher
    from .events import append_events
    from .settings import SettingsError, load_settings, save_settings, settings_path
    from .views import flows_view, ingest_path, insights_view, office_view
except ImportError:  # python3 backend/server.py from a checkout
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.alerts import AlertWatcher
    from backend.events import append_events
    from backend.settings import SettingsError, load_settings, save_settings, settings_path
    from backend.views import flows_view, ingest_path, insights_view, office_view

HOST = "127.0.0.1"
PORT = 19200
VERSION = "0.4.0"
WATCHER = AlertWatcher()
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
                self._json({"error": "请从本机打开Bot协作室。"}, status=403)
                return
            query = parse_qs(url.query, max_num_fields=4)
            settings = load_settings()
            # With language "auto", only the page knows the browser language; demo names follow it.
            if settings.get("language") == "auto" and query.get("lang", [""])[0] in ("zh", "en"):
                settings["language"] = query["lang"][0]
            if path == "/api/office":
                self._json(office_view(settings))
            elif path == "/api/insights":
                self._json(insights_view(settings))
            elif path == "/api/flows":
                try:
                    hours = int(query.get("hours", ["24"])[0])
                except ValueError:
                    hours = 24
                self._json(flows_view(hours if hours in WINDOWS else 24, settings))
            elif path == "/api/settings":
                settings = load_settings()
                # Read-only facts for the settings page; dropped again when settings are saved.
                settings["_meta"] = {"file": str(settings_path()), "ingest": str(ingest_path(settings)), "version": VERSION}
                self._json(settings)
            elif path == "/api/alerts":
                self._json({"enabled": bool(load_settings()["alerts"]["enabled"]), "alerts": WATCHER.snapshot()})
            else:
                self.send_error(404)
            return
        if path == "/":
            path = "/index.html"
        elif path in ("/settings", "/tv"):
            path = "/settings.html" if path == "/settings" else "/index.html"
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

    def _body(self, limit: int):
        """The JSON request body, or None after answering 400. JSON only, so a plain form on
        another site cannot post here without a CORS preflight, which this server never grants."""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if not 0 < length <= limit or "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json({"error": "bad request"}, status=400)
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json({"error": "invalid json"}, status=400)
            return None

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/events":
            # Scripts on this machine (no Origin header) or the local page may append events.
            if not self._local():
                self._json({"error": "forbidden"}, status=403)
                return
            body = self._body(2_000_000)
            if body is None:
                return
            if isinstance(body, list):
                items = body
            elif isinstance(body, dict):
                items = body["events"] if isinstance(body.get("events"), list) else [body]
            else:
                self._json({"error": "send an event object or a list of events"}, status=400)
                return
            target = ingest_path(load_settings())
            try:
                written = append_events(target, items[:5000])
            except OSError as error:
                self._json({"error": str(error)}, status=500)
                return
            self._json({"ok": True, "written": written, "file": str(target)})
            return
        if path not in ("/api/settings", "/api/alerts/test"):
            self.send_error(404)
            return
        # Only the page served from this machine may change settings or send test alerts.
        if not self._local() or not self.headers.get("Origin"):
            self._json({"error": "forbidden"}, status=403)
            return
        body = self._body(256_000)
        if body is None:
            return
        if path == "/api/alerts/test":
            self._json({"results": WATCHER.test()})
            return
        try:
            saved = save_settings(body)
        except SettingsError:
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
        sys.exit("Bot Office needs Python 3.9 or newer.")
    parser = argparse.ArgumentParser(description="Bot Office — a local office view of your Grok Bot team.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GROK_COLLAB_PORT", PORT)), help=f"port to listen on (default {PORT})")
    parser.add_argument("--demo", action="store_true", help="always show the built-in demo team")
    parser.add_argument("--events", metavar="PATH", help="read a JSONL event log (file or folder) instead of Grok Bot, see docs/events.md")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    parser.add_argument("--tv", action="store_true", help="with --open, open the big-screen view")
    parser.add_argument("--version", action="version", version=f"Bot Office {VERSION}")
    args = parser.parse_args()
    if args.demo:
        os.environ["GROK_COLLAB_DEMO"] = "1"
    if args.events:
        os.environ["GROK_COLLAB_EVENTS"] = str(Path(args.events).expanduser().resolve())
    try:
        server = ThreadingHTTPServer((HOST, args.port), Handler)
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, 10048):
            sys.exit(f"Port {args.port} is already in use. Is the room already open? Try --port {args.port + 1}.")
        raise
    url = f"http://{HOST}:{args.port}"
    mode = "  (demo)" if args.demo else f"  (events: {os.environ['GROK_COLLAB_EVENTS']})" if args.events else ""
    print(f"Bot Office {VERSION}  {url}{mode}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    WATCHER.base_url = url
    WATCHER.start()
    if args.open:
        target = f"{url}/tv" if args.tv else url
        threading.Timer(0.6, lambda: webbrowser.open(target)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        WATCHER.stop()
        server.server_close()


if __name__ == "__main__":
    main()
