"""What the page actually gets: pick the data source, then apply the user's local settings.

Settings can rename or reorder rooms, hide rooms or bots, give bots an alias and a
custom look, and switch on privacy mode, which blanks every message text before it
leaves the server (handy for screenshots and screen sharing).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from .box_source import load_box_cache
from .collab import flows_from, office_from
from .demo import demo_cache
from .events import event_files, events_cache
from .grok_cache import Cache, default_support_dir, load_cache
from .insights import insights_from
from .internal_box import mode_status
from .settings import data_dir, load_settings

MASK = "•••"


def _now() -> int:
    return int(time.time() * 1000)


def events_path(settings: dict) -> Path | None:
    """The JSONL event file or folder in use: --events / GROK_COLLAB_EVENTS, then settings."""
    value = os.environ.get("GROK_COLLAB_EVENTS", "").strip() or settings.get("eventsPath", "").strip()
    return Path(value).expanduser() if value else None


def ingest_path(settings: dict) -> Path:
    """Where POST /api/events appends: the configured .jsonl file, else data/events.jsonl."""
    path = events_path(settings)
    if path is not None and (path.suffix == ".jsonl" or path.is_file()):
        return path
    if path is not None and path.is_dir():
        return path / "events.jsonl"
    return data_dir() / "events.jsonl"


def use_box(settings: dict, box: bool | None = None) -> bool:
    """Internal mode (reading the Grok Bot box itself).

    An explicit ``?box=1`` / ``?box=0`` wins, then ``--demo`` / ``--events``, then the
    read-mode setting: "internal", "external", or "auto" (internal whenever this
    machine is a Grok Bot box). The page, alerts, the big screen and the menu-bar
    app all go through here, so they always agree on the source.
    """
    if box is not None:
        return box
    if os.environ.get("GROK_COLLAB_DEMO") == "1" or os.environ.get("GROK_COLLAB_EVENTS", "").strip():
        return False
    # On a Grok Bot box there is no app cache to read "externally": that would only be the demo
    # team. So a box always reads itself; readMode only matters where both are possible.
    return bool(mode_status()["internal_available"])


def resolve_cache(settings: dict, now_ms: int, box: bool | None = None) -> Cache:
    # Internal mode reads the box. It never substitutes the built-in demo team.
    if use_box(settings, box):
        return load_box_cache()
    if os.environ.get("GROK_COLLAB_DEMO") == "1":
        source = "demo"
    elif os.environ.get("GROK_COLLAB_EVENTS", "").strip():
        source = "events"
    else:
        source = settings.get("dataSource", "auto")
    language = "en" if settings.get("language") == "en" else "zh"
    if source == "demo":
        return demo_cache(now_ms, language)
    if source == "events":
        return events_cache(events_path(settings) or ingest_path(settings), now_ms)
    cache = load_cache(default_support_dir(settings.get("supportDir", "")))
    if source == "auto" and not cache.roster:
        # No Grok Bot here: try an event log (configured, or what POST /api/events wrote).
        for path in (events_path(settings), ingest_path(settings)):
            if path is not None and event_files(path):
                events = events_cache(path, now_ms)
                if events.roster:
                    return events
        # Nothing real to show: an empty office that says so. The demo team only appears when
        # someone asks for it (--demo, or Settings → Data source → Demo).
    return cache


def _source(cache: Cache) -> dict:
    return {
        "demo": bool(cache.demo),
        "kind": cache.source,
        "box": bool(cache.box),
        "empty": bool(cache.box and cache.empty),
        "supportDir": "" if cache.demo else str(cache.support),
        "found": bool(cache.roster),
        "dataAt": int(cache.data_at or 0),
    }


def _bot(settings: dict, bot_id: str) -> dict:
    return settings.get("bots", {}).get(bot_id, {})


def office_view(settings: dict | None = None, now_ms: int | None = None, box: bool | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms, box=box)
    office = office_from(cache, now_ms)
    rooms = settings.get("rooms", {})
    hidden_rooms = {room_id for room_id, room in rooms.items() if room.get("hidden")}
    wings = []
    for index, wing in enumerate(office["wings"]):
        room = rooms.get(wing["id"], {})
        if wing["id"] in hidden_rooms:
            continue
        wings.append({**wing, "name": room.get("name") or wing["name"], "order": room.get("order", index)})
    wings.sort(key=lambda wing: wing["order"])
    agents = []
    for agent in office["agents"]:
        bot = _bot(settings, agent["id"])
        if bot.get("hidden") or agent["wingId"] in hidden_rooms:
            continue
        agent = {**agent, "originalName": agent["name"], "name": bot.get("alias") or agent["name"], "look": bot.get("look") or {}}
        wing = next((item for item in wings if item["id"] == agent["wingId"]), None)
        if wing is not None:
            agent["wingName"] = wing["name"]
        if settings.get("privacy"):
            agent.update(snippet=MASK if agent["snippet"] else "", roleLine=MASK if agent["roleLine"] else "",
                         detailParam=agent["detailParam"] and MASK)
        agents.append(agent)
    # Every bot in the roster, hidden or not, for the settings page.
    roster = [{
        "id": row["id"], "name": row.get("name") or "", "title": row.get("title") or "",
        "avatarShape": row.get("avatarShape") or "", "avatarColor": row.get("avatarColor") or "",
        "sidebarHidden": bool(row.get("isHiddenFromSidebar")),
    } for row in cache.roster]
    all_rooms = [{"id": wing["id"], "name": wing["name"]} for wing in office["wings"]]
    return {**office, "wings": wings, "agents": agents, "roster": roster, "allRooms": all_rooms,
            "source": _source(cache), "privacy": bool(settings.get("privacy"))}


def flows_view(hours: int, settings: dict | None = None, now_ms: int | None = None, box: bool | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms, box=box)
    data = flows_from(cache, now_ms, hours)
    names = {row["id"]: row.get("name") or "" for row in cache.roster}
    # Bots hidden from the office still take part in flows; show them under their alias.
    external = {item["id"]: item for item in data["external"]}
    for bot_id, bot in settings.get("bots", {}).items():
        if bot.get("hidden") and bot_id in names:
            external[bot_id] = {"id": bot_id, "name": bot.get("alias") or names[bot_id]}
    for item in external.values():
        if item["id"] in settings.get("bots", {}) and settings["bots"][item["id"]].get("alias"):
            item["name"] = settings["bots"][item["id"]]["alias"]
    data["external"] = list(external.values())
    if settings.get("privacy"):
        for flow in data["flows"]:
            if flow["trigger"]["text"]:
                flow["trigger"]["text"] = MASK
            for step in flow["steps"]:
                step["text"] = MASK if step["text"] else ""
    data["source"] = _source(cache)
    return data


def insights_view(settings: dict | None = None, now_ms: int | None = None, box: bool | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms, box=box)
    data = insights_from(cache, now_ms)
    hidden = {bot_id for bot_id, bot in settings.get("bots", {}).items() if bot.get("hidden")}
    for profile in data["profiles"]:
        alias = _bot(settings, profile["id"]).get("alias")
        if alias:
            profile["name"] = alias
        if settings.get("privacy") and profile["description"]:
            profile["description"] = MASK
    data["awards"] = [award for award in data["awards"] if award["id"] not in hidden]
    # Last seven days of collaboration, for the weekly report export.
    week = flows_from(cache, now_ms, 168)
    data["week"] = {
        "flows": week["flowCount"], "handoffs": week["handoffCount"], "solo": week["soloCount"],
        "hub": week["hub"], "bottleneck": week["bottleneck"],
        "topLinks": [{key: link[key] for key in ("from", "to", "count", "avgWaitMs")} for link in week["links"][:5]],
    }
    if settings.get("privacy"):
        for item in data["feed"]:
            if item["kind"] != "automation" and item.get("text"):
                item["text"] = MASK
    data["source"] = _source(cache)
    return data
