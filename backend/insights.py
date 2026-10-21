"""Per-bot profiles, office awards and a live feed, from everything in the local cache.

Profiles use every cached entry (not the flow window) so habits like active
hours and reply speed have enough samples to mean something.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime
from pathlib import Path

from .collab import _plain, _ref, _reply_text, _stamp
from .grok_cache import Cache, load_cache

DAY_MS = 24 * 3600 * 1000
SPARK_DAYS = 14
FEED_LIMIT = 60
FEED_CHARS = 90
DESC_CHARS = 600
GONE = {"deleted", "disabled"}


def _hour(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000).hour


def _day_index(ms: int, now_ms: int) -> int:
    today = datetime.fromtimestamp(now_ms / 1000).date()
    return (today - datetime.fromtimestamp(ms / 1000).date()).days


def _empty_stats() -> dict:
    return {
        "replies": 0, "asks": 0, "handoffsOut": 0, "handoffsIn": 0, "chars": 0, "longest": 0,
        "attachments": 0, "hours": [0] * 24, "days": [0] * SPARK_DAYS, "responseMs": [],
        "partners": {}, "automations": {}, "firstAt": 0, "lastAt": 0,
        "week": [[0] * 24 for _ in range(7)],
    }


def _empty_day() -> dict:
    return {"outputs": 0, "replies": 0, "asks": 0, "handoffs": 0, "automations": 0,
            "first": 0, "last": 0, "byAgent": {}, "pairs": {}}


def _collect(cache: Cache, now_ms: int) -> tuple[dict[str, dict], list[dict], list[dict]]:
    stats: dict[str, dict] = {}
    feed: list[dict] = []
    days = [_empty_day(), _empty_day()]  # today, yesterday

    def day_of(at: int):
        index = _day_index(at, now_ms) if at else -1
        return days[index] if 0 <= index < 2 else None

    def mark(at: int, agent_id: str, field: str) -> None:
        day = day_of(at)
        if day is None:
            return
        day[field] += 1
        day["first"] = min(day["first"] or at, at)
        day["last"] = max(day["last"], at)
        if field in ("replies", "handoffs"):
            day["outputs"] += 1
            day["byAgent"][agent_id] = day["byAgent"].get(agent_id, 0) + 1
    for agent_id, (entries, _mtime) in cache.transcripts.items():
        mine = stats.setdefault(agent_id, _empty_stats())
        waiting: dict[str, int] = {}

        def output(at: int, text: str) -> None:
            mine["chars"] += len(text)
            mine["longest"] = max(mine["longest"], len(text))
            if at:
                mine["hours"][_hour(at)] += 1
                mine["week"][datetime.fromtimestamp(at / 1000).weekday()][_hour(at)] += 1
                day = _day_index(at, now_ms)
                if 0 <= day < SPARK_DAYS:
                    mine["days"][SPARK_DAYS - 1 - day] += 1

        for entry in entries:
            at, kind, role = _stamp(entry), entry.get("kind"), entry.get("role")
            request = entry.get("requestId") if isinstance(entry.get("requestId"), str) else ""
            if at:
                mine["firstAt"] = min(mine["firstAt"] or at, at)
                mine["lastAt"] = max(mine["lastAt"], at)
            if kind == "message" and role == "user":
                source = _ref(entry, "fromAgent")
                text = _plain(entry.get("content"))
                if source:
                    mine["handoffsIn"] += 1
                    mine["partners"][source["id"]] = mine["partners"].get(source["id"], 0) + 1
                    if cache.box:
                        # On the box only the receiver's copy exists: credit the sender from here.
                        theirs = stats.setdefault(source["id"], _empty_stats())
                        theirs["handoffsOut"] += 1
                        theirs["partners"][agent_id] = theirs["partners"].get(agent_id, 0) + 1
                        mark(at, source["id"], "handoffs")
                        day = day_of(at)
                        if day is not None:
                            key = "|".join(sorted([source["id"], agent_id]))
                            day["pairs"][key] = day["pairs"].get(key, 0) + 1
                        feed.append({"kind": "handoff", "at": at, "from": source["id"], "to": agent_id,
                                     "toName": "", "text": _plain(text, FEED_CHARS)})
                else:
                    mine["asks"] += 1
                    mark(at, agent_id, "asks")
                    if request and request not in waiting:
                        waiting[request] = at
                    feed.append({"kind": "ask", "at": at, "from": "you", "to": agent_id, "text": _plain(text, FEED_CHARS)})
            elif kind == "message" and role == "assistant":
                target = _ref(entry, "toAgent")
                text = _plain(entry.get("content"))
                output(at, text)
                if entry.get("boxReply"):
                    # Box reading: the bot answered you (time only, no text).
                    mine["replies"] += 1
                    mark(at, agent_id, "replies")
                    started = waiting.pop(request, None) if request else None
                    if started and at >= started:
                        mine["responseMs"].append(at - started)
                    feed.append({"kind": "reply", "at": at, "from": agent_id, "to": "you", "text": ""})
                    continue
                if target:
                    mark(at, agent_id, "handoffs")
                    day = day_of(at)
                    if day is not None:
                        key = "|".join(sorted([agent_id, target["id"]]))
                        day["pairs"][key] = day["pairs"].get(key, 0) + 1
                    mine["handoffsOut"] += 1
                    mine["partners"][target["id"]] = mine["partners"].get(target["id"], 0) + 1
                    feed.append({"kind": "handoff", "at": at, "from": agent_id, "to": target["id"],
                                 "toName": str(target.get("name") or ""), "text": _plain(text, FEED_CHARS)})
            elif kind == "send-message":
                text = _reply_text(entry)
                if not text:
                    continue
                mine["replies"] += 1
                mark(at, agent_id, "replies")
                output(at, text)
                started = waiting.pop(request, None) if request else None
                if started and at >= started:
                    mine["responseMs"].append(at - started)
                feed.append({"kind": "reply", "at": at, "from": agent_id, "to": "you", "text": _plain(text, FEED_CHARS)})
            elif kind == "user-attachment":
                mine["attachments"] += 1
            elif kind == "event":
                event = entry.get("event") if isinstance(entry.get("event"), dict) else {}
                if event.get("type") != "automation-changed":
                    continue
                auto_id = str(event.get("automationId") or "")
                name = _plain(event.get("automationName"), 40)
                action = str(event.get("action") or "")
                if auto_id and name:
                    mark(at, agent_id, "automations")
                    mine["automations"][auto_id] = {"name": name, "action": action, "at": at}
                    feed.append({"kind": "automation", "at": at, "from": agent_id, "to": agent_id,
                                 "action": action, "text": name})
    feed.sort(key=lambda item: item["at"], reverse=True)
    digest = []
    for index, day in enumerate(days):
        busiest = max(day["byAgent"].items(), key=lambda item: item[1]) if day["byAgent"] else None
        pair = max(day["pairs"].items(), key=lambda item: item[1]) if day["pairs"] else None
        digest.append({
            "day": index, "outputs": day["outputs"], "replies": day["replies"], "asks": day["asks"],
            "handoffs": day["handoffs"], "automations": day["automations"], "first": day["first"], "last": day["last"],
            "activeBots": len(day["byAgent"]),
            "busiest": {"id": busiest[0], "count": busiest[1]} if busiest else None,
            "topPair": {"ids": pair[0].split("|"), "count": pair[1]} if pair else None,
        })
    return stats, feed[:FEED_LIMIT], digest


def _award(rows: list[dict], score_of, key: str, emoji: str, minimum: float = 1, low: bool = False):
    """Pick the bot with the best score. The page turns key + value into words in its language."""
    scored = [(score_of(row), row) for row in rows]
    scored = [(score, row) for score, row in scored if score is not None and (score <= minimum if low else score >= minimum)]
    if not scored:
        return None
    score, row = (min if low else max)(scored, key=lambda item: item[0])
    return {"id": row["id"], "key": key, "emoji": emoji, "value": score}


def insights_from(cache: Cache, now_ms: int) -> dict:
    stats, feed, digest = _collect(cache, now_ms)
    rows = []
    for row in cache.roster:
        agent_id = row["id"]
        mine = stats.get(agent_id, _empty_stats())
        responses = mine.pop("responseMs")
        automations = sorted(mine.pop("automations").values(), key=lambda item: item["at"], reverse=True)
        partners = sorted(mine.pop("partners").items(), key=lambda item: item[1], reverse=True)
        outputs = sum(mine["hours"])
        night = sum(mine["hours"][h] for h in range(0, 5))
        dawn = sum(mine["hours"][h] for h in range(5, 9))
        rows.append({
            "id": agent_id,
            "name": row.get("name") or "",
            "hidden": bool(row.get("isHiddenFromSidebar")),
            "description": _plain(row.get("description"), DESC_CHARS),
            "createdAt": int(row.get("createdAt") or 0),
            **mine,
            "outputs": outputs,
            "medianResponseMs": int(statistics.median(responses)) if responses else None,
            "responseSamples": len(responses),
            "nightShare": night / outputs if outputs else 0,
            "dawnShare": dawn / outputs if outputs else 0,
            "peakHour": max(range(24), key=lambda h: mine["hours"][h]) if outputs else None,
            "partners": [{"id": pid, "count": n} for pid, n in partners[:6]],
            "partnerCount": len(partners),
            "automations": [{**item, "active": item["action"] not in GONE} for item in automations],
        })

    visible = [row for row in rows if not row["hidden"]]
    awards = [a for a in [
        _award(visible, lambda r: r["chars"], "chatterbox", "💬", 200),
        _award(visible, lambda r: r["handoffsOut"], "dispatcher", "📮", 2),
        _award(visible, lambda r: r["handoffsIn"], "anchor", "🙌", 2),
        _award(visible, lambda r: r["partnerCount"], "connector", "🤝", 2),
        _award(visible, lambda r: r["medianResponseMs"] if r["responseSamples"] >= 3 else None, "quickdraw", "⚡", 10**12, low=True),
        _award(visible, lambda r: round(r["nightShare"], 3) if r["outputs"] >= 6 else None, "nightowl", "🦉", 0.12),
        _award(visible, lambda r: round(r["dawnShare"], 3) if r["outputs"] >= 6 else None, "earlybird", "🌅", 0.15),
        _award(visible, lambda r: sum(1 for a in r["automations"] if a["active"]), "scheduler", "⏰", 1),
        _award(visible, lambda r: r["createdAt"] or None, "newcomer", "🌱", 1),
    ] if a]

    first = min((row["firstAt"] for row in rows if row["firstAt"]), default=0)
    totals = {
        "replies": sum(r["replies"] for r in rows),
        "asks": sum(r["asks"] for r in rows),
        "handoffs": sum(r["handoffsOut"] for r in rows),
        "chars": sum(r["chars"] for r in rows),
        "automations": sum(1 for r in rows for a in r["automations"] if a["active"]),
        "hours": [sum(r["hours"][h] for r in rows) for h in range(24)],
        "days": [sum(r["days"][d] for r in rows) for d in range(SPARK_DAYS)],
        "week": [[sum(r["week"][d][h] for r in rows) for h in range(24)] for d in range(7)],
        "since": first,
    }
    return {"generatedAt": now_ms, "profiles": rows, "awards": awards, "feed": feed, "totals": totals, "digest": digest}


def load_insights(support: Path | None = None, now_ms: int | None = None) -> dict:
    return insights_from(load_cache(support), int(now_ms if now_ms is not None else time.time() * 1000))
