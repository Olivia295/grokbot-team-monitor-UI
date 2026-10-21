"""Tiny client for sending your agents' activity to Bot Office. Standard library only.

Copy this file next to your code (or `pip install` the project) and call it from
whatever framework runs your agents:

    from bot_office import BotOffice

    office = BotOffice()                         # POSTs to http://127.0.0.1:19200/api/events
    # office = BotOffice(file="runs.jsonl")      # or append to a file: bot-office --events runs.jsonl
    office.bot("planner", name="Planner", title="Lead", team="Core")
    run = office.new_run()
    office.ask("planner", "Write the release notes", run=run)
    office.handoff("planner", "writer", "Draft notes from the changelog", run=run)
    office.reply("planner", "Release notes are live", run=run)

Every call is fire-and-forget: if Bot Office is not running, the event is dropped with a
warning and your agents carry on.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

__all__ = ["BotOffice"]


class BotOffice:
    def __init__(self, url: str = "http://127.0.0.1:19200", file: str | Path | None = None, quiet: bool = False):
        self.url = url.rstrip("/") + "/api/events"
        self.file = Path(file).expanduser() if file else None
        self.quiet = quiet
        self._lock = threading.Lock()
        self._warned = False

    # ------------------------------------------------------------ events

    def bot(self, id: str, name: str | None = None, title: str | None = None, team: str | None = None,
            description: str | None = None, shape: str | None = None, color: str | None = None, pinned: bool | None = None) -> None:
        """Introduce a bot. Optional: everything else works with bare ids too."""
        self.emit({"type": "bot", "id": id, "name": name, "title": title, "team": team,
                   "description": description, "shape": shape, "color": color, "pinned": pinned})

    def ask(self, to: str, text: str = "", run: str | None = None) -> None:
        """A person gives a bot a task."""
        self.emit({"type": "ask", "to": to, "text": text, "run": run})

    def handoff(self, sender: str, to: str, text: str = "", run: str | None = None) -> None:
        """One bot passes work to another."""
        self.emit({"type": "handoff", "from": sender, "to": to, "text": text, "run": run})

    def reply(self, sender: str, text: str = "", run: str | None = None) -> None:
        """A bot answers the person who asked."""
        self.emit({"type": "reply", "from": sender, "text": text, "run": run})

    def status(self, bot: str, state: str, text: str = "") -> None:
        """working | idle | waiting (needs a person) | error"""
        self.emit({"type": "status", "bot": bot, "state": state, "text": text})

    def error(self, bot: str, text: str = "", run: str | None = None) -> None:
        self.emit({"type": "error", "bot": bot, "text": text, "run": run})

    def schedule(self, bot: str, name: str, active: bool = True) -> None:
        """A recurring job that wakes a bot up."""
        self.emit({"type": "schedule", "bot": bot, "name": name, "active": active})

    @staticmethod
    def new_run() -> str:
        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------ transport

    def emit(self, event: dict) -> None:
        event = {key: value for key, value in event.items() if value is not None}
        event.setdefault("ts", int(time.time() * 1000))
        line = json.dumps(event, ensure_ascii=False)
        try:
            if self.file:
                with self._lock:
                    self.file.parent.mkdir(parents=True, exist_ok=True)
                    with self.file.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
            else:
                request = urllib.request.Request(self.url, data=line.encode("utf-8"), method="POST",
                                                 headers={"Content-Type": "application/json"})
                urllib.request.urlopen(request, timeout=2).close()
        except (OSError, ValueError) as error:
            if not self.quiet and not self._warned:
                self._warned = True
                print(f"bot_office: could not send events ({error}); is Bot Office running?", file=sys.stderr)
