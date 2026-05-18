# MIGRATION-REGISTRY-DESIGN.md

> **实施进度（更新于 2026-05-18）**
>
> | 阶段 | 状态 | 说明 |
> | --- | --- | --- |
> | P1 设计文档 | ✅ 已完成 | 本文档（commit `1f7f273`） |
> | **P2 baseline** | **✅ 已完成** | `schema_migrations` 表 + `ensure_schema_migrations_table` / `baseline_schema_migrations` 已落地 [bot/database.py](../bot/database.py)；`init_db()` 已接入；现有 9 个 `_migrate_*` **照旧执行、顺序未改**；本表当前**仅记录历史 baseline，不参与执行决策**。详见 [第八节阶段 A](#阶段-abaseline承认现状) 的实际实现。 |
> | P3 新迁移走注册器 | ⬜ 未启动 | 当前**没有**任何新迁移通过 `MIGRATIONS` 列表注册；新增 schema 变更仍按"加一个 `_migrate_*` 函数 + 加 baseline 行"的模式 |
> | P4 healthcheck 接入 | ✅ 已完成（与 P2 同期） | [scripts/healthcheck.sh](../scripts/healthcheck.sh) 已能识别 `success=0` 行，按 kind 分级输出（hard → ERR，soft / 未知 → WARN，表不存在 → WARN 兼容口径） |
> | P5 update.sh 接入 | ⬜ 未启动 | `update.sh` 仍只看 systemd / journalctl，不读 `schema_migrations` |
> | P6 pytest 覆盖 | ✅ 已完成（与 P2 同期） | [tests/test_schema_migrations_baseline.py](../tests/test_schema_migrations_baseline.py) 13 用例 |
>
> **重要：当前的 P2 实现仍处于"baseline 录入"阶段，不是完整的迁移注册器。**
> 文档中所有以"建议"、"将"措辞的小节，仍是未落地的目标 —— 阅读时请对照本表。
> 现有 9 个 `_migrate_*` 函数**仍按原顺序无条件执行**，与 P2 之前完全一致。

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
6. **回滚判定难**：[POLICY-reimbursement.md](POLICY-reimbursement.md) 涉及的
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

[update.sh](../update.sh) 在启动健康检查后多跑一句：

```bash
if sqlite3 "$DB_PATH" "SELECT 1 FROM schema_migrations WHERE success=0 AND kind='hard' LIMIT 1" \
       | grep -q 1; then
    err "存在未成功的 hard migration，请人工排查，或执行 ./update.sh rollback"
    exit 1
fi
```

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
| **P3** | 新迁移开始走 `MIGRATIONS` 注册器（[阶段 B](#阶段-b新迁移走注册器)） | ⬜ 未启动 | 中 | 仅影响**新增**迁移代码风格 |
| **P4** | `scripts/healthcheck.sh` 增加迁移状态检查（[阶段 C](#阶段-chealthchecksh-接入)） | ✅ 已完成 | 低 | 只读 |
| **P5** | `update.sh` 检测 hard failed migration 并提示 rollback（[阶段 D](#阶段-d-updatesh-接入)） | ⬜ 未启动 | 中 | 部署流程多一步判断 |
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

## 相关文档

- [DEPLOYMENT.md](DEPLOYMENT.md) §14 备份与恢复、§16 验收 Checklist
- [RUNBOOK.md](RUNBOOK.md) §四 更新失败怎么办、§五 数据库异常怎么办
- [POLICY-reimbursement.md](POLICY-reimbursement.md) `reimbursements_new` 残留表的历史背景
- [STABILITY-AUDIT-2026-05-18.md](STABILITY-AUDIT-2026-05-18.md) 当前稳定化状态
- 实现入口：[bot/database.py](../bot/database.py) `init_db()` 与 `_migrate_*`
