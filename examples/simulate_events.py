#!/usr/bin/env python3
"""Pretend to be a small software team so you can try the event adapter end to end.

    python3 examples/simulate_events.py --out data/sim.jsonl          # a day of history
    python3 backend/server.py --events data/sim.jsonl --open          # look at it
    python3 examples/simulate_events.py --out data/sim.jsonl --live   # keep adding relays

Or stream straight into a running server (it appends to data/events.jsonl):

    python3 examples/simulate_events.py --post --live
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations"))
from bot_office import BotOffice  # noqa: E402

TEAM = [
    ("planner", "Planner", "Lead", "Core", "round", "lemon"),
    ("coder", "Coder", "Engineer", "Build", "square", "sky"),
    ("reviewer", "Reviewer", "Code review", "Build", "cat", "lavender"),
    ("tester", "Tester", "QA", "Build", "bean", "mint"),
    ("docs", "Docs", "Writer", "Core", "cloud", "peach"),
    ("ops", "Ops", "Release", "Ship", "bear", "charcoal"),
]
RUNS = [
    ("Fix the login timeout bug", [
        ("planner", "coder", "Repro and fix the session timeout"),
        ("coder", "tester", "Patch is up, please run the auth suite"),
        ("tester", "coder", "Two tests still flaky", "fail"),
        ("coder", "tester", "Retry with the fixed clock mock"),
        ("tester", "reviewer", "All green, ready for review"),
        ("reviewer", "planner", "Approved with one nit"),
    ], "Login timeout fixed and reviewed."),
    ("Ship v2.3", [
        ("planner", "docs", "Write the changelog for v2.3"),
        ("docs", "planner", "Changelog drafted"),
        ("planner", "ops", "Cut the release and deploy"),
        ("ops", "planner", "Deployed to production"),
    ], "v2.3 is live, changelog published."),
    ("Add CSV export", [
        ("planner", "coder", "Build CSV export for reports"),
        ("coder", "reviewer", "PR #142 ready"),
        ("reviewer", "coder", "Please stream rows instead of buffering"),
        ("coder", "reviewer", "Streaming now, take another look"),
        ("reviewer", "docs", "Merged, please document it"),
    ], "CSV export merged and documented."),
]


def play(office: BotOffice, ask: str, steps, reply: str, start: float, pace: float, live: bool) -> None:
    run = office.new_run()
    at = start

    def stamp():
        return int(at * 1000)

    def send(event):
        event["ts"] = int(time.time() * 1000) if live else stamp()
        office.emit(event)
        if live:
            time.sleep(pace)

    send({"type": "ask", "to": "planner", "text": ask, "run": run})
    for sender, receiver, text, *flag in steps:
        at += random.uniform(20, 90) if not live else 0
        send({"type": "handoff", "from": sender, "to": receiver, "text": text, "run": run})
        if flag:
            at += 25 if not live else 0
            send({"type": "error", "bot": receiver, "text": "Test run failed", "run": run})
    at += 30 if not live else 0
    send({"type": "reply", "from": "planner", "text": reply, "run": run})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="append to this JSONL file")
    target.add_argument("--post", nargs="?", const="http://127.0.0.1:19200", help="send to a running Bot Office")
    parser.add_argument("--history", type=int, default=14, help="relays to backfill over the last day")
    parser.add_argument("--live", action="store_true", help="keep playing new relays in real time")
    parser.add_argument("--pace", type=float, default=6.0, help="seconds between live events")
    args = parser.parse_args()
    office = BotOffice(file=args.out) if args.out else BotOffice(url=args.post)
    now = time.time()
    for bot_id, name, title, team, shape, color in TEAM:
        office.emit({"type": "bot", "id": bot_id, "name": name, "title": title, "team": team, "shape": shape,
                     "color": color, "ts": int((now - 86400) * 1000)})
    office.emit({"type": "schedule", "bot": "ops", "name": "Nightly deploy", "ts": int((now - 86400) * 1000)})
    for index in range(args.history):
        ask, steps, reply = RUNS[index % len(RUNS)]
        play(office, ask, steps, reply, now - 86400 + index * 86400 / max(1, args.history), args.pace, live=False)
    print(f"Wrote {args.history} relays of history.", flush=True)
    if args.live:
        print("Playing live relays, Ctrl+C to stop.", flush=True)
        index = 0
        try:
            while True:
                office.status("coder", "working")
                ask, steps, reply = RUNS[index % len(RUNS)]
                play(office, ask, steps, reply, time.time(), args.pace, live=True)
                index += 1
                time.sleep(args.pace * 2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
