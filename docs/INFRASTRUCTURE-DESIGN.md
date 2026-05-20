# INFRASTRUCTURE-DESIGN

> 数据库与运维基础设施设计文档。合并自原 `MIGRATION-REGISTRY-DESIGN.md` + `PRUNING-DESIGN.md`。
>
> 面向人群：后续接手 `bot/database.py` schema 维护、`scripts/prune.sh` / `scripts/backup.sh` / `scripts/healthcheck.sh` / `update.sh` 线上排查路径、以及做"破坏性 schema 变更"或"数据治理"的开发者与运维。
>
> **2026-05-20**：两份框架设计合并为单一文档，A / B 两大部分相互独立，各自保留原章节编号。

## 目录

- [Part A：Migration Registry（迁移注册器）](#part-amigration-registry迁移注册器) — `schema_migrations` 表 + Migration dataclass + soft/hard 等级 + healthcheck/update.sh 接入
- [Part B：Pruning（历史数据清理）](#part-bpruning历史数据清理) — 表级保留策略 + 白/黑名单 + dry-run + 备份前置 + scheduler 边界

---

# Part A：Migration Registry（迁移注册器）

面向人群：后续接手 `bot/database.py` schema 维护、`update.sh` / `healthcheck.sh`
线上排查路径、以及任何想要给数据库做"破坏性变更"的开发者。

---

## 一、当前迁移方式

当前实现位于 [bot/database.py](../bot/database.py)：

- **入口**：`async def init_db()` 启动时被 `bot/main.py` 调用一次。
- **建表**：`init_db()` 中用一组 `CREATE TABLE IF NOT EXISTS` 落地基础 schema。
- **增量迁移**：紧接 `CREATE TABLE` 之后，依次 `await _migrate_*()` 共 **9 个**：

  | 迁移函数 | 业务对应 |
  | --- | --- |
  | `_migrate_teacher_ranking_columns` | Phase 3：teachers 排序权重相关字段 |
  | `_migrate_user_source_columns` | Phase 4：users 来源追踪 4 字段 |
  | `_migrate_user_onboarding_column` | Phase 7.1：onboarding_seen |
  | `_migrate_teacher_profile_columns` | Phase 9.1：teachers 老师档案 10 字段 |
  | `_migrate_users_total_points` | Phase P.1：积分余额字段 |
  | `_migrate_lotteries_entry_cost` | 抽奖参与积分门槛 |
  | `_migrate_reviews_request_reimbursement` | 报销请求字段 |
  | `_migrate_reviews_anonymous` | 匿名评价字段 |
  | `_migrate_reimbursements_queued_status` | 报销 CHECK 约束 + 半完成态自愈（表重建） |

- **检测方式**：`PRAGMA table_info(<table>)` 拿现有列名集合，存在则跳过。
- **失败处理**：绝大多数迁移函数在内部 `try: ALTER TABLE ... ADD COLUMN ... except Exception: pass`
  —— **失败被静默吞掉**，启动不阻断。少数复杂迁移（如 `_migrate_reimbursements_queued_status`）
  会 `logger.warning(...)` 但同样不抛。

启动流程示意：

```text
bot/main.py
  └─ await init_db()
       ├─ CREATE TABLE IF NOT EXISTS …            (基础 schema)
       ├─ INSERT super_admin 到 admins            (幂等)
       ├─ await _migrate_teacher_ranking_columns
       ├─ await _migrate_user_source_columns
       ├─ …
       └─ await db.commit()
```

---

## 二、当前方式的优点

不要轻易抛弃这套现状。它**对当前业务规模是合适的**：

1. **简单**：每次新增 schema 变更，只要写一个 `_migrate_<name>(db)` 加进 `init_db()`
   末尾，启动时自动执行。没有版本号需要维护，没有元数据需要清理。
2. **SQLite 友好**：`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` 是 SQLite 原生
   支持的最稳定路径；ORM/Alembic 在 SQLite 上需要特殊配置（`batch_alter_table`）。
3. **不依赖 ORM**：项目坚持 SQL-first + `aiosqlite`，schema 由人写、查询由人写，
   出问题时直接读 SQL 比读 ORM session 上下文容易。
4. **适合单进程 polling Bot**：没有多副本并发跑迁移的问题，没有应用半启动状态。
5. **天然幂等**：所有 `_migrate_*` 都用"检测后变更"，反复启动同一份代码不会出错。

---

## 三、当前方式的问题

但它在**线上可观测性**上有明显短板：

1. **无 `schema_migrations` 表**：没有任何持久化记录说明"这个 DB 已经跑过哪些迁移"。
2. **看不出当前版本**：在线上拿到一份 `bot.db`，无法快速判断它处于哪个 Phase 的 schema。
3. **失败被吞掉**：`try/except: pass` 后，迁移失败和"列已存在跳过"在外部观察不到区别。
4. **`update.sh` 只能扫日志**：要判定迁移是否成功，必须 `journalctl -u chiyanlu-bot | grep`
   关键字，没有结构化信号。
5. **`healthcheck.sh` 无法报告 failed migration**：当前 [scripts/healthcheck.sh](../scripts/healthcheck.sh)
   只能检查 `integrity_check=ok` 和**核心表存在**，无法识别"列缺失"或"迁移失败留下的中间态"。
6. **回滚判定难**：[POLICY.md Part II 报销规则](POLICY.md#part-ii报销规则) 涉及的
   `reimbursements_new` 残留表问题，本质就是表重建型迁移中途失败、人工排查时
   缺少"哪一步停下来的"的证据。

这些都不是日常开发的痛点，但只要发生一次"用户反馈但日志已轮转"的事故就会非常被动。

---

## 四、目标设计

**建议**在保留全部现有 `_migrate_*` 函数的前提下，引入一张 `schema_migrations` 表用于
持久化迁移状态。设计如下（SQLite DDL）：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       TEXT    PRIMARY KEY,            -- 例如 '2026-05-18-001-add-teacher-rank'
    name          TEXT    NOT NULL,                -- 人类可读名称
    kind          TEXT    NOT NULL DEFAULT 'soft', -- 'soft' | 'hard'（见第七节）
    applied_at    TEXT,                            -- ISO8601 UTC；NULL 表示尚未执行
    success       INTEGER NOT NULL DEFAULT 0,      -- 0 / 1
    error         TEXT,                            -- 失败时填写异常摘要（截断到 ~512 字符）
    checksum      TEXT,                            -- 迁移代码 / SQL 的指纹（防外部篡改后误判已跑）
    duration_ms   INTEGER,                         -- 单次执行耗时
    created_at    TEXT    DEFAULT CURRENT_TIMESTAMP
);
```

字段说明：

| 字段 | 用途 | 备注 |
| --- | --- | --- |
| `version` | 全局唯一标识 | 用日期前缀 `YYYY-MM-DD-NN-<slug>` 保证字典序 = 执行顺序 |
| `name` | 给人看 | 不参与逻辑判断 |
| `kind` | 失败是否阻断启动 | 详见 [第七节](#七迁移等级) |
| `applied_at` | 最后一次尝试时间 | 即使失败也写入；失败再重试会刷新此字段 |
| `success` | 是否成功 | 启动时只跳过 `success=1` 的迁移 |
| `error` | 失败原因 | 仅 `success=0` 时有意义；成功时清空 |
| `checksum` | 防误判 | 若迁移代码改过但 version 没改，checksum 不同 → 提示开发者 |
| `duration_ms` | 性能基线 | 帮助识别变慢的迁移 |
| `created_at` | 首次注册时间 | 仅供审计 |

> ⚠️ 这张表**本身的创建必须是迁移注册器的第 0 步**，且 `CREATE TABLE IF NOT EXISTS`
> 必须幂等。否则没法引导新老库。

---

## 五、迁移注册格式

**建议**两种风格二选一（推荐 Migration 对象版本，更结构化）。

### 5.1 Migration 对象版本（推荐）

```python
from dataclasses import dataclass
from typing import Awaitable, Callable
import aiosqlite

@dataclass(frozen=True)
class Migration:
    version: str                                       # '2026-05-18-001-add-teacher-rank'
    name: str                                          # 'Phase 3: teacher ranking columns'
    kind: str                                          # 'soft' | 'hard'
    apply: Callable[[aiosqlite.Connection], Awaitable[None]]

MIGRATIONS: list[Migration] = [
    Migration(
        version="2026-05-18-001-teacher-rank",
        name="Phase 3: teachers 排序权重相关字段",
        kind="soft",
        apply=_migrate_teacher_ranking_columns,        # 沿用现有函数
    ),
    # ……
    Migration(
        version="2026-05-18-009-reimb-queued-rebuild",
        name="报销 CHECK 重建 + 半完成态自愈",
        kind="hard",                                   # 表重建必须 hard
        apply=_migrate_reimbursements_queued_status,
    ),
]
```

### 5.2 tuple 版本（更紧凑，弱类型）

```python
MIGRATIONS = [
    ("2026-05-18-001-teacher-rank",
     "Phase 3: teachers 排序权重相关字段",
     "soft",
     _migrate_teacher_ranking_columns),
    # ……
]
```

无论哪种风格，**注册表的顺序就是执行顺序**，新迁移**只追加在末尾**。
不要插入到中间，否则新装的库会按字典序跑、旧库已经按追加顺序跑过，行为不一致。

---

## 六、迁移执行流程

`init_db()` 的内部流程**建议**改造为如下伪代码（保留所有现有 `_migrate_*` 不动）：

```python
async def init_db():
    db = await get_db()
    try:
        # Step 0: 基础 schema（保持现状，CREATE TABLE IF NOT EXISTS）
        await db.executescript(BASE_SCHEMA_SQL)

        # Step 1: 确保 schema_migrations 表存在（幂等）
        await _ensure_schema_migrations_table(db)

        # Step 2: 读取已成功的 version 集合
        applied = await _load_applied_versions(db)  # 返回 set[str]

        # Step 3: 按注册顺序执行未成功的迁移
        for m in MIGRATIONS:
            if m.version in applied:
                continue
            t0 = time.monotonic()
            try:
                await m.apply(db)
            except Exception as e:
                duration = int((time.monotonic() - t0) * 1000)
                await _record_migration(db, m, success=False,
                                        error=_truncate(repr(e), 512),
                                        duration_ms=duration)
                await db.commit()
                if m.kind == "hard":
                    raise                  # hard 失败 → 立刻阻断启动
                logger.warning("soft migration failed: %s (%s)", m.version, e)
                continue                  # soft 失败 → 记录但继续
            duration = int((time.monotonic() - t0) * 1000)
            await _record_migration(db, m, success=True, error=None,
                                    duration_ms=duration)
            await db.commit()

        # Step 4: 其它原有初始化（超管插入、默认模板等）
        ...

    finally:
        await db.close()
```

要点：

- **每条迁移独立提交**，避免一条失败回滚多条已成功的迁移。
- **失败也要写一行**到 `schema_migrations`（`success=0` + `error`），方便外部巡检。
- **下次启动重试**：因为只跳过 `success=1` 的，失败的会自动再试一次。这意味着所有迁移
  **必须是幂等的**（与现状一致）。
- **hard 失败立刻 raise**：让 systemd 看到非 0 退出码，触发 `journalctl` 报错，运维
  能直接执行 `./update.sh rollback`。

---

## 七、迁移等级

按"失败时是否应阻断启动"分为两级：

| 等级 | 适用场景 | 失败处理 | 业务例子 |
| --- | --- | --- | --- |
| **`soft`** | ADD COLUMN、CREATE INDEX、非关键配置插入 | logger.warning，记录到表，继续启动 | 增加可选字段、来源追踪、onboarding_seen |
| **`hard`** | 表重建、CHECK 约束、积分/报销/抽奖/评价**核心字段变更**、外键变更 | 写入 `success=0`，**立刻 raise**，systemd 退出，触发回滚 | `_migrate_reimbursements_queued_status` 这类表重建；未来的积分余额 schema 调整 |

判定原则：**如果这条迁移失败后业务读到旧 schema 会出现"扣了分但没记录"、
"报销算错金额"、"抽奖状态错乱"这种用户感知到的不一致**，就必须是 `hard`。

> 经验法则：
> - 单纯 `ALTER TABLE ADD COLUMN ... DEFAULT NULL` → 几乎一定是 soft
> - 任何涉及 `CREATE TABLE ..._new` + `INSERT INTO ..._new SELECT ...` + `RENAME` 的
>   表重建 → 必须 hard
> - 任何会让旧版业务代码 `INSERT` 报错的变更（如新增 NOT NULL 列）→ 必须 hard

---

## 八、与现有 `_migrate_*` 的兼容策略

**绝不**一次性把现有 9 个 `_migrate_*` 全部注册进新表。分四阶段平滑过渡：

### 阶段 A：Baseline（"承认现状"）

> **✅ 此阶段已实现**（2026-05-18）。
> 实际代码位于 [bot/database.py](../bot/database.py) 中：
> - 常量 `SCHEMA_MIGRATIONS_BASELINE`：9 条历史迁移的 (version, name, kind) 元组
> - 函数 `ensure_schema_migrations_table(db)`：幂等创建表
> - 函数 `baseline_schema_migrations(db)`：用 `INSERT OR IGNORE` 写入 baseline
> - `init_db()` 在 INSERT super_admin 之后调用 `ensure_*`，
>   在 9 个 `_migrate_*` 全部执行完之后调用 `baseline_*`
> 现有 9 个 `_migrate_*` 函数**仍按原顺序无条件执行**，本表当前不参与执行决策。

在 P2 引入 `schema_migrations` 表的同一次启动里：

1. 创建 `schema_migrations` 表（幂等）。
2. 对所有**已存在的** `_migrate_*` 函数，**先执行一次**（沿用现状）。
3. 执行成功后，**手动写入** baseline 行：

   ```sql
   INSERT OR IGNORE INTO schema_migrations
       (version, name, kind, applied_at, success, error)
   VALUES
       ('20260518_001_migrate_teacher_ranking_columns',
        'Phase 3: teachers 排序/精选字段',
        'soft', CURRENT_TIMESTAMP, 1, NULL),
       ……;
   ```
4. 之后再启动，这些 baseline 行已存在，`INSERT OR IGNORE` 静默跳过。

> ⚠️ **当前 P2 实现的限制**：
> baseline 是"无条件追加 success=1"。如果 9 个 `_migrate_*` 中某个真实失败了
> （现状下被 `try/except: pass` 吞掉），baseline 仍会写 success=1。这就是"承认
> 现状"的代价——但因为现有 `_migrate_*` 全部是 `PRAGMA table_info` 检测后才
> ALTER 的真幂等迁移，这种偏差在实践中极小。**P3 阶段引入的新迁移**会按
> [第六节](#六迁移执行流程) 的真实成功/失败写入，行为更精确。

> ⚠️ baseline 的关键陷阱：如果旧库**本来就装过**这些迁移、新库**从未装过**，二者
> 跑到这一步看到的 `applied` 集合不同。必须保证 **step 2 的"先执行一次"是真正
> 幂等的**，否则 baseline 在新库上会把"列已存在"误判为"已迁移"。
> 现状 9 个 `_migrate_*` 均检测后变更，符合幂等要求。

### 阶段 B：新迁移走注册器

阶段 A 之后，**新增**的 schema 变更都通过 `MIGRATIONS` 列表注册，不再直接加到
`init_db()` 末尾。审查 PR 时强制要求迁移文件命名 `migrations/<version>_<slug>.py`。

### 阶段 C：healthcheck.sh 接入

> **✅ 此阶段已实现**（2026-05-18，与 P2 同期）。
> 实际位置：[scripts/healthcheck.sh](../scripts/healthcheck.sh) 「三、SQLite 检查」
> 区段末尾的 `if grep -Fxq "schema_migrations" <<<"${existing_tables}"` 分支。
> 实现细节与下方设计完全一致；唯一区别是**只输出数量**，不打印 `error` 内容
> （满足"不打印数据片段"的安全约束）。

在 [scripts/healthcheck.sh](../scripts/healthcheck.sh) 增加一节"数据库迁移检查"：

```sql
SELECT version, name, error FROM schema_migrations
WHERE success = 0;
```

- 若返回行数 > 0：
  - kind='hard' 的失败 → `[ERR ]`，退出码 1
  - kind='soft' 的失败 → `[WARN]`
  - kind 不在 {soft, hard} 中的失败 → `[WARN]`（防御未来扩展）
- **只输出数量**，不打印 `error` 内容（避免日志冗长 / 潜在敏感信息）
- 表不存在 → `[WARN]` 兼容旧库

### 阶段 D：update.sh 接入

> **✅ 此阶段已实现**（2026-05-18 commit *next*）。实际位置：
> [update.sh](../update.sh) 顶部新增 `_check_schema_migrations_status()` 函数；
> 完整 update 流程在 systemd 服务进入 active + `_scan_post_start_logs` 通过之后调用。

[update.sh](../update.sh) 在启动健康检查后多跑一组查询：

```bash
sqlite3 "$DB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations';"
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM schema_migrations WHERE success=0 AND kind='hard';"
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM schema_migrations WHERE success=0 AND kind='soft';"
```

行为：
- 表不存在 → WARN，不阻断（兼容旧库 / 未启动新版本）
- hard failed > 0 → **ERR + 内置 `./update.sh rollback` 建议 + exit 1**
- soft failed > 0 → WARN，不阻断
- 全 0 → OK

发现 hard failed migration 时**不要**自动 rollback，而是**提示**运维人工决定。
自动回滚一个表重建中失败的库可能比"暂停服务等人来看"更危险。

---

## 九、为什么不引入 Alembic

Alembic 是优秀的工具，但**对本项目成本大于收益**：

1. **SQL-first 项目**：业务层手写 SQL，Alembic 的 ORM model autogenerate 用不上。
2. **SQLite 限制多**：Alembic 在 SQLite 上修改约束 / 字段类型，需要 `batch_alter_table`
   做表重建模拟，开发者仍要手写表重建逻辑——相当于绕了一圈回到现状。
3. **学习成本**：新开发者要先理解 Alembic 的 revision 链 + autogenerate diff，
   而本项目迁移点不多（一年大约 5-10 条），不值得引入新概念。
4. **额外依赖**：增加 `alembic` + `sqlalchemy` 依赖体积，启动时间也会变慢。
5. **回滚语义不匹配**：Alembic 的 `downgrade` 在 SQLite 表重建场景几乎无法可靠实现，
   而项目实际依赖的回滚是 `update.sh rollback`（恢复 `bot.db` 文件备份），与 Alembic
   的版本号下行完全是两条线。

**唯一例外**：如果未来真的迁到 PostgreSQL（见下一节），可以重新评估 Alembic。

---

## 十、为什么不迁移 PostgreSQL

当前 SQLite WAL 模式 + busy_timeout + synchronous=NORMAL 对本项目体量足够：

- 单进程 polling Bot，无并发写
- 数据量级（用户表 / 评价表 / 报销表 / 抽奖参与表）在百万行内，SQLite 完全胜任
- 读多写少，WAL 模式下读写互不阻塞
- 备份只需 `sqlite3 .backup` 一条命令 + 一份文件

**真正影响线上稳定性的风险，不是数据库引擎**，而是：

1. **备份完整性**：见 [DEPLOYMENT.md §14](DEPLOYMENT.md#14-备份与恢复) —— 必须用
   `sqlite3 .backup`，不能 `cp`。已通过 `scripts/backup.sh` 解决。
2. **迁移可观测性**：本文档要解决的问题。
3. **历史数据 pruning**：评价 / 流水表长期增长后，索引膨胀 / vacuum 频率需要规划。
   现状未规划。
4. **集成测试**：见 [DEPLOYMENT.md §16](DEPLOYMENT.md#16-验收-checklist) 0.5 步骤
   的 pytest，目前只覆盖纯逻辑，**没有覆盖迁移自身**。

迁 PostgreSQL 不会解决以上任何一项。在解决以上四项之前，迁库属于**用更复杂的运维
换更不复杂的潜在收益**，性价比为负。

---

## 十一、与 update.sh / backup.sh / healthcheck.sh 的关系

迁移注册器与三个脚本的协作矩阵：

| 脚本 | 当前行为 | 引入注册器后的扩展 |
| --- | --- | --- |
| [update.sh](../update.sh) | 拉代码 → 备份 DB → 重启服务；不感知迁移结果 | 重启后**额外查询** `schema_migrations`，发现 `success=0 AND kind='hard'` 时阻断并提示回滚 |
| [scripts/backup.sh](../scripts/backup.sh) | `sqlite3 .backup` + `integrity_check` | **不变**。备份必须在 `_migrate_*` 修改 schema **之前**完成 |
| [scripts/healthcheck.sh](../scripts/healthcheck.sh) | 检查 `integrity_check=ok` + 10 张核心表存在 | 新增「七、迁移状态检查」小节：扫 `schema_migrations` 中 `success=0` 的行，按 kind 分级输出 |

时序约束：

```text
任何 schema 变更前：
    ./scripts/backup.sh                   # 必须先做，且必须验证 integrity_check=ok
    └─ 备份成功 → 才允许继续

启动 / 部署时：
    init_db()
      ├─ CREATE TABLE IF NOT EXISTS …
      ├─ ensure schema_migrations
      ├─ 按 MIGRATIONS 顺序执行
      └─ commit

部署后：
    ./scripts/healthcheck.sh             # 扫迁移失败
    ./update.sh                           # （未来）若 hard failed → 阻断并提示 rollback
```

---

## 十二、实施计划

按风险递增分 6 阶段：

| 阶段 | 内容 | 状态 | 风险 | 业务影响 |
| --- | --- | --- | --- | --- |
| **P1** | 仅新增本设计文档 | ✅ 已完成 | 无 | 无 |
| **P2** | 引入 `schema_migrations` 表 + baseline 写入（[阶段 A](#阶段-abaseline承认现状)） | ✅ 已完成 | 低 | 启动时多一次 INSERT |
| **P3** | 新迁移开始走 `MIGRATIONS` 注册器（[阶段 B](#阶段-b新迁移走注册器)） | ✅ 框架已完成 | 中 | 仅影响**新增**迁移代码风格；`MIGRATIONS=[]`，无任何实际迁移变更 |
| **P4** | `scripts/healthcheck.sh` 增加迁移状态检查（[阶段 C](#阶段-chealthchecksh-接入)） | ✅ 已完成 | 低 | 只读 |
| **P5** | `update.sh` 检测 hard failed migration 并提示 rollback（[阶段 D](#阶段-d-updatesh-接入)） | ✅ 已完成 | 中 | 部署流程多一步判断；只读 SELECT，不自动 rollback |
| **P6** | 补 pytest 覆盖迁移注册器逻辑（applied 集合、kind 路由、checksum 比对、幂等性） | 🟡 部分完成 | 低 | 仅测试代码 |

P1 即为本文档。P2-P6 必须在确认 P1 设计被 review、达成共识后再依次推进。
P3 之后**不要**再把现有 `_migrate_*` 改写——它们已通过 baseline 被认作"已应用"，
反向迁移没有意义。

---

## 十三、风险与注意事项

落地过程中需要规避的"会让人睡不着觉"的坑：

1. **baseline 不能误判旧库状态**
   引入 `schema_migrations` 的那次启动，**必须**先把全部现有 `_migrate_*` 执行
   一遍（它们已幂等），然后**才**写入 baseline 行。
   反过来——先写 baseline、后跑 `_migrate_*`——会让全新空库错过实际迁移。

2. **hard migration 失败不要自动继续业务**
   `init_db()` 抛异常 → 让 systemd 看到退出码 → 服务停 → 运维介入。
   不要做"业务降级开关"绕开迁移，那是在生产数据上玩俄罗斯轮盘。

3. **表重建型迁移前必须备份**
   `_migrate_reimbursements_queued_status` 这类创建 `_new` 表 → 拷数据 → RENAME 的
   迁移，启动期间一旦中途断电 / OOM，会留下 `reimbursements_new` 残留表。
   规范：**带表重建的 hard migration**，注册器在执行 apply 之前**主动调一次
   `sqlite3 .backup`**（或要求 `update.sh` 已经备过）。
   未来可在 Migration 对象上加 `requires_backup: bool = False` 字段，hard + 表重建
   一律为 True。

4. **`schema_migrations` 表本身也要幂等创建**
   `CREATE TABLE IF NOT EXISTS schema_migrations (...)` + `CREATE INDEX IF NOT EXISTS`
   不允许任何"假定它存在"的 SQL 提前执行。

5. **`success=0` 行不要被外部脚本误删**
   失败行是**唯一**的失败证据。任何"清理旧记录"的脚本只允许删 `success=1` 的旧行。

6. **不允许同一 `version` 被两个 PR 注册**
   PR review 时要核对 `MIGRATIONS` 列表是否冲突。可在 P6 写一条 pytest 断言
   `len({m.version for m in MIGRATIONS}) == len(MIGRATIONS)`。

7. **`error` 字段截断**
   异常 `repr` 在某些路径下可能包含 SQL 参数（含用户输入 / 老师信息）。
   写入前**强制截断到 ~512 字符**，并避免直接把 `error` 内容打回 Telegram / 日志群。

8. **checksum 不是安全机制**
   它只用来提示"代码改过但 version 没变"。攻击者改库的场景下保护力为 0。
   真正的防篡改靠**只读运维账号 + 备份完整性校验**。

9. **不要在迁移里写业务回填**
   迁移负责 schema，不负责数据语义。回填用户积分 / 报销金额这类业务逻辑应该是
   单独的一次性脚本（甚至更稳的方式是放到管理后台触发），不要混进 `MIGRATIONS`
   列表，否则未来重置 baseline 会很痛苦。

---

---

# Part B：Pruning（历史数据清理）


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
| `schema_migrations` | 迁移历史 | 系统元数据 | ❌ 不清理 | 永久 | — | `applied_at` / `created_at` | 唯一的迁移历史证据；详见 [Part A：Migration Registry](#part-amigration-registry迁移注册器) |
| `point_transactions` | 积分流水 | **权益** | ❌ 不自动删 | 永久 | 长期 | `created_at` | 失败一次会引发积分对账事故；详见 [POLICY.md Part I 积分规则](POLICY.md#part-i积分规则) |
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

> **✅ 此小节已实现**（2026-05-18，P2）。实际脚本：[scripts/prune.sh](../scripts/prune.sh)。
> 自 2026-05-20 Sprint 7 §9.2 起，脚本同时支持 `--dry-run` 与 `--confirm`：
> `--dry-run` 仅统计；`--confirm` 真实删除（详见下面 §六）。
> 任何 `--delete / --vacuum / --execute` 参数仍然会立即 `[ERR ]` 并 exit 1。
> 注：`user_teacher_views` 的真实时间字段是 `viewed_at`（不是 `created_at`），
> 输出中 `condition:` 行使用每张表的真实字段名；`oldest_created_at` / `newest_created_at`
> 是固定的报告字段名（即使源列叫 `viewed_at`）。

`scripts/prune.sh` 默认**只做统计、不删除**：

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

> **✅ 此小节已实现**（2026-05-20，P3，Sprint 7 §9.2）。实际实现含
> [scripts/prune.sh](../scripts/prune.sh) `--confirm` 路径 +
> [tests/test_prune_script_confirm.py](../tests/test_prune_script_confirm.py)
> 17 个 test（A 静态契约 11 + B 集成 6）覆盖。

`scripts/prune.sh --confirm` 的不可破坏前置条件（已实施）：

1. **必须有当天 backup** —— 脚本启动时检测 `backups/bot.db.YYYYMMDD-*.manual.bak` 存在且非空，否则 `[ERR ]` + exit 1
2. **必须显式 `--days N`** —— `--confirm` 不能裸用，即便用默认 180 也得显式 `--days 180`（强制运维重新输入而非依赖默认值）
3. **`--dry-run` 与 `--confirm` 互斥** —— 同时传立即 exit 1
4. **白名单严格** —— 仅 `WHITELIST_TABLES` (`user_events` / `user_teacher_views`)；脚本顶部 `PERMANENT_FORBIDDEN_TABLES`（8 张权益表）做交集检查纵深防御
5. **5 秒安全倒计时** —— 进入 DELETE 前 stderr 倒计数 5→1，可 Ctrl-C 中止
6. **每表独立事务** —— `BEGIN / DELETE / COMMIT`，单表失败 `ROLLBACK` 不影响其它表
7. **删除后完整性校验** —— `PRAGMA integrity_check`，返回非 `ok` 立即 exit 2 并提示从 backup 恢复
8. **写入 admin_audit_logs** —— 完成后追加一条 `(admin_id=0, action='prune_confirm', target_type='database', detail={days, tables, total_deleted, backup})` audit 记录
9. **不引入 VACUUM** —— SQLite WAL 模式 VACUUM 会重写整个数据库可能造成长锁；删除空间靠 SQLite auto-incremental 自然回收。如需 VACUUM 是单独的维护窗口工作，不在本脚本范围

退出码：
- `0` —— 全部成功（dry-run 或 confirm 全表删除）
- `1` —— 参数错误 / 缺 backup / 部分表删除失败
- `2` —— DELETE 后 `integrity_check` 异常（数据库可能损坏，必须立即从 backup 恢复）

完整命令序列：

```bash
# 第 1 步：准备
cd /opt/Chiyanlu-Exclusive-Bot
./scripts/backup.sh                       # 必须先生成当天 manual 备份
./scripts/prune.sh --dry-run --days 180   # 看一下要删多少

# 第 2 步：真正执行（看清 dry-run 输出之后）
./scripts/prune.sh --confirm --days 180   # 5 秒倒计时可 Ctrl-C 中止

# 第 3 步：复检
sqlite3 data/bot.db "PRAGMA integrity_check;"   # 必须返回 ok
sqlite3 data/bot.db "PRAGMA journal_mode;"      # 必须仍为 wal
ls -lh data/bot.db                              # 看文件大小是否如预期下降
sqlite3 data/bot.db "SELECT * FROM admin_audit_logs WHERE action='prune_confirm' ORDER BY id DESC LIMIT 1"

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
| [Part A：Migration Registry](#part-amigration-registry迁移注册器) | 迁移注册器设计 | 与 pruning 无直接关系；`schema_migrations` 不应被 pruning 清理 |

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

| 阶段 | 内容 | 状态 | 风险 | 业务影响 |
| --- | --- | --- | --- | --- |
| **P1** | 本设计文档 | ✅ 已完成 | 无 | 无 |
| **P2** | `scripts/prune.sh --dry-run`，只读统计，白名单 = `user_events` + `user_teacher_views` | ✅ 已完成 | 极低 | 无 |
| **P3** | `scripts/prune.sh --confirm`，仅清理 P2 白名单内的表；强制先 backup | ✅ 已完成（2026-05-20 Sprint 7 §9.2） | 低 | 行数下降，业务不可感知 |
| **P4** | [scripts/healthcheck.sh](../scripts/healthcheck.sh) 加"DB 文件大小提醒"（如 > 500 MB → WARN） | ⬜ 未启动 | 低 | 只读 |
| **P5** | [RUNBOOK.md](RUNBOOK.md) 增加 pruning 操作流程小节 | 🟡 部分完成 | 无 | 仅文档 |
| **P6** | 视生产数据量评估是否把 `user_events` 接入 scheduler；权益类**永不**接入 | ⬜ 未启动 | 中 | 视实施 |

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
- [POLICY.md Part I 积分规则](POLICY.md#part-i积分规则) 积分流水保留期对应的口径
- [POLICY.md Part II 报销规则](POLICY.md#part-ii报销规则) 报销记录与重置票据
- [POLICY.md Part III 抽奖规则](POLICY.md#part-iii抽奖规则) 抽奖参与 / 中奖记录保留要求
- [Part A：Migration Registry](#part-amigration-registry迁移注册器) 同文档的迁移注册器部分
- [scripts/backup.sh](../scripts/backup.sh) pruning 的强前置依赖
- [scripts/healthcheck.sh](../scripts/healthcheck.sh) 未来 P4 加 DB 体积提醒
