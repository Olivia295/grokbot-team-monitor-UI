"""Read-only box adapter for internal mode.

Builds the same ``Cache`` the office, flow and insight views already consume
(roster, sidebar sections, transcripts) from this machine:

- ``roster.md`` names, labels, ids, duties and sidebar groups
- ``agent-data/agents/<id>/profile.json`` ``name`` only, for bots that are not
  on the roster (they show up ungrouped)
- ``agent-data/search-index.db`` ``messages``, opened with a ``mode=ro`` URI
- ``dispatch-log.md`` rows (date | task | bot | status) as Grok Bot → bot edges

There is no structured to/from field. A ``user`` message in bot X whose body,
after leading whitespace is stripped, starts with another roster name inside
the first 30 characters is a handoff from that bot to X. Any other ``user``
message is a request from You; its body is never stored. The next ``assistant``
message in X shares that turn (one relay leg) and its body is never stored.

Willow Mage is included with the other bots, but only as work metadata.
Her rows are read without the body column. A handoff from her is still a
prefix match on her name in another bot's message; the rest of that text is
not kept. Every title or preview that would have been her words, or words
sent to her, is the neutral placeholder.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from backend.grok_cache import Cache
from backend.internal_box import (
    WILLOW_ID,
    WILLOW_NAME,
    BoxConfig,
    BoxError,
    PrivacyError,
    default_config,
    guarded_scandir,
    is_forbidden,
    is_secret_name,
    is_separator_line,
    load_roster,
    next_nonempty,
    read_log,
    split_table_row,
    SYDNEY,
)

PREFIX_WINDOW = 30
TITLE_CHARS = 40
HIDDEN_TITLE = "（内容已隐藏）"
WILLOW_HIDDEN = "（Willow 内容不显示）"
SENSITIVE = ("心情", "情绪", "感受", "难过", "焦虑", "抑郁", "日记", "周记", "mood", "feel", "willow")

# Other bots: the body is required for prefix matching and for their own titles.
_MESSAGE_SQL = """
SELECT agent_id, entry_id, role, timestamp_ms, body, seq
FROM messages
WHERE agent_id NOT IN ({marks})
ORDER BY agent_id, timestamp_ms, COALESCE(seq, 0), entry_id
"""

# Willow: metadata columns only. NULL stands in for the body so callers share one tuple shape.
_WILLOW_SQL = """
SELECT agent_id, entry_id, role, timestamp_ms, NULL, seq
FROM messages
WHERE agent_id IN ({marks})
ORDER BY agent_id, timestamp_ms, COALESCE(seq, 0), entry_id
"""


def sqlite_ro_uri(path: Path) -> str:
    """``file:...?mode=ro`` so SQLite cannot create or write the index."""
    resolved = path.resolve()
    return "file:" + quote(resolved.as_posix(), safe="/:") + "?mode=ro"


def empty_box_cache(support: Path | None = None) -> Cache:
    cache = Cache(support=support or Path("box"))
    cache.box = True
    cache.empty = True
    cache.demo = False
    return cache


def _willow_ids(bots: list[dict]) -> set[str]:
    found = {WILLOW_ID}
    for bot in bots:
        if bot.get("name") == WILLOW_NAME or bot.get("id") == WILLOW_ID:
            if isinstance(bot.get("id"), str) and bot["id"]:
                found.add(bot["id"])
    return found


def _is_willow(agent_id: str | None, name: str | None, willow_ids: set[str]) -> bool:
    return bool((agent_id and agent_id in willow_ids) or name == WILLOW_NAME)


def _boundary_ok(text: str, end: int) -> bool:
    if end >= len(text):
        return True
    ch = text[end]
    return not (ch.isascii() and ch.isalnum())


def leading_bot(body: str, names_longest_first: list[str]) -> str | None:
    """Roster name that the stripped body starts with, inside the first 30 chars."""
    stripped = body.lstrip()
    window = stripped[:PREFIX_WINDOW]
    for name in names_longest_first:
        if not name or len(name) > PREFIX_WINDOW:
            continue
        if window.startswith(name) and _boundary_ok(stripped, len(name)):
            return name
    return None


def is_sensitive(text: str) -> bool:
    folded = text.lower()
    return any(word in folded for word in SENSITIVE)


def task_title(body: str) -> str:
    """Short handoff title. Sensitive text is replaced; nothing longer than 40 chars is kept."""
    if is_sensitive(body):
        return HIDDEN_TITLE
    collapsed = " ".join(body.split())
    return collapsed[:TITLE_CHARS].rstrip()


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(sqlite_ro_uri(path), uri=True)


def load_messages(db_path: Path, willow_ids: set[str]) -> list[tuple]:
    """Read message rows. Willow's query does not select ``body``."""
    if not willow_ids or not db_path.is_file():
        return []
    if db_path.name != "search-index.db":
        return []
    ids = tuple(sorted(willow_ids))
    marks = ",".join("?" for _ in ids)
    other_sql = _MESSAGE_SQL.format(marks=marks)
    willow_sql = _WILLOW_SQL.format(marks=marks)
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return []
    try:
        try:
            rows = list(conn.execute(other_sql, ids))
            rows.extend(conn.execute(willow_sql, ids))
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    rows.sort(key=lambda row: (str(row[0]), int(row[3] or 0), int(row[5] or 0), str(row[1])))
    return rows


def _profile_names(config: BoxConfig, willow_ids: set[str]) -> dict[str, str]:
    """``name`` from each ``profile.json``. No other file in those folders is opened."""
    root = config.agent_data / "agents"
    if is_forbidden(root, config) or not root.is_dir():
        return {}
    found: dict[str, str] = {}
    try:
        children = list(guarded_scandir(root, config))
    except (OSError, PrivacyError):
        return {}
    for entry in children:
        if entry.name in willow_ids:
            continue
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if is_forbidden(entry.path, config):
            continue
        profile = Path(entry.path) / "profile.json"
        if is_forbidden(profile, config) or is_secret_name(profile.name) or profile.name != "profile.json":
            continue
        try:
            payload = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            found[entry.name] = name.strip()
    return found


def _roster_rows(bots: list[dict], extra: dict[str, str]) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Office roster rows, plus name→id and id→name maps.

    Willow's role line is her roster label. The duty column (只做的一件事) is not copied.
    """
    rows: list[dict] = []
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for bot in bots:
        bot_id = str(bot.get("id") or "")
        name = str(bot.get("name") or "")
        if not bot_id or not name:
            continue
        willow = name == WILLOW_NAME or bot_id == WILLOW_ID
        label = str(bot.get("label") or "")
        row = {
            "id": bot_id,
            "name": name,
            "title": label,
            "description": label if willow else str(bot.get("duty") or ""),
            "avatarShape": "",
            "avatarColor": "",
            "createdAt": 0,
            "lastActivityAt": 0,
            "unreadCount": 0,
            "awaitingUserResponse": None,
            "isHiddenFromSidebar": False,
        }
        rows.append(row)
        name_to_id.setdefault(name, bot_id)
        id_to_name[bot_id] = name
    known = set(id_to_name)
    for agent_id, name in sorted(extra.items(), key=lambda item: (item[1], item[0])):
        if agent_id in known or agent_id == WILLOW_ID or name == WILLOW_NAME:
            continue
        rows.append({
            "id": agent_id,
            "name": name,
            "title": "",
            "description": "",
            "avatarShape": "",
            "avatarColor": "",
            "createdAt": 0,
            "lastActivityAt": 0,
            "unreadCount": 0,
            "awaitingUserResponse": None,
            "isHiddenFromSidebar": False,
        })
        id_to_name[agent_id] = name
    return rows, name_to_id, id_to_name


def _sections(groups: list[dict], name_to_id: dict[str, str]) -> list[dict]:
    sections = []
    for index, group in enumerate(groups):
        ids = []
        for member in group.get("members") or []:
            bot_id = name_to_id.get(member)
            if bot_id and bot_id not in ids:
                ids.append(bot_id)
        if not ids:
            continue
        # Sidebar group is her room, the same rule as every other bot.
        sections.append({"id": f"box-room-{index}", "name": group.get("name") or "", "agentIds": ids})
    return sections


def _activity(entry_id: str, at: int, request_id: str) -> dict:
    return {
        "kind": "message",
        "role": "assistant",
        "id": entry_id,
        "timestampMs": at,
        "requestId": request_id,
        "content": "",
        "isStreaming": False,
    }


def _user_entry(entry_id: str, at: int, request_id: str, content: str, sender: tuple[str, str] | None) -> dict:
    entry = {
        "kind": "message",
        "role": "user",
        "id": entry_id,
        "timestampMs": at,
        "requestId": request_id,
        "content": content,
        "isStreaming": False,
    }
    if sender is not None:
        entry["fromAgent"] = {"id": sender[0], "name": sender[1]}
    return entry


def _transcripts(
    messages: list[tuple],
    *,
    name_to_id: dict[str, str],
    id_to_name: dict[str, str],
    names_longest_first: list[str],
    willow_ids: set[str],
) -> dict[str, tuple[list[dict], int]]:
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for agent_id, entry_id, role, timestamp_ms, body, seq in messages:
        if role not in ("user", "assistant"):
            continue
        # Willow rows arrive with a null body. Never substitute the original text.
        text = body if isinstance(body, str) else ""
        grouped[str(agent_id)].append((str(entry_id), role, int(timestamp_ms or 0), text, seq))

    transcripts: dict[str, tuple[list[dict], int]] = {}
    for agent_id, rows in grouped.items():
        if agent_id not in id_to_name:
            # A message for someone with no roster row and no profile name still needs a seat.
            id_to_name[agent_id] = agent_id
        entries: list[dict] = []
        index = 0
        owner_willow = _is_willow(agent_id, id_to_name.get(agent_id), willow_ids)
        while index < len(rows):
            entry_id, role, at, body, _seq = rows[index]
            if role != "user":
                entries.append(_activity(entry_id, at, f"box:{agent_id}:{entry_id}"))
                index += 1
                continue
            # Prefix-match the name only. Willow's own body was never selected.
            sender_name = leading_bot(body, names_longest_first) if body else None
            own_name = id_to_name.get(agent_id, "")
            sender_id = name_to_id.get(sender_name or "")
            reply = rows[index + 1] if index + 1 < len(rows) and rows[index + 1][1] == "assistant" else None
            request_id = f"box:{agent_id}:{entry_id}"
            sender_willow = _is_willow(sender_id, sender_name, willow_ids)
            handoff = bool(sender_name and sender_id and sender_name != own_name)
            if sender_name and not handoff:
                # Starts with this bot's own name: not a You request and not an edge.
                if reply is not None:
                    entries.append(_activity(reply[0], reply[2], request_id))
                    index += 1
                index += 1
                continue
            if handoff:
                # Her words, and anything addressed to her, stay behind the placeholder.
                content = WILLOW_HIDDEN if sender_willow or owner_willow else task_title(body)
                sender = (sender_id, sender_name)
            elif owner_willow:
                content = WILLOW_HIDDEN
                sender = None
            else:
                # You → this bot. Metadata only: time is the timestamp, target is the transcript owner.
                content = ""
                sender = None
            entries.append(_user_entry(entry_id, at, request_id, content, sender))
            if reply is not None:
                entries.append(_activity(reply[0], reply[2], request_id))
                index += 1
            index += 1
        last = max((item["timestampMs"] for item in entries), default=0)
        transcripts[agent_id] = (entries, last)
    return transcripts


def _dispatch_edges(
    config: BoxConfig,
    *,
    name_to_id: dict[str, str],
    willow_ids: set[str],
) -> list[tuple[str, str, int, str]]:
    """``(target_id, title, timestamp_ms, key)`` for each Grok Bot → bot row."""
    grok_id = name_to_id.get("Grok Bot")
    if not grok_id or grok_id in willow_ids:
        return []
    path = config.dispatch_log
    if is_forbidden(path, config):
        return []
    try:
        ready = path.is_file()
    except OSError:
        return []
    if not ready:
        return []
    try:
        text = read_log(path, config)
    except (OSError, PrivacyError, UnicodeError):
        return []
    lines = text.splitlines()
    found: list[tuple[str, str, int, str]] = []
    for index, line in enumerate(lines):
        nxt = next_nonempty(lines, index)
        if nxt is not None and is_separator_line(nxt):
            continue
        cells = split_table_row(line)
        if not cells or len(cells) < 3:
            continue
        date_cell, task, bot_cell = cells[0], cells[1], cells[2]
        if not _looks_like_date(date_cell):
            continue
        target_id = name_to_id.get(bot_cell)
        if not target_id or target_id == grok_id:
            continue
        stamp = _date_ms(date_cell)
        if stamp is None:
            continue
        # Keep rows on the same day in file order without collapsing them.
        stamp += index
        # A dispatch aimed at Willow is a handoff to her: keep the link, hide the task text.
        title = WILLOW_HIDDEN if _is_willow(target_id, bot_cell, willow_ids) else task_title(task)
        found.append((target_id, title, stamp, f"dispatch:{index}:{target_id}"))
    return found


def _looks_like_date(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= 10 and stripped[4:5] == "-" and stripped[:4].isdigit()


def _date_ms(text: str) -> int | None:
    token = text.strip()[:10]
    try:
        stamp = datetime.strptime(token, "%Y-%m-%d").replace(tzinfo=SYDNEY)
    except ValueError:
        return None
    return int(stamp.timestamp() * 1000)


def _apply_dispatch(
    transcripts: dict[str, tuple[list[dict], int]],
    edges: list[tuple[str, str, int, str]],
    grok_id: str,
) -> None:
    for target_id, title, stamp, key in edges:
        entries, mtime = transcripts.get(target_id, ([], 0))
        entries = list(entries)
        entries.append(_user_entry(key, stamp, key, title, (grok_id, "Grok Bot")))
        entries.sort(key=lambda item: (item["timestampMs"], item.get("id") or ""))
        transcripts[target_id] = (entries, max(mtime, stamp))


def _has_records(transcripts: dict[str, tuple[list[dict], int]]) -> bool:
    for entries, _mtime in transcripts.values():
        for entry in entries:
            if entry.get("kind") == "message" and entry.get("role") == "user":
                return True
    return False


def _touch_activity(rows: list[dict], transcripts: dict[str, tuple[list[dict], int]]) -> None:
    for row in rows:
        entries, mtime = transcripts.get(row["id"], ([], 0))
        row["lastActivityAt"] = mtime or max((entry["timestampMs"] for entry in entries), default=0)


def load_box_cache(config: BoxConfig | None = None) -> Cache:
    """Cache for internal mode. Never a demo team. Missing data is an explicit empty cache."""
    config = config if config is not None else default_config()
    try:
        bots, groups = load_roster(config)
    except (OSError, PrivacyError, BoxError, ValueError, UnicodeError):
        return empty_box_cache(config.agent_data)

    willow_ids = _willow_ids(bots)
    try:
        profiles = _profile_names(config, willow_ids)
    except (OSError, PrivacyError):
        profiles = {}
    rows, name_to_id, id_to_name = _roster_rows(bots, profiles)
    names = sorted(name_to_id, key=len, reverse=True)
    db_path = config.agent_data / "search-index.db"
    messages = [] if is_forbidden(db_path, config) else load_messages(db_path, willow_ids)
    transcripts = _transcripts(
        messages,
        name_to_id=name_to_id,
        id_to_name=id_to_name,
        names_longest_first=names,
        willow_ids=willow_ids,
    )
    # Messages can mention an agent that has no profile yet. Give them an ungrouped seat.
    for agent_id, name in list(id_to_name.items()):
        if any(row["id"] == agent_id for row in rows):
            continue
        if agent_id in willow_ids:
            continue
        rows.append({
            "id": agent_id,
            "name": name,
            "title": "",
            "description": "",
            "avatarShape": "",
            "avatarColor": "",
            "createdAt": 0,
            "lastActivityAt": 0,
            "unreadCount": 0,
            "awaitingUserResponse": None,
            "isHiddenFromSidebar": False,
        })
    edges = _dispatch_edges(config, name_to_id=name_to_id, willow_ids=willow_ids)
    grok_id = name_to_id.get("Grok Bot", "")
    if grok_id:
        _apply_dispatch(transcripts, edges, grok_id)
    _touch_activity(rows, transcripts)
    cache = Cache(
        support=config.agent_data,
        roster=rows,
        sections=_sections(groups, name_to_id),
        transcripts=transcripts,
    )
    cache.box = True
    cache.demo = False
    cache.empty = not _has_records(transcripts)
    return cache
