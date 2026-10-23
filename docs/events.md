# Event log format

Bot Office reads Grok Bot's local cache out of the box. Any other multi-agent system (CrewAI, LangGraph, the OpenAI Agents SDK, AutoGen, or your own scripts) can show up in the same office by writing **one JSON object per line** to a `.jsonl` file, or by POSTing events to the local server.

```bash
# Point Bot Office at a file (or a folder of *.jsonl files)
python3 backend/server.py --events ~/agents/runs.jsonl --open

# ...or let your code POST events; they're appended to data/events.jsonl
curl -X POST http://127.0.0.1:8080/api/events -H 'Content-Type: application/json' \
  -d '{"type":"handoff","from":"planner","to":"coder","text":"Fix the login bug","run":"r42"}'
```

You can also pick **Settings → Data source → Event log** and paste the path there. With the source set to **Auto**, Bot Office uses Grok Bot if it finds Grok Bot data, then your event log, and otherwise shows an empty office that says nothing was found.

## Events

Every event has a `type`. `ts` is optional: epoch seconds, epoch milliseconds or an ISO 8601 string. Without it, the time the line is read is used. `run` is optional too and groups the events of one task into one relay. Without `run`, a bot's events stay in the same turn until it has been quiet for 30 minutes.

| type | fields | what it means |
|---|---|---|
| `bot` | `id`, `name`, `title`, `team`, `description`, `shape`, `color`, `pinned`, `hidden` | Introduces a bot. Optional, because bare ids work too. `team` becomes a room. `shape`/`color` use the avatar kit names (`cat`, `bear`, `cloud`… / `sky`, `mint`, `grape`…). |
| `ask` | `to`, `text`, `run` | A person gives a bot a task. Starts a relay. |
| `handoff` | `from`, `to`, `text`, `run` | One bot passes work to another. This is the core event. |
| `reply` | `from`, `text`, `run` | A bot answers the person. Ends a relay. |
| `error` | `bot`, `text`, `run` | Something failed. Shows up in error rates and alerts. |
| `status` | `bot`, `state` (`working` · `idle` · `waiting` · `error`), `text` | Live state. `waiting` means the bot needs a person. |
| `schedule` | `bot`, `name`, `active` | A recurring job (shown under Schedules). |

A complete relay:

```jsonl
{"type":"bot","id":"planner","name":"Planner","title":"Lead","team":"Core","shape":"cat","color":"lemon"}
{"type":"bot","id":"coder","name":"Coder","team":"Build"}
{"type":"ask","to":"planner","text":"Fix the login timeout","run":"r42","ts":"2026-10-18T09:00:00Z"}
{"type":"handoff","from":"planner","to":"coder","text":"Repro and fix the session timeout","run":"r42","ts":"2026-10-18T09:01:10Z"}
{"type":"error","bot":"coder","text":"Auth tests failed","run":"r42","ts":"2026-10-18T09:04:00Z"}
{"type":"handoff","from":"planner","to":"coder","text":"Try again with the clock mock","run":"r42","ts":"2026-10-18T09:05:00Z"}
{"type":"handoff","from":"coder","to":"planner","text":"Fixed, PR #142","run":"r42","ts":"2026-10-18T09:12:30Z"}
{"type":"reply","from":"planner","text":"Login timeout fixed and reviewed.","run":"r42","ts":"2026-10-18T09:13:00Z"}
```

That gives you the relay replay, the time each bot took to pick up (planner → coder: 7m 30s), one error, one retry, and the Sankey of who hands work to whom.

## Python helper

[`integrations/bot_office.py`](../integrations/bot_office.py) is one standard-library file. Copy it into your project, or import it from the installed package (`from grokbot_teamwork_ui.integrations.bot_office import BotOffice`):

```python
from bot_office import BotOffice

office = BotOffice()                      # POST to http://127.0.0.1:8080
# office = BotOffice(file="runs.jsonl")   # or append to a file
run = office.new_run()
office.ask("planner", "Write the release notes", run=run)
office.handoff("planner", "writer", "Draft notes from the changelog", run=run)
office.reply("planner", "Release notes are live", run=run)
```

Calls never raise. If Bot Office isn't running, events are dropped with a single warning.

Try it without writing any code: `python3 examples/simulate_events.py --post --live` plays a small software team into a running Bot Office.

## Recipes

These are sketches of where to hook in. Check them against the version of your framework.

**OpenAI Agents SDK**: run hooks see every handoff.

```python
from agents import RunHooks
from bot_office import BotOffice

office = BotOffice()

class OfficeHooks(RunHooks):
    def __init__(self, run_id):
        self.run_id = run_id
    async def on_handoff(self, context, from_agent, to_agent):
        office.handoff(from_agent.name, to_agent.name, run=self.run_id)

# await Runner.run(triage_agent, question, hooks=OfficeHooks(BotOffice.new_run()))
```

**LangGraph**: each node update in a stream is a step. Hand off from the previous node to the next.

```python
run, previous = BotOffice.new_run(), None
office.ask("supervisor", question, run=run)
for update in graph.stream(inputs, stream_mode="updates"):
    for node in update:
        if previous and node != previous:
            office.handoff(previous, node, run=run)
        previous = node
office.reply(previous or "supervisor", "done", run=run)
```

**CrewAI**: `task_callback` fires as each task finishes. Hand off to the agent of the next task.

```python
run, last = BotOffice.new_run(), None
def on_task(output):
    global last
    agent = str(output.agent)
    if last and last != agent:
        office.handoff(last, agent, output.description[:120], run=run)
    last = agent
# Crew(agents=[...], tasks=[...], task_callback=on_task).kickoff()
```

**Anything else**: write lines to a file from any language:

```js
fs.appendFileSync("runs.jsonl", JSON.stringify({ type: "handoff", from: "a", to: "b", text: "…", ts: Date.now() }) + "\n");
```

## Notes

- Bot Office reads only the last 20 MB of each file (64 files at most per folder), so long-running logs stay fast.
- The ingest endpoint only listens on 127.0.0.1. It accepts requests from local scripts (no `Origin` header) and from the Bot Office page itself, never from other websites.
- Privacy mode, aliases, hidden bots, custom looks and alerts work the same way as for Grok Bot data.
