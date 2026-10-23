"""Internal service-status board: counts and timestamps only.

Reads the same sources the rest of internal mode already uses (roster.md,
search-index.db, dispatch-log.md, host_status). Never returns message bodies.
Willow Mage appears by name and activity counts; her message text is not read.
A metric that cannot be computed is omitted (the page shows 暂无数据).
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from .box_source import PREFIX_WINDOW, leading_bot
from .host_status import REFRESH_SECONDS, collect as collect_host_status
from .internal_box import (
    UNMONITORED,
    WILLOW_ID,
    BoxConfig,
    BoxError,
    PrivacyError,
    default_config,
    is_forbidden,
    load_roster,
    SYDNEY,
)

NA = "暂无数据"
WINDOW_DAYS = 14
REPLY_CAP_MS = 30 * 60 * 1000
PREFIX_CHARS = 40
HOUR_MS = 3600_000
MINUTE_MS = 60_000
REFRESH = REFRESH_SECONDS
MEMORY_WATCH = 0.9
REPLY_WATCH_MS = 120_000

_COUNT_SQL = "SELECT agent_id, role, timestamp_ms FROM messages WHERE timestamp_ms >= ?"
_PREFIX_SQL = (
    "SELECT agent_id, role, timestamp_ms, seq, substr(body, 1, ?) FROM messages "
    "WHERE timestamp_ms >= ?{skip} ORDER BY agent_id, timestamp_ms, COALESCE(seq, 0), entry_id"
)


def _sqlite_ro_uri(path: Path) -> str:
    return "file:" + quote(Path(path).resolve().as_posix(), safe="/:") + "?mode=ro"


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _pct(current: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return round(100.0 * (current - baseline) / baseline, 1)


def _median(samples: list[int]) -> float | None:
    if not samples:
        return None
    return float(statistics.median(samples))


def _willow_ids(roster: list[dict]) -> set[str]:
    found = {WILLOW_ID}
    for bot in roster:
        if bot.get("name") == UNMONITORED or bot.get("id") == WILLOW_ID:
            bot_id = bot.get("id")
            if isinstance(bot_id, str) and bot_id:
                found.add(bot_id)
    return found


def _connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.is_file():
        return None
    try:
        return sqlite3.connect(_sqlite_ro_uri(db_path), uri=True)
    except sqlite3.Error:
        return None


def _load_counts(db_path: Path, since_ms: int) -> list[tuple[str, str, int]] | None:
    """Timestamps only. None means the index could not be read."""
    conn = _connect(db_path)
    if conn is None:
        return None
    try:
        rows = []
        for agent_id, role, timestamp_ms in conn.execute(_COUNT_SQL, (since_ms,)):
            rows.append((str(agent_id or ""), str(role or ""), int(timestamp_ms or 0)))
        return rows
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _load_prefixes(
    db_path: Path, since_ms: int, skip_ids: set[str]
) -> list[tuple[str, str, int, str]] | None:
    """First 40 characters of body, never the rest. Willow's agent ids are excluded in SQL."""
    conn = _connect(db_path)
    if conn is None:
        return None
    ids = tuple(sorted(skip_ids)) or ("",)
    skip = " AND agent_id NOT IN ({})".format(",".join("?" for _ in ids))
    try:
        rows = []
        for agent_id, role, timestamp_ms, _seq, prefix in conn.execute(
            _PREFIX_SQL.format(skip=skip), (PREFIX_CHARS, since_ms, *ids)
        ):
            rows.append(
                (
                    str(agent_id or ""),
                    str(role or ""),
                    int(timestamp_ms or 0),
                    prefix if isinstance(prefix, str) else "",
                )
            )
        return rows
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _kpi(
    kid: str,
    *,
    available: bool,
    status: str = "none",
    value=None,
    total=None,
    unit: str = "",
    yesterday_pct: float | None = None,
    week_pct: float | None = None,
    meta: dict | None = None,
) -> dict:
    return {
        "id": kid,
        "available": available,
        "status": status if available else "none",
        "value": value if available else None,
        "total": total,
        "unit": unit,
        "compare": {"yesterday_pct": yesterday_pct, "week_pct": week_pct},
        "meta": meta or {},
    }


def _host_watch(host: dict | None) -> bool:
    if not host:
        return False
    memory = host.get("memory") or {}
    used = memory.get("used_mib")
    total = memory.get("total_mib")
    try:
        if total and float(total) > 0 and float(used) / float(total) >= MEMORY_WATCH:
            return True
    except (TypeError, ValueError):
        return False
    return False


def _hour_window(now: datetime, hours: int = 24) -> tuple[int, int, list[int], list[str]]:
    end = _floor_hour(now)
    end_ms = _ms(end)
    start_ms = end_ms - (hours - 1) * HOUR_MS
    starts = [start_ms + i * HOUR_MS for i in range(hours)]
    labels = [datetime.fromtimestamp(stamp / 1000, SYDNEY).strftime("%H") for stamp in starts]
    return start_ms, end_ms, starts, labels


def _day_window(now: datetime, days: int = 7) -> tuple[list, list[str]]:
    today = now.date()
    dates = [today - timedelta(days=days - 1 - i) for i in range(days)]
    labels = [item.strftime("%m-%d") for item in dates]
    return dates, labels


def _in_range(ms: int, start: int, end: int) -> bool:
    return start <= ms < end


def build(
    config: BoxConfig | None = None,
    *,
    now: datetime | None = None,
    host: dict | None = None,
    host_collect=None,
) -> dict:
    """Assemble the board payload. Missing sources become available=false, not zeros."""
    config = config if config is not None else default_config()
    now = now if now is not None else datetime.now(SYDNEY)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SYDNEY)

    roster: list[dict] = []
    groups: list[dict] = []
    try:
        roster, groups = load_roster(config)
    except (OSError, PrivacyError, BoxError, ValueError, UnicodeError):
        roster, groups = [], []

    group_of = {bot.get("name"): bot.get("group") or "" for bot in roster}
    willow_ids = _willow_ids(roster)
    name_to_id = {str(bot["name"]): str(bot["id"]) for bot in roster if bot.get("name") and bot.get("id")}
    id_to_name = {str(bot["id"]): str(bot["name"]) for bot in roster if bot.get("name") and bot.get("id")}
    mention_names = [name for name in name_to_id if name != UNMONITORED]
    mention_names.sort(key=len, reverse=True)

    if host is None:
        collector = host_collect or collect_host_status
        try:
            host = collector()
        except (OSError, ValueError, TypeError):
            host = None

    now_ms = _ms(now)
    since_ms = now_ms - WINDOW_DAYS * 86400 * 1000
    db_path = config.agent_data / "search-index.db"
    if is_forbidden(db_path, config):
        counts = None
        prefixes = None
    else:
        counts = _load_counts(db_path, since_ms)
        prefixes = _load_prefixes(db_path, since_ms, willow_ids)

    hour_start_ms, hour_end_ms, hour_starts, hour_labels = _hour_window(now, 24)
    day_dates, day_labels = _day_window(now, 7)
    today = now.date()
    win_15 = 15 * MINUTE_MS
    win_1h = 60 * MINUTE_MS
    win_24h = 24 * HOUR_MS

    def count_between(start: int, end: int, agent_id: str | None = None) -> int:
        if counts is None:
            return 0
        n = 0
        for aid, _role, ms in counts:
            if agent_id is not None and aid != agent_id:
                continue
            if _in_range(ms, start, end):
                n += 1
        return n

    def active_ids(start: int, end: int) -> set[str]:
        found: set[str] = set()
        if counts is None:
            return found
        roster_ids = set(id_to_name)
        for aid, _role, ms in counts:
            if aid in roster_ids and _in_range(ms, start, end):
                found.add(aid)
        return found

    # --- messages 15m / 1h and their yesterday / 7-day windows
    msg_15 = count_between(now_ms - win_15, now_ms) if counts is not None else None
    msg_1h = count_between(now_ms - win_1h, now_ms) if counts is not None else None
    msg_15_yday = count_between(now_ms - 86400_000 - win_15, now_ms - 86400_000) if counts is not None else None
    msg_1h_yday = count_between(now_ms - 86400_000 - win_1h, now_ms - 86400_000) if counts is not None else None
    week_15 = (
        [count_between(now_ms - d * 86400_000 - win_15, now_ms - d * 86400_000) for d in range(1, 8)]
        if counts is not None
        else []
    )
    week_1h = (
        [count_between(now_ms - d * 86400_000 - win_1h, now_ms - d * 86400_000) for d in range(1, 8)]
        if counts is not None
        else []
    )
    avg_15 = (sum(week_15) / 7.0) if week_15 else None
    avg_1h = (sum(week_1h) / 7.0) if week_1h else None

    # --- bots online
    roster_n = len(roster)
    active_now = active_ids(now_ms - win_24h, now_ms) if counts is not None else None
    active_yday = active_ids(now_ms - 2 * win_24h, now_ms - win_24h) if counts is not None else None
    week_active = (
        [len(active_ids(now_ms - (d + 1) * win_24h, now_ms - d * win_24h)) for d in range(1, 8)]
        if counts is not None
        else []
    )
    avg_active = (sum(week_active) / 7.0) if week_active else None

    # --- handoffs and reply times from prefixes (Willow excluded)
    handoff_times: list[int] = []
    reply_samples: list[int] = []
    if prefixes is not None:
        by_agent: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        for agent_id, role, ts, prefix in prefixes:
            by_agent[agent_id].append((role, ts, prefix))
        for agent_id, rows in by_agent.items():
            own_name = id_to_name.get(agent_id, "")
            pending: int | None = None
            for role, ts, prefix in rows:
                if role == "user":
                    sender = leading_bot(prefix[:PREFIX_WINDOW], mention_names)
                    if sender and sender != own_name and sender != UNMONITORED and name_to_id.get(sender):
                        handoff_times.append(ts)
                        pending = None
                    else:
                        pending = ts
                elif role == "assistant":
                    if pending is not None:
                        delta = ts - pending
                        if 0 < delta <= REPLY_CAP_MS:
                            reply_samples.append(delta)
                    pending = None

    def handoffs_between(start: int, end: int) -> int:
        return sum(1 for ts in handoff_times if _in_range(ts, start, end))

    hof_24 = handoffs_between(now_ms - win_24h, now_ms) if prefixes is not None else None
    hof_yday = handoffs_between(now_ms - 2 * win_24h, now_ms - win_24h) if prefixes is not None else None
    hof_week = (
        [handoffs_between(now_ms - (d + 1) * win_24h, now_ms - d * win_24h) for d in range(1, 8)]
        if prefixes is not None
        else []
    )
    avg_hof = (sum(hof_week) / 7.0) if hof_week else None
    median_ms = _median(reply_samples) if prefixes is not None else None

    # --- hourly / daily series
    hours_24 = [0] * 24
    hours_24_avg7 = [0.0] * 24
    hod_day: dict[tuple, int] = defaultdict(int)
    bot_hours: dict[str, list[int]] = {bot["id"]: [0] * 24 for bot in roster if bot.get("id")}
    bot_days: dict[str, list[int]] = {bot["id"]: [0] * 7 for bot in roster if bot.get("id")}
    bot_hod: dict[str, list[int]] = {bot["id"]: [0] * 24 for bot in roster if bot.get("id")}
    last_ms: dict[str, int] = {}
    days_7 = [0] * 7
    prev_days_7 = [0] * 7
    if counts is not None:
        day_index = {d: i for i, d in enumerate(day_dates)}
        prev_dates = [today - timedelta(days=13 - i) for i in range(7)]
        prev_index = {d: i for i, d in enumerate(prev_dates)}
        for aid, _role, ms in counts:
            dt = datetime.fromtimestamp(ms / 1000, SYDNEY)
            hod_day[(dt.date(), dt.hour)] += 1
            last_ms[aid] = max(last_ms.get(aid, 0), ms)
            idx = (ms - hour_start_ms) // HOUR_MS
            if 0 <= idx < 24:
                hours_24[int(idx)] += 1
                if aid in bot_hours:
                    bot_hours[aid][int(idx)] += 1
            day_i = day_index.get(dt.date())
            if day_i is not None:
                days_7[day_i] += 1
                if aid in bot_days:
                    bot_days[aid][day_i] += 1
            prev_i = prev_index.get(dt.date())
            if prev_i is not None:
                prev_days_7[prev_i] += 1
            if (today - dt.date()).days < 7 and aid in bot_hod:
                bot_hod[aid][dt.hour] += 1
        for i, start in enumerate(hour_starts):
            hour_dt = datetime.fromtimestamp(start / 1000, SYDNEY)
            samples = [hod_day.get((hour_dt.date() - timedelta(days=d), hour_dt.hour), 0) for d in range(1, 8)]
            hours_24_avg7[i] = round(sum(samples) / 7.0, 2)
    hours_7d = [0] * 24
    hours_7d_avg_prev = [0.0] * 24
    if counts is not None:
        for hod in range(24):
            hours_7d[hod] = sum(hod_day.get((today - timedelta(days=d), hod), 0) for d in range(7))
            prev = [hod_day.get((today - timedelta(days=d), hod), 0) for d in range(7, 14)]
            hours_7d_avg_prev[hod] = round(sum(prev) / 7.0, 2)

    bots_out = []
    for bot in roster:
        bot_id = str(bot.get("id") or "")
        name = str(bot.get("name") or "")
        quiet = name == UNMONITORED or bot_id in willow_ids
        seen = last_ms.get(bot_id)
        hours = bot_hours.get(bot_id, [0] * 24)
        days = bot_days.get(bot_id, [0] * 7)
        hod = bot_hod.get(bot_id, [0] * 24)
        last_iso = None
        if seen:
            last_iso = datetime.fromtimestamp(seen / 1000, SYDNEY).isoformat(timespec="seconds")
        bots_out.append(
            {
                "name": name,
                "group": group_of.get(name, ""),
                "id": bot_id,
                "unmonitored": quiet,
                "last_active": last_iso,
                "messages_24h": sum(hours) if counts is not None else None,
                "hours_24": hours if counts is not None else [0] * 24,
                "hours_7d": hod if counts is not None else [0] * 24,
                "days_7": days if counts is not None else [0] * 7,
            }
        )

    bots_kpi = _kpi(
        "bots",
        available=counts is not None and roster_n > 0,
        status="ok",
        value=len(active_now) if active_now is not None else None,
        total=roster_n or None,
        unit="online",
        yesterday_pct=_pct(len(active_now or ()), len(active_yday or ())) if active_now is not None else None,
        week_pct=_pct(len(active_now or ()), avg_active) if active_now is not None else None,
        meta={"active": len(active_now) if active_now is not None else None, "roster": roster_n},
    )
    msg_kpi = _kpi(
        "messages",
        available=msg_15 is not None,
        status="ok",
        value=msg_15,
        unit="per_15m",
        yesterday_pct=_pct(msg_15 or 0, msg_15_yday or 0) if msg_15 is not None else None,
        week_pct=_pct(msg_15 or 0, avg_15) if msg_15 is not None else None,
        meta={
            "messages_15m": msg_15,
            "messages_1h": msg_1h,
            "messages_1h_yesterday": msg_1h_yday,
            "messages_1h_week_avg": round(avg_1h, 2) if avg_1h is not None else None,
        },
    )
    hof_kpi = _kpi(
        "handoffs",
        available=hof_24 is not None,
        status="ok",
        value=hof_24,
        unit="per_24h",
        yesterday_pct=_pct(hof_24 or 0, hof_yday or 0) if hof_24 is not None else None,
        week_pct=_pct(hof_24 or 0, avg_hof) if hof_24 is not None else None,
        meta={"last_24h": hof_24, "yesterday": hof_yday},
    )
    reply_available = prefixes is not None and median_ms is not None
    reply_status = "ok"
    if reply_available and median_ms is not None and median_ms >= REPLY_WATCH_MS:
        reply_status = "watch"
    reply_kpi = _kpi(
        "reply",
        available=reply_available,
        status=reply_status,
        value=round(median_ms / 1000.0, 1) if reply_available else None,
        unit="seconds",
        yesterday_pct=None,
        week_pct=None,
        meta={"median_ms": int(median_ms) if reply_available else None, "samples": len(reply_samples)},
    )

    host_available = bool(host) and (host.get("uptime") or {}).get("text") not in (None, "", "unavailable")
    host_status_flag = "watch" if _host_watch(host) else "ok"
    memory = (host or {}).get("memory") or {}
    host_kpi = _kpi(
        "host",
        available=host_available,
        status=host_status_flag if host_available else "none",
        value=(host or {}).get("uptime", {}).get("text") if host_available else None,
        unit="uptime",
        yesterday_pct=None,
        week_pct=None,
        meta={
            "load": (host or {}).get("load") or [],
            "memory_text": memory.get("text") or NA,
            "memory_used_mib": memory.get("used_mib"),
            "memory_total_mib": memory.get("total_mib"),
        },
    )
    fail_kpi = _kpi(
        "fail",
        available=False,
        status="none",
        value=None,
        unit="percent",
        meta={"reason": "no-error-flag"},
    )

    kpis = [bots_kpi, msg_kpi, hof_kpi, reply_kpi, host_kpi, fail_kpi]
    overall_ok = True
    reasons: list[str] = []
    if any(item["status"] == "watch" for item in kpis):
        overall_ok = False
        reasons.append("watch")
    services = []
    if host:
        for svc in host.get("services") or []:
            services.append(
                {
                    "name": svc.get("name"),
                    "port": svc.get("port"),
                    "up": bool(svc.get("up")),
                    "latency_ms": svc.get("latency_ms"),
                }
            )

    series_available = counts is not None
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": "Australia/Sydney",
        "refresh_seconds": REFRESH,
        "overall": {"ok": overall_ok, "reasons": reasons},
        "kpis": kpis,
        "bots": bots_out,
        "groups": [{"name": g.get("name"), "members": list(g.get("members") or [])} for g in groups],
        "messages": {
            "available": series_available,
            "hour_labels_24": hour_labels,
            "hours_24": hours_24 if series_available else None,
            "hours_24_avg7": hours_24_avg7 if series_available else None,
            "hours_7d": hours_7d if series_available else None,
            "hours_7d_prev_avg": hours_7d_avg_prev if series_available else None,
            "day_labels_7": day_labels,
            "days_7": days_7 if series_available else None,
            "days_7_prev": prev_days_7 if series_available else None,
            "partial_hour": True,
            "partial_day": True,
        },
        "services": services,
        "host": {
            "available": bool(host),
            "uptime": (host or {}).get("uptime"),
            "load": (host or {}).get("load") or [],
            "memory": memory,
        } if host else {"available": False},
    }
    _validate(payload)
    return payload


def _validate(payload: dict) -> None:
    if not payload.get("generated_at"):
        raise BoxError("status board missing generated_at")
    blob = json.dumps(payload, ensure_ascii=False)
    if "SECRET" in blob:
        raise BoxError("status board leaked a secret token")
    for bot in payload["bots"]:
        if bot.get("unmonitored"):
            allowed = {"name", "group", "id", "unmonitored", "last_active", "messages_24h", "hours_24", "hours_7d", "days_7"}
            extra = set(bot) - allowed
            if extra:
                raise BoxError(f"Willow Mage extra keys: {extra}")
    for kpi in payload["kpis"]:
        if kpi["id"] == "fail" and kpi.get("available"):
            raise BoxError("failure share is not a structured metric")
        if not kpi.get("available"):
            if kpi.get("value") is not None:
                raise BoxError(f"{kpi['id']} unavailable but has a value")
    series = payload["messages"]
    if series.get("available"):
        for key in ("hours_24", "hours_24_avg7", "hours_7d"):
            if series.get(key) is None:
                raise BoxError(f"missing {key}")
    else:
        if series.get("hours_24") is not None:
            raise BoxError("unavailable series must not invent hourly zeros")
