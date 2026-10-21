"""A made-up team so anyone can try the room without Grok Bot.

Timestamps are generated relative to the clock (snapped to buckets so a page refresh
does not reshuffle everything), and a fresh relay starts every couple of minutes so
the live parts of the page have something to show.
"""

from __future__ import annotations

import random
from pathlib import Path

from .grok_cache import Cache

MIN = 60 * 1000
HOUR = 60 * MIN
DAY = 24 * HOUR

# id, zh name, en name, zh title, en title, shape, color, zh role, en role
BOTS = [
    ("demo-atlas", "Atlas", "Atlas", "总指挥", "Lead", "pebble", "yellow", "拆解任务、分派给合适的同事，最后汇总给你。", "Breaks work down, hands it to the right teammate and reports back."),
    ("demo-ledger", "Ledger", "Ledger", "档案管家", "Archivist", "squircle", "black", "把资料、会议纪要和结论整理进知识库。", "Files notes, minutes and decisions into the knowledge base."),
    ("demo-quill", "Quill", "Quill", "主笔", "Writer", "bean", "violet", "写文案、写周报、写邮件。", "Drafts copy, weekly reports and emails."),
    ("demo-pixel", "Pixel", "Pixel", "设计师", "Designer", "cloud", "pink", "做封面、配图和排版。", "Makes covers, illustrations and layouts."),
    ("demo-echo", "Echo", "Echo", "编辑", "Editor", "drop", "teal", "润色、校对、统一语气。", "Polishes, proofreads and keeps the voice consistent."),
    ("demo-spark", "Spark", "Spark", "点子王", "Ideas", "blob", "orange", "头脑风暴，给出三个方向。", "Brainstorms and always comes back with three options."),
    ("demo-scout", "Scout", "Scout", "侦察兵", "Researcher", "pebble", "green", "搜索网页和社交媒体，带回要点。", "Searches the web and socials and brings back the gist."),
    ("demo-radar", "Radar", "Radar", "早报员", "News desk", "squircle", "blue", "每天早上整理新闻简报。", "Puts together the morning news brief."),
    ("demo-deepsea", "Deepsea", "Deepsea", "研究员", "Analyst", "bean", "blue", "做深度研究，读论文和长文。", "Does deep research across papers and long reads."),
    ("demo-concierge", "Concierge", "Concierge", "前台", "Front desk", "blob", "gray", "接待你的请求，转给合适的部门。", "Takes your requests and routes them to the right room."),
]
SECTIONS = [
    ("demo-hq", "指挥部", "Command", ["demo-atlas", "demo-ledger", "demo-quill"]),
    ("demo-studio", "创作组", "Studio", ["demo-pixel", "demo-echo", "demo-spark"]),
    ("demo-intel", "情报站", "Intel", ["demo-scout", "demo-radar", "demo-deepsea"]),
]
PINNED = ["demo-concierge"]
SLOW = {"demo-deepsea": 3, "demo-pixel": 2}

# Each script: trigger ("user" | "auto"), root bot, ask (zh, en), steps [(from, to, zh, en[, "fail"])], reply (zh, en).
# A "fail" step errors out on the receiver's side; the next step is usually the retry.
SCRIPTS = [
    ("user", "demo-atlas", ("帮我准备下周发布会的材料", "Get the launch materials ready for next week"), [
        ("demo-atlas", "demo-scout", "查一下竞品最近一周的动态", "Check what competitors shipped this week"),
        ("demo-scout", "demo-atlas", "三条竞品更新已整理好", "Three competitor updates summarised"),
        ("demo-atlas", "demo-quill", "按这个大纲写发布文案", "Write the launch copy from this outline"),
        ("demo-quill", "demo-echo", "帮我润色第二段", "Could you polish the second paragraph?"),
        ("demo-echo", "demo-quill", "改好了，语气更轻松", "Done, it reads lighter now"),
        ("demo-quill", "demo-atlas", "文案初稿完成", "First draft of the copy is ready"),
        ("demo-atlas", "demo-pixel", "配一张发布会封面", "Please make a cover for the launch"),
    ], ("材料齐了：竞品摘要、发布文案和封面。", "All set: competitor brief, launch copy and a cover.")),
    ("auto", "demo-radar", ("", ""), [
        ("demo-radar", "demo-scout", "帮我补两条行业新闻", "Find me two more industry stories"),
        ("demo-scout", "demo-radar", "找到了，附链接", "Found them, links attached"),
        ("demo-radar", "demo-ledger", "今天的早报请归档", "Please file today's brief"),
    ], ("早报已送达，五条要闻。", "Morning brief delivered: five headlines.")),
    ("user", "demo-pixel", ("做一张周报封面图", "Make a cover image for the weekly report"), [
        ("demo-pixel", "demo-spark", "给我三个配色方向", "Give me three colour directions"),
        ("demo-spark", "demo-pixel", "暖橙、雾蓝、薄荷绿", "Warm orange, mist blue, mint"),
        ("demo-pixel", "demo-echo", "标题文字帮我看一眼", "Can you check the title text?"),
    ], ("封面做好了，选了雾蓝配色。", "Cover done, went with mist blue.")),
    ("auto", "demo-deepsea", ("", ""), [
        ("demo-deepsea", "demo-scout", "找三篇关于多智能体协作的论文", "Find three papers on multi-agent collaboration"),
        ("demo-scout", "demo-deepsea", "三篇都在这里", "Here are all three"),
        ("demo-deepsea", "demo-ledger", "研究笔记请收进知识库", "Please add the research notes to the wiki"),
    ], ("本周深挖：多智能体协作的三种模式。", "This week's deep dive: three patterns for multi-agent work.")),
    ("user", "demo-concierge", ("今天有什么需要我处理的？", "Anything that needs me today?"), [
        ("demo-concierge", "demo-atlas", "汇总一下各组进度", "Could you round up progress from each room?"),
        ("demo-atlas", "demo-ledger", "把待办清单发我", "Send me the open to-do list"),
        ("demo-ledger", "demo-atlas", "还有两件待确认", "Two items still need sign-off"),
        ("demo-atlas", "demo-concierge", "两件事需要你拍板", "Two decisions are waiting for you"),
    ], ("有两件事等你确认：预算和发布时间。", "Two things need your call: budget and launch date.")),
    ("user", "demo-atlas", ("把上周的数据做成图表", "Turn last week's numbers into a chart"), [
        ("demo-atlas", "demo-deepsea", "先把上周的数据拉出来", "Pull last week's numbers first"),
        ("demo-deepsea", "demo-pixel", "按这份数据画个趋势图", "Plot a trend chart from this data", "fail"),
        ("demo-deepsea", "demo-pixel", "再试一次，我把表格简化了", "Trying again with a simpler table"),
        ("demo-pixel", "demo-deepsea", "图做好了", "Chart is done"),
        ("demo-deepsea", "demo-atlas", "数据和图表都在这", "Numbers and chart attached"),
    ], ("图表做好了：上周增长 12%。", "Chart's ready: up 12% last week.")),
    ("user", "demo-quill", ("写一封给合作方的感谢信", "Write a thank-you note to our partners"), [
        ("demo-quill", "demo-spark", "开头想个有意思的点", "Need a fun opening line"),
        ("demo-spark", "demo-quill", "用他们的吉祥物开场", "Open with their mascot"),
        ("demo-quill", "demo-echo", "最后再顺一遍", "One last read-through please"),
    ], ("感谢信写好了，可以直接发。", "The thank-you note is ready to send.")),
]
# A handoff nobody picks up (no reply), so the "no pickup" alert and bottleneck rows have a live example.
HANGING = ("user", "demo-concierge", ("帮我约下周和设计团队的评审", "Book a review with the design team next week"), [
    ("demo-concierge", "demo-atlas", "需要约下周的设计评审", "Need a design review booked next week"),
    ("demo-atlas", "demo-pixel", "下周哪天方便做评审？", "Which day next week works for the review?"),
], None)
AUTOMATIONS = [
    ("demo-radar", "morning-brief", "每日早报", "Morning brief"),
    ("demo-deepsea", "weekly-dive", "每周深挖", "Weekly deep dive"),
    ("demo-ledger", "weekly-archive", "每周归档", "Weekly archive"),
    ("demo-atlas", "standup", "每日站会汇总", "Daily stand-up"),
]


class _Builder:
    def __init__(self, lang: int):
        self.lang = lang
        self.entries: dict[str, list[dict]] = {bot[0]: [] for bot in BOTS}
        self.seq = 0

    def _push(self, agent: str, entry: dict) -> None:
        self.seq += 1
        entry.setdefault("id", f"e{self.seq}")
        entry["seq"] = self.seq
        self.entries[agent].append(entry)

    def play(self, key: str, script, start: int, rng: random.Random, until: int | None = None) -> None:
        kind, root, ask, steps, reply = script
        turns: dict[str, str] = {}
        counter: dict[str, int] = {}

        def new_turn(agent: str) -> str:
            counter[agent] = counter.get(agent, 0) + 1
            turns[agent] = f"{key}-{agent}-{counter[agent]}"
            return turns[agent]

        at = start
        new_turn(root)
        if kind == "user":
            self._push(root, {"kind": "message", "role": "user", "timestampMs": at, "requestId": turns[root],
                              "content": ask[self.lang], "isStreaming": False})
        for sender, receiver, *texts in steps:
            # Some teammates are slower to answer, so the bottleneck view has something to find.
            at += rng.randint(25, 95) * 1000 * SLOW.get(sender, 1)
            if until is not None and at > until:
                return
            text = texts[self.lang]
            failed = len(texts) > 2 and texts[2] == "fail"
            names = {bot[0]: bot[1 + self.lang] for bot in BOTS}
            self._push(sender, {"kind": "message", "role": "assistant", "timestampMs": at, "requestId": turns.get(sender) or new_turn(sender),
                                "content": text, "isStreaming": False, "toAgent": {"id": receiver, "name": names[receiver], "kind": "agent"}})
            self._push(receiver, {"kind": "message", "role": "user", "timestampMs": at + 400, "requestId": new_turn(receiver),
                                  "content": text, "isStreaming": False, "fromAgent": {"id": sender, "name": names[sender]}})
            if failed:
                at += rng.randint(20, 50) * 1000
                if until is not None and at > until:
                    return
                self._push(receiver, {"kind": "event", "timestampMs": at, "requestId": turns[receiver],
                                      "event": {"type": "tool-error", "message": "timeout"}})
        at += rng.randint(20, 60) * 1000
        if reply is None or (until is not None and at > until):
            return
        self._push(steps[-1][1] if kind == "auto" else root, {"kind": "send-message", "timestampMs": at,
                   "requestId": turns.get(steps[-1][1] if kind == "auto" else root, f"{key}-end"),
                   "message": {"type": "text", "content": reply[self.lang]}})


def demo_cache(now_ms: int, language: str = "zh", anchor_ms: int | None = None) -> Cache:
    lang = 1 if language == "en" else 0
    builder = _Builder(lang)
    # History: one relay every ~2.5 hours over the last week, stable within a 10-minute bucket
    # (or pinned to anchor_ms, which the static site build uses to keep frames consistent).
    anchor = anchor_ms if anchor_ms is not None else now_ms - now_ms % (10 * MIN)
    rng = random.Random(anchor // DAY)
    at = anchor - 7 * DAY
    index = 0
    while at < anchor - 20 * MIN:
        script = SCRIPTS[rng.randrange(len(SCRIPTS))]
        builder.play(f"h{index}", script, at, random.Random(index))
        at += rng.randint(90, 220) * MIN
        index += 1
    builder.play("hang", HANGING, anchor - 16 * MIN, random.Random(7))
    # Live: a new relay starts every two minutes and each plays up to "now" for eight minutes,
    # long enough for slow teammates, retries and final replies to happen in front of you.
    newest = now_ms - now_ms % (2 * MIN)
    for live_bucket in range(newest - 3 * 2 * MIN, newest + 1, 2 * MIN):
        if live_bucket - 40 * 1000 < anchor - 20 * MIN:
            continue
        live_script = SCRIPTS[(live_bucket // (2 * MIN)) % len(SCRIPTS)]
        builder.play(f"live{live_bucket}", live_script, live_bucket - 40 * 1000, random.Random(live_bucket), until=now_ms)
    for agent, auto_id, zh, en in AUTOMATIONS:
        builder._push(agent, {"kind": "event", "timestampMs": anchor - 5 * DAY + len(auto_id) * HOUR,
                              "event": {"type": "automation-changed", "action": "created", "automationId": auto_id, "automationName": (zh, en)[lang]}})

    roster = []
    for bot_id, zh_name, en_name, zh_title, en_title, shape, color, zh_role, en_role in BOTS:
        entries = sorted(builder.entries[bot_id], key=lambda e: e["timestampMs"])
        builder.entries[bot_id] = entries
        last = max((e["timestampMs"] for e in entries), default=0)
        roster.append({
            "id": bot_id, "name": (zh_name, en_name)[lang], "title": (zh_title, en_title)[lang],
            "description": (zh_role, en_role)[lang], "avatarShape": shape, "avatarColor": color,
            "createdAt": anchor - (12 + len(bot_id)) * DAY, "lastActivityAt": last,
            "unreadCount": 2 if bot_id == "demo-radar" else 0,
            "awaitingUserResponse": {"since": now_ms} if bot_id == "demo-concierge" else None,
            "isHiddenFromSidebar": False,
        })
    sections = [{"id": sid, "name": (zh, en)[lang], "agentIds": ids} for sid, zh, en, ids in SECTIONS]
    cache = Cache(support=Path("demo"), account="demo", roster=roster, sections=sections, pinned=list(PINNED))
    cache.usage = {"percentUsed": 42.0, "nextResetMs": anchor + 3 * DAY, "plan": "SuperGrok"}
    cache.transcripts = {bot_id: (entries, now_ms - 60 * 1000) for bot_id, entries in builder.entries.items()}
    cache.demo = True
    cache.source = "demo"
    cache.data_at = now_ms
    return cache
