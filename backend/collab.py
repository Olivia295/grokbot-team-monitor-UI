"""Turn the Grok Bot cache into an office (who is where, doing what) and
collaboration flows (who handed what to whom, in which order).

A handoff is written twice: the sender's transcript gets an assistant message
with `toAgent`, the receiver's gets a user message with `fromAgent`. Entries in
one transcript that share a `requestId` belong to one turn, so matching the two
copies lets us follow a task from the person who asked, through every bot that
touched it.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path


from backend.grok_cache import Cache, app_online, load_cache

ACTIVE_MS = 5 * 60 * 1000
WRITING_MS = 90 * 1000
HANDOFF_MS = 3 * 60 * 1000
LIVE_WRITE_MS = 25 * 1000
MATCH_MS = 5 * 60 * 1000
FLOW_LIMIT = 80
STEP_CHARS = 160
TRIGGER_CHARS = 140
BUBBLE_CHARS = 42
ROLE_CHARS = 72
YOU = "you"

STATE_LABELS = {
    "idle": "待命",
    "writing": "在写",
    "researching": "在查",
    "executing": "在做",
    "syncing": "在交接",
    "error": "出错",
}


def _plain(value, limit: int | None = None) -> str:
    if isinstance(value, str):
        text = " ".join(value.split())
    elif isinstance(value, list):
        text = " ".join(part for part in (_plain(item) for item in value) if part)
    elif isinstance(value, dict):
        if value.get("type") not in (None, "text", "input_text", "output_text"):
            return ""
        for key in ("text", "content", "body"):
            if key in value:
                text = _plain(value.get(key))
                break
        else:
            text = ""
    else:
        text = ""
    if limit is not None and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _stamp(entry: dict) -> int:
    value = entry.get("timestampMs")
    return int(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0


def _ref(entry: dict, field: str) -> dict | None:
    ref = entry.get(field)
    if isinstance(ref, dict) and isinstance(ref.get("id"), str) and ref["id"]:
        return ref
    return None


def _reply_text(entry: dict) -> str:
    body = entry.get("message")
    if isinstance(body, dict) and body.get("type") == "text":
        return _plain(body.get("content"))
    return ""


# ---------------------------------------------------------------- office state


def _derive(now_ms: int, awaiting, entries: list[dict], mtime_ms: int) -> tuple[str, str, str, str]:
    """Return state, detail code, detail param, handoff target id. Same six states as Star-Office-UI.

    Detail codes are translated by the page, so the backend stays language-neutral.
    """
    if awaiting:
        return "idle", "awaiting", "", ""
    tail = entries[-40:]
    if any(entry.get("isStreaming") for entry in tail):
        return "executing", "replying", "", ""

    last_user = last_assistant = last_error = 0
    last_assistant_entry = None
    for entry in tail:
        stamp = _stamp(entry)
        kind = entry.get("kind")
        if kind == "message" and entry.get("role") == "user":
            last_user = max(last_user, stamp)
        elif (kind == "message" and entry.get("role") == "assistant") or (kind == "send-message" and _reply_text(entry)):
            if stamp >= last_assistant:
                last_assistant, last_assistant_entry = stamp, entry
        event = entry.get("event") if isinstance(entry.get("event"), dict) else {}
        event_type = str(event.get("type") or "").lower()
        if "error" in event_type or "fail" in event_type:
            last_error = max(last_error, stamp)

    if last_error and now_ms - last_error <= ACTIVE_MS and last_error >= max(last_user, last_assistant):
        return "error", "error", "", ""
    if last_user and last_user > last_assistant and now_ms - last_user <= ACTIVE_MS:
        return "researching", "reading", "", ""
    if last_assistant_entry is not None:
        age = now_ms - last_assistant
        target = _ref(last_assistant_entry, "toAgent")
        if target and age <= HANDOFF_MS:
            return "syncing", "handoff", str(target.get("name") or ""), target["id"]
        if age <= WRITING_MS:
            return "writing", "wrote", "", ""
    if mtime_ms and now_ms - mtime_ms <= LIVE_WRITE_MS:
        return "executing", "working", "", ""
    return "idle", "idle", "", ""


def _last_snippet(entries: list[dict]) -> str:
    for entry in reversed(entries):
        text = _reply_text(entry) if entry.get("kind") == "send-message" else (
            _plain(entry.get("content")) if entry.get("kind") == "message" else "")
        if text:
            return text
    return ""


def office_from(cache: Cache, now_ms: int) -> dict:
    visible = {row["id"]: row for row in cache.roster if not row.get("isHiddenFromSidebar")}
    named = [s for s in cache.sections if s.get("id") != "__agents__" and isinstance(s.get("name"), str)]
    wings, agents, placed = [], [], set()

    def add(agent_id: str, wing_id: str, wing_name: str, slot: int) -> None:
        row = visible[agent_id]
        entries, mtime = cache.transcript(agent_id)
        state, detail, param, handoff = _derive(now_ms, row.get("awaitingUserResponse"), entries, mtime)
        snippet = _last_snippet(entries)
        agents.append({
            "id": agent_id,
            "name": row.get("name") or "",
            "wingId": wing_id,
            "wingName": wing_name,
            "slot": slot,
            "pinned": agent_id in cache.pinned,
            "state": state,
            "stateLabel": STATE_LABELS[state],
            "detail": detail,
            "detailParam": param,
            "handoffTo": handoff,
            "snippet": _plain(snippet, BUBBLE_CHARS),
            "roleLine": _plain((row.get("description") or "").split("\n", 1)[0], ROLE_CHARS),
            "title": _plain(row.get("title"), 16),
            "avatarShape": str(row.get("avatarShape") or ""),
            "avatarColor": str(row.get("avatarColor") or ""),
            "createdAt": int(row.get("createdAt") or 0),
            "unreadCount": int(row.get("unreadCount") or 0),
            "lastActivityAt": int(row.get("lastActivityAt") or 0),
        })

    for section in named:
        ids = [item for item in section.get("agentIds") or [] if item in visible and item not in placed]
        wings.append({"id": section.get("id"), "name": section["name"]})
        for slot, agent_id in enumerate(ids):
            placed.add(agent_id)
            add(agent_id, section.get("id"), section["name"], slot)

    # Pinned bots outside any group stay at the front desk. Everyone else without a group
    # gets a room of their own, so people who never made sidebar groups still see an office.
    door = [a for a in cache.pinned if a in visible and a not in placed][:4]
    loose = [a for a in visible if a not in placed and a not in door]
    if loose:
        wings.append({"id": "__loose__", "name": ""})
        for slot, agent_id in enumerate(loose):
            add(agent_id, "__loose__", "", slot)
    for slot, agent_id in enumerate(door):
        add(agent_id, "__door__", "", slot)

    return {
        "generatedAt": now_ms,
        "sourceReady": bool(cache.roster),
        "appOnline": app_online(cache.support, now_ms),
        "wings": wings,
        "agents": agents,
        "usage": cache.usage or None,
    }


# ---------------------------------------------------------------- flows


def _requests(cache: Cache):
    """Split every transcript into turns and pull out the collaboration markers."""
    requests: dict[tuple[str, str], dict] = {}
    outs, ins = [], []
    for agent_id, (entries, _mtime) in cache.transcripts.items():
        for index, entry in enumerate(entries):
            request_id = entry.get("requestId")
            key = (agent_id, request_id if isinstance(request_id, str) and request_id else f"entry:{entry.get('id', index)}")
            turn = requests.setdefault(key, {"key": key, "agent": agent_id, "prompt": None, "replies": [], "outs": [], "ins": []})
            kind, role, at = entry.get("kind"), entry.get("role"), _stamp(entry)
            if kind == "message" and role == "user":
                source = _ref(entry, "fromAgent")
                if source:
                    marker = {"key": key, "from": source["id"], "fromName": str(source.get("name") or ""),
                              "to": agent_id, "at": at, "text": _plain(entry.get("content"), STEP_CHARS)}
                    turn["ins"].append(marker)
                    ins.append(marker)
                elif turn["prompt"] is None:
                    turn["prompt"] = {"at": at, "text": _plain(entry.get("content"), TRIGGER_CHARS)}
            elif kind == "message" and role == "assistant":
                target = _ref(entry, "toAgent")
                if target:
                    marker = {"key": key, "from": agent_id, "to": target["id"], "toName": str(target.get("name") or ""),
                              "at": at, "text": _plain(entry.get("content"), STEP_CHARS), "child": None}
                    turn["outs"].append(marker)
                    outs.append(marker)
            elif kind == "send-message":
                text = _reply_text(entry)
                if text:
                    turn["replies"].append({"at": at, "text": _plain(text, STEP_CHARS)})
    return requests, outs, ins


def _match(outs: list[dict], ins: list[dict]) -> set[int]:
    """Pair each outgoing handoff with the receiver's copy. Returns ids of matched incoming markers."""
    pool: dict[tuple[str, str], list[dict]] = {}
    for marker in ins:
        pool.setdefault((marker["from"], marker["to"]), []).append(marker)
    used: set[int] = set()
    for out in sorted(outs, key=lambda m: m["at"]):
        best = None
        for candidate in pool.get((out["from"], out["to"]), []):
            if id(candidate) in used:
                continue
            gap = abs(candidate["at"] - out["at"])
            if gap <= MATCH_MS and (best is None or gap < abs(best["at"] - out["at"])):
                best = candidate
        if best is not None:
            used.add(id(best))
            out["child"] = best["key"]
    return used


def _flow_id(key: tuple[str, str]) -> str:
    return hashlib.sha1(f"{key[0]}|{key[1]}".encode("utf-8")).hexdigest()[:12]


def flows_from(cache: Cache, now_ms: int, hours: int = 24) -> dict:
    names = {row["id"]: row.get("name") or "" for row in cache.roster}
    hidden = {row["id"] for row in cache.roster if row.get("isHiddenFromSidebar")}
    requests, outs, ins = _requests(cache)
    matched = _match(outs, ins)
    children = {out["child"] for out in outs if out["child"]}
    external: dict[str, str] = {}

    def remember(agent_id: str, name: str) -> None:
        if agent_id not in names or agent_id in hidden:
            external.setdefault(agent_id, names.get(agent_id) or name or "")

    for out in outs:
        remember(out["to"], out["toName"])
    for marker in ins:
        remember(marker["from"], marker["fromName"])

    def walk(key, steps, seen, depth=0):
        turn = requests.get(key)
        if turn is None or key in seen:
            return
        seen.add(key)
        for out in sorted(turn["outs"], key=lambda m: m["at"]):
            steps.append({"kind": "handoff", "from": out["from"], "to": out["to"], "at": out["at"],
                          "text": out["text"], "traced": out["child"] is not None, "depth": depth})
            if out["child"]:
                walk(out["child"], steps, seen, depth + 1)
        if turn["replies"]:
            last = turn["replies"][-1]
            steps.append({"kind": "reply", "from": turn["agent"], "to": YOU, "at": last["at"],
                          "text": last["text"], "traced": True, "depth": depth})

    flows, solo = [], 0
    since = now_ms - hours * 3600 * 1000
    for key, turn in requests.items():
        if key in children:
            continue
        orphan_ins = [m for m in turn["ins"] if id(m) not in matched]
        if not turn["outs"] and not orphan_ins:
            if turn["prompt"] and turn["replies"] and turn["replies"][-1]["at"] >= since:
                solo += 1
            continue
        steps: list[dict] = []
        for marker in orphan_ins:
            steps.append({"kind": "handoff", "from": marker["from"], "to": marker["to"], "at": marker["at"],
                          "text": marker["text"], "traced": True, "depth": 0})
        seen: set = set()
        walk(key, steps, seen)
        order = {id(step): index for index, step in enumerate(steps)}
        steps.sort(key=lambda step: (step["at"], order[id(step)]))

        if orphan_ins:
            first = orphan_ins[0]
            trigger = {"kind": "agent", "agentId": first["from"], "at": first["at"], "text": first["text"]}
        elif turn["prompt"]:
            trigger = {"kind": "user", "agentId": YOU, "at": turn["prompt"]["at"], "text": turn["prompt"]["text"]}
        else:
            trigger = {"kind": "automation", "agentId": "automation", "at": steps[0]["at"] if steps else 0, "text": ""}

        stamps = [s["at"] for s in steps if s["at"]] + ([trigger["at"]] if trigger["at"] else [])
        started, ended = (min(stamps), max(stamps)) if stamps else (0, 0)
        if ended < since:
            continue
        participants: list[str] = []
        for agent_id in [trigger["agentId"], turn["agent"], *[x for s in steps for x in (s["from"], s["to"])]]:
            if agent_id not in participants:
                participants.append(agent_id)
        handoffs = sum(1 for s in steps if s["kind"] == "handoff")
        flows.append({
            "id": _flow_id(key),
            "rootAgentId": turn["agent"],
            "trigger": trigger,
            "startedAt": started,
            "endedAt": ended,
            "active": now_ms - ended <= HANDOFF_MS,
            "participants": participants,
            "handoffCount": handoffs,
            "depth": max((s["depth"] for s in steps), default=0),
            "steps": steps,
        })
    flows.sort(key=lambda flow: flow["endedAt"], reverse=True)

    links: dict[tuple[str, str], dict] = {}
    for flow in flows:
        for step in flow["steps"]:
            if step["kind"] != "handoff":
                continue
            link = links.setdefault((step["from"], step["to"]), {"from": step["from"], "to": step["to"], "count": 0, "lastAt": 0})
            link["count"] += 1
            link["lastAt"] = max(link["lastAt"], step["at"])
    touches: dict[str, int] = {}
    for link in links.values():
        for agent_id in (link["from"], link["to"]):
            touches[agent_id] = touches.get(agent_id, 0) + link["count"]
    hub = max(touches, key=touches.get) if touches else None

    return {
        "generatedAt": now_ms,
        "hours": hours,
        "flows": flows[:FLOW_LIMIT],
        "flowCount": len(flows),
        "soloCount": solo,
        "handoffCount": sum(link["count"] for link in links.values()),
        "activeCount": sum(1 for flow in flows if flow["active"]),
        "links": sorted(links.values(), key=lambda link: link["count"], reverse=True),
        "hub": {"id": hub, "touches": touches[hub]} if hub else None,
        "external": [{"id": key, "name": value} for key, value in external.items()],
    }


def load_office(support: Path | None = None, now_ms: int | None = None) -> dict:
    import time
    return office_from(load_cache(support), int(now_ms if now_ms is not None else time.time() * 1000))


def load_flows(hours: int = 24, support: Path | None = None, now_ms: int | None = None) -> dict:
    import time
    return flows_from(load_cache(support), int(now_ms if now_ms is not None else time.time() * 1000), hours)
