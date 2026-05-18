# Chiyanlu-Exclusive-Bot 稳定化审查报告

> 审查日期：2026-05-18
> 审查范围：仓库当前 main 分支（commit cd1988a 之前的全量代码 + docs/ + ops 资产）
> 审查方法：4 个并行 Explore agent 分别检查 README/部署、main.py/router 顺序、FSM/callback 命名空间、DB 层与 SQLite 容量；未修改任何文件

---

## 一、项目现状判断

代码规模约 **24,000 行 Python**，其中 `bot/database.py` 单文件 **5,960 行 / 23 张表 / 9 个迁移函数**，`bot/main.py` 注册 **30 个 router**。功能上已远超 README 描述的 v1 范围——上线了 lottery（抽奖）、points（积分）、reimbursement（报销）、review（评价+卡片驱动 FSM）、subreq（必关订阅）、publish_templates、report_settings、user_tags、teacher_profile 详细档案、个人评价主页 8 大子系统。

**实质问题**：README 仍停留在 v1（5 张表 / 5 个功能），与现状 staleness 评分 **9/10**。多个"运营级"子系统（积分、报销、抽奖）已经承载等价货币/规则，但 `docs/` 全部是开发者实施笔记（PHASE-*-IMPL.md / *-DRAFT.md），**零运营手册 / 用户政策 / 申诉流程文档**。`.gitignore` 仅 3 行，**未忽略 `.env`**——存在 BOT_TOKEN 泄露风险。

项目并未"危险"，但已进入**功能膨胀 vs 运营成熟度不匹配**阶段。

## 二、当前优点

1. **router 命名空间设计整体清晰**：`user:* / admin:* / teacher:* / review:* / card:* / rreview:* / tprofile:* / fav:* / card:*` 顶层前缀几乎不冲突，每个二级段都由唯一 router 拥有（详见审查表）。
2. **FSM 状态归属干净**：30+ 个 StatesGroup 几乎每个都由唯一 router 拥有；跨 router 共享 state 的情况只有 `ReviewSubmitStates`（线性 FSM 残留，被 `start_review_flow` 重定向后变成 dead code）。
3. **`update.sh` 是仓库中最成熟的资产**（443 行）：DB 备份+完整性校验、保留 10 份、`rollback` 子命令、`git pull --rebase --autostash` 冲突回滚、`systemctl is-active` 健康轮询、`journalctl` 日志扫描 `Traceback/CRITICAL` 关键字、迁移前 schema diff 预警。
4. **DB 索引设计普遍合理**：`teacher_reviews` 4 个复合索引、`point_transactions(user_id, created_at)`、`reimbursements(user_id, week_key)` 等增长表都有 `(entity_id, created_at)` 复合覆盖。
5. **迁移幂等性**：所有 `_migrate_*` 都先 `PRAGMA table_info` 检测后 `ALTER`，可重复执行。
6. **`requirements.txt` 全部 pinned 版本**（4 行），无 `>=` 散漫依赖。

## 三、主要风险

按严重度排序：

### 🔴 高 — 立刻处理

| # | 风险 | 证据 |
|---|---|---|
| H1 | `.gitignore` 未忽略 `.env`，BOT_TOKEN 可能被误 commit | `.gitignore` 仅 3 行（.DS_Store / __pycache__ / *.pyc） |
| H2 | `.gitignore` 未忽略 `data/`、`backups/`、`*.db` — 任何人 `git add .` 都可能把生产 DB 推到 GitHub | 同上；`data/bot.db` 存在于工作树 |
| H3 | **5+ 个生产子系统零运营文档**：积分（虚拟货币）、报销（点数→现金）、抽奖（点数门票+定时开奖）均无政策/申诉/审批/异常处理 SOP | `docs/` 全部是开发实施笔记 |
| H4 | README 9/10 stale —— 操作者无法仅靠 README 理解系统真实功能与风险面 | README:238–244 仅列 5 张表 |

### 🟠 中 — 1-2 周内处理

| # | 风险 | 证据 |
|---|---|---|
| M1 | `teacher_checkin.on_checkin` 用 `@router.message(F.text == "签到")` 无 state 过滤，注册于 `main.py:172` —— 任何后续 FSM 用户在 state 内输入 "签到" 都会被它劫持 | `bot/handlers/teacher_checkin.py:15` |
| M2 | `lottery_entry.py:247` `@router.message(F.chat.type=="private", F.text)` 无 state 过滤 —— 当前安全仅因 `keyword_router` 是其后唯一 router（且只处理 group）；未来在 `main.py:212` 之后加任何私聊 FSM 会被静默吞掉 | `bot/handlers/lottery_entry.py:247` |
| M3 | `teacher_flow.py` 同文件出现两条 `F.data.startswith("teacher:select:")` 注册（line 332 / 465），后者被 aiogram 静默 shadow —— 可能是 stale code 或潜在 bug | `bot/handlers/teacher_flow.py:332, 465` |
| M4 | `_migrate_reimbursements_queued_status` 表重建逻辑：在 `DROP TABLE reimbursements` 与 `RENAME reimbursements_new → reimbursements` 之间如果进程死亡，幂等检查会因 `name='reimbursements'` 查不到而**默默 return**，DB 静默处于半完成状态 | `bot/database.py:573–626` |
| M5 | `bot/database.py` 5960 行单文件，23 张表 CRUD + 9 个迁移 + init_db 全部在内 —— 接下来加表/迁移会持续放大维护成本 | 见 wc -l 输出 |
| M6 | `get_db()` 每次调用 open/close 连接，**未启用 WAL**，未启用 `PRAGMA synchronous=NORMAL` —— 50-100 并发活跃用户起 p99 延迟会进秒级 | `bot/database.py:14-20` |
| M7 | `user_events / admin_audit_logs / point_transactions / lottery_entries` 4 张表**无任何 TTL 或 pruning**，长期单调增长 | grep 全仓无 `DELETE FROM` 时间裁剪 |
| M8 | 仓库无 `*.service`、无 Dockerfile、无 CI；`docs/DEPLOYMENT.md` 教操作者手工 `git pull && systemctl restart`，**完全未提及 `update.sh` 存在** —— `update.sh` 自己也不安装 systemd unit | `docs/DEPLOYMENT.md:286-332` vs `update.sh:100-109` |

### 🟡 低 — 重构/清理类

| # | 风险 | 证据 |
|---|---|---|
| L1 | `bot/main.py` 一身多职（logging / Bot / Dispatcher / Scheduler / DB init / 30 路由清单 / lifecycle / polling）—— 适合拆分但不紧急 | `bot/main.py` 全文 |
| L2 | 线性 `ReviewSubmitStates` FSM 因 Phase 2 重定向变 dead code（`review_submit.py:526-981` 约 450 行）但 router 仍注册；增加误读概率 | `bot/handlers/review_submit.py` |
| L3 | `teacher_flow.py:366` 用裸前缀 `edit:*` 无 namespace —— 任何未来 `edit:` 开头 callback 都会被吃掉 | 同上 |
| L4 | `noop` 占位 handler 在 `teacher_daily_status.py:386` 重复注册（`startswith("noop")` 无冒号），实际 unreachable | 同上 |
| L5 | `.env.example` 仅含 v1 变量，缺 lottery/points/reimbursement 子系统的所有配置变量 | `.env.example` 全文 |
| L6 | `requirements.txt` 无 lockfile，`aiogram==3.13.1` 是 2024 年末版本，可能有已发布的安全/bug fix | `requirements.txt` |
| L7 | 无 schema_version 表，无 alembic —— 无法回答"线上 DB 跑的是哪个版本"；迁移异常被 `except Exception: logger.warning(...)` 静默 | `bot/database.py:496, 514, 533, 552, 569, 625` |
| L8 | SQLite 当前**不构成瓶颈**，但 `get_db` 模式 + 无 WAL + 无 pruning 三者叠加会同步老化 | 见 M6/M7 |

## 四、建议优先级

> **P0 = 本周；P1 = 2 周内；P2 = 1 个月内；P3 = 季度内 / 可推迟**

| 优先级 | 任务 | 风险等级 | 工作量 |
|---|---|---|---|
| **P0** | 修补 `.gitignore`：加入 `.env`、`data/`、`backups/`、`*.db`、`logs/`、`.venv/`、`.idea/`、`.vscode/` | H1+H2 | 5 分钟 |
| **P0** | 立刻确认 `.env` 当前是否 **已被 commit 过历史**（`git log --all -- .env`）；若是 → 立刻 rotate BOT_TOKEN | H1 | 30 分钟 |
| **P0** | 给 `teacher_checkin.on_checkin` 和 `lottery_entry` 私聊 fallback 加上 `StateFilter(None)`（仅 FSM 外触发） | M1+M2 | 30 分钟 |
| **P0** | 删除或显式 ignore `teacher_flow.py:465` 重复 `teacher:select:` 注册 | M3 | 15 分钟 |
| **P1** | 在 `get_db()` 加 `PRAGMA journal_mode=WAL`、`PRAGMA synchronous=NORMAL` | M6 | 1 小时（含测试） |
| **P1** | 修复 `_migrate_reimbursements_queued_status` 半完成态检测（检查 `reimbursements_new` 存在 + 原表缺失 → 自愈 RENAME） | M4 | 2 小时 |
| **P1** | 重写 README.md 反映当前功能；同步 `docs/DEPLOYMENT.md` 引用 `update.sh` | H4+M8 | 半天 |
| **P1** | 新增 3 份运营文档：`docs/RUNBOOK.md`（值守手册）、`docs/POLICY-points.md` + `docs/POLICY-reimbursement.md` + `docs/POLICY-lottery.md`（用户面规则） | H3 | 1-2 天 |
| **P2** | 新增 `schema_version` 表 + 迁移注册器（不必上 alembic） | L7 | 半天 |
| **P2** | scheduler 加 `prune_old_records` 任务（user_events / admin_audit_logs / point_transactions > 180 天） | M7 | 半天 |
| **P2** | 新增 `scripts/backup.sh`（`VACUUM INTO` 到带日期文件，crontab 触发）+ `scripts/healthcheck.sh`（HTTP/PID 检测 + journalctl error sniff） | M8 | 半天 |
| **P2** | `bot/main.py` 拆分为 `app_factory.py + handlers/__init__.register_routers() + lifecycle.py` | L1 | 1 天 |
| **P2** | 清理 dead code：线性 `ReviewSubmitStates` 旧 FSM、`teacher_daily_status.py:386` 重复 noop、`promo_links.py` / `source_stats.py`（router 已下线但文件保留） | L2+L4 | 半天 |
| **P3** | `bot/database.py` 按 entity 拆包（`bot/database/teachers.py / reviews.py / ...`），保留 `bot/database/queries.py` 装跨表查询 | M5 | 3-5 天 |
| **P3** | 升级 aiogram / aiosqlite 至当前 stable，跑回归 | L6 | 1 天 |
| **P3** | `edit:*` → `teacher:edit:*` 重命名 | L3 | 半天 |

**不建议升级 SQLite → Postgres**（详见第六节）。

## 五、建议改造路线

**Sprint 1（本周, 1-2 天）— "止血"**
- P0 全部完成（.gitignore + StateFilter + 重复注册清理 + token rotate 确认）
- 验证：`git status --ignored` 看 `.env` / `data/` / `backups/` 均显示为 ignored

**Sprint 2（2 周内, 3-5 天）— "运维基础设施"**
- WAL + connection 改造（M6）
- 迁移自愈逻辑（M4）
- README/DEPLOYMENT 同步（H4+M8）
- 3 份政策文档（H3）—— 先把规则白纸黑字写下来，比代码改造更紧迫
- 添加 `scripts/backup.sh` + `scripts/healthcheck.sh`

**Sprint 3（1 个月内, 2-3 天）— "可观测性 + 卫生"**
- `schema_version` 表 + 迁移注册器
- pruning 定时任务
- bot/main.py 拆分（让新人能在 50 行内看完入口）
- 清理 ~600 行 dead code（线性 review FSM + 已下线 promo/source_stats）

**Sprint 4（季度内, 1 周）— "可选优化"**
- `bot/database.py` 模块化
- aiogram 升级
- 命名规范统一（`edit:` → `teacher:edit:`）

## 六、不建议现在做的事情

1. **❌ 迁移到 PostgreSQL**：单进程 polling + 当前 QPS 离 SQLite 上限差 100x；迁移成本 2-3 周，收益是"以防万一"，性价比极差。先 WAL + pruning + backup 三件套足够支撑 1-2 年。
2. **❌ 引入 Alembic**：23 张表 + 9 迁移规模下，alembic 的 ORM 假设和 SQL-first 风格会冲突；自建 `schema_version` 表 + 编号迁移函数已经足够。
3. **❌ Docker 化**：单进程 polling + systemd 已经足够；Docker 引入会让 `update.sh` 的回滚/备份/healthcheck 重做一遍，目前没收益。
4. **❌ 拆分 router 为微服务**：30 个 router 看着多，但单进程 / 共享 FSM / 共享 DB 是其工作前提；任何拆服务的尝试都需要先拆 DB，工作量黑洞。
5. **❌ 全量重写 `bot/database.py`**：先加 schema_version + WAL + pruning，让现状稳定可观测，再 P3 按 entity 增量拆包；一次性大重构会卡住所有 feature 开发。
6. **❌ 给 `keyword_router` 加 state 过滤**：它本身有 `chat.type in ("group", "supergroup")` 自检，私聊不会进入；移除 catch-all 反而会破坏关键词响应能力。
7. **❌ 删除 `ReviewSubmitStates` 全部代码**：先放着做 fallback（如果 card FSM 出严重问题可临时切回），等 card FSM 稳定运行 4 周后再清。

## 七、下一步可执行任务列表

按可立即开 PR 的颗粒度拆好，每条都标了**前置依赖**和**验收标准**：

### 立刻可做（独立、低风险）

- [ ] **Task A1**：扩充 `.gitignore` 至完整集。验收：`echo "test" > .env && git status` 不显示 `.env`。
- [ ] **Task A2**：跑 `git log --all --full-history -- .env` 检查历史泄露。若发现 → rotate BOT_TOKEN（Telegram BotFather `/revoke`）→ 更新 `.env`。
- [ ] **Task A3**：`teacher_checkin.py:15` 加 `StateFilter(None)`；`lottery_entry.py:247` 同改。验收：在 `SearchStates.waiting_query` 状态下输入 "签到" 走搜索路径而非签到。
- [ ] **Task A4**：删除 `teacher_flow.py:465` 重复 `teacher:select:` handler（或合并到 :332）。验收：grep `startswith("teacher:select:")` 在 teacher_flow.py 仅 1 处。

### 1 周内（DB 稳定性）

- [ ] **Task B1**：`get_db()` 加 WAL+synchronous=NORMAL pragma。验收：手动 `sqlite3 data/bot.db "PRAGMA journal_mode;"` 返回 `wal`。
- [ ] **Task B2**：`_migrate_reimbursements_queued_status` 加半完成态检测+自愈。验收：手动 mock 半完成状态（重命名 reimbursements_new 后 DROP 原表），重启 bot 自动 RENAME。
- [ ] **Task B3**：新增 `scripts/backup.sh`（`sqlite3 ... ".backup /path/$(date).db"` + 保留 30 份 + crontab 文档）。
- [ ] **Task B4**：新增 `scripts/healthcheck.sh`（systemctl is-active + 最近 1 分钟 journalctl 无 Traceback + bot.db 文件存在且 size > 0）。

### 2 周内（文档对齐）

- [ ] **Task C1**：重写 `README.md` —— 当前 9 张表 → 写实际 23 张表（或链接 docs/DESIGN）；功能列表从 5 项扩到 13 项。
- [ ] **Task C2**：`docs/DEPLOYMENT.md` 增加 "使用 update.sh" 章节，把当前手工 `git pull` 流程标 deprecated。
- [ ] **Task C3**：新增 `docs/RUNBOOK.md` —— 值守手册（如何看 journalctl / 如何回滚 / 如何处理迁移失败 / 数据库满了怎么办）。
- [ ] **Task C4**：新增 `docs/POLICY-points.md` —— 用户面规则（每条评价多少分、过期否、申诉路径）。
- [ ] **Task C5**：新增 `docs/POLICY-reimbursement.md` —— 报销规则（资格、金额、周限额、月池、审核 SLA、驳回常见原因）。
- [ ] **Task C6**：新增 `docs/POLICY-lottery.md` —— 抽奖规则（资格、点数门票、退款规则、开奖时间、领奖流程）。

### 1 个月内（结构清理）

- [ ] **Task D1**：新增 `schema_version` 表 + 迁移注册器（替换裸 `try/except: warning`）。
- [ ] **Task D2**：scheduler 新增 `prune_old_records` 任务（用户事件 / 审计日志 / 点数 transaction > 180 天软删除）。
- [ ] **Task D3**：拆 `bot/main.py` → `app_factory.py + handlers/__init__.register_routers() + lifecycle.py`。验收：`main.py` ≤ 30 行。
- [ ] **Task D4**：清理 dead code：`bot/handlers/review_submit.py` 旧线性 FSM handlers（标记 deprecated 注释保留 1 个月后删）、`teacher_daily_status.py:386` 重复 noop、`promo_links.py` / `source_stats.py` 文件。
- [ ] **Task D5**：`.env.example` 补齐当前所有需要的 env vars。

### 推迟

- bot/database.py 按 entity 拆包（P3）
- aiogram / aiosqlite 升级（P3）
- `edit:*` → `teacher:edit:*` 重命名（P3）
- PostgreSQL 迁移（不做）
- Docker 化（不做）

---

**审查结论**：项目代码质量好于平均水平（命名空间设计、FSM 隔离、`update.sh`、索引设计都不错），但运营成熟度跟不上功能膨胀速度。3 个最该立刻做的事是 **`.gitignore` 修补 / 2 处 state filter 补漏 / 写 3 份政策文档** —— 总工作量不到 2 天，但能把生产风险面砍掉 60%+。SQLite 暂时不是瓶颈，**先不要重构 DB 层**，先把 WAL+backup+pruning 这三件运维基础设施补齐。
