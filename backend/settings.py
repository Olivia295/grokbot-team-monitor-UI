"""Local settings for the collaboration room.

Stored as JSON next to the project (data/settings.json, git-ignored) when run from a
checkout, in the user's app-data folder when installed with pip/pipx/uvx/Homebrew, or
wherever GROK_COLLAB_SETTINGS points. Nothing here is ever written into Grok Bot's own files.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LANGUAGES = {"auto", "zh", "en"}
THEMES = {"auto", "light", "dark"}
MOTIONS = {"full", "calm", "off"}
SOURCES = {"auto", "grok", "events", "demo"}
READ_MODES = {"auto", "internal", "external"}
HOOK_KINDS = {"slack", "discord", "feishu", "dingtalk", "generic"}
MAX_HOOKS = 8
WINDOWS = {24, 168, 720}
LOOK_KEYS = {"shape", "color", "eyes", "mouth", "hat", "item", "outfit"}
TOKEN = re.compile(r"^[a-z0-9-]{1,24}$")
MAX_ENTRIES = 500
MAX_SERVICES = 20

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
    # Grok Bot box: "auto" reads the box when this machine is one, "internal" / "external" pin it.
    "readMode": "auto",
    "supportDir": "",
    "eventsPath": "",
    "tvSeconds": 20,
    "alerts": {
        "enabled": False,
        "desktop": True,
        "error": True,
        "awaiting": True,
        "stuck": True,
        "done": False,
        "stuckMinutes": 10,
        "cooldownMinutes": 15,
        "quiet": False,
        "quietFrom": 23,
        "quietTo": 8,
        "webhooks": [],
    },
    "rooms": {},
    "bots": {},
    # Local services the box's Host tab watches: [{"name": "JupyterLab", "port": 8888}].
    "services": [],
}


class SettingsError(ValueError):
    pass


def data_dir() -> Path:
    """data/ in a source checkout; the per-user app-data folder when installed as a package."""
    if (ROOT / "pyproject.toml").exists() or (ROOT / ".git").exists():
        return ROOT / "data"
    home = Path.home()
    if sys.platform == "darwin":
        base, new, old = home / "Library" / "Application Support", "Bot Monitoring Room", "Bot Office"
    elif os.name == "nt":
        base, new, old = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming"), "Bot Monitoring Room", "Bot Office"
    else:
        base, new, old = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config"), "bot-monitor", "bot-office"
    # Installs from before the rename keep their settings where they already are.
    return base / old if (base / old).is_dir() and not (base / new).exists() else base / new


def settings_path() -> Path:
    override = os.environ.get("GROK_COLLAB_SETTINGS", "").strip()
    return Path(override).expanduser() if override else data_dir() / "settings.json"


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _clean_look(look) -> dict:
    if not isinstance(look, dict):
        return {}
    return {key: value for key, value in look.items() if key in LOOK_KEYS and isinstance(value, str) and TOKEN.match(value)}


def _clean_hook(hook) -> dict | None:
    if not isinstance(hook, dict):
        return None
    url = hook.get("url").strip() if isinstance(hook.get("url"), str) else ""
    local = url.startswith(("http://127.0.0.1", "http://localhost"))
    if not url or len(url) > 600 or not (url.startswith("https://") or local) or any(c.isspace() for c in url):
        return None
    out = {"kind": hook.get("kind") if hook.get("kind") in HOOK_KINDS else "generic", "url": url,
           "enabled": hook.get("enabled") is not False}
    if _text(hook.get("name"), 40):
        out["name"] = _text(hook.get("name"), 40)
    if isinstance(hook.get("secret"), str) and hook["secret"].strip():
        out["secret"] = hook["secret"].strip()[:200]
    return out


def _clean_alerts(raw) -> dict:
    out = copy.deepcopy(DEFAULTS["alerts"])
    if not isinstance(raw, dict):
        return out
    for key in ("enabled", "desktop", "error", "awaiting", "stuck", "done", "quiet"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key, low, high in (("stuckMinutes", 1, 720), ("cooldownMinutes", 0, 1440), ("quietFrom", 0, 23), ("quietTo", 0, 23)):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            out[key] = value
    hooks = raw.get("webhooks") if isinstance(raw.get("webhooks"), list) else []
    out["webhooks"] = [hook for hook in (_clean_hook(item) for item in hooks[:MAX_HOOKS]) if hook]
    return out


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
    if raw.get("readMode") in READ_MODES:
        out["readMode"] = raw["readMode"]
    out["supportDir"] = _text(raw.get("supportDir"), 512)
    out["eventsPath"] = _text(raw.get("eventsPath"), 512)
    if isinstance(raw.get("tvSeconds"), int) and 5 <= raw["tvSeconds"] <= 600:
        out["tvSeconds"] = raw["tvSeconds"]
    out["alerts"] = _clean_alerts(raw.get("alerts"))

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

    services = raw.get("services") if isinstance(raw.get("services"), list) else []
    for item in services[:MAX_SERVICES]:
        if not isinstance(item, dict):
            continue
        name, port = _text(item.get("name"), 40), item.get("port")
        if name and isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            out["services"].append({"name": name, "port": port})

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
