"""Read-only access to the local Grok Bot cache.

The cache lives under ~/Library/Application Support/Grok Bot. Blob file names
are base32 of their key; keys carry a URL-encoded account segment. Nothing here
writes to that directory.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


def support_candidates() -> list[Path]:
    """Where Grok Bot keeps its data on each desktop OS, most likely first."""
    home = Path.home()
    found = [home / "Library" / "Application Support" / "Grok Bot"]
    if os.environ.get("APPDATA"):
        found.append(Path(os.environ["APPDATA"]) / "Grok Bot")
    found.append(home / "AppData" / "Roaming" / "Grok Bot")
    config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    found.append((Path(config) if config else home / ".config") / "Grok Bot")
    return found


def default_support_dir(override: str = "") -> Path:
    override = override.strip() or os.environ.get("GROK_BOT_SUPPORT", "").strip()
    if override:
        return Path(override).expanduser()
    candidates = support_candidates()
    return next((path for path in candidates if (path / "sand-client-persistence").is_dir()), candidates[0])


def decode_blob_name(filename: str) -> str:
    raw = filename[: -len(".blob")].upper()
    pad = "=" * ((8 - len(raw) % 8) % 8)
    return base64.b32decode(raw + pad).decode("utf-8")


def encode_blob_name(key: str) -> str:
    return base64.b32encode(key.encode("utf-8")).decode("ascii").rstrip("=").lower() + ".blob"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _value(payload):
    if not isinstance(payload, dict):
        return None
    return payload.get("value", payload)


@dataclass
class Cache:
    support: Path
    account: str = ""
    roster: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    pinned: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    demo: bool = False
    source: str = "grok"  # grok | demo | events | box
    online: bool | None = None  # None: ask the Grok Bot desktop app
    # Box adapter (internal mode). `empty` means the roster may exist but there
    # is no collaboration record to show, so the page must not invent a demo team.
    box: bool = False
    empty: bool = False
    transcripts: dict[str, tuple[list[dict], int]] = field(default_factory=dict)

    def transcript(self, agent_id: str) -> tuple[list[dict], int]:
        return self.transcripts.get(agent_id, ([], 0))


def _blobs(persist_dir: Path) -> list[tuple[str, Path, dict]]:
    found = []
    if not persist_dir.is_dir():
        return found
    for path in persist_dir.glob("*.blob"):
        try:
            key = decode_blob_name(path.name)
        except (ValueError, UnicodeError):
            continue
        payload = _read_json(path)
        if isinstance(payload, dict):
            found.append((key, path, payload))
    return found


def _account_token(blobs) -> str:
    for key, _path, payload in blobs:
        if key.endswith("client-meta.account-slot"):
            value = payload.get("value")
            if isinstance(value, str) and value:
                return quote(value, safe="")
    counts: dict[str, int] = {}
    marker = ".account."
    for key, _path, _payload in blobs:
        start = key.find(marker)
        if start < 0:
            continue
        token = key[start + len(marker):].split(".", 1)[0]
        if token:
            counts[token] = counts.get(token, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def load_cache(support: Path | None = None) -> Cache:
    support = support or default_support_dir()
    blobs = _blobs(support / "sand-client-persistence")
    cache = Cache(support=support, account=_account_token(blobs))
    scoped = f".account.{cache.account}." if cache.account else ""
    for key, path, payload in blobs:
        if scoped and ".account." in key and scoped not in key:
            continue
        value = _value(payload)
        if not isinstance(value, dict):
            continue
        if key.endswith("roster.last-roster"):
            rows = value.get("rows")
            if isinstance(rows, list):
                cache.roster = [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
        elif key.endswith("sidebar.last-sections"):
            sections = value.get("sections")
            if isinstance(sections, list):
                cache.sections = [item for item in sections if isinstance(item, dict)]
        elif key.endswith("ui-agent-refs"):
            ids = value.get("pinnedAgentIds")
            if isinstance(ids, list):
                cache.pinned = [item for item in ids if isinstance(item, str)]
        elif key.endswith("weekly-usage.cache"):
            reading = value.get("reading") if isinstance(value.get("reading"), dict) else {}
            usage = reading.get("usage") if isinstance(reading.get("usage"), dict) else {}
            percent = usage.get("percentUsed")
            if isinstance(percent, (int, float)):
                cache.usage = {
                    "percentUsed": float(percent),
                    "nextResetMs": int(usage.get("nextResetMs") or 0),
                    "plan": str(usage.get("grokPlanLabel") or ""),
                }
        elif ".transcript.replicas." in key:
            agent_id = key.rsplit("transcript.replicas.", 1)[1]
            entries = value.get("entries")
            entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
            try:
                mtime_ms = int(path.stat().st_mtime * 1000)
            except OSError:
                mtime_ms = 0
            cache.transcripts[agent_id] = (entries, mtime_ms)
    return cache


def app_online(support: Path, now_ms: int) -> bool:
    status = _read_json(support / "desktop-status.json")
    if not isinstance(status, dict):
        return False
    pid = status.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    started = status.get("startedAtMs")
    return not (isinstance(started, (int, float)) and started > now_ms + 60_000)
