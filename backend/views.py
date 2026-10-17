"""What the page actually gets: pick the data source, then apply the user's local settings.

Settings can rename or reorder rooms, hide rooms or bots, give bots an alias and a
custom look, and switch on privacy mode, which blanks every message text before it
leaves the server (handy for screenshots and screen sharing).
"""

from __future__ import annotations

import os
import time

from backend.collab import flows_from, office_from
from backend.demo import demo_cache
from backend.grok_cache import Cache, default_support_dir, load_cache
from backend.insights import insights_from
from backend.settings import load_settings

MASK = "•••"


def _now() -> int:
    return int(time.time() * 1000)


def resolve_cache(settings: dict, now_ms: int) -> Cache:
    source = "demo" if os.environ.get("GROK_COLLAB_DEMO") == "1" else settings.get("dataSource", "auto")
    language = "en" if settings.get("language") == "en" else "zh"
    if source == "demo":
        return demo_cache(now_ms, language)
    cache = load_cache(default_support_dir(settings.get("supportDir", "")))
    if source == "auto" and not cache.roster:
        return demo_cache(now_ms, language)
    return cache


def _source(cache: Cache) -> dict:
    return {"demo": cache.demo, "supportDir": "" if cache.demo else str(cache.support), "found": bool(cache.roster)}


def _bot(settings: dict, bot_id: str) -> dict:
    return settings.get("bots", {}).get(bot_id, {})


def office_view(settings: dict | None = None, now_ms: int | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms)
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


def flows_view(hours: int, settings: dict | None = None, now_ms: int | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms)
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


def insights_view(settings: dict | None = None, now_ms: int | None = None) -> dict:
    settings = settings or load_settings()
    now_ms = now_ms or _now()
    cache = resolve_cache(settings, now_ms)
    data = insights_from(cache, now_ms)
    hidden = {bot_id for bot_id, bot in settings.get("bots", {}).items() if bot.get("hidden")}
    for profile in data["profiles"]:
        alias = _bot(settings, profile["id"]).get("alias")
        if alias:
            profile["name"] = alias
        if settings.get("privacy") and profile["description"]:
            profile["description"] = MASK
    data["awards"] = [award for award in data["awards"] if award["id"] not in hidden]
    if settings.get("privacy"):
        for item in data["feed"]:
            if item["kind"] != "automation" and item.get("text"):
                item["text"] = MASK
    data["source"] = _source(cache)
    return data
