# PRUNING-DESIGN.md

> **本文档仅是设计方案**，不代表项目已经实现任何 pruning 脚本或定时任务。
> 任何描述"建议"、"未来"、"P2 阶段引入"的段落都是**尚未落地**的目标。
> 当前线上系统**没有任何 pruning 逻辑**，所有表自部署起累积至今。

面向人群：后续接手数据治理 / 数据库容量规划 / 写 `scripts/prune.sh` 的开发者和运维人员。

> 表名以 `bot/database.py` 当前真实定义为准。本文档中所列出的 24 张表都已在
> `init_db()` 的 `CREATE TABLE IF NOT EXISTS` 中真实存在；任何与设计 spec 命名
> 不一致之处都在表格备注列说明。

---

## 一、为什么需要 pruning

长期运行后，以下表会持续单调增长：

- 用户行为日志：`user_events`、`user_teacher_views`、`user_sources`
- 审计日志：`admin_audit_logs`
- 业务记录：`lottery_entries`、`teacher_reviews`、`point_transactions`、`reimbursements`
- 模板/历史记录：`sent_messages`、`teacher_channel_posts`、`teacher_daily_status`

SQLite WAL 模式对本项目体量仍然胜任，但**长期无清理**会让以下指标缓慢恶化：

1. **数据库文件持续增大** —— 影响 `sqlite3 .backup` 与 `update.sh` 的备份时长
2. **备份变慢** —— 现有 ~300KB 体积在百万行后会涨到几百 MB；`scripts/backup.sh` 单次耗时可能从毫秒级升到秒级
3. **查询变慢** —— 即使有索引，扫表/范围查询的代价仍随行数线性增长
4. **冷数据噪声** —— 排查问题时翻 `admin_audit_logs` 命中大量无关历史
5. **VACUUM 成本** —— 长期不清理积累大量删除空洞（DELETE 后空间不会自动归还操作系统），需要离线 `VACUUM`

但 pruning 是**双刃剑**：错误地删除积分流水 / 报销记录 / 抽奖中奖人会直接造成用户权益事故。本文档的核心目的是**先把"哪些能删 / 哪些不能删"写清楚**，再讨论实施。

---

## 二、数据分类原则

### 1. 可清理日志类

**特征**：不直接影响用户权益、可从运营角度接受过期、删除后用户当前可见状态不变。

**示例**：`user_events`、`user_teacher_views`、`user_sources`（视分析需求保留期）

### 2. 谨慎保留审计类

**特征**：用于追责 / 申诉 / 运营复盘；删除会降低可追溯性；可长期保留，或先归档（导出 JSONL / 单独 SQLite 副本）再删除。

**示例**：`admin_audit_logs`

### 3. 不建议自动删除权益类

**特征**：涉及积分、报销、抽奖公平性、评价证据；删除后会影响用户申诉或权益核对。**必须长期保留，至少不能自动删**。

**示例**：`point_transactions`、`reimbursements`、`reimbursement_resets`、`lottery_entries`、`teacher_reviews`、`lotteries`

### 4. 主数据类 / 配置类 / 系统元数据

**特征**：当前业务状态直接依赖；**永远不 pruning**。

**示例**：`users`、`teachers`、`favorites`、`config`、`required_subscriptions`、`schema_migrations`、`admins`、`publish_templates`

---

## 三、建议表级策略

下表覆盖 `bot/database.py` 中**全部 24 张** `CREATE TABLE IF NOT EXISTS` 表
（已加 `schema_migrations`，commit `496cb5b` 引入）。

时间戳字段：列出可用于按时间清理的字段。`config` 是**唯一**没有时间戳字段的表
——但它是主配置，本来就不应 pruning。

| 表 | 用途 | 类型 | 自动清理建议 | 保留周期 | 归档 | 时间戳字段 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `admins` | 管理员名单 | 主数据 | ❌ 不清理 | 永久 | — | `created_at` | 极少变动；删除会丢失权限链 |
| `teachers` | 老师档案 | 主数据 | ❌ 不清理 | 永久 | — | `created_at` | 含老师资料、价格、地区等 |
| `users` | 用户主表 | 主数据 | ❌ 不清理 | 永久 | — | `created_at` / `last_active_at` | 含积分余额、来源、设置；不可删 |
| `favorites` | 收藏关系 | 主状态 | ❌ 不清理 | 永久 | — | `created_at` | 用户当前可见状态 |
| `config` | key-value 配置 | 配置 | ❌ 不清理 | 永久 | — | （无） | 全局开关 / 阈值；不应基于时间清理 |
| `required_subscriptions` | 必关订阅配置 | 配置 | ❌ 不清理 | 永久 | — | `created_at` | 仅在管理员调整时才变动 |
| `publish_templates` | 发布模板 | 配置 | ❌ 不清理 | 永久 | — | `created_at` | 默认模板由 `_ensure_default_publish_template` 初始化 |
| `schema_migrations` | 迁移历史 | 系统元数据 | ❌ 不清理 | 永久 | — | `applied_at` / `created_at` | 唯一的迁移历史证据；详见 [MIGRATION-REGISTRY-DESIGN](MIGRATION-REGISTRY-DESIGN.md) |
| `point_transactions` | 积分流水 | **权益** | ❌ 不自动删 | 永久 | 长期 | `created_at` | 失败一次会引发积分对账事故；详见 [POLICY-points](POLICY-points.md) |
| `reimbursements` | 报销记录 | **权益** | ❌ 不自动删 | 永久 | 长期 | `created_at` / `updated_at` | 含金额、状态、审批；用户可申诉 1 年内的记录 |
| `reimbursement_resets` | 报销重置授权 | **权益** | ❌ 不自动删 | 永久 | 长期 | `granted_at` / `consumed_at` | 超管发放的"豁免周上限"票据；不能丢 |
| `teacher_reviews` | 评价 / 报告 | **权益** | ❌ 不自动删 | 永久 | 长期 | `created_at` / `updated_at` | 含评价证据、审批历史；删除会破坏申诉链 |
| `lotteries` | 抽奖主表 | **权益** | ❌ 不自动删 | 永久 | 长期 | 多个 `_at` 字段 | 主表，含开奖时间 / 状态机；不应清理 |
| `lottery_entries` | 抽奖参与记录 | **权益** | ❌ 不自动删 | ≥ 365 天 | 视情况 | `entered_at` / `notified_at` | **中奖记录绝不删**（`won=1`）；未中奖记录长期来看可考虑归档 |
| `admin_audit_logs` | 管理员操作审计 | **审计** | 🟡 谨慎 | ≥ 365 天 | 建议归档后删 | `created_at` | 第一阶段不建议自动删；归档为外部 JSONL 后再删才安全 |
| `user_events` | 用户事件日志 | 日志 | ✅ 可清理 | 180 天 | 不必 | `created_at` | 行为分析用；已建 `created_at` 索引，按时间 DELETE 高效 |
| `user_teacher_views` | 用户浏览老师记录 | 日志 | ✅ 可清理 | 180 天 | 不必 | `viewed_at` | 已建 `(user_id, viewed_at)` 索引；或仅保留每用户最近 N 条 |
| `user_sources` | 用户首/末次来源 | 日志 | 🟡 谨慎 | ≥ 365 天 | 不必 | `first_seen_at` / `last_seen_at` | 用于来源归因，运营报表可能依赖；删除前与产品确认 |
| `user_tags` | 用户标签快照 | 日志 / 派生 | 🟡 谨慎 | 视用法 | 不必 | `created_at` / `updated_at` | 标签由用户行为派生；若可重算则可清理，否则谨慎 |
| `checkins` | 老师每日签到 | 业务历史 | 🟡 谨慎 | ≥ 365 天 | 视情况 | `created_at` / `checkin_date` | 一日一行，单表体量小；是否影响历史统计需产品确认 |
| `sent_messages` | 已发送频道帖引用 | 业务历史 | 🟡 谨慎 | 90-180 天 | 不必 | `created_at` / `sent_date` | 用于"删除旧频道帖"；如确认不再用于审计，可清理；删除条目**不等于**删除频道消息本身 |
| `teacher_daily_status` | 老师每日状态 | 业务历史 | 🟡 谨慎 | ≥ 365 天 | 视情况 | `created_at` | 一老师一日一行；统计报表可能依赖 |
| `teacher_channel_posts` | 频道发布记录 | 业务历史 | 🟡 谨慎 | ≥ 180 天 | 视情况 | 多个 `_at` 字段 | 含已发布消息 id 和回流交互计数；删除前确认是否还用于"重新编辑/置顶" |
| `teacher_edit_requests` | 老师档案修改申请 | 业务历史 | 🟡 谨慎 | ≥ 180 天 | 视情况 | `created_at` / `approved_at` | 审批历史；与申诉链相关 |

**图例**：
- ❌ 不清理 = 任何阶段都不应自动 DELETE
- 🟡 谨慎 = 视产品 / 运营 / 合规确认后才能进入 pruning 范围
- ✅ 可清理 = 第一阶段就可以纳入 `scripts/prune.sh`

---

## 四、默认建议

**第一阶段** P3 仅纳入下列"绿色"表，其它表暂不动：

```
✅ user_events           保留 180 天，按 created_at 清理
✅ user_teacher_views    保留 180 天，按 viewed_at 清理（或每用户保留最近 200 条）
```

**第二阶段**（视生产数据量增长再评估）：

```
🟡 admin_audit_logs      ≥ 365 天 + 归档为外部 JSONL 后再删
🟡 sent_messages         90-180 天，确认不再用于审计后清理
🟡 user_sources          ≥ 365 天，与产品确认运营报表是否依赖
🟡 user_tags             视用法（若可重算则可清理）
🟡 teacher_daily_status  ≥ 365 天，确认报表口径
🟡 teacher_channel_posts ≥ 180 天，确认是否还用于"编辑/置顶"
🟡 teacher_edit_requests ≥ 180 天，确认申诉时效
🟡 checkins              ≥ 365 天，确认产品统计口径
```

**永远不进入 pruning**：

```
❌ point_transactions    永久保留
❌ reimbursements        永久保留
❌ reimbursement_resets  永久保留
❌ lottery_entries       永久保留（中奖记录绝不删）
❌ lotteries             永久保留
❌ teacher_reviews       永久保留
❌ users / teachers / favorites / admins / config /
   required_subscriptions / publish_templates / schema_migrations
   主数据 / 配置 / 系统元数据
```

---

## 五、dry-run 设计

**未来**的 `scripts/prune.sh` 必须**默认只做统计、不删除**，需要显式 `--confirm`
才执行真正的 DELETE：

```bash
./scripts/prune.sh --dry-run --days 180
```

输出 schema（每张表一段）：

```text
[DRY-RUN] user_events
  condition:      created_at < datetime('now', '-180 days')
  matched_rows:   12345
  oldest:         2026-01-01 00:00:00
  newest:         2026-03-01 00:00:00
  total_rows:     45678
  action:         safe-to-delete-after-backup
```

输出字段定义：

| 字段 | 含义 |
| --- | --- |
| `condition` | 实际 WHERE 子句，便于人工核对 |
| `matched_rows` | 该条件命中的行数 |
| `oldest` / `newest` | 命中行中的最早/最新时间戳 |
| `total_rows` | 表当前总行数（参考） |
| `action` | `safe-to-delete-after-backup` / `requires-manual-confirm` / `not-eligible` |

**dry-run 应包含**：

- 一张表如果**不在白名单**：直接输出 `action: not-eligible`，不查统计
- 一张表如果**没有时间戳字段**（如 `config`）：输出 `action: not-eligible (no timestamp column)`
- 一张表如果**找到 0 行命中**：输出 `matched_rows: 0`，仍打印，便于运维确认条件正确

---

## 六、执行设计

未来 `scripts/prune.sh --confirm` 必须满足以下不可破坏的前置条件：

1. **先 backup** —— 检测 `backups/` 中**当天**是否已有 `*.manual.bak`，若无则
   要求先手动跑 `./scripts/backup.sh`，或脚本内部主动调用一次
2. **再 dry-run** —— 同样参数运行一次 dry-run，把统计写入日志（便于事后核对）
3. **必须显式 `--confirm`** —— 默认不带 `--confirm` 时只 dry-run
4. **白名单严格** —— 表名必须在脚本内部白名单中，黑名单（权益类）即使误传 `--days 30` 也不会被命中
5. **不动 `lottery_entries` 中 `won=1` 的行** —— 如未来真要对该表 pruning，必须
   `WHERE won=0`；中奖记录绝对不能在任何 pruning 路径下被删
6. **删除后完整性校验** —— `sqlite3 data/bot.db "PRAGMA integrity_check;"`，
   返回非 `ok` 立即 `[ERR ]` 并提示运维 `./update.sh rollback`
7. **可选 VACUUM** —— 仅当显式 `--vacuum` 时执行；**必须先停服**或在低峰窗口，
   因 VACUUM 锁库

完整命令序列（建议）：

```bash
# 第 1 步：准备
cd /opt/Chiyanlu-Exclusive-Bot
./scripts/backup.sh                       # 强制本机最新 manual 备份
./scripts/prune.sh --dry-run --days 180   # 看一下要删多少

# 第 2 步：真正执行（看清 dry-run 输出之后）
./scripts/prune.sh --confirm --days 180

# 第 3 步：复检
sqlite3 data/bot.db "PRAGMA integrity_check;"   # 必须返回 ok
sqlite3 data/bot.db "PRAGMA journal_mode;"      # 必须仍为 wal
ls -lh data/bot.db                              # 看文件大小是否如预期下降

# 第 4 步（可选）：回收磁盘空间
sudo systemctl stop chiyanlu-bot                # VACUUM 锁库前停服
sqlite3 data/bot.db "VACUUM;"
sqlite3 data/bot.db "PRAGMA integrity_check;"
sudo systemctl start chiyanlu-bot
```

---

## 七、scheduler 还是脚本

两条路线对比：

| 维度 | scheduler 自动任务 | `scripts/prune.sh` 人工触发 |
| --- | --- | --- |
| 人工成本 | 低，自动跑 | 高，每次需要值守人员 |
| 误删风险 | **高** —— 一次失误持续每天 | 低，dry-run + 确认两步 |
| 失败可见性 | 差 —— 自动任务失败容易没人看 | 好 —— 终端立即有输出 |
| 与写入冲突 | 高 —— 大表 DELETE 可能持锁 | 可选低峰窗口 |
| 权益类适用性 | 完全不适用 | 完全不适用 |
| 现阶段适用性 | ❌ 不建议 | ✅ 建议 |

**建议**：
- **第一阶段**只做 `scripts/prune.sh`，人工触发、强制 dry-run、强制备份
- 稳定运行 ≥ 3 个月、生产数据未出过事故之后，**仅对 `user_events` 这种纯日志表**
  考虑接入 scheduler，且必须由 scheduler 主动调用 `prune.sh --confirm`，**不在**
  scheduler 代码里写 SQL DELETE
- **永远不**让 scheduler 直接操作权益类表（`point_transactions` / `reimbursements`
  / `lottery_entries` / `teacher_reviews` / `reimbursement_resets`）

---

## 八、与 backup / healthcheck / RUNBOOK / update.sh 的关系

| 脚本 / 文档 | 当前作用 | 与 pruning 的关系 |
| --- | --- | --- |
| [scripts/backup.sh](../scripts/backup.sh) | 独立 WAL-safe 备份 | **pruning 前置依赖**；任何 `--confirm` 前必须有当天的 `*.manual.bak` |
| [scripts/healthcheck.sh](../scripts/healthcheck.sh) | 体检脚本 | 未来 P4 可增加"数据库文件大小提醒"（如 > 500 MB → WARN），引导运维触发 pruning |
| [docs/RUNBOOK.md](RUNBOOK.md) | 值守手册 | 未来 P5 应增加"如何 dry-run / 如何 confirm / 如何回滚 pruning 误操作"一节 |
| [update.sh](../update.sh) | 更新 + 备份 + 重启 | **绝不**在 `update.sh` 中自动跑 pruning；两者完全解耦 |
| [docs/MIGRATION-REGISTRY-DESIGN.md](MIGRATION-REGISTRY-DESIGN.md) | 迁移注册器设计 | 与 pruning 无直接关系；`schema_migrations` 不应被 pruning 清理 |

---

## 九、风险

落地时需要规避的"会让人睡不着觉"的坑：

1. **误删权益数据** —— 一旦 `point_transactions` / `reimbursements` 误删，
   用户申诉无据可查；必须靠**白名单 + 黑名单双重校验**，黑名单写死在脚本里
2. **删除后无法处理用户申诉** —— 即使是"日志类"表，长期来看用户也可能问
   "我去年 X 月看过这个老师"；`user_teacher_views` 至少保留 180 天
3. **VACUUM 锁库** —— `VACUUM` 全程独占锁，业务请求会卡死；必须停服执行
4. **大量 DELETE 长时间写锁** —— `WHERE created_at < ...` 命中 10 万行的
   DELETE 在 WAL 模式下也会长时间持锁；建议**分批**（如 5000 行一批），
   每批 commit 后短暂 sleep
5. **`created_at` 格式不一致** —— 大部分表用 `DEFAULT CURRENT_TIMESTAMP`，
   存的是 `YYYY-MM-DD HH:MM:SS` UTC；少数表（如 `lottery_entries`）有自己的
   时间字段。**pruning 条件必须用 `datetime(col)` 包一层**避免字符串比较陷阱
6. **没有时间戳的表** —— `config` 无时间戳字段；任何按时间清理都不适用
7. **清理后报表口径变化** —— 历史"过去 1 年签到分布"在清理后会缺数；
   清理前必须先和产品确认报表保留期
8. **备份失败但 pruning 继续** —— `prune.sh --confirm` 必须把 backup 失败
   视为终止条件，**不能**仅 warning
9. **dry-run 条件与 confirm 条件不一致** —— 两者必须**共用同一个 SQL 模板**，
   不能 dry-run 跑 A、confirm 跑 B
10. **`lottery_entries.won=1` 误删** —— 即使未来对该表 pruning，WHERE 必须
    显式 `won=0`；建议在脚本中做硬断言"删除前再 `SELECT COUNT(*) WHERE won=1`，
    数量必须不变"

---

## 十、实施计划

按风险递增：

| 阶段 | 内容 | 风险 | 业务影响 |
| --- | --- | --- | --- |
| **P1** | 本设计文档 | 无 | 无 |
| **P2** | `scripts/prune.sh --dry-run`，只读统计，白名单 = `user_events` + `user_teacher_views` | 极低 | 无 |
| **P3** | `scripts/prune.sh --confirm`，仅清理 P2 白名单内的表；强制先 backup | 低 | 行数下降，业务不可感知 |
| **P4** | [scripts/healthcheck.sh](../scripts/healthcheck.sh) 加"DB 文件大小提醒"（如 > 500 MB → WARN） | 低 | 只读 |
| **P5** | [RUNBOOK.md](RUNBOOK.md) 增加 pruning 操作流程小节 | 无 | 仅文档 |
| **P6** | 视生产数据量评估是否把 `user_events` 接入 scheduler；权益类**永不**接入 | 中 | 视实施 |

P2 引入前必须先做：
- 生产 `data/bot.db` 当前每张表行数评估（手动跑一遍 `SELECT COUNT(*) FROM …`，记入 PR 描述）
- 与产品 / 运营确认 `user_events` 保留期可以是 180 天（如有报表依赖 365 天则改保留期）

---

## 十一、明确不做

无论生产数据量增长到什么程度，下列动作**永远不做**：

- 自动删除 `point_transactions`（积分流水）
- 自动删除 `reimbursements`（报销记录）
- 自动删除 `reimbursement_resets`（报销重置授权）
- 自动删除 `teacher_reviews`（评价 / 报告）
- 自动删除 `lottery_entries` 中 `won=1` 的中奖记录
- 自动删除 `lotteries`（抽奖主表）
- 在 [update.sh](../update.sh) 中混入 pruning 调用
- 在 [bot/database.py](../bot/database.py) 的迁移函数里做 DELETE
- 在没有当天 `*.manual.bak` 的情况下执行 `--confirm`
- 把 dry-run 的 WHERE 条件与 confirm 的 WHERE 条件分开实现（必须共用同一模板）

---

## 十二、相关文档

- [RUNBOOK.md](RUNBOOK.md) §四 更新失败怎么办、§五 数据库异常怎么办、§六 备份与恢复流程
- [DEPLOYMENT.md](DEPLOYMENT.md) §14 备份与恢复、§16 验收 Checklist
- [POLICY-points.md](POLICY-points.md) 积分流水保留期对应的口径
- [POLICY-reimbursement.md](POLICY-reimbursement.md) 报销记录与重置票据
- [POLICY-lottery.md](POLICY-lottery.md) 抽奖参与 / 中奖记录保留要求
- [MIGRATION-REGISTRY-DESIGN.md](MIGRATION-REGISTRY-DESIGN.md) 迁移注册器（与 pruning 无关，但都涉及 `schema_migrations` 表的"不可清理"语义）
- [scripts/backup.sh](../scripts/backup.sh) pruning 的强前置依赖
- [scripts/healthcheck.sh](../scripts/healthcheck.sh) 未来 P4 加 DB 体积提醒
