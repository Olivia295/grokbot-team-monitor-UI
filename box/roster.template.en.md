# Bot roster (/workspace/roster.md)

> This file lives at /workspace/roster.md on the Grok Bot box, for Bot Office and every bot on the box to read.
> Keep the headings and table headers as they are, since Bot Office reads them. Change everything in the tables.
> Text in angle brackets is a hint; replace it. Delete any section you don't need, and Bot Office will skip it.

## Bots

| Name | Label | id | The one thing it does | Trigger |
| --- | --- | --- | --- | --- |
| Grok Bot | Lead | <agent id: the folder name under /home/box/agent-data/agents/> | Splits tasks, hands them out, reports back | Chat |
| <e.g. Morning Bridge> | <News> | <agent id> | <Morning news brief> | <Schedule> |

### Sidebar groups

| Group | Members |
| --- | --- |
| <Command> | Grok Bot, <another bot> |
| <Intel> | <bot>, <bot> |

### Old names

> When a bot is renamed, list it here so old logs still match.

| Old name | New name |
| --- | --- |
| <earlier names, comma-separated> | <current name> |

### Folders in /workspace

> Which folder under /workspace each bot uses. Without this, Bot Office looks for a folder named after the bot (Morning Bridge → morning-bridge). A shared folder can list several bots and won't be credited to any one of them.

| Folder | Owner | What's in it |
| --- | --- | --- |
| `/workspace/<grok-bot>/` | Grok Bot | Dispatch log |

### Logs

> log.md, dispatch-log.md, evolution-log.md and any *-log.md are read automatically. List other log files here.

| Bot | Logs |
| --- | --- |
| <Morning Bridge> | log.md, <news-log.md> |

## Push schedule (local time)

> Schedules live on the platform's servers, not on the box. List them here and Bot Office checks the message log to tell you whether today's push went out.
> Write times as 07:30. Add "weekdays", "weekends" or a weekday name if it isn't daily.

| Time | Bot | What |
| --- | --- | --- |
| <daily 07:30> | <Morning Bridge> | <News brief> |

## Bot Office privacy

> Bots listed here show work only: busy or not, last active, message counts, whether handoffs were answered. What they write or receive, their folder and their instructions are never read or shown.

| Bot | Rule |
| --- | --- |
| <e.g. a companion bot> | work only |

## Handoff format (recommended)

> When the dispatching bot hands work to another bot, write two sections:
>
> - "Original request": the user's own words
> - "My understanding": what the dispatcher understood and wants done
>
> Bot Office recognises these messages as handoffs, and shows only "My understanding" as the title. The user's words never appear.

## Change log

| Date | What changed |
| --- | --- |
| <2026-10-22> | Created the roster |
