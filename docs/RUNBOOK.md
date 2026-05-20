# RUNBOOK.md — 池砚卤独家 Bot 值守手册

本文档面向**值守人员、管理员、超管**，用于处理线上事故和日常排查。

> ⚠️ 阅读须知
> - 本手册不是开发文档，不讲实现细节，只讲「出问题之后怎么办」。
> - 所有命令默认在 **服务器** 上执行，工作目录默认是 `/opt/Chiyanlu-Exclusive-Bot`。
> - 涉及 **危险操作**（停服、改库、rollback、revoke token）必须先看「确认」与「备份」要求。
> - 涉及用户隐私 / 老师资料 / 报销凭证 / BOT_TOKEN，**禁止外发、禁止截图发群、禁止粘进任何在线工具**。

---

## 一、值守原则

值守不是写代码，是把损失降到最小。**任何时候都遵守这六条**：

1. **先保服务，再查原因**。用户能用，比你立刻知道根因更重要。
2. **先备份，再做危险操作**。改库、删文件、覆盖文件之前，先 `sqlite3 .backup`。
3. **不直接修改生产数据库**。优先用超管后台 / 命令，DB 直接 `UPDATE` 是**最后手段**。
4. **不公开用户隐私和老师资料**。报销截图、聊天记录、手机号、真实姓名一律不外传。
5. **不在群内承诺报销 / 抽奖结果**。所有结论以系统记录为准，回复用户用「已记录、走流程」。
6. **重大操作要留痕**。截图、记录时间、记录命令、写进事故记录模板（见第十二节）。

---

## 二、常用命令速查

> 这些命令是**只读 + 标准操作**，可以放心执行。涉及修改的命令在后续章节会单独标红。

```bash
# 进入项目目录（所有命令前置）
cd /opt/Chiyanlu-Exclusive-Bot

# === 一键体检（首选）===
./scripts/healthcheck.sh                      # 只读检查：文件 / Python / SQLite / systemd / Git
                                              # 含 DB 体积提醒（默认 > 512 MB → WARN，引导 prune dry-run）
                                              # 退出码 0 = 全 OK 或仅有 WARN；1 = 存在 ERR
HEALTHCHECK_DB_WARN_MB=1024 ./scripts/healthcheck.sh   # 调大体积提醒阈值

# === 手动数据库备份（重大操作前必跑）===
./scripts/backup.sh                           # WAL-safe，sqlite3 .backup + integrity_check
./scripts/backup.sh --keep 10                 # 自定义保留份数（默认 30）

# === 历史数据 pruning · dry-run（只统计，不删除）===
./scripts/prune.sh --dry-run                  # 默认统计过去 180 天可清理的日志行数
./scripts/prune.sh --dry-run --days 365       # 自定义保留天数
                                              # ⚠️ 当前版本无 --confirm 能力；不会删任何数据

# === 服务状态 ===
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 100 --no-pager
journalctl -u chiyanlu-bot -f                 # 实时跟随日志，Ctrl+C 退出
journalctl -u chiyanlu-bot --since "10 min ago" --no-pager

# === update.sh ===
./update.sh status                            # 查看版本、commit、运行状态
./update.sh restart                           # 重启服务
./update.sh rollback                          # 回滚到上一个备份（首选恢复手段）

# === 数据库只读检查 ===
sqlite3 data/bot.db "PRAGMA journal_mode;"    # 应返回 wal
sqlite3 data/bot.db "PRAGMA integrity_check;" # 应返回 ok
sqlite3 data/bot.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"

# === 磁盘 / 进程 ===
df -h /opt
ps -ef | grep -i bot | grep -v grep
```

---

## 三、服务挂了怎么办

### 触发场景
- 用户反馈 Bot 不回复 / 命令没响应
- `systemctl status` 显示 `inactive` / `failed`
- `journalctl` 有 `Traceback` / `CRITICAL` / `Exception`

### 处理流程

**Step 1 — 确认现状**

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 先跑一次健康检查，拿到环境全貌（只读，安全）
./scripts/healthcheck.sh

# 再看 systemd 当前状态与最近日志
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 200 --no-pager
```

> 💡 `./scripts/healthcheck.sh` 会一次性报告 Python / SQLite / systemd / Git 是否正常，
> 比逐条手敲命令更快锁定症结。它**只读**，不会修改任何业务数据。

**Step 2 — 判断类型**

| 现象 | 处置 |
| --- | --- |
| 服务只是 `inactive`（dead），没有 Traceback | 走 Step 3 直接拉起 |
| 服务 `failed`，日志末尾有 Traceback | 走 Step 4 看错误 |
| 刚刚执行过 `./update.sh update` 后挂了 | 直接走 Step 5 回滚 |

**Step 3 — 直接拉起**

```bash
./update.sh restart
# 或
sudo systemctl start chiyanlu-bot
systemctl status chiyanlu-bot
```

观察 30 秒，看是否进入 `active (running)`，并且 `journalctl -f` 没有继续报错。

**Step 4 — 启动失败排查（不要急着改库！）**

按顺序检查：
1. `.env` 是否存在、权限是否 600、是否被改坏（**不要 cat .env，不要把内容粘出来**）

   ```bash
   ls -l .env
   # 仅检查存在与权限，不要输出内容
   ```
2. 依赖是否完整：`./update.sh status` 看版本和 venv 状态
3. 数据库完整性：`sqlite3 data/bot.db "PRAGMA integrity_check;"`，**结果必须是 `ok`**
4. 磁盘是否写满：`df -h /opt`

**Step 5 — 刚更新后失败，立即回滚**

```bash
./update.sh rollback
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 100 --no-pager
```

`./update.sh rollback` 是**首选恢复手段**，它会自动恢复代码与数据库备份。

**Step 6 — 留痕**

按第十二节模板记录：发现时间、错误摘要、采取的命令、恢复时间。

---

## 四、更新失败怎么办

### 触发场景
- `./update.sh update` 中途报错
- `git pull` / `git rebase` 提示冲突
- `pip install` 失败
- `compileall` 失败
- 启动后日志有 Traceback / migration failed

### 处理原则
- **优先按 `update.sh` 的输出处理**，它会提示在哪一步失败。
- **不要手工 `git reset --hard` / `git checkout .`**，会丢失备份逻辑。
- **不要手工 `pip install` 任何包**，会污染 venv。
- **不要手工改数据库**，迁移失败时最后手段是回滚整个备份。

### 处理流程

**Step 1 — 看 update.sh 输出的最后一行**

通常会写 `[FAIL] xxx`，对照下表处理：

| 失败阶段 | 处置 |
| --- | --- |
| `git pull` / rebase 冲突 | 走 Step 2 |
| `pip install` 失败 | 走 Step 3 |
| `compileall` 失败 | 走 Step 4 |
| `alembic upgrade` 失败 | 走 Step 5（最严重，立刻回滚） |
| 服务启动失败 | 走第三节 Step 5 |

**Step 2 — git 冲突**

```bash
cd /opt/Chiyanlu-Exclusive-Bot
git status
```

如果有未提交的本地修改，**先别 stash**，确认这些修改不是某次值守临时改出来的。
如果确实是干净的冲突，使用：

```bash
./update.sh rollback
```

回到上一个版本，**让开发者处理冲突**，不要在服务器上手 merge。

**Step 3 — pip install 失败**

通常是网络或源问题。先 `./update.sh status` 看当前是否还是旧版本：
- 如果代码已切到新版本但 venv 没装好 → `./update.sh rollback`
- 如果代码还在旧版本 → 重试一次 `./update.sh update`，仍失败转开发者

**Step 4 — compileall 失败**

说明新代码有语法错误，不要尝试修。

```bash
./update.sh rollback
```

**Step 5 — alembic 迁移失败（数据库相关）**

⚠️ 这是最高危情形。

```bash
# 1. 立刻停服（避免后续半态写入）
sudo systemctl stop chiyanlu-bot

# 2. 完整性检查
sqlite3 data/bot.db "PRAGMA integrity_check;"

# 3. 回滚
./update.sh rollback

# 4. 再次完整性检查
sqlite3 data/bot.db "PRAGMA integrity_check;"

# 5. 启动并观察
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 100 --no-pager
```

如果 `./update.sh rollback` 失败 → 升级给开发者（第十三节）。

**Step 6 — 服务停了但代码没更新成功**

只要现在服务能起来就先起来：

```bash
sudo systemctl start chiyanlu-bot
systemctl status chiyanlu-bot
```

起不来 → 走 `./update.sh rollback`。

---

## 五、数据库异常怎么办

### 触发场景
- `PRAGMA integrity_check` 返回不是 `ok`
- 日志出现 `SQLite database is locked`
- 日志出现 `no such table` / `no such column`
- `alembic` 迁移失败
- 看到 `reimbursements_new` 残留表

### SQLite WAL 提醒

⚠️ 本项目使用 **WAL 模式**，磁盘上同时有：
- `data/bot.db`（主库）
- `data/bot.db-wal`（写前日志，可能有未提交数据）
- `data/bot.db-shm`（共享内存）

> **不要 `cp data/bot.db`**，否则 `-wal` 里的数据会丢，库内容会变成几分钟前甚至几小时前的状态。
> **必须用 `sqlite3 .backup`**（见第六节）。

### 只读排查命令

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 1. WAL 模式确认
sqlite3 data/bot.db "PRAGMA journal_mode;"

# 2. 完整性
sqlite3 data/bot.db "PRAGMA integrity_check;"

# 3. 表清单
sqlite3 data/bot.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"

# 4. 关键计数
sqlite3 data/bot.db "SELECT COUNT(*) FROM reimbursements;"
sqlite3 data/bot.db "SELECT COUNT(*) FROM reimbursements_new;"   # 应为 0
sqlite3 data/bot.db "SELECT COUNT(*) FROM users;"
sqlite3 data/bot.db "SELECT COUNT(*) FROM lottery_entries;"

# 5. alembic 当前版本
sqlite3 data/bot.db "SELECT * FROM alembic_version;"
```

### 处理对照表

| 现象 | 处置 |
| --- | --- |
| `integrity_check` 不为 `ok` | **立刻停服**，备份，升级给开发者，**不要继续部署任何版本** |
| `database is locked` | 多见于并发 / 长事务。先重启服务：`./update.sh restart`，再观察 |
| `no such table` / `no such column` | 通常是迁移没执行完。停服 → 备份 → 升级给开发者 |
| `alembic upgrade` 失败 | 见第四节 Step 5 |
| `reimbursements_new` 非空 | **不要删表**，按 docs/POLICY.md Part II 人工对比后由开发者处理 |

### 何时绝对不要直接执行 SQL UPDATE / DELETE

- 报销 / 积分 / 抽奖业务表
- `alembic_version`
- `users` 表的余额字段

需要修正时走超管后台或第八、九节流程。

---

## 六、备份与恢复流程

### 6.1 何时备份
- 任何**计划内**的更新 / 回滚 / 数据库维护**之前**
- 任何要执行 `UPDATE` / `DELETE` SQL **之前**
- 任何怀疑数据库异常**之前**
- 任何要做手动恢复 / 覆盖主库 **之前**（再多备一份保命）

> `./update.sh update` 自身会做自动备份，但**只在远程有新提交时**才触发。
> 你手工动数据库前，必须用 `./scripts/backup.sh` 再做一次，**不依赖** update.sh 是否检测到新提交。

### 6.2 手动备份（首选 scripts/backup.sh）

```bash
cd /opt/Chiyanlu-Exclusive-Bot
./scripts/backup.sh
# 期望输出 [ OK ] 备份成功，并打印路径、大小、integrity_check=ok
# 退出码 0 = 成功；非 0 = 备份失败，不要继续后续危险操作

# 如需自定义保留份数（默认保留 30 份 manual 备份）：
./scripts/backup.sh --keep 10
```

脚本行为（已内置）：
- 使用 `sqlite3 .backup` 创建 WAL-safe 一致性快照
- 自动执行 `PRAGMA integrity_check`，返回 `ok` 才算成功
- 生成 `backups/bot.db.YYYYMMDD-HHMMSS.manual.bak`
- **只清理 `*.manual.bak`，不会动 `update.sh` 产生的 `*.bak`**
- 不读取或打印 `.env` / `BOT_TOKEN`

⚠️ **绝对不要** `cp data/bot.db backups/...`：WAL 模式下复制的是过期数据。
⚠️ 即使是临时调试，也**不允许**用 `cp` 替代 `sqlite3 .backup`。

### 6.3 历史数据 pruning · dry-run（不删除任何数据）

**触发场景**：`./scripts/healthcheck.sh` 输出
`[WARN] DB size: XXX MB > 512 MB，建议执行 ./scripts/prune.sh --dry-run --days 180`
时，按如下顺序处理（**仍然不会真删除任何数据**）：

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 第 1 步：先做一次备份（pruning 任何阶段的前置依赖）
./scripts/backup.sh

# 第 2 步：跑只读 dry-run，看过去 180 天可清理的日志行数
./scripts/prune.sh --dry-run --days 180

# 第 3 步：如需真正清理，等待 P3 confirm 路径实现；
#         绝不要手工 DELETE 任何业务表
```

dry-run 输出会列出 `user_events` / `user_teacher_views` 两张表的命中行数、
最早 / 最新时间戳与 `action`（`safe-to-delete-after-backup` / `nothing-to-prune`）。

> ⚠️ **当前 `scripts/prune.sh` 没有 `--confirm` 能力**。任何 `--confirm` /
> `--delete` / `--vacuum` / `--execute` 都会被脚本直接拒绝（exit 1）。
> 即使 dry-run 显示有 100 万行可清理，**不要**手工 `sqlite3 ... "DELETE FROM ..."`
> 替代脚本；永远不要对 `point_transactions` / `reimbursements` / `teacher_reviews`
> / `lottery_entries` 等权益类表手工 `DELETE`。
> 详见 [INFRASTRUCTURE-DESIGN.md Part B §六](INFRASTRUCTURE-DESIGN.md#六执行设计) 与 [Part B §十一](INFRASTRUCTURE-DESIGN.md#十一明确不做)。

#### 6.2.x 降级方案：scripts/backup.sh 也跑不起来时

仅在脚本本身有问题（极少见）的紧急情况使用，命令必须等价于脚本内部行为：

```bash
cd /opt/Chiyanlu-Exclusive-Bot
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/bot.db.${TS}.manual.bak"
mkdir -p backups
sqlite3 data/bot.db ".backup '$BACKUP'"
sqlite3 "$BACKUP" "PRAGMA integrity_check;"
# 必须看到输出 ok，否则该备份不可用
ls -lh "$BACKUP"
```

### 6.4 恢复（优先用 update.sh rollback）

```bash
./update.sh rollback
```

它会恢复代码 + 数据库备份。99% 的情况用这条就够。

### 6.5 手动恢复（最后手段）

⚠️ 操作前**必须**：
- 已经手动备份当前 `data/` 目录（用 6.2 的方式）
- 服务必须先停
- 删除 `-wal` / `-shm`，否则恢复后旧 WAL 会污染主库

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 1. 停服
sudo systemctl stop chiyanlu-bot

# 2. 当前库再备份一次（保命）
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p backups/before-restore/$TS
sqlite3 data/bot.db ".backup 'backups/before-restore/$TS/bot.db'" || true

# 3. 删除 WAL/SHM 残留
rm -f data/bot.db-wal data/bot.db-shm

# 4. 覆盖主库（替换为你选的备份路径）
cp /path/to/backup/bot.db data/bot.db

# 5. 完整性检查
sqlite3 data/bot.db "PRAGMA integrity_check;"
sqlite3 data/bot.db "PRAGMA journal_mode;"

# 6. 启动并观察
sudo systemctl start chiyanlu-bot
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 100 --no-pager
```

如果 5 步 `integrity_check` 不是 `ok` → 升级给开发者。

---

## 七、抽奖事故处理

> 政策原文见 [POLICY.md Part III](POLICY.md#part-iii抽奖规则)。

### 触发场景
- 到点没有发布抽奖
- 到点没有开奖
- 用户说无法参与
- 用户积分被扣但没有参与成功
- 中奖用户未收到通知
- 频道开奖结果没发出来

### 处理思路

1. **结果以 DB 中 `lottery_entries.won` 为准**，不以群消息为准。
2. **不要手工重抽**，除非产品 / 超管明确允许并写下书面依据。
3. **不在群内承诺结果**，统一回复「已记录，正在核对」。

### 只读 SQL 排查

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 当前抽奖
sqlite3 data/bot.db "SELECT id, status, draw_time, message_id FROM lotteries ORDER BY id DESC LIMIT 5;"

# 某个抽奖的参与情况（把 <LID> 替换为抽奖 ID）
sqlite3 data/bot.db "SELECT COUNT(*) FROM lottery_entries WHERE lottery_id=<LID>;"

# 某个用户在某抽奖里的状态（替换 <UID> <LID>）
sqlite3 data/bot.db "SELECT id, status, won, entry_cost, created_at FROM lottery_entries WHERE user_id=<UID> AND lottery_id=<LID>;"

# 中奖名单
sqlite3 data/bot.db "SELECT user_id, won FROM lottery_entries WHERE lottery_id=<LID> AND won=1;"

# 必关频道配置
sqlite3 data/bot.db "SELECT id, lottery_id, chat_id FROM required_chat_ids WHERE lottery_id=<LID>;"
```

### 日志侧

```bash
journalctl -u chiyanlu-bot --since "2 hours ago" | grep -i -E "lottery|apscheduler|draw"
```

### 对照处理

| 现象 | 处置 |
| --- | --- |
| 到点没发布 | 查 APScheduler 日志、Bot 进程是否健康；不要手工补发，让开发者确认调度状态 |
| 到点没开奖 | 同上 |
| 用户说无法参与 | 检查必关频道（`required_chat_ids`）、用户积分、`lottery_entries` 是否已有记录 |
| 扣分但没参与成功 | 查 `lottery_entries` 是否存在该用户；如确实异常，走第九节积分修正流程 |
| 中奖未通知 | 查日志 Telegram API 错误；不要在群里二次广播中奖名单 |
| 频道结果没发出 | 检查 Bot 在频道是否仍有管理员权限 |

---

## 八、报销事故处理

> 政策原文见 [POLICY.md Part II](POLICY.md#part-ii报销规则)。

### 触发场景
- 用户说满足条件但没看到报销
- 报销长期处于 `queued`
- 报销池不足
- 用户本周已达上限
- 驳回后用户申诉
- `reimbursements_new` 非空（迁移残留）

### 处理思路

1. **对照 POLICY.md Part II** 判断是否符合策略，不能凭印象。
2. **先查 review_id / reimbursement id**，让用户提供，再去 DB 确认。
3. **不承诺一定通过**，话术统一：「我帮你查一下记录」。
4. **不直接 `UPDATE reimbursements.status`**。需要补偿时走积分修正（第九节）或超管后台。

### 只读 SQL 排查

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 按 review id 查报销记录
sqlite3 data/bot.db "SELECT id, user_id, review_id, status, amount, created_at FROM reimbursements WHERE review_id=<RID>;"

# 按用户查最近报销
sqlite3 data/bot.db "SELECT id, review_id, status, amount, created_at FROM reimbursements WHERE user_id=<UID> ORDER BY id DESC LIMIT 10;"

# 报销池余量（按你们配置的池模型字段查，名称参考 POLICY.md Part II）
sqlite3 data/bot.db "SELECT * FROM reimbursement_pool ORDER BY id DESC LIMIT 3;"

# 残留表检查
sqlite3 data/bot.db "SELECT COUNT(*) FROM reimbursements_new;"
```

### 对照处理

| 现象 | 处置 |
| --- | --- |
| 用户说没收到报销 | 先按 review_id 查记录；若 `status=queued` 属预期，告知用户排队中 |
| 报销卡 `queued` 过久 | 检查池余量；不要手动改 status |
| 池不足 | 不在群内宣布，按超管流程处理补池 |
| 已达每周上限 | 按政策回复用户，不要破例 |
| 驳回申诉 | 让用户提交新材料，**不要直接改驳回记录**；如确认是系统误判，由超管处理 |
| `reimbursements_new` 非空 | **不要 DROP**，截图 + 计数后升级给开发者 |

---

## 九、积分事故处理

> 政策原文见 [POLICY.md Part I](POLICY.md#part-i积分规则)。

### 触发场景
- 用户说积分没加
- 用户说积分被误扣
- 抽奖扣分失败
- `total_points` 与流水（积分明细）不一致
- 需要人工修正积分

### 处理思路

1. **对照 POLICY.md Part I** 确认获取 / 消耗规则。
2. **通过超管后台手动加扣分**，让系统写入流水，**不要直接 `UPDATE users SET total_points = ...`**。
3. **每次修正必须写 note**：填写业务编号（review_id / lottery_id）和原因。
4. 保留用户提供的截图和聊天记录，作为修正依据。

### 只读 SQL 排查

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 用户当前积分
sqlite3 data/bot.db "SELECT id, total_points FROM users WHERE id=<UID>;"

# 积分流水（表名以实际为准，常见为 point_transactions / points_log）
sqlite3 data/bot.db "SELECT id, user_id, change, reason, note, created_at FROM point_transactions WHERE user_id=<UID> ORDER BY id DESC LIMIT 20;"

# 流水合计 vs 余额（用于查不一致）
sqlite3 data/bot.db "SELECT user_id, SUM(change) FROM point_transactions WHERE user_id=<UID> GROUP BY user_id;"
```

### 对照处理

| 现象 | 处置 |
| --- | --- |
| 应加未加 | 找触发动作的业务记录（review/lottery），确认状态，再由超管补加 |
| 应扣未扣 | 同上，由超管补扣 |
| 抽奖扣分失败 | 检查 `lottery_entries`；若用户没参与成功且确实被扣，按超管流程补回 |
| `total_points` 与流水不一致 | **停止任何积分修正动作**，备份后升级给开发者 |

---

## 十、评价 / 报告事故处理

### 触发场景
- 用户提交评价卡住 / 报错
- 必关频道校验失败
- 审核通过后没有发布到讨论群
- 用户匿名显示异常
- 评价证据照片无法查看

### 处理思路

1. **审核相关操作只由超管处理**，值守人员不审核。
2. **不在群里讨论评价具体内容**，不公开老师资料。
3. 排查时优先看日志，再看 DB，**不要直接改 review 表**。

### 只读 SQL 排查

```bash
cd /opt/Chiyanlu-Exclusive-Bot

# 评价状态
sqlite3 data/bot.db "SELECT id, user_id, teacher_id, status, anonymous, created_at FROM reviews WHERE id=<RID>;"

# 必关订阅配置
sqlite3 data/bot.db "SELECT * FROM required_subscriptions;"

# 最近卡住的评价
sqlite3 data/bot.db "SELECT id, user_id, status, created_at FROM reviews WHERE status NOT IN ('approved','rejected') ORDER BY id DESC LIMIT 20;"
```

### 对照处理

| 现象 | 处置 |
| --- | --- |
| 用户提交卡住 | 看日志是否有 Telegram API 错误；引导用户重新提交一次 |
| 必关频道校验失败 | 检查 `required_subscriptions`、Bot 是否在该频道有管理员权限 |
| 审核通过未发布到讨论群 | 检查 Bot 是否仍在讨论群、是否有发送权限 |
| 匿名显示异常 | 备份后升级给开发者，不要改 `reviews.anonymous` 字段 |
| 照片无法查看 | 检查存储路径 / 文件是否还在；不要把照片转存到其他位置 |

---

## 十一、权限与安全事故

### 触发场景
- BOT_TOKEN 疑似泄露（被贴到聊天、截图、issue、PR）
- `.env` 被提交到 git
- `data/bot.db` 被提交到 git
- 管理员误操作（删消息、踢用户、放错频道）
- 服务器有异常登录记录

### ⚠️ 关键提醒

> 排查过程中**绝对不要**输出 `BOT_TOKEN` 或 `.env` 的任何字段内容到聊天、日志、截图、协作工具。
> 即使是「确认是不是某个 token」，也只比对 token 的**前 6 位 / 后 4 位**。

### 处理流程（BOT_TOKEN 泄露 / 怀疑泄露）

```bash
# 1. 立刻停服，防止旧 token 继续被使用
sudo systemctl stop chiyanlu-bot

# 2. 到 @BotFather 执行 /revoke 撤销当前 token，并获取新 token
#    手机或可信电脑上的 Telegram 操作，不在服务器上做

# 3. 在服务器编辑 .env，替换 BOT_TOKEN（用 vim/nano，不要 echo 到屏幕）
#    nano .env

# 4. 权限收紧
chmod 600 .env
ls -l .env

# 5. 启动服务
sudo systemctl start chiyanlu-bot
systemctl status chiyanlu-bot
journalctl -u chiyanlu-bot -n 50 --no-pager
```

### 处理流程（.env / bot.db 被提交到 git）

```bash
cd /opt/Chiyanlu-Exclusive-Bot
git log --all --full-history -- .env data/bot.db
```

如果有提交记录：
- **不要在服务器上 `git push --force`**
- 立刻通知开发者，按 GitHub 「移除敏感数据」流程清理远端
- 同时按上文 revoke token

### 处理流程（服务器异常登录）

```bash
# 1. 看登录记录
last -n 50
who
# 2. 看 ssh 配置 / authorized_keys 是否被改
ls -l ~/.ssh/
# 3. 若有可疑 IP，先封禁来源，再修改密码 / 替换 ssh key
# 4. 修改完成后重启服务并观察
```

异常 IP 与时间 → 同步给开发者 + 项目负责人。

---

## 十二、事故记录模板

每次事故都按这个模板填一份，保存在 `docs/INCIDENTS/` 或团队约定的位置。

```markdown
# 事故记录

时间：2026-MM-DD HH:MM（发现时间） ~ HH:MM（恢复时间）
发现人：
影响范围：（哪些用户、哪些功能、影响多久）
现象：（用户看到什么、监控看到什么）
关键日志：
```
（粘贴 5-20 行最相关的 journalctl 输出，**不要包含 token / .env / 用户隐私**）
```
初步原因：
处理步骤：
  1.
  2.
  3.
恢复时间：
是否需要回滚：是 / 否（命令、结果）
是否涉及用户权益：是 / 否（积分 / 报销 / 抽奖结果 / 评价审核）
后续改进：
```

---

## 十三、什么时候升级给开发者处理

遇到以下任意一项，**立刻停止操作**并联系开发者，附事故记录与日志摘要：

- `PRAGMA integrity_check` 不是 `ok`
- `alembic` 迁移失败
- `reimbursements_new` 非空
- 抽奖开奖状态异常（状态机错乱、`status` 字段非预期值）
- 积分流水合计与 `users.total_points` 不一致
- 大量 Telegram API `Forbidden` / `BadRequest`（短时间内 > 几十条）
- `./update.sh rollback` 失败
- 服务在 10 分钟内连续重启 ≥ 3 次
- BOT_TOKEN 泄露 / 服务器异常登录
- 任何你拿不准要不要改库的情况

**升级时要提供：**
- 事故时间窗
- `journalctl -u chiyanlu-bot --since "..." --until "..."` 的输出（脱敏后）
- `./update.sh status` 输出
- `PRAGMA integrity_check` 输出
- 是否已 `./update.sh rollback`、是否已停服

---

## 十四、相关文档

- [README.md](../README.md) — 项目总览
- [DEPLOYMENT.md](DEPLOYMENT.md) — 部署与 `update.sh` 详细说明
- [POLICY.md Part I](POLICY.md#part-i积分规则) — 积分获取 / 消耗规则
- [POLICY.md Part II](POLICY.md#part-ii报销规则) — 报销规则、池模型、每周上限
- [POLICY.md Part III](POLICY.md#part-iii抽奖规则) — 抽奖发布、参与、开奖规则
