"""Read-only box adapter for internal mode.

Builds the same ``Cache`` the office, flow and insight views already consume
(roster, sidebar sections, transcripts) from this machine:

- ``roster.md`` names, labels, ids, duties and sidebar groups
- ``agent-data/agents/<id>/profile.json`` name, title and avatar (never the
  description, which holds the bot's instructions); bots not on the roster show up ungrouped
- ``roster.md``'s 旧名对照 table, so old names still match, and the folder of the
  bot that keeps ``dispatch-log.md`` (the dispatcher)
- ``agent-data/search-index.db`` ``messages``, opened with a ``mode=ro`` URI
- ``dispatch-log.md`` rows (date | task | bot | status) as Grok Bot → bot edges

There is no structured to/from field. A ``user`` message in bot X is a handoff when
- its body starts with another roster name (or an old name from the roster's
  旧名对照 table) inside the first 30 characters: from that bot, or
- it is written in the dispatcher's format, with 「她的原话」 / 「我的理解」
  sections: from the dispatcher (the bot that keeps dispatch-log.md).
A handoff's title only ever comes from 「我的理解」; 「她的原话」 is your own words
and is never kept. Any other ``user`` message is a request from You; its body is
never stored. The next ``assistant`` message in X shares that turn (one relay leg)
and its body is never stored.

Willow Mage is included with the other bots, but only as work metadata.
Her rows are read without the body column. A handoff from her is still a
prefix match on her name in another bot's message; the rest of that text is
not kept. Every title or preview that would have been her words, or words
sent to her, is the neutral placeholder.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .grok_cache import Cache
from .internal_box import (
    WILLOW_ID,
    WILLOW_NAME,
    BoxConfig,
    BoxError,
    PrivacyError,
    default_config,
    is_forbidden,
    is_separator_line,
    next_nonempty,
    read_log,
    split_table_row,
    connect_ro,
    find_dispatcher,
    empty_extras,
    load_bots,
    load_extras,
    read_profiles,
    resolve_folders,
)

PREFIX_WINDOW = 30
TITLE_CHARS = 40
HIDDEN_TITLE = "（内容已隐藏）"
WILLOW_HIDDEN = "（Willow 内容不显示）"
PRIVATE_HIDDEN = "（私密内容不显示）"  # other bots the roster marks private
SENSITIVE = ("心情", "情绪", "感受", "难过", "焦虑", "抑郁", "日记", "周记", "mood", "feel", "willow")

YOUR_TURN_MS = 12 * 3600 * 1000
PENDING_MS = 10 * 60 * 1000

# Other bots: the body is required for prefix matching and for their own titles.
# {main} is in_main_chat when the index has it (1 = the bot's main chat with you).
_MESSAGE_SQL = """
SELECT agent_id, entry_id, role, timestamp_ms, body, seq, {main}
FROM messages
WHERE agent_id NOT IN ({marks})
ORDER BY agent_id, timestamp_ms, COALESCE(seq, 0), entry_id
"""

# Willow: metadata columns only. NULL stands in for the body so callers share one tuple shape.
_WILLOW_SQL = """
SELECT agent_id, entry_id, role, timestamp_ms, NULL, seq, {main}
FROM messages
WHERE agent_id IN ({marks})
ORDER BY agent_id, timestamp_ms, COALESCE(seq, 0), entry_id
"""

# The dispatcher writes 「她的原话」 then 「我的理解」, in brackets, bold or as headings.
def _section(word: str) -> re.Pattern[str]:
    return re.compile(r"(?:【|\[|\*\*|#{1,6}\s*)?\s*(?:" + word + r")\s*(?:】|\]|\*\*)?\s*[:：]?")


# 「她的原话」 in the original box; other people write 他的原话 / 原话 / Original request.
ORIGINAL_RE = _section(r"(?:(?:她|他|TA|用户)的)?原话|原始需求|(?i:original request|their words)")
UNDERSTANDING_RE = _section(r"我的理解|(?i:my understanding)")
_messages_memo: dict[tuple, list[tuple]] = {}


def sqlite_ro_uri(path: Path) -> str:
    """``file:...?mode=ro`` so SQLite cannot create or write the index."""
    resolved = path.resolve()
    return "file:" + quote(resolved.as_posix(), safe="/:") + "?mode=ro"


def empty_box_cache(support: Path | None = None) -> Cache:
    cache = Cache(support=support or Path("box"))
    cache.source = "box"
    cache.box = True
    cache.empty = True
    cache.demo = False
    return cache


def _willow_ids(bots: list[dict], private: set[str] | frozenset = frozenset()) -> set[str]:
    """Ids of private bots (metadata only): Willow Mage, plus any bot roster.md marks private."""
    found = {WILLOW_ID}
    for bot in bots:
        if bot.get("name") == WILLOW_NAME or bot.get("id") == WILLOW_ID or bot.get("name") in private:
            if isinstance(bot.get("id"), str) and bot["id"]:
                found.add(bot["id"])
    return found


def _placeholder(*ids_and_names: str | None) -> str:
    """Willow keeps her own placeholder; any other private bot gets the generic one."""
    return WILLOW_HIDDEN if WILLOW_ID in ids_and_names or WILLOW_NAME in ids_and_names else PRIVATE_HIDDEN


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


def dispatch_sections(body: str) -> tuple[bool, str | None]:
    """(written in the dispatch format, the 「我的理解」 part). 「她的原话」 is never returned."""
    original = ORIGINAL_RE.search(body)
    understanding = UNDERSTANDING_RE.search(body)
    if not original and not understanding:
        return False, None
    if not understanding:
        return True, None
    end = original.start() if original and original.start() > understanding.end() else len(body)
    return True, body[understanding.end():end].strip() or None


def handoff_title(body: str) -> str:
    """The title of a handoff. In the dispatch format only 「我的理解」 counts."""
    is_dispatch, understanding = dispatch_sections(body)
    if is_dispatch:
        return task_title(understanding) if understanding else HIDDEN_TITLE
    return task_title(body)


def _connect_ro(path: Path) -> sqlite3.Connection:
    return connect_ro(path)


def _db_signature(db_path: Path) -> tuple:
    """Changes whenever the index changes. New rows land in the -wal file first, so it counts too."""
    parts = []
    for suffix in ("", "-wal"):
        try:
            stat = os.stat(str(db_path) + suffix)
            parts.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def load_messages(db_path: Path, willow_ids: set[str]) -> list[tuple]:
    """Read message rows. Willow's query does not select ``body``.

    Rows are (agent_id, entry_id, role, timestamp_ms, body, seq, in_main_chat). The result is
    kept until the index (or its -wal file) changes, so polling pages don't re-read it.
    """
    if not willow_ids or not db_path.is_file():
        return []
    if db_path.name != "search-index.db":
        return []
    ids = tuple(sorted(willow_ids))
    key = (os.path.abspath(db_path), ids, _db_signature(db_path))
    if key in _messages_memo:
        return list(_messages_memo[key])
    marks = ",".join("?" for _ in ids)
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return []
    try:
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            main = "in_main_chat" if "in_main_chat" in columns else "1"
            rows = list(conn.execute(_MESSAGE_SQL.format(marks=marks, main=main), ids))
            rows.extend(conn.execute(_WILLOW_SQL.format(marks=marks, main=main), ids))
        except sqlite3.Error:
            return []
    finally:
        conn.close()
    rows.sort(key=lambda row: (str(row[0]), int(row[3] or 0), int(row[5] or 0), str(row[1])))
    _messages_memo.clear()
    _messages_memo[key] = rows
    return list(rows)


def _profile_names(config: BoxConfig, willow_ids: set[str]) -> dict[str, str]:
    """``name`` from each ``profile.json``. No other file in those folders is opened."""
    return {agent_id: fields["name"] for agent_id, fields in read_profiles(config, willow_ids).items()}


def _roster_rows(bots: list[dict], extra: dict[str, dict],
                 private: set[str] | frozenset = frozenset()) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Office roster rows, plus name→id and id→name maps.

    Willow's role line is her roster label. The duty column (只做的一件事) is not copied.
    Avatars and titles come from each bot's profile.json when it has them.
    """
    rows: list[dict] = []
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for bot in bots:
        bot_id = str(bot.get("id") or "")
        name = str(bot.get("name") or "")
        if not bot_id or not name:
            continue
        willow = name == WILLOW_NAME or bot_id == WILLOW_ID or name in private
        label = str(bot.get("label") or "")
        profile = extra.get(bot_id, {})
        row = {
            "id": bot_id,
            "name": name,
            "title": label or profile.get("title", ""),
            "description": label if willow else str(bot.get("duty") or ""),
            "avatarShape": profile.get("avatarShape", ""),
            "avatarColor": profile.get("avatarColor", ""),
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
    for agent_id, profile in sorted(extra.items(), key=lambda item: (item[1]["name"], item[0])):
        name = profile["name"]
        if agent_id in known or agent_id == WILLOW_ID or name == WILLOW_NAME:
            continue
        rows.append({
            "id": agent_id,
            "name": name,
            "title": profile.get("title", ""),
            "description": "",
            "avatarShape": profile.get("avatarShape", ""),
            "avatarColor": profile.get("avatarColor", ""),
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
    aliases: dict[str, str] | None = None,
    dispatcher: str = "",
) -> dict[str, tuple[list[dict], int]]:
    aliases = aliases or {}
    dispatcher_id = name_to_id.get(dispatcher, "")
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for agent_id, entry_id, role, timestamp_ms, body, seq, *_main in messages:
        if role not in ("user", "assistant"):
            continue
        # Willow rows arrive with a null body. Never substitute the original text.
        text = body if isinstance(body, str) else ""
        grouped[str(agent_id)].append((str(entry_id), role, int(timestamp_ms or 0), text, seq))

    transcripts: dict[str, tuple[list[dict], int]] = {}
    for agent_id, rows in grouped.items():
        if agent_id not in id_to_name:
            # A message for someone with no roster row and no profile name still needs a seat.
            id_to_name[agent_id] = WILLOW_NAME if agent_id == WILLOW_ID else agent_id
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
            sender_name = aliases.get(sender_name, sender_name) if sender_name else None
            if not sender_name and body and dispatcher_id and agent_id != dispatcher_id and dispatch_sections(body)[0]:
                sender_name = dispatcher
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
                content = (_placeholder(sender_id, sender_name, agent_id, own_name)
                           if sender_willow or owner_willow else handoff_title(body))
                sender = (sender_id, sender_name)
            elif owner_willow:
                content = _placeholder(agent_id, own_name)
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
    dispatcher: str = "Grok Bot",
    path: Path | None = None,
    aliases: dict[str, str] | None = None,
) -> list[tuple[str, str, int, str]]:
    """``(target_id, title, timestamp_ms, key)`` for each dispatcher → bot row."""
    aliases = aliases or {}
    grok_id = name_to_id.get(dispatcher)
    if not grok_id or grok_id in willow_ids:
        return []
    path = path or config.dispatch_log
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
        bot_cell = aliases.get(bot_cell, bot_cell)
        target_id = name_to_id.get(bot_cell)
        if not target_id or target_id == grok_id:
            continue
        stamp = _date_ms(date_cell)
        if stamp is None:
            continue
        # Keep rows on the same day in file order without collapsing them.
        stamp += index
        # A dispatch aimed at Willow is a handoff to her: keep the link, hide the task text.
        title = _placeholder(target_id, bot_cell) if _is_willow(target_id, bot_cell, willow_ids) else task_title(task)
        found.append((target_id, title, stamp, f"dispatch:{index}:{target_id}"))
    return found


def _looks_like_date(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= 10 and stripped[4:5] == "-" and stripped[:4].isdigit()


def _date_ms(text: str) -> int | None:
    token = text.strip()[:10]
    try:
        stamp = datetime.strptime(token, "%Y-%m-%d")  # local midnight on the box's own clock
    except ValueError:
        return None
    return int(stamp.timestamp() * 1000)


def _apply_dispatch(
    transcripts: dict[str, tuple[list[dict], int]],
    edges: list[tuple[str, str, int, str]],
    grok_id: str,
    dispatcher: str = "Grok Bot",
) -> None:
    for target_id, title, stamp, key in edges:
        entries, mtime = transcripts.get(target_id, ([], 0))
        entries = list(entries)
        entries.append(_user_entry(key, stamp, key, title, (grok_id, dispatcher)))
        entries.sort(key=lambda item: (item["timestampMs"], item.get("id") or ""))
        transcripts[target_id] = (entries, max(mtime, stamp))


def _has_records(transcripts: dict[str, tuple[list[dict], int]]) -> bool:
    for entries, _mtime in transcripts.values():
        for entry in entries:
            if entry.get("kind") == "message" and entry.get("role") == "user":
                return True
    return False


def status_hints(messages: list[tuple], now_ms: int) -> dict[str, str]:
    """What the message timeline says when nothing else is recorded on the box.

    "yourturn": the bot's last message is its reply in your main chat (within 12 hours).
    "pending":  the bot got a message and hasn't answered for more than 10 minutes (within 12 hours).
    """
    last: dict[str, tuple] = {}
    for row in messages:
        last[str(row[0])] = row
    hints: dict[str, str] = {}
    for agent_id, row in last.items():
        role, stamp = row[2], int(row[3] or 0)
        main = row[6] if len(row) > 6 else 1
        age = now_ms - stamp
        if role == "assistant" and main == 1 and 0 <= age <= YOUR_TURN_MS:
            hints[agent_id] = "yourturn"
        elif role == "user" and PENDING_MS < age <= YOUR_TURN_MS:
            hints[agent_id] = "pending"
    return hints


def _transcript_activity(config: BoxConfig, agent_id: str) -> int:
    """Newest change in agent-transcripts/<id> (names and times only, nothing is opened)."""
    folder = config.agent_data / "agent-transcripts" / agent_id
    if is_forbidden(folder, config):
        return 0
    try:
        return int(max((entry.stat().st_mtime for entry in os.scandir(folder)), default=0) * 1000)
    except OSError:
        return 0


def _touch_activity(rows: list[dict], transcripts: dict[str, tuple[list[dict], int]]) -> None:
    for row in rows:
        entries, mtime = transcripts.get(row["id"], ([], 0))
        row["lastActivityAt"] = mtime or max((entry["timestampMs"] for entry in entries), default=0)


def load_box_cache(config: BoxConfig | None = None) -> Cache:
    """Cache for internal mode. Never a demo team. Missing data is an explicit empty cache."""
    config = config if config is not None else default_config()
    try:
        bots, groups, roster_source = load_bots(config)
    except (OSError, PrivacyError, BoxError, ValueError, UnicodeError):
        return empty_box_cache(config.agent_data)

    extras = load_extras(config, [bot["name"] for bot in bots]) if roster_source == "roster" else empty_extras()
    private = set(extras["private"])
    willow_ids = _willow_ids(bots, private)
    try:
        profiles = read_profiles(config, willow_ids)
    except (OSError, PrivacyError):
        profiles = {}
    rows, name_to_id, id_to_name = _roster_rows(bots, profiles, private)
    aliases = {old: new for old, new in extras["aliases"].items() if new in name_to_id}
    resolve_folders(config, bots, extras)
    dispatcher, dispatch_path = find_dispatcher(config, bots)
    names = sorted(list(name_to_id) + list(aliases), key=len, reverse=True)
    db_path = config.agent_data / "search-index.db"
    messages = [] if is_forbidden(db_path, config) else load_messages(db_path, willow_ids)
    transcripts = _transcripts(
        messages,
        name_to_id=name_to_id,
        id_to_name=id_to_name,
        names_longest_first=names,
        willow_ids=willow_ids,
        aliases=aliases,
        dispatcher=dispatcher,
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
    edges = _dispatch_edges(config, name_to_id=name_to_id, willow_ids=willow_ids,
                            dispatcher=dispatcher, path=dispatch_path, aliases=aliases)
    grok_id = name_to_id.get(dispatcher, "")
    if grok_id:
        _apply_dispatch(transcripts, edges, grok_id, dispatcher)
    # A transcript folder that just changed means the bot is working right now.
    for agent_id, (entries, mtime) in list(transcripts.items()):
        if agent_id not in willow_ids:
            transcripts[agent_id] = (entries, max(mtime, _transcript_activity(config, agent_id)))
    _touch_activity(rows, transcripts)
    hints = status_hints(messages, int(time.time() * 1000))
    for row in rows:
        if hints.get(row["id"]):
            row["statusHint"] = hints[row["id"]]
    cache = Cache(
        support=config.agent_data,
        roster=rows,
        sections=_sections(groups, name_to_id),
        transcripts=transcripts,
    )
    cache.source = "box"
    cache.box = True
    cache.demo = False
    cache.empty = not _has_records(transcripts)
    cache.roster_missing = roster_source != "roster"
    return cache
