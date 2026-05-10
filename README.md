# Chiyanlu-Exclusive-Bot

Chiyanlu-Exclusive-Bot 是一个基于 Telegram 的社区管理 Bot，用于提供老师签到管理、每日开课信息发布、老师信息管理、关键词查询和管理员后台操作等功能。

项目使用 Python 3.11+、aiogram 3.x、SQLite 和 APScheduler 构建，适合部署在 VPS 上作为长期运行的 systemd 服务。

## 功能概览

### 老师签到

- 已录入且启用的老师可在私聊 Bot 中发送“签到”。
- Bot 会记录老师当天签到状态。
- 支持重复签到检测。
- 支持按发布时间作为签到截止时间。
- 停用或未录入的老师无法签到。

### 每日自动发布

- Bot 会在配置的每日发布时间自动执行发布任务。
- 查询当天已签到老师。
- 生成包含老师按钮的 Telegram Inline Keyboard。
- 将当天开课老师列表发送到管理员配置的频道或群组。
- 发布新消息前会尝试删除前一天已发送的消息。

### 管理员面板

管理员可通过 `/start` 或 `/admin` 打开按钮式管理面板，无需记忆复杂命令。

支持功能包括：

- 老师管理
  - 添加老师
  - 编辑老师
  - 停用老师
  - 启用老师
  - 查看老师列表
- 管理员管理
  - 添加管理员
  - 移除管理员
  - 查看管理员列表
- 频道和群组设置
  - 设置发布频道
  - 设置响应群组
  - 查看当前配置
- 系统设置
  - 系统状态检查
  - 发布预览
  - 手动发布
  - 今日签到统计
  - 修改发布时间
  - 修改响应冷却时间

### 老师信息管理

添加老师时使用引导式录入流程，逐步收集以下信息：

- Telegram 数字 ID
- Telegram 用户名
- 艺名或展示名称
- 地区
- 价格
- 标签
- 展示图片，可选
- 按钮跳转链接

编辑老师时可单独修改字段，包括艺名、地区、价格、标签、图片和链接。

### 关键词查询

Bot 可在管理员指定的群组中响应关键词。

匹配规则：

- 精准匹配老师艺名：返回老师卡片，可包含图片、文字信息和按钮。
- 精准匹配地区、价格或标签：返回符合条件的老师超链接列表。
- 匹配不区分大小写。
- 无匹配结果时不回复，避免刷屏。
- 支持冷却时间，减少频繁触发。

## 技术栈

| 组件 | 说明 |
| --- | --- |
| Python | 3.11+ |
| aiogram | Telegram Bot 异步框架 |
| SQLite | 本地轻量数据库 |
| aiosqlite | SQLite 异步访问 |
| APScheduler | 定时任务调度 |
| python-dotenv | 环境变量加载 |
| systemd | 推荐生产部署方式 |

## 项目结构

```text
Chiyanlu-Exclusive-Bot/
├── bot/
│   ├── main.py                 # 程序入口，初始化 Bot、数据库和调度器
│   ├── config.py               # 环境变量配置加载
│   ├── database.py             # 数据库初始化与 CRUD 操作
│   ├── handlers/
│   │   ├── admin_panel.py      # 管理员面板与系统设置回调
│   │   ├── keyword.py          # 群组关键词响应
│   │   ├── teacher_checkin.py  # 老师签到处理
│   │   └── teacher_flow.py     # 老师添加、编辑、停用和启用流程
│   ├── keyboards/
│   │   └── admin_kb.py         # Inline Keyboard 定义
│   ├── scheduler/
│   │   └── tasks.py            # 每日发布和定时任务逻辑
│   ├── states/
│   │   └── teacher_states.py   # FSM 状态定义
│   └── utils/
│       └── permissions.py      # 管理员权限校验
├── data/                       # SQLite 数据库目录，运行时自动创建
├── .env.example                # 环境变量示例
├── requirements.txt            # Python 依赖
└── docs/
    ├── DESIGN.md               # 设计需求文档
    └── DEPLOYMENT.md           # 部署文档
```

## 环境变量

复制 `.env.example` 为 `.env`，并按实际情况修改：

```env
BOT_TOKEN=your_telegram_bot_token
SUPER_ADMIN_ID=123456789
DATABASE_PATH=./data/bot.db
TIMEZONE=Asia/Shanghai
PUBLISH_TIME=14:00
COOLDOWN_SECONDS=30
```

配置说明：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| BOT_TOKEN | 是 | Telegram Bot Token |
| SUPER_ADMIN_ID | 是 | 超级管理员 Telegram 数字 ID |
| DATABASE_PATH | 否 | SQLite 数据库路径，默认 `./data/bot.db` |
| TIMEZONE | 否 | 时区，默认 `Asia/Shanghai` |
| PUBLISH_TIME | 否 | 每日自动发布时间，格式 `HH:MM` |
| COOLDOWN_SECONDS | 否 | 群组关键词响应冷却时间，单位秒 |

## 安装与运行

### 1. 克隆项目

```bash
git clone <repository-url>
cd Chiyanlu-Exclusive-Bot
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填写真实的 Bot Token 和超级管理员 ID。

### 5. 启动 Bot

```bash
python3 -m bot.main
```

首次启动时会自动初始化数据库，并创建必要的数据表。

## Telegram 使用说明

### 获取超级管理员 ID

可通过 Telegram 用户信息 Bot 或其他可信方式获取自己的 Telegram 数字 ID，然后写入 `.env` 中的 `SUPER_ADMIN_ID`。

### 初始化管理

1. 启动 Bot。
2. 超级管理员私聊 Bot，发送 `/start` 或 `/admin`。
3. 在管理面板中完成基础配置：
   - 设置发布频道。
   - 设置响应群组。
   - 添加老师。
   - 如需多人管理，添加管理员。

### 设置发布频道

在“频道/群组设置”中设置发布频道 ID。

注意：Bot 必须已加入目标频道或群组，并具备发送消息权限。如果需要删除前一天的发布消息，还需要具备删除消息权限。

### 设置响应群组

在“频道/群组设置”中设置响应群组。只有配置过的群组会触发关键词查询。

### 添加老师

在“老师管理”中点击“添加老师”，按照提示依次输入老师信息。保存后，该老师可以：

- 私聊 Bot 进行签到。
- 出现在每日发布内容中。
- 被群组关键词查询匹配。

### 老师签到

老师在私聊 Bot 中发送：

```text
签到
```

Bot 会根据老师状态、当天是否已签到、当前时间是否超过截止时间进行处理。

## 数据库说明

项目使用 SQLite，默认数据库文件为：

```text
./data/bot.db
```

主要数据表：

| 表名 | 用途 |
| --- | --- |
| admins | 管理员和超级管理员 |
| teachers | 老师基础信息 |
| checkins | 老师每日签到记录 |
| config | Bot 运行配置 |
| sent_messages | 已发送发布消息记录 |

建议定期备份 `data/bot.db`，尤其是在生产环境中。

## 定时发布逻辑

每日发布时间由 `PUBLISH_TIME` 或后台系统设置决定。

发布任务会执行以下流程：

1. 获取当前日期。
2. 删除前一天由 Bot 发送并记录的发布消息。
3. 查询当天已签到老师。
4. 如果没有老师签到，则跳过发布。
5. 如果存在签到老师，则生成按钮并发送到发布频道。
6. 保存发送记录，用于后续删除。

管理员也可以在系统设置中使用：

- 发布预览：在私聊中查看当天将发布的内容，不会发送到频道。
- 手动发布：立即将当天签到汇总发送到已配置的发布频道。

## 开发检查

可使用 Python 编译检查基础语法：

```bash
python3 -m compileall bot
```

## 生产部署示例

以下是 systemd 服务示例，可根据实际路径调整。

```ini
[Unit]
Description=Chiyanlu Exclusive Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/Chiyanlu-Exclusive-Bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/Chiyanlu-Exclusive-Bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

常用命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable chiyanlu-bot
sudo systemctl start chiyanlu-bot
sudo systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -f
```

## 常见问题

### Bot 无法启动

检查：

- `.env` 是否存在。
- `BOT_TOKEN` 是否正确。
- `SUPER_ADMIN_ID` 是否为数字。
- 依赖是否已安装。

### 管理员无法打开后台

检查：

- 当前 Telegram 用户 ID 是否等于 `SUPER_ADMIN_ID`。
- 如果是普通管理员，确认是否已由超级管理员添加。

### 定时发布没有发送消息

检查：

- 是否已设置发布频道。
- Bot 是否有频道或群组发送权限。
- 当天是否有老师完成签到。
- 发布时间和时区配置是否正确。

### 群组关键词没有响应

检查：

- 是否已设置响应群组。
- Bot 是否在该群组内。
- 用户消息是否完整等于老师艺名、地区、价格或标签。
- 是否处于冷却时间内。

## 相关文档

更多产品设计和功能细节可查看 [docs/DESIGN.md](docs/DESIGN.md)，部署细节见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。
