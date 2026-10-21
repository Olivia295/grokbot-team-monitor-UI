# roster.md: a roster for your Grok Bot box

[中文说明在下面](#中文)

Bot Office can run inside your Grok Bot box (the machine your bots work on). It works there **without a roster**, reading each bot's name, title and avatar from its `profile.json`. A `/workspace/roster.md` makes it much better, and it helps your bots too.

## Why write a roster

| With roster.md | Without it |
| --- | --- |
| Rooms follow your sidebar groups | Every bot sits in one "Ungrouped" room |
| Each bot's role line ("the one thing it does") and trigger | Name and title only |
| Old names in old logs still match (Old names table) | Renamed bots look like strangers |
| The right folder and every log for each bot | Folders guessed from the bot's name, standard log names only |
| Push schedule: Bot Office tells you whether today's push went out or was missed | No schedule (schedules live on the platform's servers, not on the box) |
| Privacy: bots you list show work only, never their words | Only the built-in rules apply |
| Your bots share one source of truth about who does what, who owns which folder, and how handoffs are written | Each bot keeps its own idea of the team |

It's one Markdown file. Writing it once costs a single short agent task, and Bot Office only ever reads it.

## Three ways to make one

1. **Download a draft from Bot Office.** On the box, open Bot Office and switch to **Grok Bot box (internal)**. Then in **On this box**, click **Download roster draft**. It's pre-filled from what the box already has: every bot's name, title and id, the folders and logs it found, and any existing roster. Fill in the places marked TODO and save it as `/workspace/roster.md`.
2. **Ask a bot on your box to write it.** Pull this repository onto the box and paste the prompt below to your lead bot (Grok Bot, or whichever bot manages the team). It fetches the same draft with one command, so this costs very little.
3. **Copy a template by hand:** [`roster.template.en.md`](roster.template.en.md) (English) or [`roster.template.md`](roster.template.md) (中文).

Keep the headings and table headers. Bot Office reads tables by their headings, in English or Chinese. Delete sections you don't need.

### Prompt for your box agent

```text
Please create a bot roster at /workspace/roster.md for Bot Office and the other bots on this computer.

1. If Bot Office is running here, get the pre-filled draft with one command:
   curl -s "http://127.0.0.1:19200/api/roster-draft?lang=en"
   (use the right port if it runs on another one). If that fails, start from
   box/roster.template.en.md in the grokbot-teamwork-UI repository.
2. Fill in every TODO: "the one thing it does" and "trigger" for each bot from what you know.
   Fill in sidebar groups and the push schedule if you know them; otherwise ask me.
3. Do not read any bot's conversations or instructions, credential files, or inbox / snapshots / raw folders.
4. Show me the full file first, and save it to /workspace/roster.md only after I confirm.
```

## Keeping it current

Whoever creates or renames a bot should add or update its row (and the Old names table). Bot Office picks up changes on the next refresh. When you rename something, add a line to the change log at the bottom.

---

## 中文

Bot协作室可以在 Grok Bot 电脑（bot 们干活的那台机器）里运行。**没有名册也能用**：名字、头衔和头像会从每个 bot 的 `profile.json` 读取。有了 `/workspace/roster.md`，效果会好很多，对你的 bot 们也有帮助。

### 为什么要写名册

| 有 roster.md | 没有 |
| --- | --- |
| 房间按你的侧栏分组来分 | 所有 bot 都在一个「未分组」房间 |
| 能看到每个 bot「只做的一件事」和怎么触发 | 只有名字和头衔 |
| 旧名对照：旧日志里的旧名字也能认出来 | 改过名的 bot 认不出来 |
| 每个 bot 的文件夹和所有日志都能对上 | 只能按名字猜文件夹，只读标准的日志文件名 |
| 推送时间表：告诉你今天的推送发了没有、有没有漏 | 没有时间表（定时任务存在平台服务器上，盒子里看不到） |
| 隐私：你列出的 bot 只显示工作信息，永远不显示它们说的话 | 只有内置规则 |
| 所有 bot 共用同一份"谁做什么、文件夹归谁、交接怎么写"的说明 | 每个 bot 对团队各有各的理解 |

它只是一个 Markdown 文件。写一次只需要 agent 做一个很短的任务；Bot协作室只读它，从来不写。

### 三种生成方式

1. **从Bot协作室下载草稿。** 在盒子上打开Bot协作室，切到「Grok Bot 本机读取」，在「本机工作状态」里点「下载名册草稿」。草稿会用盒子上已有的信息自动填好：每个 bot 的名字、头衔和 id，找到的文件夹和日志，以及已有名册的内容。把标了「待填写」的地方补上，保存为 `/workspace/roster.md`。
2. **让盒子里的 bot 帮你写。** 把这个仓库拉到盒子上，把下面这段话发给你的主力 bot（Grok Bot，或者负责管理团队的那个）。它用一条命令就能拿到同一份草稿，花的额度很少。
3. **手动复制模板：** [`roster.template.md`](roster.template.md)（中文）或 [`roster.template.en.md`](roster.template.en.md)（English）。

标题和表头请保持原样，Bot协作室按标题读取表格，中文英文都认。用不上的部分可以整段删掉。

### 发给盒子里 agent 的话

```text
请帮我在 /workspace/roster.md 建一份 bot 名册，给 Bot协作室和这台电脑上的其他 bot 用。

1. 如果 Bot协作室正在这台电脑上运行，用一条命令拿到自动生成的草稿：
   curl -s "http://127.0.0.1:19200/api/roster-draft?lang=zh"
   （端口不同就换成对应端口）。拿不到的话，用 grokbot-teamwork-UI 仓库里的
   box/roster.template.md 作为起点。
2. 把所有「待填写」补上：根据你的了解写每个 bot「只做的一件事」和「怎么触发」。
   侧栏分组和推送时间表你知道就填，不知道就问我。
3. 不要读任何 bot 的对话内容或指令、密钥类文件，也不要打开 inbox / snapshots / raw 文件夹。
4. 先把全文给我看，我确认后再保存到 /workspace/roster.md。
```

### 保持更新

谁新建或改名了 bot，就顺手更新名册里对应的那一行（以及「旧名对照」）。Bot协作室下次刷新就会读到。改了东西，最好在最后的「改动记录」里记一笔。
