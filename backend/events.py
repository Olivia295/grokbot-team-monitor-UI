"""Generic event adapter: any multi-agent system can feed Bot Office with a JSONL file.

One JSON object per line. The fields that matter:

    {"type": "bot",      "id": "planner", "name": "Planner", "title": "Lead", "team": "Core"}
    {"type": "ask",      "to": "planner", "text": "Ship the release notes", "run": "r1"}
    {"type": "handoff",  "from": "planner", "to": "writer", "text": "Draft the notes", "run": "r1"}
    {"type": "reply",    "from": "planner", "text": "Done, notes are live", "run": "r1"}
    {"type": "status",   "bot": "writer", "state": "working"}     # working | idle | waiting | error
    {"type": "error",    "bot": "writer", "text": "Rate limited", "run": "r1"}
    {"type": "schedule", "bot": "radar", "name": "Morning brief"}

`ts` (epoch seconds, epoch ms or an ISO 8601 string) is optional and defaults to the
time the line was read in order. `run` groups the events of one task; without it, a
bot's events stay in the same turn until it goes quiet for 30 minutes. The events are
turned into the same shape as a Grok Bot cache, so every view works unchanged.
See docs/events.md for the full format.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path

from .grok_cache import Cache

TURN_IDLE_MS = 30 * 60 * 1000
WORKING_MS = 15 * 60 * 1000
ONLINE_MS = 5 * 60 * 1000
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 64
TYPES = {"bot", "ask", "handoff", "reply", "status", "error", "schedule"}
STATES = {"working", "idle", "waiting", "error"}


def event_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))[-MAX_FILES:]
    return []


def _tail_lines(path: Path) -> list[str]:
    """The last MAX_BYTES of a file, split into lines (a cut first line is dropped)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_BYTES:
                handle.seek(size - MAX_BYTES)
                handle.readline()
            data = handle.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def parse_ts(value, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        # Seconds, not milliseconds, for anything before the year 33658.
        return int(value * 1000) if value < 1e12 else int(value)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError:
            return fallback
    return fallback


def _id(value) -> str:
    return value.strip()[:128] if isinstance(value, str) and value.strip() else ""


def _text(value, limit: int = 2000) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def read_events(path: Path, now_ms: int | None = None) -> list[dict]:
    """Every valid event under `path`, oldest first."""
    now_ms = now_ms or int(time.time() * 1000)
    events: list[dict] = []
    order = 0
    for file in event_files(path):
        for line in _tail_lines(file):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict) or raw.get("type") not in TYPES:
                continue
            order += 1
            raw["_ts"] = parse_ts(raw.get("ts"), now_ms)
            raw["_order"] = order
            events.append(raw)
    events.sort(key=lambda event: (event["_ts"], event["_order"]))
    return events


class _Turns:
    """Hands out Grok-style request ids so handoffs chain into flows."""

    def __init__(self):
        self.current: dict[tuple[str, str], tuple[str, int]] = {}
        self.count = 0

    def new(self, bot: str, run: str, at: int) -> str:
        self.count += 1
        request = f"{run or 'turn'}:{bot}:{self.count}"
        self.current[(bot, run)] = (request, at)
        return request

    def get(self, bot: str, run: str, at: int) -> str:
        found = self.current.get((bot, run))
        if found and (run or at - found[1] <= TURN_IDLE_MS):
            self.current[(bot, run)] = (found[0], at)
            return found[0]
        return self.new(bot, run, at)


def events_cache(path: Path, now_ms: int | None = None) -> Cache:
    now_ms = now_ms or int(time.time() * 1000)
    events = read_events(path, now_ms)
    bots: dict[str, dict] = {}
    order: list[str] = []
    transcripts: dict[str, list[dict]] = {}
    statuses: dict[str, tuple[str, int]] = {}
    turns = _Turns()
    seq = 0

    def bot(bot_id: str, at: int = 0) -> dict:
        if bot_id not in bots:
            bots[bot_id] = {"id": bot_id, "name": bot_id, "createdAt": at, "lastActivityAt": 0}
            order.append(bot_id)
            transcripts[bot_id] = []
        row = bots[bot_id]
        if at:
            row["lastActivityAt"] = max(row["lastActivityAt"], at)
            row["createdAt"] = min(row["createdAt"] or at, at)
        return row

    def push(bot_id: str, entry: dict) -> None:
        nonlocal seq
        seq += 1
        entry.setdefault("id", f"ev{seq}")
        entry["seq"] = seq
        transcripts[bot_id].append(entry)

    for event in events:
        kind, at, run = event["type"], event["_ts"], _id(event.get("run"))
        text = _text(event.get("text"))
        if kind == "bot":
            bot_id = _id(event.get("id"))
            if not bot_id:
                continue
            row = bot(bot_id)
            for key, limit in (("name", 40), ("title", 24), ("description", 600), ("team", 40)):
                value = _text(event.get(key), limit)
                if value:
                    row[key] = value
            for key, target in (("shape", "avatarShape"), ("color", "avatarColor")):
                value = _id(event.get(key))
                if value:
                    row[target] = value[:24]
            if isinstance(event.get("pinned"), bool):
                row["pinned"] = event["pinned"]
            if isinstance(event.get("hidden"), bool):
                row["isHiddenFromSidebar"] = event["hidden"]
        elif kind == "ask":
            target = _id(event.get("to") or event.get("bot"))
            if not target:
                continue
            bot(target, at)
            push(target, {"kind": "message", "role": "user", "timestampMs": at, "content": text,
                          "requestId": turns.new(target, run, at), "isStreaming": False})
            statuses.pop(target, None)
        elif kind == "handoff":
            sender, receiver = _id(event.get("from")), _id(event.get("to"))
            if not sender or not receiver or sender == receiver:
                continue
            bot(sender, at)
            receiver_row = bot(receiver, at)
            sender_name = bots[sender]["name"]
            push(sender, {"kind": "message", "role": "assistant", "timestampMs": at, "content": text,
                          "requestId": turns.get(sender, run, at), "isStreaming": False,
                          "toAgent": {"id": receiver, "name": receiver_row["name"], "kind": "agent"}})
            push(receiver, {"kind": "message", "role": "user", "timestampMs": at + 1, "content": text,
                            "requestId": turns.new(receiver, run, at), "isStreaming": False,
                            "fromAgent": {"id": sender, "name": sender_name}})
            statuses.pop(sender, None)
        elif kind == "reply":
            sender = _id(event.get("from") or event.get("bot"))
            if not sender:
                continue
            bot(sender, at)
            push(sender, {"kind": "send-message", "timestampMs": at, "requestId": turns.get(sender, run, at),
                          "message": {"type": "text", "content": text}})
            statuses.pop(sender, None)
        elif kind == "error":
            target = _id(event.get("bot") or event.get("from"))
            if not target:
                continue
            bot(target, at)
            push(target, {"kind": "event", "timestampMs": at, "requestId": turns.get(target, run, at),
                          "event": {"type": "error", "message": text}})
            statuses[target] = ("error", at)
        elif kind == "status":
            target = _id(event.get("bot"))
            state = event.get("state")
            if not target or state not in STATES:
                continue
            bot(target, at)
            statuses[target] = (state, at)
            if state == "error":
                push(target, {"kind": "event", "timestampMs": at, "event": {"type": "error", "message": text}})
        elif kind == "schedule":
            target = _id(event.get("bot"))
            name = _text(event.get("name"), 40)
            if not target or not name:
                continue
            bot(target, at)
            action = "deleted" if event.get("active") is False else "created"
            push(target, {"kind": "event", "timestampMs": at,
                          "event": {"type": "automation-changed", "action": action,
                                    "automationId": _id(event.get("id")) or name, "automationName": name}})

    # Latest statuses become live state the office understands.
    for bot_id, (state, at) in statuses.items():
        if state == "working" and now_ms - at <= WORKING_MS:
            push(bot_id, {"kind": "message", "role": "assistant", "timestampMs": at, "content": "", "isStreaming": True})
        elif state == "waiting":
            bots[bot_id]["awaitingUserResponse"] = {"since": at}

    teams: dict[str, list[str]] = {}
    for bot_id in order:
        team = bots[bot_id].get("team")
        if team:
            teams.setdefault(team, []).append(bot_id)
    sections = [{"id": f"team:{name}", "name": name, "agentIds": ids} for name, ids in teams.items()]
    roster = [{key: value for key, value in bots[bot_id].items() if key not in ("team", "pinned")} for bot_id in order]
    last = max((row["lastActivityAt"] for row in roster), default=0)
    cache = Cache(support=path, account="events", roster=roster, sections=sections,
                  pinned=[bot_id for bot_id in order if bots[bot_id].get("pinned")])
    cache.transcripts = {bot_id: (entries, last) for bot_id, entries in transcripts.items()}
    cache.source = "events"
    cache.online = bool(last) and now_ms - last <= ONLINE_MS
    return cache


def append_events(path: Path, items: list[dict]) -> int:
    """Append validated events to a JSONL file (used by POST /api/events)."""
    lines = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in TYPES:
            continue
        clean = {key: value for key, value in item.items() if isinstance(key, str) and not key.startswith("_")}
        clean.setdefault("ts", int(time.time() * 1000))
        lines.append(json.dumps(clean, ensure_ascii=False))
    if not lines:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return len(lines)
