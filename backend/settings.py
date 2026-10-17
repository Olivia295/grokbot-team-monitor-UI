"""Local settings for the collaboration room.

Stored as JSON next to the project (data/settings.json, git-ignored) or wherever
GROK_COLLAB_SETTINGS points. Nothing here is ever written into Grok Bot's own files.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LANGUAGES = {"auto", "zh", "en"}
THEMES = {"auto", "light", "dark"}
MOTIONS = {"full", "calm", "off"}
SOURCES = {"auto", "grok", "demo"}
WINDOWS = {24, 168, 720}
LOOK_KEYS = {"shape", "color", "eyes", "mouth", "hat", "item", "outfit"}
TOKEN = re.compile(r"^[a-z0-9-]{1,24}$")
MAX_ENTRIES = 500

DEFAULTS = {
    "version": 1,
    "language": "auto",
    "theme": "auto",
    "hours": 24,
    "ambient": True,
    "motion": "full",
    "privacy": False,
    "refreshSeconds": 3,
    "dataSource": "auto",
    "supportDir": "",
    "rooms": {},
    "bots": {},
}


class SettingsError(ValueError):
    pass


def settings_path() -> Path:
    override = os.environ.get("GROK_COLLAB_SETTINGS", "").strip()
    return Path(override).expanduser() if override else ROOT / "data" / "settings.json"


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _clean_look(look) -> dict:
    if not isinstance(look, dict):
        return {}
    return {key: value for key, value in look.items() if key in LOOK_KEYS and isinstance(value, str) and TOKEN.match(value)}


def clean(raw) -> dict:
    """Validate a settings object coming from disk or the page. Unknown keys are dropped."""
    if not isinstance(raw, dict):
        raise SettingsError("settings must be an object")
    out = copy.deepcopy(DEFAULTS)
    if raw.get("language") in LANGUAGES:
        out["language"] = raw["language"]
    if raw.get("theme") in THEMES:
        out["theme"] = raw["theme"]
    if raw.get("hours") in WINDOWS:
        out["hours"] = raw["hours"]
    if isinstance(raw.get("ambient"), bool):
        out["ambient"] = raw["ambient"]
    if raw.get("motion") in MOTIONS:
        out["motion"] = raw["motion"]
    if isinstance(raw.get("privacy"), bool):
        out["privacy"] = raw["privacy"]
    if isinstance(raw.get("refreshSeconds"), int) and 2 <= raw["refreshSeconds"] <= 60:
        out["refreshSeconds"] = raw["refreshSeconds"]
    if raw.get("dataSource") in SOURCES:
        out["dataSource"] = raw["dataSource"]
    out["supportDir"] = _text(raw.get("supportDir"), 512)

    rooms = raw.get("rooms") if isinstance(raw.get("rooms"), dict) else {}
    for room_id, room in list(rooms.items())[:MAX_ENTRIES]:
        if not isinstance(room_id, str) or len(room_id) > 128 or not isinstance(room, dict):
            continue
        entry = {}
        if _text(room.get("name"), 40):
            entry["name"] = _text(room.get("name"), 40)
        if isinstance(room.get("hidden"), bool) and room["hidden"]:
            entry["hidden"] = True
        if isinstance(room.get("order"), int) and -1000 <= room["order"] <= 1000:
            entry["order"] = room["order"]
        if entry:
            out["rooms"][room_id] = entry

    bots = raw.get("bots") if isinstance(raw.get("bots"), dict) else {}
    for bot_id, bot in list(bots.items())[:MAX_ENTRIES]:
        if not isinstance(bot_id, str) or len(bot_id) > 128 or not isinstance(bot, dict):
            continue
        entry = {}
        if _text(bot.get("alias"), 40):
            entry["alias"] = _text(bot.get("alias"), 40)
        if isinstance(bot.get("hidden"), bool) and bot["hidden"]:
            entry["hidden"] = True
        look = _clean_look(bot.get("look"))
        if look:
            entry["look"] = look
        if entry:
            out["bots"][bot_id] = entry
    return out


def load_settings() -> dict:
    path = settings_path()
    try:
        return clean(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, SettingsError):
        return copy.deepcopy(DEFAULTS)


def save_settings(raw) -> dict:
    data = clean(raw)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash never leaves half a file behind.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return data
