# grokbot-teamwork-UI · Bot Office

🌐 [中文](./README.md) | **English**

Turns the handoffs between your [Grok Bot](https://grok.com) bots into a living office: who is busy, who handed what to whom, and every leg a task took from your first message to the final reply. Inspired by [Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI).

- **Runs on your machine only**: listens on `127.0.0.1`, reads Grok Bot's local cache read-only, never uploads anything.
- **Zero dependencies**: Python 3.9+ standard library and plain HTML/JS. No `pip install`, no build step.
- **Works without Grok Bot too**: if no data is found it switches to a demo team that shows every feature.
- **Chinese / English**, dark mode, works on phones.

## Quick start

```bash
git clone <your-repo-url> grokbot-teamwork-UI
cd grokbot-teamwork-UI
./start.sh
```

Your browser opens http://127.0.0.1:19200. Or:

| OS | How |
| --- | --- |
| macOS | double-click `start.command` |
| Windows | double-click `start.bat` |
| any | `python3 backend/server.py --open` |

Handy flags:

```bash
python3 backend/server.py --demo        # always show the demo team (screenshots, trying it out)
python3 backend/server.py --port 8080   # different port
```

The Grok Bot data folder is found automatically:

| OS | Default location |
| --- | --- |
| macOS | `~/Library/Application Support/Grok Bot` |
| Windows | `%APPDATA%\Grok Bot` |
| Linux | `~/.config/Grok Bot` |

If yours lives elsewhere, set it in **Settings → Data source** or via the `GROK_BOT_SUPPORT` environment variable.

## What you get

**Stage** (three views, one animation engine)

- **Studio**: each Grok sidebar group is a room (more groups wrap to new rows and rooms grow with headcount; bots without a group get an “Ungrouped” room, pinned bots sit at the front desk). Busy bots sit at their desks, idle ones relax in the lounge, and an icon above each head shows the status (gear = working, check = just wrote, dots = reading, envelope = handing off, ! = stuck, z = quiet for a while).
- **Bot-to-bot interaction**: on a handoff the sender walks over, says the first line of the message, passes a winged letter, and the receiver answers “Got it!” before the sender walks back. Requests from you show “You” walking over; replies to you bring the bot to the hallway. Regular partners drop by each other. New handoffs pop a toast and are acted out live.
- **Network**: a relationship map weighted by handoffs, with dots flowing in the handoff direction.
- **Timeline**: one row per bot, one coloured thread per relay; replay turns it into a step-by-step sequence.

**Panels**

- HUD: live relays, who is busy, a rolling headline, and your weekly SuperGrok quota as an energy bar.
- Achievements: Chatterbox, Dispatcher, Go-to teammate, Connector, Quick draw, Night owl, Early bird, Alarm lover, New hire.
- Relays (replay leg by leg, change speed, step through), Partners (who hands work to whom, one-way or two-way, jump to their latest exchange) and Activity.
- **Insights**:
  - Needs you: bots waiting for your reply, unread messages, errors, relays running too long.
  - Daily digest: today vs yesterday — output, handoffs, busiest bot, best duo, active hours — copy as Markdown in one click.
  - Team rhythm: weekday × hour heatmap.
  - Schedules: every scheduled task across all bots.
- Team cards and profiles: level and XP, two-week output, busiest hour, partners, reply speed, schedules and recent relays.

## Settings (⚙️, top right)

Everything is saved to `data/settings.json` on your machine (git-ignored).

- **General**: language (system / 中文 / English), theme, default time range, refresh rate, animation level, auto replay.
- **Privacy mode**: hides every message and bot description, keeping only who works with whom — for screenshots, recordings and screen sharing.
- **Data source**: automatic / Grok Bot only / demo, plus a custom data folder.
- **Rooms**: rename, reorder, hide.
- **Bots & looks**: rename a bot for this room, hide it from the office, and dress it up.

### Avatar kit

Each bot is built from swappable parts. The default look comes from its Grok avatar shape, colour and role:

| Part | Options |
| --- | --- |
| Body | Dumpling, Bean, Sugar cube, Cloud, Droplet, Ghostie, Kitty, Bear, Bunny |
| Colour | Peach, Tangerine, Lemon, Matcha, Mint, Sky, Ocean, Lavender, Grape, Sakura, Cocoa, Charcoal, Cloud white |
| Eyes | Dots, Sparkly, Happy, Sleepy, Wink, Glasses |
| Mouth | Smile, Cat, Laugh, Tiny, Oh |
| Hat | Crown, Beanie, Cap, Headphones, Bow, Sprout, Wizard, Beret, Halo, Antenna, Party hat |
| Holding | Laptop, Book, Pencil, Magnifier, Coffee, Light bulb, Dice, Clipboard, Brush |
| Outfit | Scarf, Bow tie, Tie, Badge, Apron |

All of it is SVG in `frontend/js/avatars.js` — no image files.

## Make it yours

- **Add a language**: copy the `en` block in `frontend/js/i18n.js`, translate it, and add an option to the language picker in `frontend/settings.html`.
- **Add an avatar part**: add its name to the `AV` catalog in `frontend/js/avatars.js`, draw it in `hatArt` / `itemArt` / `outfitArt`, and name it in `i18n.js`.
- **Change default looks**: `ROLE_PARTS` in `avatars.js` matches bot names and roles to hats and held items.

## How relays are reconstructed

A handoff is recorded twice: the sender's transcript gets a reply with `toAgent`, the receiver's gets a message with `fromAgent`, at almost the same time. Entries sharing a `requestId` belong to one turn. Pairing the two copies lets the room follow a task from your message (or a schedule) through every bot that touched it, up to the reply you got. When the receiver's cache has no matching record, that leg is marked as untraced.

## Project layout

```text
backend/
  server.py      local HTTP server (--port / --demo / --open)
  grok_cache.py  read-only Grok Bot cache reader, cross-platform folder lookup
  collab.py      office state and relay reconstruction
  insights.py    profiles, achievements, activity, digest, rhythm
  views.py       picks the data source and applies your settings (renames, hiding, privacy)
  settings.py    reads, validates and writes data/settings.json
  demo.py        the demo team
frontend/
  index.html  settings.html
  js/  i18n.js avatars.js common.js stage.js panels.js main.js settings.js
  css/app.css
tests/           python3 -B -m unittest discover -s tests
start.sh  start.command  start.bat
```

## Tests

```bash
python3 -B -m unittest discover -s tests -v
```

## FAQ

- **The page says “Demo data”**: no Grok Bot cache was found. Open Grok Bot and sign in once, or set the folder in Settings.
- **Port already in use**: `python3 backend/server.py --port 19201`.
- **Sharing a screenshot**: turn on privacy mode in Settings and all message text is hidden.

## License

Code is [MIT](./LICENSE) licensed. Every character, scene and icon is SVG shipped with the project and free to use. Grok is a trademark of xAI; this project is not affiliated with xAI.
