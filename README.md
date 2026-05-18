# Chiyanlu-Exclusive-Bot

**痴颜录 Telegram 私域运营 Bot**——一个面向社区运营的 Telegram 中台雏形。

项目从 v1 的「老师签到 + 每日发布 + 关键词查询」起步，已逐步扩展为覆盖**老师档案、用户私聊菜单、评价/报告、积分、报销、抽奖、必关订阅、推广追踪、发布模板、日报/周报**的运营平台。所有子系统共用一套 SQLite 后台、一套 systemd 单进程部署。

> 本 README 反映截至 2026-05-18 的实际代码能力。早期版本的产品需求与设计见 [`docs/DESIGN.md`](docs/DESIGN.md)（v1）和 [`docs/FEATURES-v2.md`](docs/FEATURES-v2.md)（v2 增量），各阶段实施记录在 `docs/PHASE-*-IMPL.md` / `docs/*-FEATURE-DRAFT.md`。运维稳定化路线见 [`docs/STABILITY-AUDIT-2026-05-18.md`](docs/STABILITY-AUDIT-2026-05-18.md)。

---

## 目录

- [角色与功能矩阵](#角色与功能矩阵)
- [按子系统的能力清单](#按子系统的能力清单)
- [技术栈](#技术栈)
- [数据库](#数据库)
- [项目结构](#项目结构)
- [环境变量](#环境变量)
- [快速开始（开发环境）](#快速开始开发环境)
- [生产部署](#生产部署)
- [日常运维（update.sh）](#日常运维updatesh)
- [备份与恢复](#备份与恢复)
- [当前稳定化状态](#当前稳定化状态)
- [常见问题](#常见问题)
- [相关文档](#相关文档)

---

## 角色与功能矩阵

| 角色 | 主要入口 | 能做什么 |
|---|---|---|
| **普通用户** | 私聊 `/start`、群组关键词、群组按钮 | 浏览每日开课、私聊主菜单（推荐 / 筛选 / 收藏 / 提醒 / 最近看过 / 搜索历史 / 积分 / 报销 / 写评价）、群组直接搜艺名/地区/价格/标签、领抽奖、写评价并申请报销 |
| **老师** | 私聊发送「签到」、`/me` 自助菜单 | 每日签到、设置今日状态（取消/已满）、查看个人统计、自助修改部分档案字段、上传/管理相册 |
| **管理员** | `/admin` 后台 | 老师管理、签到/发布概览、关键词测试、热门推荐管理、报销审批、抽奖管理、报表查看 |
| **超级管理员** | `/admin`（含超管专属入口） | 配置发布频道/讨论群/必关订阅、管理管理员、调整系统设置、积分加扣分、超管报告审核（rreview）、报销池配置、抽奖创建/开奖、发布模板管理、报表设置、报销重置 voucher |

---

## 按子系统的能力清单

### 1. 每日发布 + 老师签到

- 老师在私聊发送「签到」即视为今日开课，可设置「取消今日」「已满」状态及取消原因
- 调度器在 `PUBLISH_TIME` 自动汇总当日已签到老师，发布到指定频道；老师按钮可定制文案（艺名 / 地区+艺名 / 价格）
- 发布前自动删除前一日的发布消息（需 Bot 具备删除权限）
- 签到提醒：在发布前 N 分钟向未签到老师推送提醒
- 管理员可在后台「发布预览」「立即发布」「修改发布时间」

### 2. 群组关键词 + 组合搜索

- 精确匹配老师艺名 → 返回卡片（图 + 文 + 按钮）
- 匹配地区 / 价格 / 标签 → 返回符合条件的老师超链接列表
- 组合搜索：`#地区 #价格档 #标签` 多维过滤
- 不区分大小写，无匹配静默跳过
- 冷却时间防刷屏；群组级别的快捷菜单按钮（今日开课、热门、搜索）

### 3. 用户私聊中台（主菜单 13 项）

- **📚 今天能约谁**：当日已开课老师快捷列表
- **🎯 帮我推荐 / 🔥 热门推荐**：基于热度分 + 个性化标签
- **🔎 按条件找**：地区 × 价格 × 标签 多步筛选 FSM
- **⭐ 我的收藏**：列表分页，可直接进详情页或取消收藏
- **🕘 最近看过**：浏览历史
- **🔍 直接搜索**：艺名/地区/价格 精确/模糊查
- **💝 收藏开课**：仅显示「收藏过且今日已签到」的老师
- **🔔 我的提醒**：管理老师开课通知订阅
- **📜 搜索历史**：最近搜索词快捷回放
- **💰 我的积分**：积分总览 + 明细分页
- **🧾 我的报销**：报销总览 + 月池/周限额 + 明细分页
- **📝 写评价**：进入「个人评价主页」（统计 + 筛选 + 自己历史评价分页 + 写新评价入口）

### 4. 老师详情页

- 单卡片展示老师全档案（含基本信息 / 价格 / 服务内容 / 禁忌 / 相册 / 评价统计 + 最近 3 条评价）
- 按钮：📩 联系老师 · ⭐ 收藏 · 🔔 开课提醒 · 📖 查看全部评价 · ✨ 相似推荐 · 📝 写评价 · 🔙 返回

### 5. 老师档案录入 + 自助管理

- 管理员录入：「转发老师消息」起步的 9 步详细档案 FSM（auto-extract user_id / username / 联系方式；自动派生 description / taboos / 价格标签）
- 老师自助 `/me`：可修改艺名/地区/价格/标签/链接/简介；相册 add / remove / replace；管理员锁定的字段（如 button_url）显式禁用并提示申请
- 频道档案帖一键同步：管理员修改后台档案 → 一键刷新频道 caption + 评价区按钮

### 6. 评价 / 报告系统

- 入口：主菜单「📝 写评价」→ 个人评价主页（统计 / 状态筛选 / 评级筛选 / 分页 / 写车评） → 输入艺名 → **卡片驱动 FSM**
- 卡片中心视图：9 个字段按钮（出击证明 / 评级 / 6 维评分 / 过程描述）任意顺序填写
- 提交模式：[😟 匿名提交]（隐藏 user_id） / [😎 默认提交]
- 资格审查：3 项限频 + 必关订阅校验
- 报销意愿：满足资格条件时弹出报销询问（按价位分档 100/150/200 元）
- 超管审核（rreview）：媒体组预览 + 6 维评分一览 + 通过/驳回 + 自定义加分；驳回需选预设原因或填自定义
- 通过后自动发布到讨论群（半匿名 `****6789` 或匿名 `匿*`），并联动创建 pending reimbursement

### 7. 积分系统

- 用户积分总账：评价通过 +N、抽奖参与 -N（可配置）、手动加扣分
- 超管工具：按 user_id / @username / first_name 查询积分；4 步 FSM 加扣分（含套餐快捷 +1/+5/+8）；积分明细分页
- 用户侧：「💰 我的积分」总览 + 明细分页（含老师反查）

### 8. 报销系统

- 资格：`user.total_points ≥ reimbursement_min_points`（默认 5）+ 老师价位 > 0
- 金额规则：displayed price ≤8P → 100 元 / =9P → 150 元 / ≥10P → 200 元
- 频率限制：周限 1 笔（ISO week）+ 月度池总额配置
- Feature toggle：报销关闭时仍录入 `queued` 状态（admin 可在「报销名单」单独激活），开启时进 pending 队列
- 超管审批：通过 / 驳回（必填原因） / 重置某用户周 voucher
- 用户侧「🧾 我的报销」总览 + 明细分页 + 状态显示（待审/已通过/已驳回/已取消/已录入名单）

### 9. 抽奖系统

- 超管 10 步 FSM 创建抽奖：名称 / 描述 / 封面 / 入场方式（button / code） / 奖品数量 / 奖品描述 / 必关频道 / 发布模式（立即/定时） / 开奖时间 / 入场积分门票
- 触发方式：button（频道海报按钮）或 code（私聊口令）
- 入场扣积分：用户取消时自动退积分
- 调度：APScheduler 定时发布 + 定时开奖（bot 重启自动重注册）
- 客服链接配置（中奖后跳转领奖）
- 抽奖编辑 / 提前开奖 / 取消并退款

### 10. 必关订阅校验

- 写评价 / 抽奖入场前校验用户已加入指定频道/群组
- 超管管理 active 列表（含友好名称 + 邀请链接）
- bot 异常（频道不存在 / bot 没权限）自动 skip + warning

### 11. 推广链接 + 来源统计（已下线入口，handler / DB 保留）

- 入口已下架；DB 字段 + handler 文件保留以便未来恢复

### 12. 发布模板

- 多套发布模板（每日开课消息文案）
- 超管设置默认模板，立即生效

### 13. 日报 / 周报

- 调度器定时生成统计：当日签到数 / 发布老师数 / 新增评价数 / 报销/抽奖动作数等
- 推送到指定 chat_id

### 14. 审计日志

- 所有超管/管理员关键操作（老师增删 / 报销批驳 / 加分 / 配置变更等）写入 `admin_audit_logs`
- 后台「审计」入口分页查看

---

## 技术栈

| 组件 | 版本 / 说明 |
|---|---|
| Python | 3.11+ |
| aiogram | 3.13.1（Telegram Bot 异步框架） |
| SQLite | 3.x，**已启用 WAL 模式** |
| aiosqlite | 0.20.0（SQLite 异步访问） |
| APScheduler | 3.10.4（每日发布 / 报表 / 抽奖调度） |
| python-dotenv | 1.0.1 |
| 部署方式 | systemd 单进程 polling，**不推荐 Docker / Webhook**（详见稳定化报告） |

---

## 数据库

SQLite 单文件，默认 `./data/bot.db`，**已启用 WAL 模式**（`PRAGMA journal_mode=WAL`）。

当前 23 张表，按模块分组：

| 模块 | 主要表 |
|---|---|
| 管理员与配置 | `admins`, `bot_config`, `required_subscriptions`, `publish_templates`, `report_settings` |
| 老师资料与签到 | `teachers`, `checkins`, `teacher_daily_status`, `teacher_channel_posts` |
| 用户与互动 | `users`, `favorites`, `user_teacher_views`, `notification_subscriptions`, `user_search_history` |
| 来源追踪与用户画像 | `user_sources`, `user_tags`, `promo_links`, `source_events` |
| 评价 / 报告 | `teacher_reviews`（含 `request_reimbursement` / `anonymous` 列） |
| 积分 | `point_transactions`（用户 `users.total_points` 派生） |
| 报销 | `reimbursements`（5 状态 CHECK：pending/approved/rejected/cancelled/queued）+ `reimbursement_resets` |
| 抽奖 | `lotteries`, `lottery_entries`, `lottery_required_chats` |
| 操作记录 | `admin_audit_logs`, `user_events`, `sent_messages` |

> 详细字段定义见 [`bot/database.py`](bot/database.py)（DDL 在文件开头 `init_db`）。迁移历史与设计记录见 `docs/PHASE-*-IMPL.md`。

---

## 项目结构

```
Chiyanlu-Exclusive-Bot/
├── bot/
│   ├── main.py                        # 入口：30 个 router 注册 + 调度器启动
│   ├── config.py                      # 环境变量加载
│   ├── database.py                    # 5960 行单文件：DDL + 9 个迁移 + 全部 CRUD
│   ├── handlers/                      # 35 个 router 文件，按子系统组织
│   │   ├── admin_panel.py             # 管理员后台主菜单
│   │   ├── admin_lottery.py           # 抽奖管理（创建 / 编辑 / 开奖）
│   │   ├── admin_points.py            # 积分查询 / 加扣分
│   │   ├── admin_reimburse.py         # 报销审批 / 重置 voucher
│   │   ├── admin_review.py            # 评价审核（普管视角）
│   │   ├── rreview_admin.py           # 超管报告审核队列（带媒体组预览）
│   │   ├── review_submit.py           # 个人评价主页 + 入口分流
│   │   ├── review_card.py             # 卡片驱动评价 FSM
│   │   ├── review_list.py             # 评价分页列表
│   │   ├── teacher_profile.py         # 老师档案 9 步详细录入 + 一键同步
│   │   ├── teacher_self.py            # 老师自助菜单 /me
│   │   ├── teacher_detail.py          # 老师详情页
│   │   ├── teacher_daily_status.py    # 今日状态（取消/已满）
│   │   ├── teacher_checkin.py         # 老师签到（StateFilter(None)）
│   │   ├── teacher_flow.py            # 简版老师 CRUD（保留）
│   │   ├── user_panel.py              # 主菜单
│   │   ├── user_search.py             # 关键词 / 艺名搜索 + 历史
│   │   ├── user_filter.py             # 多维筛选 FSM
│   │   ├── user_recommend.py          # 推荐 / 热门
│   │   ├── user_history.py            # 搜索历史 / 提醒
│   │   ├── user_points.py             # 我的积分
│   │   ├── user_reimburse.py          # 我的报销
│   │   ├── favorite.py                # 收藏切换
│   │   ├── hot_teachers.py            # 热门推荐管理
│   │   ├── keyword.py                 # 群组关键词 catch-all
│   │   ├── lottery_entry.py           # 抽奖参与（StateFilter(None)）
│   │   ├── discussion_anchor_listener.py  # 讨论群锚消息捕获
│   │   ├── subreq_admin.py            # 必关订阅管理
│   │   ├── publish_templates.py       # 发布模板
│   │   ├── report_settings.py         # 报表设置
│   │   ├── user_tags.py               # 用户标签管理
│   │   ├── start_router.py            # /start 角色分流
│   │   └── noop_handlers.py           # noop:* 占位 callback
│   ├── keyboards/                     # admin_kb.py / user_kb.py / teacher_self_kb.py
│   ├── scheduler/
│   │   ├── tasks.py                   # 每日发布 / 签到提醒 / 日报 / 周报
│   │   └── lottery_tasks.py           # 抽奖发布 / 开奖调度
│   ├── states/                        # 30+ StatesGroup（FSM）
│   └── utils/                         # 渲染 / 通知 / 必关校验 / 抽奖逻辑等
├── data/                              # SQLite 数据库目录（已 .gitignore）
├── backups/                           # update.sh 自动备份目录（已 .gitignore）
├── docs/                              # 设计 + 实施 + 部署 + 稳定化文档
├── update.sh                          # 运维更新 + 回滚 + 健康检查脚本
├── .env.example                       # 环境变量模板
├── .gitignore
└── requirements.txt
```

---

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

```env
BOT_TOKEN=your_telegram_bot_token
SUPER_ADMIN_ID=123456789
DATABASE_PATH=./data/bot.db
TIMEZONE=Asia/Shanghai
PUBLISH_TIME=14:00
COOLDOWN_SECONDS=30
```

| 变量 | 必填 | 说明 |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram BotFather 颁发的 token |
| `SUPER_ADMIN_ID` | ✅ | 超管 Telegram 数字 ID |
| `DATABASE_PATH` | ❌ | SQLite 路径，默认 `./data/bot.db` |
| `TIMEZONE` | ❌ | 时区，默认 `Asia/Shanghai` |
| `PUBLISH_TIME` | ❌ | 每日发布时间 `HH:MM` |
| `COOLDOWN_SECONDS` | ❌ | 群组关键词冷却秒数 |

⚠️ **`.env` 不可提交**（已写入 `.gitignore`）。`.env` 中含 `BOT_TOKEN`，泄露后必须立刻去 BotFather `/revoke` 重发。

---

## 快速开始（开发环境）

```bash
git clone <repository-url>
cd Chiyanlu-Exclusive-Bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # 填入真实 BOT_TOKEN / SUPER_ADMIN_ID
python3 -m bot.main           # 首次启动自动初始化数据库
```

启动后超管私聊 Bot 发送 `/start` 进入管理面板，依次配置：发布频道 → 讨论群 → 必关订阅 → 添加管理员/老师。

---

## 生产部署

### 系统依赖

- **Python 3.11+**
- **sqlite3 命令行工具**（用于 `update.sh` 的 WAL-safe 备份与 `integrity_check`）：
  ```bash
  # Debian / Ubuntu
  apt install sqlite3 python3-venv

  # RHEL / CentOS / Rocky
  yum install sqlite python3
  ```
- **systemd**

### 推荐目录结构

```text
/opt/Chiyanlu-Exclusive-Bot/
├── bot/                # 代码
├── .venv/              # 虚拟环境
├── data/bot.db         # 数据库（+ bot.db-wal + bot.db-shm）
├── backups/            # update.sh 自动备份
└── .env                # 敏感配置（chmod 600）
```

### systemd 单元

```ini
[Unit]
Description=Chiyanlu Exclusive Telegram Bot
After=network.target

[Service]
Type=simple
User=chiyanlu                                     # 强烈建议非 root
Group=chiyanlu
WorkingDirectory=/opt/Chiyanlu-Exclusive-Bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/Chiyanlu-Exclusive-Bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable chiyanlu-bot
sudo systemctl start chiyanlu-bot
journalctl -u chiyanlu-bot -f
```

### 部署注意

- **`.env` 必须 `chmod 600 .env` 且仅 service 用户可读**
- **运行用户**：
  - 测试 / 个人小规模部署可以用 root 快速跑通
  - **生产环境不建议长期用 root 运行**，长期运营建议创建独立 `chiyanlu` 用户
  - 原因：降低 Bot token 泄露、依赖漏洞或误操作造成的影响面
  - 详细做法见 [`docs/DEPLOYMENT.md` §9.2](docs/DEPLOYMENT.md#92-推荐生产创建独立用户运行)
- **`data/` 目录权限**：service 用户可读写；备份目录同
- **不需要 Docker**：项目设计为单进程 polling，systemd 已足够；Docker 化会让 `update.sh` 的备份/回滚/healthcheck 失效

详细部署文档：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

---

## 日常运维（update.sh）

`update.sh`（项目根目录）是统一的运维入口，覆盖更新 / 回滚 / 健康检查：

```bash
./update.sh                 # 默认：拉代码 + 装依赖 + WAL-safe 备份 + 重启服务 + 日志扫描
./update.sh start           # 仅启动（不更新代码）
./update.sh stop            # 仅停止
./update.sh restart         # 仅重启（不更新代码，改 .env 后用）
./update.sh status          # 显示运行状态和最近 20 行日志
./update.sh rollback        # 紧急回滚：还原最近一次备份 + git reset --hard HEAD~1
./update.sh help
```

`update.sh` 的安全特性：

- **拉代码前**自动 schema-diff 警告（检测远程 commits 是否含新 `_migrate_*` / `ALTER TABLE`）
- **备份**：`sqlite3 .backup`（WAL-safe）+ `PRAGMA integrity_check` 必须返回 `ok`，保留最近 10 份
- **重启后**：systemctl is-active 健康轮询 15s + journalctl 日志扫描 `Traceback / CRITICAL / 迁移失败` 关键字
- **rebase + autostash**：兼容服务器侧本地未推送提交（如 .gitignore 调整）
- **rollback** 还原 DB 前自动清残留 `-wal` / `-shm`，避免旧 WAL replay 污染恢复结果

---

## 备份与恢复

⚠️ **本项目已启用 SQLite WAL 模式。数据库由 3 个文件组成**：

```text
data/bot.db          # 主库
data/bot.db-wal      # 预写日志（最近未 checkpoint 的写入）
data/bot.db-shm      # 共享内存映射
```

### ❌ 不要直接 cp 主库

```bash
# 错误：会丢掉仍在 bot.db-wal 里未 checkpoint 的最近写入
cp data/bot.db /backup/
```

### ✅ 正确：`sqlite3 .backup` 在线一致性快照

```bash
TS=$(date +%F-%H%M%S)
sqlite3 data/bot.db ".backup '/backup/bot-${TS}.db'"
sqlite3 "/backup/bot-${TS}.db" "PRAGMA integrity_check;"   # 必须返回 ok
```

详细备份方案（含 crontab 自动备份脚本模板）见 [`docs/DEPLOYMENT.md` §14](docs/DEPLOYMENT.md)。

**建议定期备份**：crontab 每日凌晨 03:30 自动 `.backup` + 保留 30 份。

---

## 当前稳定化状态

> 详细审查报告见 [`docs/STABILITY-AUDIT-2026-05-18.md`](docs/STABILITY-AUDIT-2026-05-18.md)。

### ✅ 已完成（截至 2026-05-18）

#### 代码层稳定化

| 项 | 说明 | commit |
|---|---|---|
| `.gitignore` 敏感文件保护 | `.env` / `data/` / `backups/` / `*.db` / `.venv/` / IDE 全覆盖 + 已纳入版本控制 | `7b1be01` |
| FSM 抢占修复 | `teacher_checkin` 和 `lottery_entry` 私聊 fallback 加 `StateFilter(None)`，避免劫持其它 FSM 中的文字输入 | `7b1be01` |
| SQLite WAL + busy_timeout | `get_db()` 启用 `journal_mode=WAL` / `synchronous=NORMAL` / `busy_timeout=5000`；并发吞吐显著改善 | `afb239a` |
| `update.sh` WAL-safe 备份 | 备份用 `sqlite3 .backup` + `PRAGMA integrity_check`；rollback 还原前清 `-wal`/`-shm` 残留 | `9cc0f8b` |
| 报销迁移半完成态自愈 | `_migrate_reimbursements_queued_status` 重写 5 个状态分支：正常已迁移 / 半完成态自愈 / 残留空 _new 清理 / 非空 _new 保护 / 标准重建（含 BEGIN IMMEDIATE 事务保护） | `99aec2b` |

#### 运营 / 运维基建

| 项 | 说明 | commit |
|---|---|---|
| 运营政策文档 | `docs/POLICY-points.md` / `POLICY-reimbursement.md` / `POLICY-lottery.md` 用户面规则 | `8661e22` |
| 值守手册 | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) 14 节：值守原则 / 常用命令 / 服务-更新-数据库-抽奖-报销-积分-评价-权限安全事故处理 / 事故记录模板 / 升级判定 | `6680e83` |
| 健康检查脚本 | [`scripts/healthcheck.sh`](scripts/healthcheck.sh) 只读体检：基础文件 / Python / SQLite WAL & integrity_check / 核心表 / systemd / Git；存在 ERR 时退出码 1 | `6680e83` |
| 数据库备份脚本 | [`scripts/backup.sh`](scripts/backup.sh) 独立 WAL-safe 备份 + `integrity_check`，产物 `*.manual.bak`；不影响 `update.sh` 的 `*.bak` | `6680e83` |
| pytest 测试体系 | `tests/` 67 用例，覆盖 `parse_start_args` / `compute_reimbursement_amount` / `group_search` 工具函数 / 抽奖状态常量；1 秒内跑完；不连 Telegram / 不读真实 .env / 不触碰 data/bot.db | `bea20c1` |
| 迁移注册器设计 | [`docs/MIGRATION-REGISTRY-DESIGN.md`](docs/MIGRATION-REGISTRY-DESIGN.md) `schema_migrations` 表 + 注册器 13 节方案；保留现有 9 个 `_migrate_*`，通过 baseline 平滑接入 | `1f7f273` |
| 迁移注册器 P2 baseline | `schema_migrations` 表 + `ensure_schema_migrations_table` / `baseline_schema_migrations` 落地 [bot/database.py](bot/database.py)；接入 `init_db()`；9 个 `_migrate_*` **顺序未改、行为未改**；[scripts/healthcheck.sh](scripts/healthcheck.sh) 新增 `success=0` 行的 hard/soft 分级检查；13 个 pytest 用例 | (本次) |

### 🟡 后续建议补充

| 类别 | 任务 | 优先级 |
|---|---|---|
| 迁移注册器 P3 | 新迁移走 `MIGRATIONS` 注册器（[设计 §八阶段 B](docs/MIGRATION-REGISTRY-DESIGN.md#阶段-b新迁移走注册器)），失败按 kind 路由 ERR/WARN；P2 baseline 已就绪 | P2 |
| 迁移注册器 P5 | [`update.sh`](update.sh) 检测 hard failed migration 时阻断并提示 rollback（[设计 §八阶段 D](docs/MIGRATION-REGISTRY-DESIGN.md#阶段-d-updatesh-接入)） | P2 |
| CI | 把 `pytest` + `compileall` + `bash -n scripts/*.sh` 接入 GitHub Actions（push / PR 触发） | P2 |
| 清理 | scheduler 加 `prune_old_records`（user_events / audit_logs / point_transactions > 180 天） | P2 |
| 结构 | `bot/main.py` 拆分（30 个 router 注册 + scheduler + logging 一身多职） | P2 |
| 异地备份 | `scripts/backup.sh` 完成本机快照后，rclone / rsync 推送到对象存储 / 第二台 VPS（[DEPLOYMENT §14.4.1](docs/DEPLOYMENT.md#1441-异地备份建议)） | P2 |
| 死代码 | 线性 `ReviewSubmitStates` 旧 FSM、`promo_links.py` / `source_stats.py`（router 已下线） | P3 |

### ❌ 明确不做

- 迁移 PostgreSQL（单进程 polling 离 SQLite 瓶颈远）
- Docker 化（会让 `update.sh` 备份/回滚/healthcheck 失效）
- 拆分 router 为 microservice
- 全量重写 `bot/database.py`

---

## 常见问题

### Bot 无法启动

排查：
- `.env` 是否存在 + `BOT_TOKEN` / `SUPER_ADMIN_ID` 是否正确
- 虚拟环境是否激活 + 依赖是否安装
- `journalctl -u chiyanlu-bot -n 100 --no-pager`

### 管理员无法打开后台

- 当前 Telegram 用户 ID 是否等于 `SUPER_ADMIN_ID`？
- 普通管理员需要超管在「管理员管理」中添加

### 定时发布没有发送消息

- 已设置发布频道？
- Bot 在频道内且有发送权限？
- 当天有老师签到？（无签到默认跳过发布）
- 时区 / 发布时间是否正确？

### 群组关键词无响应

- 已设置响应群组？
- Bot 在群组内？
- 输入是否精确匹配老师艺名 / 地区 / 价格 / 标签？
- 是否在冷却时间内？

### 升级失败如何回滚

```bash
./update.sh rollback        # 自动还原最近一次备份 + git reset --hard HEAD~1
```

`rollback` 会要求输入 `yes` 二次确认。

### 系统未装 sqlite3 命令

WAL 模式下 `update.sh` 备份**强制要求** sqlite3。请先安装：

```bash
apt install sqlite3       # Debian/Ubuntu
yum install sqlite        # RHEL/CentOS
```

---

## 开发与测试

项目自带一套轻量级 pytest 套件，覆盖最容易出错的纯逻辑（deep link 解析、
报销金额计算、群组搜索工具函数、抽奖状态常量），全部**不连真实 Telegram、
不访问真实数据库、不读取真实 .env**，1 秒内跑完。

```bash
# 1. 安装依赖（含 pytest）
pip install -r requirements.txt

# 2. 运行全部测试
python3 -m pytest

# 3. 详细模式（看每个 test 用例）
python3 -m pytest -v

# 4. 只跑某个文件 / 某个用例
python3 -m pytest tests/test_start_args.py
python3 -m pytest tests/test_start_args.py::test_empty_returns_all_defaults
```

> 测试如何隔离真实环境：`tests/conftest.py` 在所有 `bot.*` 模块 import 之前
> 强制设置 `BOT_TOKEN=dummy:token`、`DATABASE_PATH=:memory:` 等环境变量，
> 并 stub 掉 `dotenv.load_dotenv` 防止读取生产服务器上的 `.env`。

新增测试时请放在 `tests/test_*.py`，遵循"只测纯函数、不连外部依赖"的原则。

### CI

GitHub Actions 会在 push 到 `main` 或 pull request 到 `main` 时自动执行
`compileall`、`pytest` 和 `bash -n update.sh / scripts/healthcheck.sh /
scripts/backup.sh` 三类检查。workflow 定义见
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)；CI 环境使用与本地测试
一致的 dummy 环境变量，不连真实 Telegram、不读真实 `.env`、不触碰
`data/bot.db`。

---

## 相关文档

- 早期设计：[`docs/DESIGN.md`](docs/DESIGN.md)（v1） / [`docs/FEATURES-v2.md`](docs/FEATURES-v2.md)（v2 增量）
- 子系统设计草稿：`docs/REVIEW-FEATURE-DRAFT.md` · `docs/POINTS-FEATURE-DRAFT.md` · `docs/LOTTERY-FEATURE-DRAFT.md` · `docs/REIMBURSEMENT-IMPL.md`
- 阶段实施记录：`docs/PHASE-9.*-IMPL.md`（评价系统）· `docs/PHASE-L.*-IMPL.md`（抽奖）· `docs/PHASE-P.*-IMPL.md`（积分）
- 部署：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- 稳定化审查：[`docs/STABILITY-AUDIT-2026-05-18.md`](docs/STABILITY-AUDIT-2026-05-18.md)

---

**Issues / PR / 二次开发**：欢迎在仓库 issue 区讨论。涉及业务规则变更建议先在对应 `docs/*-DRAFT.md` 中说明。
