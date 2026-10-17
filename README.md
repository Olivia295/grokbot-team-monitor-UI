# Grok 协作室 · Grok Collab Room

🌐 **中文** | [English](./README.en.md)

把 [Grok Bot](https://grok.com) 里各个 bot 之间的交接，变成一间会动的办公室：谁在忙、谁把活交给了谁、一件事从你开口到最后回复你经过了哪几棒，一眼就能看明白。灵感来自 [Star-Office-UI](https://github.com/ringhyacinth/Star-Office-UI)。

- **只在本机运行**：只监听 `127.0.0.1`，只读 Grok Bot 的本地缓存，不改它、不上传任何数据。
- **零依赖**：Python 3.9+ 标准库 + 原生 HTML/JS，不用 `pip install`，不用构建。
- **没有 Grok Bot 也能看**：找不到数据时自动进入演示模式，用一支虚拟团队展示全部功能。
- **中文 / English**，深色模式，手机可看。

## 快速开始

```bash
git clone <你的仓库地址> grok-collab-room
cd grok-collab-room
./start.sh
```

浏览器会自动打开 http://127.0.0.1:19200 。也可以：

| 系统 | 方式 |
| --- | --- |
| macOS | 双击 `start.command` |
| Windows | 双击 `start.bat` |
| 任意 | `python3 backend/server.py --open` |

常用参数：

```bash
python3 backend/server.py --demo        # 只看演示团队（截图、试玩）
python3 backend/server.py --port 8080   # 换端口
```

Grok Bot 数据目录会自动查找：

| 系统 | 默认位置 |
| --- | --- |
| macOS | `~/Library/Application Support/Grok Bot` |
| Windows | `%APPDATA%\Grok Bot` |
| Linux | `~/.config/Grok Bot` |

不在默认位置的话，到 **设置 → 数据来源** 填写目录，或设置环境变量 `GROK_BOT_SUPPORT`。

## 能看到什么

**舞台**（三种视图共用一套动画）

- **工作室**：Grok 侧边栏的每个分组是一个房间（分组多了会自动换行、房间按人数变高；没有分组的 bot 进「未分组」房间，钉住的 bot 在前台）。在忙的坐工位，闲着的在休息区；头顶小图标是状态（齿轮=在干活、对勾=刚写完、省略号=在读消息、信封=在交接、感叹号=卡住了、z=很久没动静）。
- **bot 之间的互动**：交接时，交出方走到对方身边、说出交接内容的第一句、递过一封带翅膀的信，对方回一句「收到！」再走回去。你发起的任务是「你」亲自走过去；回复你时 bot 走到走廊找你。最常配合的搭档会互相串门。新交接一发生，右上角弹提示并现场重演。
- **关系网**：按交接次数排出的关系图，光点沿交接方向流动。
- **时间线**：每行一个成员，每根彩线是一次协作；回放时变成逐棒顺序图。

**面板**

- 顶部 HUD：此刻几场协作、谁在忙、滚动播报；本周 SuperGrok 额度能量条。
- 本期成就：话痨王、总调度、人气接棒手、社交达人、快枪手、夜猫子、早起鸟、闹钟控、新同事。
- 协作流程（可逐棒回放、调速、单步）、搭档榜（谁给谁派活最多、单向还是双向、一键看他们最近一次）、动态时间线。
- **洞察**：
  - 需要你：在等你回复的 bot、未读、出错、跑了太久的协作。
  - 日报：今天 / 昨天的产出、交接、最忙的 bot、最佳拍档、活跃时段，一键复制成 Markdown。
  - 团队作息：一周 × 24 小时热力图，看大家什么时候最忙。
  - 定时任务总表：所有 bot 挂着的定时任务。
- 成员档案：等级和经验条、两周产出、一天里几点最忙、常搭档、回复速度、定时任务、参与过的协作。

## 设置（右上角 ⚙️）

所有设置保存在本机的 `data/settings.json`（已在 `.gitignore` 里），不会进仓库。

- **通用**：语言（跟随系统 / 中文 / English）、深浅色、默认时间范围、刷新频率、动画强度、自动放映。
- **隐私模式**：隐藏所有消息内容和 bot 介绍，只保留谁和谁在协作，适合截图、录屏、投屏。
- **数据来源**：自动 / 只用 Grok Bot / 演示数据，自定义数据目录。
- **房间**：改显示名、调顺序、隐藏。
- **成员与造型**：给每个 bot 改名、在办公室隐藏、换造型。

### 造型素材

每个 bot 由一套可替换的部件组成，默认造型根据它在 Grok 里的头像形状、颜色和职责自动生成：

| 部件 | 选项 |
| --- | --- |
| 身体 | 团子、豆豆、方糖、云朵、水滴、小幽灵、猫猫、小熊、兔兔 |
| 颜色 | 蜜桃、橘子、柠檬、抹茶、薄荷、天空、海洋、薰衣草、葡萄、樱花、可可、炭黑、云白 |
| 眼睛 | 豆豆眼、星星眼、开心、困困、眨眼、眼镜 |
| 嘴巴 | 微笑、猫嘴、大笑、小嘴、哦 |
| 帽子 | 皇冠、毛线帽、棒球帽、耳机、蝴蝶结、小芽、巫师帽、贝雷帽、光环、天线、派对帽 |
| 手持 | 笔记本、书、铅笔、放大镜、咖啡、灯泡、骰子、夹板、画笔 |
| 服饰 | 围巾、领结、领带、工牌、围裙 |

全部是 `frontend/js/avatars.js` 里的 SVG，没有外部图片。

## 自己动手改

- **加一种语言**：在 `frontend/js/i18n.js` 里复制 `en` 整块、翻译，再到 `frontend/settings.html` 的语言下拉框里加一项。
- **加一个造型部件**：在 `frontend/js/avatars.js` 的 `AV` 目录里加名字、在对应的 `hatArt` / `itemArt` / `outfitArt` 里画出来，再到 `i18n.js` 给它起中英文名。
- **改默认造型规则**：`avatars.js` 里的 `ROLE_PARTS`（按 bot 名字和职责关键词匹配帽子和手持物）。

## 流程是怎么拼出来的

一次交接会在两边各记一笔：交出方的记录里是一条带 `toAgent` 的回复，接手方的记录里是一条带 `fromAgent` 的消息，时间几乎相同。同一个 `requestId` 下的记录属于同一轮对话。把两边配对后，就能从你发出的那条消息（或定时任务）一路跟到每个转手的 bot，最后接上回复你的那条。接手方缓存里找不到对应记录时，那一棒标「对方那边没找到这一棒的后续记录」。

## 项目结构

```text
backend/
  server.py      本机 HTTP 服务（--port / --demo / --open）
  grok_cache.py  读 Grok Bot 本地缓存（只读，跨平台查找目录）
  collab.py      办公室状态 + 协作流程重建
  insights.py    成员档案、成就、动态、日报、作息
  views.py       数据来源选择 + 应用你的设置（改名、隐藏、隐私）
  settings.py    data/settings.json 的读写与校验
  demo.py        演示团队
frontend/
  index.html  settings.html
  js/  i18n.js avatars.js common.js stage.js panels.js main.js settings.js
  css/app.css
tests/           python3 -B -m unittest discover -s tests
start.sh  start.command  start.bat
```

## 测试

```bash
python3 -B -m unittest discover -s tests -v
```

## 常见问题

- **页面显示「演示数据」**：没找到 Grok Bot 的缓存。先打开 Grok Bot 并登录一次，或到设置里填写数据目录。
- **端口被占用**：`python3 backend/server.py --port 19201`。
- **想截图分享**：打开设置里的隐私模式，所有消息内容都会被隐藏。

## 许可

代码以 [MIT](./LICENSE) 许可开源。所有角色、场景和图标都是项目自带的 SVG，可以随意使用。Grok 是 xAI 的商标，本项目与 xAI 无关。
