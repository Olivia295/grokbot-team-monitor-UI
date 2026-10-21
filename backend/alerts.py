"""Alerts: notice when a bot errors, waits on you or leaves a handoff hanging, and say so
with a desktop notification and/or chat webhooks (Slack, Discord, Feishu, DingTalk or any URL).

The watcher runs inside the server, so alerts arrive even when the page is closed. It
only reads the same views the page sees, and sends nothing unless alerts are switched on.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime

from .box_source import HIDDEN_TITLE, WILLOW_HIDDEN
from .settings import load_settings
from .views import MASK, flows_view, office_view

KINDS = ("error", "awaiting", "stuck", "done")
STUCK_MAX_MS = 6 * 3600 * 1000
DONE_MAX_MS = 10 * 60 * 1000
TEXT_CHARS = 140

STRINGS = {
    "zh": {
        "error": "{name} 遇到问题了",
        "awaiting": "{name} 在等你回复",
        "stuck": "{to} 还没接手 {sender} 的交接",
        "stuckBody": "已经等了 {minutes} 分钟",
        "done": "{name} 完成了一次协作",
        "test": "测试提醒",
        "testBody": "如果你看到这条，Bot协作室的提醒已经接通了。",
        "open": "打开Bot协作室",
    },
    "en": {
        "error": "{name} ran into a problem",
        "awaiting": "{name} is waiting for your reply",
        "stuck": "{to} hasn't picked up {sender}'s handoff",
        "stuckBody": "Waiting for {minutes} min",
        "done": "{name} finished a relay",
        "test": "Test alert",
        "testBody": "If you can see this, Bot Office alerts are working.",
        "open": "Open Bot Office",
    },
}


def _lang(settings: dict) -> str:
    language = settings.get("language", "auto")
    if language in ("zh", "en"):
        return language
    import locale
    code = (locale.getlocale()[0] or "").lower()
    return "zh" if code.startswith("zh") or code.startswith("chinese") else "en"


def _clean_text(text: str) -> str:
    text = " ".join(str(text or "").split())
    # Placeholders carry no content; an alert is clearer without them.
    if text in (MASK, WILLOW_HIDDEN, HIDDEN_TITLE):
        return ""
    return text[: TEXT_CHARS - 1] + "…" if len(text) > TEXT_CHARS else text


def in_quiet_hours(config: dict, now: datetime | None = None) -> bool:
    if not config.get("quiet"):
        return False
    hour = (now or datetime.now()).hour
    start, end = config.get("quietFrom", 23), config.get("quietTo", 8)
    return start <= hour < end if start <= end else hour >= start or hour < end


# ---------------------------------------------------------------- detection


def detect(office: dict, flows: dict, config: dict, now_ms: int) -> list[dict]:
    """Every condition worth an alert right now, each with a stable key."""
    found = []
    names = {agent["id"]: agent["name"] for agent in office.get("agents", [])}
    names.update({item["id"]: item["name"] for item in flows.get("external", [])})
    for agent in office.get("agents", []):
        if config.get("error", True) and agent["state"] == "error":
            found.append({"key": f"error:{agent['id']}", "kind": "error", "bot": agent["id"],
                          "params": {"name": agent["name"]}, "text": agent.get("snippet", "")})
        if config.get("awaiting", True) and agent.get("detail") == "awaiting":
            found.append({"key": f"awaiting:{agent['id']}", "kind": "awaiting", "bot": agent["id"],
                          "params": {"name": agent["name"]}, "text": agent.get("snippet", "")})
    stuck_ms = max(1, int(config.get("stuckMinutes", 10))) * 60 * 1000
    for flow in flows.get("flows", []):
        steps = flow.get("steps") or []
        if not steps:
            continue
        last = steps[-1]
        if (config.get("stuck", True) and last["kind"] == "handoff" and last.get("traced") and not last.get("failed")
                and last.get("waitMs") is None and stuck_ms <= now_ms - last["at"] <= STUCK_MAX_MS):
            found.append({"key": f"stuck:{flow['id']}:{last['at']}", "kind": "stuck", "bot": last["to"], "flowId": flow["id"],
                          "params": {"to": names.get(last["to"], last["to"]), "sender": names.get(last["from"], last["from"]),
                                     "minutes": int((now_ms - last["at"]) / 60000)},
                          "text": last.get("text", "")})
        if config.get("done") and last["kind"] == "reply" and flow.get("handoffCount") and now_ms - last["at"] <= DONE_MAX_MS:
            found.append({"key": f"done:{flow['id']}", "kind": "done", "bot": last["from"], "flowId": flow["id"],
                          "params": {"name": names.get(last["from"], last["from"])}, "text": last.get("text", "")})
    return found


def render(item: dict, language: str) -> tuple[str, str]:
    strings = STRINGS[language]
    title = strings[item["kind"]].format(**item.get("params", {}))
    body = _clean_text(item.get("text", ""))
    if item["kind"] == "stuck":
        waited = strings["stuckBody"].format(**item["params"])
        body = f"{waited} · {body}" if body else waited
    return title, body


# ---------------------------------------------------------------- delivery


def notify_desktop(title: str, body: str) -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Darwin":
            script = ["-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run"]
            safe = [part if not part.startswith("-") else " " + part for part in (title, body or " ")]
            result = subprocess.run(["osascript", *script, *safe], capture_output=True, timeout=10)
        elif system == "Windows":
            quote = lambda text: text.replace("'", "''")
            app_id = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                "$x = $t.GetElementsByTagName('text');"
                f"$x.Item(0).AppendChild($t.CreateTextNode('{quote(title)}')) > $null;"
                f"$x.Item(1).AppendChild($t.CreateTextNode('{quote(body)}')) > $null;"
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                    capture_output=True, timeout=15)
        elif shutil.which("notify-send"):
            result = subprocess.run(["notify-send", "--app-name=Bot Office", title, body], capture_output=True, timeout=10)
        else:
            return False, "no notifier (install notify-send)"
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return result.returncode == 0, result.stderr.decode("utf-8", errors="replace").strip()[:200]


def _signed(secret: str, timestamp: str, feishu: bool) -> str:
    string = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string, b"", hashlib.sha256).digest() if feishu else hmac.new(secret.encode("utf-8"), string, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def webhook_request(hook: dict, alert: dict) -> tuple[str, bytes]:
    """The URL and JSON body for one webhook kind."""
    title, body, link = alert["title"], alert["body"], alert.get("url", "")
    url = hook["url"]
    kind = hook.get("kind", "generic")
    text = "\n".join(part for part in (f"[Bot Office] {title}", body, link) if part)
    if kind == "slack":
        payload = {"text": "\n".join(part for part in (f"*{title}*", body, f"<{link}|{alert['openLabel']}>" if link else "") if part)}
    elif kind == "discord":
        payload = {"content": "\n".join(part for part in (f"**{title}**", body, link) if part)}
    elif kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
        if hook.get("secret"):
            timestamp = str(int(time.time()))
            payload.update(timestamp=timestamp, sign=_signed(hook["secret"], timestamp, feishu=True))
    elif kind == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
        if hook.get("secret"):
            timestamp = str(int(time.time() * 1000))
            sign = urllib.parse.quote_plus(_signed(hook["secret"], timestamp, feishu=False))
            url += ("&" if "?" in url else "?") + f"timestamp={timestamp}&sign={sign}"
    else:
        payload = {"source": "bot-office", "kind": alert["kind"], "title": title, "body": body, "bot": alert.get("bot"),
                   "flowId": alert.get("flowId"), "url": link, "at": alert["at"]}
    return url, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def post_webhook(hook: dict, alert: dict) -> tuple[bool, str]:
    url, data = webhook_request(hook, alert)
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "BotOffice"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            answer = response.read(2000).decode("utf-8", errors="replace")
            # Feishu and DingTalk answer 200 with an error code in the body.
            try:
                parsed = json.loads(answer)
            except json.JSONDecodeError:
                parsed = {}
            code = parsed.get("code", parsed.get("errcode", 0)) if isinstance(parsed, dict) else 0
            if code not in (0, None):
                return False, str(parsed.get("msg") or parsed.get("errmsg") or code)[:200]
            return True, ""
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, ValueError) as error:
        return False, str(getattr(error, "reason", error))[:200]


def deliver(alert: dict, config: dict) -> list[dict]:
    results = []
    if config.get("desktop", True):
        ok, error = notify_desktop(alert["title"], alert["body"])
        results.append({"channel": "desktop", "ok": ok, "error": error if not ok else ""})
    for hook in config.get("webhooks", []):
        if not hook.get("enabled", True) or not hook.get("url"):
            continue
        ok, error = post_webhook(hook, alert)
        results.append({"channel": hook.get("name") or hook.get("kind", "webhook"), "ok": ok, "error": error})
    return results


# ---------------------------------------------------------------- watcher


class AlertWatcher:
    def __init__(self, base_url: str = "", interval: float = 15.0):
        self.base_url = base_url
        self.interval = interval
        self.recent: deque = deque(maxlen=50)
        self.seen: dict[str, int] = {}
        self.baseline = False
        self.signature = ""
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval if self.baseline else 2):
            try:
                self.scan()
            except Exception as error:  # never let one bad scan kill the watcher
                sys.stderr.write(f"alerts: {error}\n")

    def _link(self, flow_id: str | None) -> str:
        if not self.base_url:
            return ""
        return f"{self.base_url}/#flow={flow_id}" if flow_id else self.base_url

    def make(self, item: dict, settings: dict, now_ms: int) -> dict:
        language = _lang(settings)
        title, body = render(item, language)
        return {"id": f"{item['key']}@{now_ms}", "key": item["key"], "kind": item["kind"], "bot": item.get("bot"),
                "flowId": item.get("flowId"), "title": title, "body": body, "at": now_ms,
                "url": self._link(item.get("flowId")), "openLabel": STRINGS[language]["open"]}

    def scan(self, settings: dict | None = None, now_ms: int | None = None, send=deliver) -> list[dict]:
        settings = settings or load_settings()
        config = settings.get("alerts", {})
        if not config.get("enabled"):
            self.baseline = False
            self.seen.clear()
            return []
        # Switching a kind on should not replay everything that already matched: start a new baseline.
        signature = "|".join([str(config.get(key)) for key in (*KINDS, "stuckMinutes")]
                             + [str(settings.get(key)) for key in ("readMode", "dataSource", "eventsPath", "supportDir")])
        if signature != self.signature:
            self.signature = signature
            self.baseline = False
            self.seen.clear()
        now_ms = now_ms or int(time.time() * 1000)
        # Bot names in demo data follow the alert language.
        settings = {**settings, "language": _lang(settings)}
        found = detect(office_view(settings, now_ms), flows_view(24, settings, now_ms), config, now_ms)
        cooldown = max(0, int(config.get("cooldownMinutes", 15))) * 60 * 1000
        fresh = []
        with self.lock:
            current = {item["key"] for item in found}
            # Conditions that cleared may alert again after the cooldown.
            for key in list(self.seen):
                if key not in current and now_ms - self.seen[key] > cooldown:
                    del self.seen[key]
            for item in found:
                if item["key"] in self.seen:
                    continue
                self.seen[item["key"]] = now_ms
                if self.baseline:
                    fresh.append(item)
            self.baseline = True
        alerts = []
        quiet = in_quiet_hours(config)
        for item in fresh:
            alert = self.make(item, settings, now_ms)
            alert["quiet"] = quiet
            with self.lock:
                self.recent.appendleft(alert)
            if not quiet:
                threading.Thread(target=send, args=(alert, config), daemon=True).start()
            alerts.append(alert)
        return alerts

    def test(self, settings: dict | None = None) -> list[dict]:
        settings = settings or load_settings()
        language = _lang(settings)
        now_ms = int(time.time() * 1000)
        alert = {"id": f"test@{now_ms}", "key": "test", "kind": "test", "bot": None, "flowId": None,
                 "title": STRINGS[language]["test"], "body": STRINGS[language]["testBody"], "at": now_ms,
                 "url": self._link(None), "openLabel": STRINGS[language]["open"]}
        return deliver(alert, settings.get("alerts", {}))

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [{key: value for key, value in alert.items() if key != "openLabel"} for alert in self.recent]
