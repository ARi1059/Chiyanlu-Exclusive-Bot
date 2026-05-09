# 痴颜录专属 Bot 设计需求文档

## 1. 项目概述

**项目名称：** Chiyanlu-Exclusive-Bot
**平台：** Telegram
**用途：** 为"痴颜录"社区提供老师签到管理、课程展示、关键词查询等自动化服务
**部署方式：** VPS (systemd 服务)

---

## 2. 技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态成熟，Telegram Bot 库完善 |
| 框架 | aiogram 3.x | 异步架构，性能好，维护活跃 |
| 数据库 | SQLite + aiosqlite | 轻量无依赖，单机场景足够 |
| 定时任务 | APScheduler | 支持时区，与 asyncio 兼容 |
| 部署 | systemd | 稳定，自动重启，日志管理方便 |

---

## 3. 功能模块

### 3.1 老师签到模块

**流程：**

```
老师私聊 Bot 发送 "签到"
        ↓
Bot 验证该用户是否为已录入老师（通过 user_id）
        ↓
  ├─ 否 → 回复"您未被授权使用此功能"
  └─ 是 → 记录该老师今日签到状态，回复"签到成功"
```

**规则：**
- 仅已录入老师可签到
- 每日签到时间限制为当日 00:00 至 14:00     
- 当日 14:00 后不可签到
- 重复签到提示"今日已签到"

---

### 3.2 定时发布模块

**每日 14:00（北京时间 UTC+8）自动执行：**

1. 查询当日所有已签到老师
2. 生成 Inline Keyboard，每个老师一个按钮（按钮文本为为管理员预设，URL 为管理员预设链接）
3. 在管理员指定的频道/群组发送消息

**消息格式：**
```
📅 2025-01-15 开课老师 3位

[老师A按钮] [老师B按钮] [老师C按钮]
```

**次日 14:00 执行：**
- 删除前一天发送的消息（通过存储 message_id 实现）
- 发送当天新消息

---

### 3.3 管理员模块

**权限体系：**
- 超级管理员（Bot Owner）：可添加/移除管理员
- 管理员：可管理老师信息、设置频道

**交互方式：全按钮面板（Inline Keyboard）**

管理员私聊 Bot 发送 `/start` 或 `/admin` 后，Bot 展示主菜单面板：

```
🔧 痴颜录管理面板

[👩‍🏫 老师管理]  [👥 管理员管理]
[📢 频道设置]  [⚙️ 系统设置]
```

**👩‍🏫 老师管理子面板：**
```
👩‍🏫 老师管理

[➕ 添加老师]
[✏️ 编辑老师]
[❌ 删除老师]
[📋 老师列表]
[🔙 返回主菜单]
```

**👥 管理员管理子面板：**
```
👥 管理员管理

[➕ 添加管理员]
[➖ 移除管理员]
[📋 管理员列表]
[🔙 返回主菜单]
```

**📢 频道设置子面板：**
```
📢 频道/群组设置

[📌 设置发布频道]
[💬 设置响应群组]
[📋 查看当前设置]
[🔙 返回主菜单]
```

**⚙️ 系统设置子面板：**
```
⚙️ 系统设置

[⏰ 修改发布时间]
[⏳ 修改冷却时间]
[🔙 返回主菜单]
```

**面板设计原则：**
- 所有管理操作通过按钮完成，无需记忆任何命令
- 每个子面板都有"返回主菜单"按钮，支持层级导航
- 操作完成后自动返回上级面板
- 危险操作（删除老师、移除管理员）需二次确认按钮
- 编辑老师时展示该老师当前所有字段，每个字段一个编辑按钮

---

### 3.4 老师管理模块

**交互方式：引导式录入（Conversation State Machine）**

管理员点击"➕ 添加老师"后，Bot 进入逐步引导流程：

```
步骤 1/8：
📝 请输入老师的 Telegram 数字 ID：
                                        [❌ 取消]

管理员输入: 123456789
        ↓
步骤 2/8：
📝 请输入老师的 Telegram 用户名（不含@）：
                                        [❌ 取消]

管理员输入: xiayifei
        ↓
步骤 3/8：
📝 请输入老师的艺名：
                                        [❌ 取消]

管理员输入: 夏亦菲
        ↓
步骤 4/8：
📍 请输入老师的地区：
                                        [❌ 取消]

管理员输入: 天府一街
        ↓
步骤 5/8：
💰 请输入老师的价格信息（如 "1000P"）：
                                        [❌ 取消]

管理员输入: 1000P
        ↓
步骤 6/8：
🏷️ 请输入老师的标签（用空格或逗号分隔）：
例如：颜值 身材 服务好
                                        [❌ 取消]

管理员输入: 颜值 身材 服务好
        ↓
步骤 7/8：
🖼️ 请发送老师的展示图片（头像/宣传图）：
                            [⏭️ 跳过]  [❌ 取消]

管理员发送图片或点击跳过
        ↓
步骤 8/8：
🔗 请输入老师的按钮跳转链接（URL）：
                                        [❌ 取消]

管理员输入: https://t.me/xiayifei
        ↓
✅ 确认信息：
━━━━━━━━━━━━━━━
👤 夏亦菲
🆔 123456789 (@xiayifei)
📍 天府一街
💰 1000P
🏷️ 颜值 | 身材 | 服务好
🖼️ [已上传图片]
🔗 https://t.me/xiayifei
━━━━━━━━━━━━━━━

        [✅ 确认保存]  [❌ 取消]
```

**引导式录入设计原则：**
- 每步只收集一项信息，降低操作负担
- 每步都有"取消"按钮，可随时退出
- 图片为可选项，提供"跳过"按钮
- 最后一步展示完整信息供确认，避免录入错误
- 使用 FSM（有限状态机）管理对话状态
- 超时 5 分钟未响应自动取消，提示管理员

**编辑老师流程：**

管理员点击"✏️ 编辑老师"→ 展示老师列表（每人一个按钮）→ 选择老师后展示：

```
✏️ 编辑 王老师

当前信息：
🆔 123456789 (@teacher_wang)
💰 300/节
🏷️ 数学 | 高中 | 一对一
🖼️ [已上传]
🔗 https://t.me/teacher_wang

选择要修改的字段：
[📝 艺名]     [📍 地区]
[💰 价格]     [🏷️ 标签]
[🖼️ 图片]     [🔗 链接]
[🔙 返回]
```

点击对应字段按钮后，Bot 提示输入新值，修改完成后返回编辑面板。

**老师信息字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | Integer | 是 | Telegram 数字 ID（唯一标识） |
| username | String | 是 | Telegram 用户名 |
| display_name | String | 是 | 艺名/展示名称 |
| region | String | 是 | 地区（如 "天府一街"） |
| price | String | 是 | 价格信息（如 "1000P"） |
| tags | String[] | 是 | 标签列表（如 ["颜值", "身材", "服务好"]） |
| photo_file_id | String | 否 | Telegram 图片 file_id |
| button_url | String | 是 | 按钮/超链接跳转链接 |
| button_text | String | 否 | 按钮显示文本（默认为 display_name） |
| is_active | Boolean | — | 是否启用，默认 true |

---

### 3.5 关键词响应模块

**触发条件：** 用户在指定群组内发送消息
**匹配方式：** 精准匹配（用户发送的完整消息内容 = 某个关键词，非模糊/包含匹配）

**两种模式共存，同时生效：**

---

#### 模式 A：精准匹配老师艺名（display_name）→ 图片 + 文字 + 按钮

当用户发送的消息 **精确等于** 某位老师的艺名时，展示该老师的完整卡片：

```
[老师图片（如已上传）]

👤 夏亦菲
📍 天府一街
💰 1000P
🏷️ 颜值 | 身材 | 服务好

        [📩 联系老师]  ← Inline URL 按钮，跳转 button_url
```

- 有图片：发送图片消息，caption 为文字信息，附带 Inline 按钮
- 无图片：发送纯文字消息 + Inline 按钮
- 艺名唯一对应一位老师，因此模式 A 始终只展示一人

---

#### 模式 B：精准匹配标签/地区/价格 → 超链接列表

当用户发送的消息 **精确等于** 某个标签、地区或价格值时，以超链接列表展示所有匹配的老师：

**匹配示例：**
- 用户发送 `御姐` → 匹配所有 tags 中包含"御姐"的老师
- 用户发送 `天府一街` → 匹配所有 region 为"天府一街"的老师
- 用户发送 `1000P` → 匹配所有 price 为"1000P"的老师

**响应格式（使用 Telegram HTML 超链接）：**

```
🔍 找到 3 位相关老师：

夏亦菲 - 天府一街 - 1000P
林清雪 - 天府三街 - 800P
苏暮晚 - 金融城 - 1200P
```

其中每一行都是一个超链接，整行文字链接到对应老师的 `button_url`。

**实际发送的 HTML 格式：**
```html
🔍 找到 3 位相关老师：

<a href="https://t.me/xiayifei">夏亦菲 - 天府一街 - 1000P</a>
<a href="https://t.me/linqingxue">林清雪 - 天府三街 - 800P</a>
<a href="https://t.me/sumuwan">苏暮晚 - 金融城 - 1200P</a>
```

- 每行格式：`艺名 - 地区 - 价格`
- 整行作为超链接，点击跳转到该老师的 `button_url`
- 无需额外按钮，文字本身即可点击

---

#### 两种模式的共存关系

模式 A 和模式 B **同时生效、互不排斥**：

| 用户发送 | 触发模式 | 原因 |
|----------|----------|------|
| `夏亦菲` | A + B | 精确匹配艺名（触发A），同时若其他老师标签中也有"夏亦菲"则也触发B |
| `御姐` | B | 精确匹配标签，展示所有含"御姐"标签的老师列表 |
| `天府一街` | B | 精确匹配地区，展示该地区所有老师列表 |
| `1000P` | B | 精确匹配价格，展示该价格所有老师列表 |

**典型场景：** 用户发送 `夏亦菲`
- 模式 A 触发：展示夏亦菲的完整卡片（图片+详情+按钮）
- 若"夏亦菲"同时也是某个标签值，模式 B 也会触发（实际中艺名一般不会作为标签，所以通常只触发 A）

---

**规则：**
- 仅在管理员指定的群组内响应
- **精准匹配**：用户消息必须完整等于关键词，不做模糊/子串匹配
- 匹配不区分大小写
- 无匹配结果时不回复（避免刷屏）
- 可设置响应冷却时间（防止同一用户频繁触发）
- 模式 A 的图片使用 Telegram file_id 缓存，无需重复上传

---

## 4. 数据库设计

### 表结构

```sql
-- 管理员表
CREATE TABLE admins (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_super INTEGER DEFAULT 0,  -- 1=超级管理员
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 老师表
CREATE TABLE teachers (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    region TEXT NOT NULL,  -- 地区
    price TEXT NOT NULL,
    tags TEXT NOT NULL,  -- JSON 数组存储
    photo_file_id TEXT,  -- Telegram 图片 file_id，可为空
    button_url TEXT NOT NULL,
    button_text TEXT,  -- 按钮显示文本，为空时使用 display_name
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 签到记录表
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    checkin_date TEXT NOT NULL,  -- 格式: YYYY-MM-DD
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(teacher_id, checkin_date),
    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id)
);

-- Bot 配置表
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- 存储: publish_channel_id, response_group_ids, cooldown_seconds 等

-- 已发送消息记录（用于次日删除）
CREATE TABLE sent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    sent_date TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. 项目结构

```
Chiyanlu-Exclusive-Bot/
├── bot/
│   ├── __init__.py
│   ├── main.py              # 入口，初始化 Bot 和调度器
│   ├── config.py            # 配置加载（token、超管ID等）
│   ├── database.py          # 数据库初始化与连接
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── admin_panel.py   # 管理员按钮面板与回调处理
│   │   ├── teacher_flow.py  # 老师录入引导流程（FSM）
│   │   ├── teacher_checkin.py  # 老师签到处理
│   │   └── keyword.py       # 关键词响应处理（图片+文字+按钮）
│   ├── keyboards/
│   │   ├── __init__.py
│   │   └── admin_kb.py      # 所有 Inline Keyboard 面板定义
│   ├── states/
│   │   ├── __init__.py
│   │   └── teacher_states.py  # FSM 状态定义
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── tasks.py         # 定时任务（发布、删除）
│   └── utils/
│       ├── __init__.py
│       └── permissions.py   # 权限校验工具
├── data/                    # 运行时数据目录
│   └── bot.db               # SQLite 数据库（自动创建）
├── .env.example             # 环境变量模板
├── requirements.txt
├── DESIGN.md                # 本文档
└── README.md
```

---

## 6. 配置项

通过 `.env` 文件管理：

```env
BOT_TOKEN=your_telegram_bot_token
SUPER_ADMIN_ID=123456789
DATABASE_PATH=./data/bot.db
TIMEZONE=Asia/Shanghai
PUBLISH_TIME=14:00
COOLDOWN_SECONDS=30
```

---

## 7. 边界情况与约束

| 场景 | 处理方式 |
|------|----------|
| 当日无老师签到 | 14:00 不发送消息 |
| Bot 重启后恢复 | 从数据库读取当日签到状态，不丢失 |
| 老师被移除后签到 | 拒绝并提示 |
| 频道/群组未设置 | 管理员命令提示先设置 |
| 消息删除失败（已被手动删除） | 捕获异常，跳过 |
| 多群组支持 | 支持设置多个响应群组 |

---

## 8. 后续可扩展方向（暂不实现）

- 老师签到统计（月度出勤率）
- 用户收藏老师
- 课程预约功能
- Web 管理面板
- 多语言支持
