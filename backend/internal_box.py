"""Read-only view of the local Grok Bot box (roster + bot folders).

Ported from the bot-dashboard collector. Standard library only. This module
never writes, and it never lists or reads:

- an ``inbox``, ``snapshots`` or ``raw`` folder inside any bot folder (including through symlinks)
- ``~/.codex`` and ``~/.grok``
- files whose names look like credentials (see ``is_secret_name``), and any agent ``store.db``
- filenames containing 周记 or 日记
- any non-markdown file, when the caller wants log text

Bot folders, extra log files, old names and the push schedule come from
``roster.md`` itself (with a name-based fallback), so no bot names live in code
apart from the privacy rule for Willow Mage.

Willow Mage is included like the other bots for work metadata only. Her
status comes from ``search-index.db`` timestamps (never her files). Message
bodies are not selected. Her roster duty text is not published.

Paths are not fixed. ``make_config`` points the same rules at a temp workspace
so tests never touch the real box. ``os.scandir`` is not replaced process-wide;
only this module's ``guarded_scandir`` refuses a forbidden directory. The
external cache reader stays unchanged.

Morning Bridge ``log.md`` lines look like ``2026-10-21 | ...`` with no leading
``|``, ``- `` or ``## ``. Those date lines are task entries too.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# Times follow the box's own clock and timezone (the box is set to Sydney time).
# SYDNEY is the old name, kept for callers; conversions below use the local zone per instant.
LOCAL_TZ = datetime.now().astimezone().tzinfo
SYDNEY = LOCAL_TZ

WINDOW_DAYS = 7
TASK_LIMIT = 5
TASK_CHARS = 160
ENV_OVERRIDE = "BOT_OFFICE_INTERNAL"
WILLOW_NAME = "Willow Mage"
WILLOW_ID = "0aae13ef-b790-4061-a6e8-1dc6d5e45803"
# Older name for the same bot. She is no longer dropped from the office.
UNMONITORED = WILLOW_NAME
USAGE_NOTE = "无真实限额/用量数据"
ESTIMATE_LABEL = "估算：按最近7天日志条目数与文件改动数，不是真实额度消耗"

DEFAULT_WORKSPACE = Path("/workspace")
DEFAULT_ROSTER = Path("/workspace/roster.md")
DEFAULT_AGENT_DATA = Path("/home/box/agent-data")
DEFAULT_DISPATCHER = "Grok Bot"  # the platform's own lead bot; the one that writes dispatch-log.md wins

LOG_NAMES = ("log.md", "dispatch-log.md", "evolution-log.md")
# Any other "<something>-log.md" in a bot folder is a log too (news-log.md, reforge-log.md, …).
LOG_FILE_RE = re.compile(r"^[\w.\-]*(?:^|[-_.])log\.md$", re.I)
PRIVATE_CHILD_NAMES = ("inbox", "snapshots", "raw")
# Never opened, whatever the folder: credentials, browser cookies, and each agent's full store.
SECRET_NAME_RE = re.compile(r"token|secret|cookie|credential|password|passwd|private[-_]?key|id_rsa|id_ed25519", re.I)
NEVER_OPEN = {"auth.json", "store.db", "store.db-wal", "store.db-shm"}

# 7-day line counter: dates written as YYYY-MM-DD (any year, so it keeps working after 2026).
DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
# A task line may begin with any YYYY-MM-DD (Morning Bridge does this).
DATE_ENTRY_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?!\d)")
SEPARATOR_CELL_RE = re.compile(r":?-{1,}:?")
HEADING_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class PrivacyError(RuntimeError):
    pass


class BoxError(RuntimeError):
    pass


class BoxConfig:
    """Every filesystem root the collector used, so tests can redirect them."""

    def __init__(
        self,
        roster_path: Path,
        agent_data: Path,
        folder_map: dict[str, Path],
        forbidden_dirs: tuple[str, ...],
        skip_child_names: dict[str, set[str]],
        dispatch_log: Path,
        workspace: Path | None = None,
    ) -> None:
        self.roster_path = Path(roster_path)
        self.agent_data = Path(agent_data)
        # Explicit folders (tests, overrides). Everything else is resolved from the roster.
        self.folder_map = {name: Path(path) for name, path in folder_map.items()}
        self.forbidden_dirs = tuple(forbidden_dirs)
        self.skip_child_names = {key: set(names) for key, names in skip_child_names.items()}
        self.dispatch_log = Path(dispatch_log)
        self.workspace = Path(workspace) if workspace is not None else self.roster_path.parent
        self.resolved_folders: dict[str, Path] = {}
        self.extra_logs: set[str] = set()


def _forbid_roots(paths: tuple[Path, ...] | list[Path]) -> tuple[str, ...]:
    roots: list[str] = []
    for path in paths:
        raw = os.path.abspath(path)
        if raw not in roots:
            roots.append(raw)
        try:
            real = os.path.realpath(raw)
        except OSError:
            continue
        if real not in roots:
            roots.append(real)
    return tuple(roots)


def make_config(
    workspace: Path | str,
    *,
    roster: Path | str,
    agent_data: Path | str,
    home: Path | str,
    extra_folders: dict[str, Path | str] | None = None,
) -> BoxConfig:
    """Build a config rooted at ``workspace``.

    ``roster``, ``agent_data`` and ``home`` are independent of the workspace so
    a test can place the roster beside a fake ``~/.codex`` without nesting them
    inside a bot folder. ``extra_folders`` adds or replaces folder-map entries.
    A path set for Willow Mage is kept on the map and never opened.
    """
    workspace = Path(workspace)
    home = Path(home)
    folder_map: dict[str, Path] = {name: Path(path) for name, path in (extra_folders or {}).items()}
    # Private folders are closed in every bot folder, not just the ones we know about.
    roots: list[Path] = [home / ".codex", home / ".grok"]
    skip: dict[str, set[str]] = {}
    folders = list(folder_map.values())
    try:
        folders += [child for child in workspace.iterdir() if child.is_dir()]
    except OSError:
        pass
    for folder in folders:
        roots += [folder / name for name in PRIVATE_CHILD_NAMES]
        skip[os.path.abspath(folder)] = set(PRIVATE_CHILD_NAMES)
    return BoxConfig(
        roster_path=Path(roster),
        agent_data=Path(agent_data),
        folder_map=folder_map,
        forbidden_dirs=_forbid_roots(roots),
        skip_child_names=skip,
        dispatch_log=workspace / slugify(DEFAULT_DISPATCHER) / "dispatch-log.md",
        workspace=workspace,
    )


def slugify(name: str) -> str:
    """Folder name for a bot: "Spaceship Co-Pilot" → "spaceship-copilot"."""
    words = [re.sub(r"[^a-z0-9]", "", word) for word in name.lower().split()]
    return "-".join(word for word in words if word)


def default_config() -> BoxConfig:
    return make_config(
        DEFAULT_WORKSPACE,
        roster=DEFAULT_ROSTER,
        agent_data=DEFAULT_AGENT_DATA,
        home=Path.home(),
    )


def mode_status(config: BoxConfig | None = None) -> dict:
    """Whether internal reading is allowed.

    ``BOT_OFFICE_INTERNAL=0`` forces it off and ``=1`` forces it on. Otherwise
    both the roster file and the agent-data directory must exist. A symlink to
    a directory counts (``Path.is_dir`` follows links).
    """
    raw = os.environ.get(ENV_OVERRIDE)
    if raw is not None and raw.strip() == "0":
        return {"internal_available": False, "reason": "BOT_OFFICE_INTERNAL=0"}
    if raw is not None and raw.strip() == "1":
        return {"internal_available": True, "reason": "BOT_OFFICE_INTERNAL=1"}
    cfg = config if config is not None else default_config()
    roster_ok = cfg.roster_path.is_file()
    agent_ok = cfg.agent_data.is_dir()
    bots_ok = agent_ok and ((cfg.agent_data / "search-index.db").is_file() or (cfg.agent_data / "agents").is_dir())
    if roster_ok and agent_ok:
        return {"internal_available": True, "reason": "roster.md and agent-data present", "roster": True}
    if bots_ok:
        # roster.md is optional: without it, bots come from their profile.json files.
        return {"internal_available": True, "reason": "agent-data present; roster.md missing, reading bot profiles", "roster": False}
    parts: list[str] = []
    if not roster_ok:
        parts.append("roster.md missing")
    if not agent_ok:
        parts.append("agent-data is not a directory")
    elif not bots_ok:
        parts.append("agent-data has no bots yet")
    return {"internal_available": False, "reason": "; ".join(parts)}


def _abspath(path: str | Path) -> str:
    return os.path.abspath(os.fspath(path))


def _is_under(path: str, root: str) -> bool:
    path = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root + os.sep)


def _private_part(path: str, workspace: str) -> bool:
    """An inbox / snapshots / raw folder anywhere under the workspace."""
    if not _is_under(path, workspace):
        return False
    rel = os.path.relpath(path, workspace)
    return any(part in PRIVATE_CHILD_NAMES for part in Path(rel).parts)


def is_forbidden(path: str | Path, config: BoxConfig) -> bool:
    """True if ``path`` or its symlink target sits in a directory we must not touch."""
    raw = _abspath(path)
    workspace = _abspath(config.workspace)
    for root in config.forbidden_dirs:
        if _is_under(raw, root):
            return True
    if _private_part(raw, workspace):
        return True
    try:
        real = os.path.realpath(raw)
    except OSError:
        return False
    for root in config.forbidden_dirs:
        if _is_under(real, root):
            return True
    return _private_part(real, os.path.realpath(workspace))


def guarded_scandir(path: str | Path, config: BoxConfig):
    """List a directory, or refuse if it is forbidden. Does not patch ``os.scandir``."""
    if is_forbidden(path, config):
        raise PrivacyError(f"refusing to list {path}")
    return os.scandir(path)


def is_secret_name(name: str) -> bool:
    """Credentials, cookies, keys and agent stores: never opened (their mtime may still count)."""
    low = name.lower()
    if low in NEVER_OPEN or low.endswith((".env", ".pem", ".key", ".p12")):
        return True
    return bool(SECRET_NAME_RE.search(low))


def is_skipped_name(name: str) -> bool:
    """Files we neither read nor count."""
    return "周记" in name or "日记" in name


def assert_readable_log(path: Path, config: BoxConfig) -> None:
    if is_forbidden(path, config):
        raise PrivacyError(f"refusing forbidden path: {path}")
    name = path.name
    if is_skipped_name(name) or is_secret_name(name):
        raise PrivacyError(f"refusing sensitive name: {name}")
    if path.suffix.lower() != ".md":
        raise PrivacyError(f"refusing non-md read: {path}")
    if name not in LOG_NAMES and not LOG_FILE_RE.match(name) and os.path.abspath(path) not in config.extra_logs:
        raise PrivacyError(f"refusing non-log read: {path}")
    parent = path.parent.resolve()
    allowed = {item.resolve() for item in list(config.folder_map.values()) + list(config.resolved_folders.values())}
    if parent not in allowed:
        raise PrivacyError(f"refusing log outside a bot root: {path}")


def read_log(path: Path, config: BoxConfig) -> str:
    assert_readable_log(path, config)
    return path.read_text(encoding="utf-8", errors="replace")


def read_roster(config: BoxConfig) -> str:
    path = config.roster_path
    if is_forbidden(path, config) or is_skipped_name(path.name) or is_secret_name(path.name):
        raise PrivacyError("roster path is not readable under privacy rules")
    if path.suffix.lower() != ".md":
        raise PrivacyError("roster is not markdown")
    return path.read_text(encoding="utf-8", errors="replace")


def parse_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        body = stripped.strip("|")
        cells = [cell.strip() for cell in body.split("|")]
        if cells and all(SEPARATOR_CELL_RE.fullmatch(cell or "") for cell in cells):
            continue
        if cells and all(cell == "" for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return []
    return rows[1:]


def extract_table_after(text: str, heading: str) -> list[list[str]]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        raise BoxError(f"roster is missing heading: {heading}")
    table: list[str] = []
    begun = False
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if line.strip().startswith("|"):
            begun = True
            table.append(line)
        elif begun:
            break
    data = parse_table(table)
    if not data:
        raise BoxError(f"roster table under {heading} is empty")
    return data


# Section headings in roster.md, Chinese or English (see box/roster.template*.md).
BOTS_HEADING = re.compile(r"名单|\broster\b|\bbots\b", re.I)
GROUPS_HEADING = re.compile(r"侧栏分组|分组|sidebar|groups?", re.I)
COLUMNS = {
    "name": re.compile(r"名字|名称|^name$|bot", re.I),
    "label": re.compile(r"标签|头衔|label|title", re.I),
    "id": re.compile(r"^id$|agent.?id", re.I),
    "duty": re.compile(r"只做|职责|做什么|duty|job|does", re.I),
    "trigger": re.compile(r"触发|trigger|how", re.I),
}


def _table_for(text: str, heading: re.Pattern[str], exact: str):
    """Rows of the table under ``exact`` heading, else under the first heading matching ``heading``."""
    tables = roster_tables(text)
    for wanted in (lambda h: h.strip() == exact, lambda h: bool(heading.search(h))):
        for title, header, rows in tables:
            if wanted(title) and rows:
                return header, rows
    raise BoxError(f"roster is missing a table under: {exact}")


def load_roster(config: BoxConfig) -> tuple[list[dict], list[dict]]:
    text = read_roster(config)
    header, bot_rows = _table_for(text, BOTS_HEADING, "## 一、名单")
    columns = {key: next((i for i, h in enumerate(header) if pattern.search(h)), None) for key, pattern in COLUMNS.items()}
    # Positional fallback: name | label | id | duty | trigger.
    for index, key in enumerate(("name", "label", "id", "duty", "trigger")):
        if columns[key] is None and index < len(header) and index not in columns.values():
            columns[key] = index
    bots: list[dict] = []
    for cells in bot_rows:
        cell = lambda key: cells[columns[key]] if columns[key] is not None and columns[key] < len(cells) else ""
        if not cell("name") or not cell("id"):
            continue
        bots.append({"name": cell("name"), "label": cell("label"), "id": cell("id"),
                     "duty": cell("duty"), "trigger": cell("trigger")})
    if not bots:
        raise BoxError("no bots parsed from roster")

    try:
        _header, group_rows = _table_for(text, GROUPS_HEADING, "### 侧栏分组")
    except BoxError:
        group_rows = []
    groups: list[dict] = []
    group_of: dict[str, str] = {}
    for cells in group_rows:
        if len(cells) < 2:
            continue
        name = cells[0]
        members = [part.strip() for part in re.split(r"[、,，]", cells[1]) if part.strip()]
        groups.append({"name": name, "members": members})
        for member in members:
            group_of[member] = name
    for bot in bots:
        bot["group"] = group_of.get(bot["name"], "")
    return bots, groups


def load_bots(config: BoxConfig) -> tuple[list[dict], list[dict], str]:
    """(bots, groups, where they came from). roster.md first; without it, every bot's profile.json."""
    try:
        bots, groups = load_roster(config)
        return bots, groups, "roster"
    except (OSError, PrivacyError, BoxError, UnicodeError, ValueError):
        pass
    profiles = read_profiles(config, {WILLOW_ID})
    bots = [{"name": fields["name"], "label": fields.get("title", ""), "id": agent_id, "duty": "", "trigger": "", "group": ""}
            for agent_id, fields in sorted(profiles.items(), key=lambda item: item[1]["name"].lower())]
    if not bots:
        raise BoxError("no roster.md and no agent profiles")
    return bots, [], "profiles"


def is_separator_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells:
        return False
    return all(SEPARATOR_CELL_RE.fullmatch(cell or "") for cell in cells)


def next_nonempty(lines: list[str], index: int) -> str | None:
    for line in lines[index + 1 :]:
        if line.strip():
            return line
    return None


def extract_entries(text: str) -> list[str]:
    """Entry lines: table rows (not header/separator), '- ' items, '## ' date headings.

    Also a line whose text begins with ``YYYY-MM-DD``. Morning Bridge writes
    ``2026-10-21 | ...`` with no leading ``|``, ``- `` or ``## ``.
    """
    lines = text.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("|"):
            if is_separator_line(line):
                continue
            nxt = next_nonempty(lines, i)
            if nxt is not None and is_separator_line(nxt):
                continue
            content = line.strip()
            if content:
                found.append(content[:TASK_CHARS])
        elif line.startswith("- "):
            content = line.strip()
            if content[2:].strip():
                found.append(content[:TASK_CHARS])
        elif line.startswith("## "):
            rest = line[3:].strip()
            if HEADING_DATE_RE.match(rest):
                found.append(line.strip()[:TASK_CHARS])
        else:
            stripped = line.strip()
            if stripped and DATE_ENTRY_RE.match(stripped):
                found.append(stripped[:TASK_CHARS])
    return found


def line_has_recent_date(line: str, today) -> bool:
    for token in DATE_RE.findall(line):
        try:
            stamp = datetime.strptime(token, "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = (today - stamp).days
        if 0 <= delta <= WINDOW_DAYS:
            return True
    return False


def count_recent_log_lines(text: str, today) -> int:
    count = 0
    for line in text.splitlines():
        if line_has_recent_date(line, today):
            count += 1
    return count


def iter_activity_files(folder: Path, config: BoxConfig):
    """Files directly in ``folder`` and one level below. Never lists forbidden dirs."""
    if is_forbidden(folder, config):
        raise PrivacyError(f"refusing to scan forbidden folder: {folder}")
    root_key = os.path.abspath(folder)
    skip_children = config.skip_child_names.get(root_key, set()) | set(PRIVATE_CHILD_NAMES)
    try:
        children = list(guarded_scandir(folder, config))
    except OSError:
        return
    for entry in children:
        if entry.name in skip_children:
            continue
        if is_forbidden(entry.path, config):
            continue
        if is_skipped_name(entry.name):
            continue
        try:
            if entry.is_file(follow_symlinks=True):
                yield entry
                continue
            if entry.is_symlink():
                # Symlinked directories are not entered.
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if is_forbidden(entry.path, config):
            continue
        try:
            grandchildren = list(guarded_scandir(entry.path, config))
        except (OSError, PrivacyError):
            continue
        for child in grandchildren:
            if is_skipped_name(child.name) or is_forbidden(child.path, config):
                continue
            try:
                if child.is_file(follow_symlinks=True):
                    yield child
            except OSError:
                continue


def file_mtime(entry) -> float | None:
    try:
        return entry.stat(follow_symlinks=True).st_mtime
    except OSError:
        return None


def scan_folder(folder: Path, now: datetime, config: BoxConfig) -> dict:
    newest: float | None = None
    modified = 0
    cutoff = now.timestamp() - WINDOW_DAYS * 86400
    for entry in iter_activity_files(folder, config):
        # Secret filenames are never opened. mtime still reflects activity.
        mtime = file_mtime(entry)
        if mtime is None:
            continue
        if newest is None or mtime > newest:
            newest = mtime
        if mtime >= cutoff:
            modified += 1
    return {"newest": newest, "files_modified_7d": modified}


def bot_log_paths(folder: Path, config: BoxConfig) -> list[Path]:
    """The usual log names, any other "*-log.md" in the folder, and logs the roster lists for it."""
    names = list(LOG_NAMES)
    try:
        for entry in guarded_scandir(folder, config):
            if LOG_FILE_RE.match(entry.name) and entry.name not in names:
                names.append(entry.name)
    except (OSError, PrivacyError):
        pass
    for extra in sorted(config.extra_logs):
        if os.path.dirname(extra) == os.path.abspath(folder) and os.path.basename(extra) not in names:
            names.append(os.path.basename(extra))
    paths = []
    for name in names:
        path = folder / name
        if is_forbidden(path, config) or is_skipped_name(name) or is_secret_name(name):
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        paths.append(path)
    return paths


def compile_name_patterns(names: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    ordered = sorted(names, key=len, reverse=True)
    compiled = []
    for name in ordered:
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])")
        compiled.append((name, pattern))
    return compiled


def names_in_text(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    found = []
    for name, pattern in patterns:
        if pattern.search(text):
            found.append(name)
    return found


def is_willow(bot: dict, private: set[str] | frozenset = frozenset()) -> bool:
    """A private bot: work metadata only. Willow Mage always; others when roster.md lists them."""
    return bot.get("name") == WILLOW_NAME or str(bot.get("id") or "") == WILLOW_ID or bot.get("name") in private


def _sqlite_ro_uri(path: Path) -> str:
    resolved = Path(path).resolve()
    return "file:" + quote(resolved.as_posix(), safe="/:") + "?mode=ro"


def connect_ro(path: Path) -> sqlite3.Connection:
    """Open an SQLite file read-only. A WAL database whose -shm file is missing can't be opened
    that way; with no -wal file either there is nothing pending, so it is read as immutable."""
    conn = sqlite3.connect(_sqlite_ro_uri(path), uri=True)
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        return conn
    except sqlite3.OperationalError:
        conn.close()
        if os.path.exists(str(path) + "-wal"):
            raise
        return sqlite3.connect(_sqlite_ro_uri(path) + "&immutable=1", uri=True)


# Metadata columns only. The body column is intentionally absent.
_WILLOW_META_SQL = """
SELECT agent_id, role, timestamp_ms, seq
FROM messages
WHERE agent_id IN ({marks})
ORDER BY timestamp_ms, COALESCE(seq, 0)
"""


def willow_index_meta(config: BoxConfig, agent_ids: set[str]) -> dict:
    """Counts, newest timestamp and whether her latest run got a reply.

    Opens ``search-index.db`` read-only and does not select ``body``. Returns
    zeros when the index is missing. Never touches a Willow folder.
    """
    empty = {"message_count": 0, "newest_ms": None, "last_result": None}
    ids = tuple(sorted(item for item in agent_ids if item))
    if not ids:
        return empty
    db_path = config.agent_data / "search-index.db"
    if db_path.name != "search-index.db" or is_forbidden(db_path, config):
        return empty
    try:
        ready = db_path.is_file()
    except OSError:
        return empty
    if not ready:
        return empty
    sql = _WILLOW_META_SQL.format(marks=",".join("?" for _ in ids))
    try:
        conn = connect_ro(db_path)
    except sqlite3.Error:
        return empty
    try:
        try:
            rows = list(conn.execute(sql, ids))
        except sqlite3.Error:
            return empty
    finally:
        conn.close()
    newest: int | None = None
    last_user: int | None = None
    replied = False
    for _agent_id, role, timestamp_ms, _seq in rows:
        stamp = int(timestamp_ms or 0)
        if newest is None or stamp > newest:
            newest = stamp
        if role == "user":
            last_user = stamp
            replied = False
        elif role == "assistant" and last_user is not None and stamp >= last_user:
            replied = True
    result = None
    if last_user is not None:
        result = "replied" if replied else "no-reply"
    return {"message_count": len(rows), "newest_ms": newest, "last_result": result}


def status_for(newest: float | None, now: datetime, has_folder: bool) -> str:
    if not has_folder:
        return "no-folder"
    if newest is None:
        return "idle"
    age = now.timestamp() - newest
    if age < 24 * 3600:
        return "active"
    if age < 72 * 3600:
        return "recent"
    return "idle"


def iso_local(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    if is_separator_line(stripped):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def render_summary(now: datetime, counts: Counter, top_activity: list[dict], top_pairs: list[dict]) -> str:
    stamp = now.strftime("%Y-%m-%d %H:%M")
    extra = f"；另有无文件夹 {counts.get('no-folder', 0)} 个"
    unmonitored = counts.get("不监控", 0)
    if unmonitored:
        extra += f"，不监控 {unmonitored} 个"
    sentences = [
        (
            f"截至 {stamp}（{now.tzname() or '本地时间'}）：活跃 {counts.get('active', 0)} 个，"
            f"近期 {counts.get('recent', 0)} 个，空闲 {counts.get('idle', 0)} 个"
            f"{extra}。"
        )
    ]
    if top_activity:
        bits = "、".join(f"{item['name']}（{item['activity']}）" for item in top_activity)
        sentences.append(f"估算活跃度前三：{bits}。")
    else:
        sentences.append("近 7 天没有可计入的估算活动。")
    if top_pairs:
        parts = []
        for pair in top_pairs:
            kind_bits = []
            if pair["dispatch"]:
                kind_bits.append(f"分派 {pair['dispatch']}")
            if pair["mention"]:
                kind_bits.append(f"提及 {pair['mention']}")
            detail = "、".join(kind_bits) if kind_bits else f"{pair['weight']} 次"
            parts.append(f"{pair['source']} → {pair['target']}（{detail}）")
        sentences.append("协作较多：" + "、".join(parts) + "。")
    else:
        sentences.append("暂无协作记录。")
    sentences.append("无真实限额/用量数据，上面的活跃度只是估算。")
    return "".join(sentences)


def validate(payload: dict) -> None:
    if "generated_at" not in payload or not payload["generated_at"]:
        raise BoxError("missing generated_at")
    usage = payload["usage"]
    if usage.get("available") is not False:
        raise BoxError("usage.available must be false")
    if usage.get("note") != USAGE_NOTE:
        raise BoxError("usage.note mismatch")
    if usage.get("estimate_label") != ESTIMATE_LABEL:
        raise BoxError("estimate label mismatch")
    if len([bot for bot in payload["bots"] if bot.get("name") == WILLOW_NAME]) > 1:
        raise BoxError("Willow Mage listed twice")
    for willow in [bot for bot in payload["bots"] if bot.get("private")]:
        who = willow.get("name")
        if willow.get("status") == "不监控" or willow.get("status") not in ("active", "recent", "idle"):
            raise BoxError(f"{who} status must follow activity: {willow.get('status')!r}")
        if willow.get("folder"):
            raise BoxError(f"{who} folder must not be recorded")
        if willow.get("recent_tasks") or willow.get("logs") or willow.get("runs"):
            raise BoxError(f"{who} tasks must stay empty")
        if willow.get("duty"):
            raise BoxError(f"{who} duty text must not be exposed")
        if not isinstance(willow.get("message_count"), int) or willow["message_count"] < 0:
            raise BoxError(f"{who} message_count missing")
        if willow.get("last_result") not in (None, "replied", "no-reply"):
            raise BoxError(f"{who} last_result invalid: {willow.get('last_result')!r}")
    for edge in payload["edges"]:
        if edge["kind"] not in ("mention", "dispatch"):
            raise BoxError(f"unexpected edge kind: {edge['kind']}")
    for bot in payload["bots"]:
        tasks = bot.get("recent_tasks") or []
        if len(tasks) > TASK_LIMIT:
            raise BoxError(f"too many tasks for {bot['name']}")
        for task in tasks:
            if len(task) > TASK_CHARS:
                raise BoxError(f"task exceeds {TASK_CHARS} chars for {bot['name']}")
    for estimate in usage["estimates"]:
        expected = estimate["log_lines_7d"] + estimate["files_modified_7d"]
        if estimate["activity"] != expected:
            raise BoxError(f"activity mismatch for {estimate['name']}")



# ---------------------------------------------------------------- roster extras
# roster.md already says which folder and logs belong to whom, the old names, and when
# each bot pushes. Every parser here is forgiving: a table it can't understand is skipped
# and the name-based fallback (slugify) still applies.

TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
MD_RE = re.compile(r"[\w./\-]*[\w\-]+\.md\b")
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _clean_cell(cell: str) -> str:
    return re.sub(r"[`*_~]", "", cell).strip()


def roster_tables(text: str) -> list[tuple[str, list[str], list[list[str]]]]:
    """Every markdown table as (heading above it, header cells, data rows)."""
    found: list[tuple[str, list[str], list[list[str]]]] = []
    heading = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            heading = line.strip()
        if line.strip().startswith("|") and i + 1 < len(lines) and is_separator_line(lines[i + 1]):
            header = [_clean_cell(c) for c in line.strip().strip("|").split("|")]
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not is_separator_line(lines[i]):
                    rows.append([_clean_cell(c) for c in lines[i].strip().strip("|").split("|")])
                i += 1
            found.append((heading, header, rows))
            continue
        i += 1
    return found


def _names_in(cells: list[str], names: list[str]) -> list[str]:
    ordered = sorted(set(names), key=len, reverse=True)
    hits: list[str] = []
    for cell in cells:
        for name in ordered:
            if name and re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", cell) and name not in hits:
                hits.append(name)
    return hits


EN_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _days(cells: list[str]) -> list[int] | None:
    text = " ".join(cells)
    low = text.lower()
    if "每天" in text or "每日" in text or re.search(r"\bdaily\b|every ?day", low):
        return None
    if "工作日" in text or "weekday" in low:
        return [0, 1, 2, 3, 4]
    if "周末" in text or "weekend" in low:
        return [5, 6]
    days = {WEEKDAYS[ch] for ch in re.findall(r"(?:周|星期|礼拜)([一二三四五六日天])", text)}
    days |= {EN_DAYS[m] for m in re.findall(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", low)}
    return sorted(days) or None


def parse_roster_extras(text: str, names: list[str]) -> dict:
    """Old names, folders, extra logs, push schedule, deleted bots and the change log."""
    extras = {"aliases": {}, "folders": {}, "logs": {}, "schedule": [], "deleted": [], "changes": [], "private": []}
    tables = roster_tables(text)
    has = lambda heading, pattern: bool(re.search(pattern, heading, re.I))
    for heading, header, rows in tables:
        if has(heading, r"旧名|old names?|aliases"):
            old_col = next((i for i, h in enumerate(header) if re.search(r"旧|old", h, re.I)), 0)
            new_col = next((i for i, h in enumerate(header) if re.search(r"新|new|now", h, re.I)), len(header) - 1)
            for row in rows:
                if len(row) <= max(old_col, new_col):
                    continue
                new = next((n for n in names if n == row[new_col] or n in row[new_col]), None)
                if not new:
                    continue
                for old in re.split(r"[、,，/；;]", row[old_col]):
                    old = old.strip()
                    if old and old != new and old not in names and len(old) <= 40:
                        extras["aliases"][old] = new
    known = names + list(extras["aliases"])
    canonical = lambda name: extras["aliases"].get(name, name)
    for heading, header, rows in tables:
        if has(heading, r"/workspace|共享电脑|folders?"):
            for row in rows:
                bots = {canonical(name) for name in _names_in(row, known)}
                slugs = [m.group(1) for cell in row for m in re.finditer(r"(?:/workspace/)?([a-z0-9][a-z0-9._\-]*)/", cell)]
                if len(bots) == 1 and len(slugs) == 1:
                    extras["folders"].setdefault(bots.pop(), slugs[0])
        if has(heading, r"日志|\blogs?\b") and not has(heading, r"时间|schedule"):
            for row in rows:
                bots = [canonical(name) for name in _names_in(row[:1] or row, known)] or [canonical(n) for n in _names_in(row, known)]
                files = [m.group(0) for cell in row for m in MD_RE.finditer(cell)]
                if len(set(bots)) == 1 and files:
                    extras["logs"].setdefault(bots[0], [])
                    for name in files:
                        if name not in extras["logs"][bots[0]]:
                            extras["logs"][bots[0]].append(name)
        if has(heading, r"推送时间|时间表|schedule"):
            for row in rows:
                hit = next((TIME_RE.search(cell) for cell in row if TIME_RE.search(cell)), None)
                bots = [canonical(name) for name in _names_in(row, known)]
                if not hit or not bots:
                    continue
                rest = [cell for cell in row if cell and not TIME_RE.search(cell) and not _names_in([cell], known)]
                when = next((cell for cell in row if TIME_RE.search(cell)), "")
                extras["schedule"].append({
                    "bot": bots[0], "time": f"{int(hit.group(1)):02d}:{hit.group(2)}", "days": _days(row),
                    "what": max(rest, key=len)[:40] if rest else "", "when": when[:24],
                })
        if has(heading, r"已删除|deleted"):
            extras["deleted"] = [row[0] for row in rows if row and row[0]][:20]
        if has(heading, r"改动记录|change ?log|changes"):
            for row in rows:
                date = next((DATE_RE.search(cell).group(0) for cell in row if DATE_RE.search(cell)), "")
                text_cells = [cell for cell in row if cell and not DATE_RE.fullmatch(cell)]
                if text_cells:
                    extras["changes"].append({"date": date, "text": " · ".join(text_cells)[:100]})
        # Bots whose work shows but whose words never do (like Willow Mage): see the template.
        if has(heading, r"隐私|privacy"):
            for row in rows:
                for name in _names_in(row[:1], known):
                    if canonical(name) not in extras["private"]:
                        extras["private"].append(canonical(name))
    extras["changes"] = sorted(extras["changes"], key=lambda item: item["date"], reverse=True)[:10]
    return extras


def empty_extras() -> dict:
    return {"aliases": {}, "folders": {}, "logs": {}, "schedule": [], "deleted": [], "changes": [], "private": []}


def load_extras(config: BoxConfig, names: list[str]) -> dict:
    try:
        return parse_roster_extras(read_roster(config), names)
    except (OSError, PrivacyError, ValueError):
        return empty_extras()


def resolve_folders(config: BoxConfig, bots: list[dict], extras: dict) -> dict[str, Path]:
    """Bot → folder: explicit config first, then the roster's folder table, then the bot's slug.

    Only existing folders under the workspace count. The result also opens those folders
    (and the logs the roster names for them) to ``read_log``.
    """
    workspace = config.workspace
    private = set(extras.get("private", []))
    found: dict[str, Path] = {}
    for bot in bots:
        name = bot["name"]
        if is_willow(bot, private):
            continue  # a private bot's folder is never opened
        candidates = [config.folder_map.get(name)]
        if extras["folders"].get(name):
            candidates.append(workspace / extras["folders"][name])
        candidates.append(workspace / slugify(name))
        for folder in candidates:
            if folder is None or is_forbidden(folder, config):
                continue
            try:
                ok = folder.is_dir()
            except OSError:
                ok = False
            if ok and (name in config.folder_map or _is_under(os.path.abspath(folder), os.path.abspath(workspace))):
                found[name] = folder
                break
    config.resolved_folders = found
    extra_logs: set[str] = set()
    for name, files in extras["logs"].items():
        folder = found.get(name)
        if folder is None:
            continue
        for file in files:
            path = (workspace / file) if "/" in file else (folder / file)
            path_abs = os.path.abspath(path)
            if os.path.dirname(path_abs) == os.path.abspath(folder) and path.suffix.lower() == ".md" \
                    and not is_secret_name(path.name) and not is_skipped_name(path.name) and not is_forbidden(path, config):
                extra_logs.add(path_abs)
    config.extra_logs = extra_logs
    return found


def find_dispatcher(config: BoxConfig, bots: list[dict]) -> tuple[str, Path]:
    """Whoever keeps dispatch-log.md in their folder dispatches; otherwise the platform's lead bot."""
    for bot in bots:
        folder = config.resolved_folders.get(bot["name"])
        if folder is not None and (folder / "dispatch-log.md").is_file() and not is_willow(bot):  # never a private bot's folder
            return bot["name"], folder / "dispatch-log.md"
    return DEFAULT_DISPATCHER, config.dispatch_log


PROFILE_FIELDS = ("name", "title", "avatarShape", "avatarColor", "harness")


def read_profiles(config: BoxConfig, skip_ids: set[str]) -> dict[str, dict]:
    """Display fields from each agents/<id>/profile.json. ``description`` (the bot's instructions)
    is never kept, and no other file in those folders is opened."""
    import json
    root = config.agent_data / "agents"
    if is_forbidden(root, config) or not root.is_dir():
        return {}
    found: dict[str, dict] = {}
    try:
        children = list(guarded_scandir(root, config))
    except (OSError, PrivacyError):
        return {}
    for entry in children:
        if entry.name in skip_ids:
            continue
        try:
            if not entry.is_dir(follow_symlinks=False) or is_forbidden(entry.path, config):
                continue
        except OSError:
            continue
        profile = Path(entry.path) / "profile.json"
        if is_forbidden(profile, config):
            continue
        try:
            payload = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        fields = {key: payload[key].strip()[:40] for key in PROFILE_FIELDS
                  if isinstance(payload.get(key), str) and payload[key].strip()}
        if fields.get("name"):
            found[entry.name] = fields
    return found


# ---------------------------------------------------------------- run tables in logs

RESULT_HEAD = re.compile(r"结果|result|状态|status", re.I)
RETRY_HEAD = re.compile(r"重来|重试|retry|retries|attempt", re.I)
ROUNDS_HEAD = re.compile(r"轮数|rounds?|turns?", re.I)
FAILED = re.compile(r"失败|fail|error|错误|❌|✗|✘|未完成|没成功|放弃|中断|超时|timeout", re.I)


def _number(cell: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", cell or "")
    return float(match.group(0)) if match else None


def log_runs(text: str) -> dict | None:
    """A log kept as a run table (time | task | rounds | retries | result): counts, never text."""
    for _heading, header, rows in roster_tables(text):
        result = next((i for i, h in enumerate(header) if RESULT_HEAD.search(h)), None)
        if result is None or not rows or not any(RETRY_HEAD.search(h) or ROUNDS_HEAD.search(h) for h in header):
            continue
        retry = next((i for i, h in enumerate(header) if RETRY_HEAD.search(h)), None)
        rounds = next((i for i, h in enumerate(header) if ROUNDS_HEAD.search(h)), None)
        retries = failures = 0
        round_values: list[float] = []
        last = ""
        for row in rows:
            cell = lambda i: row[i] if i is not None and i < len(row) else ""
            value = _number(cell(retry))
            if value is not None:
                retries += int(value)
            elif cell(retry) and cell(retry) not in ("-", "—", "无", "否", "no", "0"):
                retries += 1
            if FAILED.search(cell(result)):
                failures += 1
            value = _number(cell(rounds))
            if value is not None:
                round_values.append(value)
            stamp = DATE_RE.search(" ".join(row[:2]))
            if stamp:
                time_hit = TIME_RE.search(" ".join(row[:2]))
                when = stamp.group(0) + (f" {int(time_hit.group(1)):02d}:{time_hit.group(2)}" if time_hit else "")
                last = max(last, when)
        return {"runs": len(rows), "retries": retries, "failures": failures, "last": last or None,
                "avg_rounds": round(sum(round_values) / len(round_values), 1) if round_values else None}
    return None


# ---------------------------------------------------------------- push schedule

def _assistant_times(config: BoxConfig, since_ms: int) -> dict[str, list[int]]:
    """When each agent last answered (timestamps only, no body)."""
    db_path = config.agent_data / "search-index.db"
    if is_forbidden(db_path, config) or not db_path.is_file():
        return {}
    try:
        conn = connect_ro(db_path)
    except sqlite3.Error:
        return {}
    found: dict[str, list[int]] = defaultdict(list)
    try:
        for agent_id, stamp in conn.execute(
                "SELECT agent_id, timestamp_ms FROM messages WHERE role='assistant' AND timestamp_ms >= ?", (since_ms,)):
            found[str(agent_id)].append(int(stamp))
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return found


def schedule_status(schedule: list[dict], ids: dict[str, str], config: BoxConfig, now: datetime) -> list[dict]:
    """Today's state of each push: upcoming, done (answered near the time), waiting or missed."""
    if not schedule:
        return []
    times = _assistant_times(config, int((now - timedelta(days=1)).timestamp() * 1000))
    out = []
    for item in schedule:
        hour, minute = map(int, item["time"].split(":"))
        days = item.get("days")
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        nxt = due if due > now else due + timedelta(days=1)
        while days is not None and nxt.weekday() not in days:
            nxt += timedelta(days=1)
        state, at = "not-today", None
        if days is None or now.weekday() in days:
            low, high = (due - timedelta(minutes=15)).timestamp() * 1000, (due + timedelta(hours=2)).timestamp() * 1000
            hits = [t for t in times.get(ids.get(item["bot"], ""), []) if low <= t <= high]
            if hits:
                state, at = "done", iso_local(min(hits) / 1000)
            elif now < due:
                state = "upcoming"
            elif now.timestamp() * 1000 > high:
                state = "missed"
            else:
                state = "waiting"
        out.append({**item, "state": state, "at": at, "next": nxt.isoformat(timespec="minutes")})
    return out


def build(config: BoxConfig | None = None) -> dict:
    """Collect internal box data. Raises ``BoxError`` or ``PrivacyError`` on failure."""
    config = config if config is not None else default_config()
    now = datetime.now().astimezone()
    today = now.date()
    roster, groups, roster_source = load_bots(config)
    roster_names = [bot["name"] for bot in roster]
    extras = load_extras(config, roster_names) if roster_source == "roster" else empty_extras()
    private = set(extras["private"])
    aliases = extras["aliases"]
    folders = resolve_folders(config, roster, extras)
    dispatcher, dispatch_path = find_dispatcher(config, roster)
    known = set(roster_names)
    # Old names in old log lines still point at the bot they belong to.
    patterns = compile_name_patterns(roster_names + list(aliases))
    willow_ids = {WILLOW_ID}
    for bot in roster:
        if is_willow(bot, private) and bot.get("id"):
            willow_ids.add(str(bot["id"]))

    edges: Counter[tuple[str, str, str]] = Counter()
    bots_out: list[dict] = []
    measured: list[dict] = []

    for bot in roster:
        name = bot["name"]
        if is_willow(bot, private):
            ids = {str(bot.get("id") or "")} | ({WILLOW_ID} if bot.get("name") == WILLOW_NAME else set())
            willow_meta = willow_index_meta(config, ids)
            newest_ms = willow_meta["newest_ms"]
            newest = None if newest_ms is None else newest_ms / 1000.0
            record = {
                "name": name,
                "label": bot["label"],
                "id": bot["id"],
                "duty": "",
                "trigger": bot["trigger"],
                "group": bot["group"],
                "folder": None,
                "status": status_for(newest, now, True),
                "last_activity": iso_local(newest) if newest is not None else None,
                "files_modified_7d": 0,
                "log_lines_7d": 0,
                "activity": 0,
                "share_pct": 0.0,
                "recent_tasks": [],
                "message_count": willow_meta["message_count"],
                "last_result": willow_meta["last_result"],
                "private": True,
            }
            bots_out.append(record)
            measured.append(record)
            continue

        folder = folders.get(name)
        has_folder = folder is not None
        record = {
            "name": name,
            "label": bot["label"],
            "id": bot["id"],
            "duty": bot["duty"],
            "trigger": bot["trigger"],
            "group": bot["group"],
            "folder": str(folder) if has_folder else None,
            "status": "no-folder",
            "last_activity": None,
            "files_modified_7d": 0,
            "log_lines_7d": 0,
            "activity": 0,
            "share_pct": 0.0,
            "recent_tasks": [],
            "logs": [],
            "runs": None,
        }
        texts: list[tuple[str, str]] = []
        if has_folder:
            scanned = scan_folder(folder, now, config)
            record["files_modified_7d"] = scanned["files_modified_7d"]
            record["status"] = status_for(scanned["newest"], now, True)
            if scanned["newest"] is not None:
                record["last_activity"] = iso_local(scanned["newest"])
            entries: list[str] = []
            log_lines = 0
            for path in bot_log_paths(folder, config):
                text = read_log(path, config)
                texts.append((path.name, text))
                record["logs"].append(path.name)
                entries.extend(extract_entries(text))
                log_lines += count_recent_log_lines(text, today)
                record["runs"] = record["runs"] or log_runs(text)
            record["log_lines_7d"] = log_lines
            record["recent_tasks"] = list(reversed(entries[-TASK_LIMIT:]))
            for _fname, text in texts:
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    for mentioned in {aliases.get(hit, hit) for hit in names_in_text(line, patterns)}:
                        if mentioned == name or mentioned not in known:
                            continue
                        edges[(name, mentioned, "mention")] += 1
        record["activity"] = record["log_lines_7d"] + record["files_modified_7d"]
        bots_out.append(record)
        measured.append(record)

    dispatch_ready = False
    if not is_forbidden(dispatch_path, config):
        try:
            dispatch_ready = dispatch_path.is_file()
        except OSError:
            dispatch_ready = False
    if dispatch_ready:
        dispatch_text = read_log(dispatch_path, config)
        lines = dispatch_text.splitlines()
        for i, line in enumerate(lines):
            nxt = next_nonempty(lines, i)
            if nxt is not None and is_separator_line(nxt):
                continue
            cells = split_table_row(line)
            if not cells or len(cells) < 3:
                continue
            bot_cell = aliases.get(cells[2], cells[2])
            targets: list[str] = []
            if bot_cell in known and bot_cell != dispatcher:
                targets = [bot_cell]
            else:
                for mentioned in names_in_text(bot_cell, patterns):
                    mentioned = aliases.get(mentioned, mentioned)
                    if mentioned == dispatcher:
                        continue
                    targets.append(mentioned)
            seen: set[str] = set()
            for target in targets:
                if target in seen:
                    continue
                seen.add(target)
                edges[(dispatcher, target, "dispatch")] += 1

    total_activity = sum(item["activity"] for item in measured)
    for item in measured:
        if total_activity <= 0:
            item["share_pct"] = 0.0
        else:
            item["share_pct"] = round(100.0 * item["activity"] / total_activity, 1)

    edge_rows = [
        {"source": source, "target": target, "kind": kind, "weight": weight}
        for (source, target, kind), weight in edges.items()
        if weight > 0
    ]
    edge_rows.sort(key=lambda row: (-row["weight"], row["source"], row["target"], row["kind"]))

    ranking = sorted(measured, key=lambda item: (-item["activity"], item["name"]))
    top_activity = [
        {"name": item["name"], "activity": item["activity"], "share_pct": item["share_pct"]}
        for item in ranking[:3]
        if item["activity"] > 0
    ]

    pair_weights: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in edge_rows:
        pair_weights[(row["source"], row["target"])][row["kind"]] += row["weight"]
    ranked_pairs = sorted(
        pair_weights.items(),
        key=lambda item: (-sum(item[1].values()), item[0][0], item[0][1]),
    )
    top_pairs = []
    for (source, target), kinds in ranked_pairs[:3]:
        top_pairs.append(
            {
                "source": source,
                "target": target,
                "weight": int(sum(kinds.values())),
                "dispatch": int(kinds.get("dispatch", 0)),
                "mention": int(kinds.get("mention", 0)),
            }
        )

    counts = Counter(bot.get("status") for bot in bots_out)
    summary_text = render_summary(now, counts, top_activity, top_pairs)
    estimates = [
        {
            "name": item["name"],
            "label": item["label"],
            "group": item["group"],
            "log_lines_7d": item["log_lines_7d"],
            "files_modified_7d": item["files_modified_7d"],
            "activity": item["activity"],
            "share_pct": item["share_pct"],
        }
        for item in ranking
    ]
    ids = {bot["name"]: str(bot.get("id") or "") for bot in roster}
    profiles = read_profiles(config, willow_ids)
    for record in bots_out:
        engine = profiles.get(str(record.get("id") or ""), {}).get("harness")
        if engine and record["status"] != "不监控":
            record["engine"] = engine
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": now.tzname() or "",
        "dispatcher": dispatcher,
        "schedule": schedule_status(extras["schedule"], ids, config, now),
        "deleted": extras["deleted"],
        "changes": extras["changes"],
        "aliases": len(aliases),
        "roster_source": roster_source,
        "summary": {
            "text": summary_text,
            "active": counts.get("active", 0),
            "recent": counts.get("recent", 0),
            "idle": counts.get("idle", 0),
            "no_folder": counts.get("no-folder", 0),
            "unmonitored": counts.get("不监控", 0),
            "top_activity": top_activity,
            "top_pairs": top_pairs,
        },
        "groups": groups,
        "bots": bots_out,
        "edges": edge_rows,
        "usage": {
            "available": False,
            "note": USAGE_NOTE,
            "estimate_label": ESTIMATE_LABEL,
            "estimates": estimates,
        },
    }
    validate(payload)
    return payload


# ---------------------------------------------------------------- roster draft
# A starting roster.md built from what the box already has (profiles, folders, logs and any
# existing roster). Bot Office only hands it out; it never writes into /workspace. Same layout
# as box/roster.template.md, so the parser above reads it back.

DRAFT = {
    "zh": {
        "title": "# Bot 名册（/workspace/roster.md）",
        "intro": "> 由Bot协作室根据这台电脑上已有的文件生成的草稿。请把标了“待填写”的地方补上，再放到 /workspace/roster.md。",
        "bots": "## 一、名单", "bots_head": "| 名字 | 标签 | id | 只做的一件事 | 怎么触发 |",
        "groups": "### 侧栏分组", "groups_head": "| 分组 | 成员 |", "groups_row": "| （分组名，待填写） | （成员，用、分隔） |",
        "aliases": "### 旧名对照", "aliases_head": "| 旧名 | 新名 |", "aliases_row": "| （以前的名字，没有就删掉这行） | （现在的名字） |",
        "folders": "### 共享电脑 /workspace", "folders_head": "| 文件夹 | 谁的 | 放什么 |",
        "logs": "### 各 bot 的日志", "logs_head": "| bot | 日志 |",
        "schedule": "## 推送时间表（本地时间）", "schedule_head": "| 时间 | bot | 推什么 |", "schedule_row": "| （例如 每天 07:30，待填写） | （bot） | （推什么） |",
        "privacy": "## Bot协作室隐私", "privacy_note": "> 列在这里的 bot 只显示工作信息（在不在忙、最近时间、条数、交接有没有回音），它们写的和收到的内容一律不显示。",
        "privacy_head": "| bot | 规则 |", "privacy_rule": "只显示工作信息", "privacy_row": "| （没有就删掉这行） | 只显示工作信息 |",
        "changes": "## 改动记录", "changes_head": "| 日期 | 改了什么 |", "changes_row": "用Bot协作室生成名册草稿",
        "todo": "待填写",
    },
    "en": {
        "title": "# Bot roster (/workspace/roster.md)",
        "intro": "> A draft Bot Office generated from files already on this box. Fill in the places marked TODO, then save it as /workspace/roster.md.",
        "bots": "## Bots", "bots_head": "| Name | Label | id | The one thing it does | Trigger |",
        "groups": "### Sidebar groups", "groups_head": "| Group | Members |", "groups_row": "| (group name, TODO) | (members, comma-separated) |",
        "aliases": "### Old names", "aliases_head": "| Old name | New name |", "aliases_row": "| (an earlier name; delete this row if none) | (current name) |",
        "folders": "### Folders in /workspace", "folders_head": "| Folder | Owner | What's in it |",
        "logs": "### Logs", "logs_head": "| Bot | Logs |",
        "schedule": "## Push schedule (local time)", "schedule_head": "| Time | Bot | What |", "schedule_row": "| (e.g. daily 07:30, TODO) | (bot) | (what it sends) |",
        "privacy": "## Bot Office privacy", "privacy_note": "> Bots listed here show work only (busy or not, last active, counts, whether handoffs were answered). What they write or receive is never shown.",
        "privacy_head": "| Bot | Rule |", "privacy_rule": "work only", "privacy_row": "| (delete this row if none) | work only |",
        "changes": "## Change log", "changes_head": "| Date | What changed |", "changes_row": "Roster draft generated by Bot Office",
        "todo": "TODO",
    },
}


def _cell(text) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def roster_draft(config: BoxConfig | None = None, language: str = "zh") -> str:
    """A roster.md draft: existing roster rows first, then every bot found in profile.json."""
    config = config if config is not None else default_config()
    words = DRAFT["en" if language == "en" else "zh"]
    try:
        bots, groups, source = load_bots(config)
    except BoxError:
        bots, groups, source = [], [], "none"
    profiles = read_profiles(config, {WILLOW_ID})
    known_ids = {str(bot.get("id")) for bot in bots}
    for agent_id, fields in sorted(profiles.items(), key=lambda item: item[1]["name"].lower()):
        if agent_id not in known_ids:
            bots.append({"name": fields["name"], "label": fields.get("title", ""), "id": agent_id, "duty": "", "trigger": "", "group": ""})
    extras = load_extras(config, [bot["name"] for bot in bots]) if source == "roster" else empty_extras()
    private = set(extras["private"]) | {bot["name"] for bot in bots if is_willow(bot)}
    folders = resolve_folders(config, bots, extras)

    out = [words["title"], "", words["intro"], "", words["bots"], "", words["bots_head"], "| --- | --- | --- | --- | --- |"]
    for bot in bots:
        duty = "" if bot["name"] in private else (bot.get("duty") or words["todo"])
        out.append(f"| {_cell(bot['name'])} | {_cell(bot.get('label'))} | {_cell(bot.get('id'))} | {_cell(duty)} | {_cell(bot.get('trigger') or words['todo'])} |")
    out += ["", words["groups"], words["groups_head"], "| --- | --- |"]
    joiner = ", " if language == "en" else "、"
    out += [f"| {_cell(group['name'])} | {joiner.join(_cell(m) for m in group['members'])} |" for group in groups] or [words["groups_row"]]
    out += ["", words["aliases"], words["aliases_head"], "| --- | --- |"]
    out += [f"| {_cell(old)} | {_cell(new)} |" for old, new in extras["aliases"].items()] or [words["aliases_row"]]
    out += ["", words["folders"], words["folders_head"], "| --- | --- | --- |"]
    out += [f"| `/workspace/{os.path.relpath(folder, config.workspace)}/` | {_cell(name)} |  |" for name, folder in folders.items()]
    out += ["", words["logs"], words["logs_head"], "| --- | --- |"]
    for name, folder in folders.items():
        logs = [path.name for path in bot_log_paths(folder, config)]
        if logs:
            out.append(f"| {_cell(name)} | {joiner.join(logs)} |")
    out += ["", words["schedule"], "", words["schedule_head"], "| --- | --- | --- |"]
    out += [f"| {_cell(item.get('when') or item['time'])} | {_cell(item['bot'])} | {_cell(item['what'])} |"
            for item in extras["schedule"]] or [words["schedule_row"]]
    out += ["", words["privacy"], "", words["privacy_note"], "", words["privacy_head"], "| --- | --- |"]
    out += [f"| {_cell(name)} | {words['privacy_rule']} |" for name in sorted(private)] or [words["privacy_row"]]
    today = datetime.now().strftime("%Y-%m-%d")
    out += ["", words["changes"], "", words["changes_head"], "| --- | --- |", f"| {today} | {words['changes_row']} |"]
    out += [f"| {item['date']} | {_cell(item['text'])} |" for item in extras["changes"]]
    return "\n".join(out) + "\n"
