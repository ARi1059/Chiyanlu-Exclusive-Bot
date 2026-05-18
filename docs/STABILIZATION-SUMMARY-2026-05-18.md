# 稳定化总结 · 2026-05-18 轮次

> 起点：[`docs/STABILITY-AUDIT-2026-05-18.md`](STABILITY-AUDIT-2026-05-18.md) 审计报告
> 终点：本文档汇总稳定化轮次中完成的所有工作 + 剩余清单 + 下一步优先级
> 时间窗：2026-05-18

本文档是**总览**：每一项的具体内容请点链接进对应文档。

---

## 一、本轮做了什么

按"代码层"和"运营/运维基建"两条线汇总。

### 1.1 代码层稳定化（已完成）

| commit | 改动 | 业务影响 |
| --- | --- | --- |
| `7b1be01` | `.gitignore` 完整化 + 2 处 `StateFilter(None)` + `teacher:select` 双 dispatch 文档化 | 防 `.env` / `data/bot.db` 误提交；FSM 抢占消失 |
| `afb239a` | SQLite `journal_mode=WAL` + `synchronous=NORMAL` + `busy_timeout=5000` | 并发读写吞吐显著提升；`database is locked` 大幅减少 |
| `9cc0f8b` | `update.sh` 备份改用 `sqlite3 .backup` + `integrity_check`；rollback 清 `-wal`/`-shm` 残留 | 备份不再"假成功"；rollback 不再被旧 WAL 污染 |
| `99aec2b` | `_migrate_reimbursements_queued_status` 重写：5 个状态分支 + BEGIN IMMEDIATE 事务保护 | 报销迁移半完成态可自愈，残留 `reimbursements_new` 不被误删 |

### 1.2 运营 / 运维基建（已完成）

| commit | 产出 | 落点 |
| --- | --- | --- |
| `f126776` | 重写 README，反映稳定化口径 | [README.md](../README.md) |
| `b3d22bc` | 重写 DEPLOYMENT.md，反映 `update.sh` / WAL / 非 root 部署 | [docs/DEPLOYMENT.md](DEPLOYMENT.md) |
| `8661e22` | 三份运营政策文档 | [POLICY-points](POLICY-points.md) / [POLICY-reimbursement](POLICY-reimbursement.md) / [POLICY-lottery](POLICY-lottery.md) |
| `50ea501` | 修正 root 运行口径 + 备份验证步骤口径 | DEPLOYMENT §9 / §16 |
| `6680e83` | 值守手册 + 健康检查 + 备份脚本（**本会话**） | [RUNBOOK.md](RUNBOOK.md) / [scripts/healthcheck.sh](../scripts/healthcheck.sh) / [scripts/backup.sh](../scripts/backup.sh) |
| `bea20c1` | pytest 测试体系，67 用例（**本会话**） | [tests/](../tests/) / [pytest.ini](../pytest.ini) |
| `1f7f273` | 迁移注册器设计方案（**本会话**） | [MIGRATION-REGISTRY-DESIGN.md](MIGRATION-REGISTRY-DESIGN.md) |
| `91e30cb` | GitHub Actions CI（compileall + pytest + bash -n） | [.github/workflows/ci.yml](../.github/workflows/ci.yml) |
| (本次) | **迁移注册器 P2 baseline** + P4 healthcheck 接入 + P6 测试 | `schema_migrations` 表 + `ensure_schema_migrations_table` / `baseline_schema_migrations` 在 [bot/database.py](../bot/database.py)；现有 9 个 `_migrate_*` 顺序与行为**未改**；[healthcheck.sh](../scripts/healthcheck.sh) 新增 hard/soft 分级检查；[tests/test_schema_migrations_baseline.py](../tests/test_schema_migrations_baseline.py) 13 用例 |

### 1.3 本轮新增工件一览（**本会话**重点）

| 工件 | 行数 | 作用 |
| --- | --- | --- |
| `docs/RUNBOOK.md` | 720+ | 14 节值守手册，覆盖服务 / 更新 / 数据库 / 抽奖 / 报销 / 积分 / 评价 / 权限安全事故；含事故记录模板与升级判定 |
| `scripts/healthcheck.sh` | 325 | 只读体检：基础文件 / Python / SQLite WAL & integrity_check & 核心表 / systemd / journalctl 关键字 / Git；存在 ERR 时退出码 1 |
| `scripts/backup.sh` | 199 | 独立 WAL-safe 备份 + `integrity_check`；产物 `*.manual.bak`，`--keep N` 仅清同后缀，不影响 `update.sh` 的 `*.bak` |
| `tests/conftest.py` + 4 份 test | 67 用例 | `parse_start_args` / `compute_reimbursement_amount` / `group_search` 工具函数 / 抽奖状态常量；1 秒内跑完；隔离真实 .env、不连 Telegram、不触碰 data/bot.db |
| `pytest.ini` + `requirements.txt` | — | `pytest==8.3.4`；`testpaths=tests` / `addopts=-q` |
| `docs/MIGRATION-REGISTRY-DESIGN.md` | 461 | `schema_migrations` 表 + 注册器 13 节设计方案；明确不引入 Alembic、不迁 PostgreSQL；保留现有 9 个 `_migrate_*` 通过 baseline 平滑接入 |

---

## 二、本轮验收

在 commit `1f7f273` 之上执行：

```text
$ python3 -m compileall -q bot
[ok] compileall passed

$ python3 -m pytest
...................................................................      [100%]
67 passed in 0.93s

$ ./scripts/healthcheck.sh
…
Healthcheck summary:
- OK: 24
- WARN: 1
- ERR: 2
```

> ℹ️ 本地 `healthcheck.sh` 的 2 项 ERR 是「缺失 `.env`」和「缺失 `.venv`」——这是
> **本地开发机的预期状态**，因为我们不在本地装运行时依赖、也不放真实 token。
> 生产部署机 `/opt/Chiyanlu-Exclusive-Bot` 下两项均应为 OK。
> 1 项 WARN（无 systemctl）同样是本地 macOS 预期。

---

## 三、还剩什么

下列条目按 README 「🟡 后续建议补充」中清单整理。

### 3.1 P2（中优先级，建议下个稳定化轮次）

| 类别 | 任务 | 估算 |
| --- | --- | --- |
| **迁移注册器实施** | 按 [MIGRATION-REGISTRY-DESIGN §12](MIGRATION-REGISTRY-DESIGN.md#十二实施计划) 落地 P2-P6：`schema_migrations` 表、baseline 写入、新迁移注册器、healthcheck 接入、update.sh 接入、注册器 pytest | 3-5 天工作量 |
| **CI** | GitHub Actions 接入 `pytest` + `compileall` + `bash -n scripts/*.sh`，触发条件 push to main / PR | 半天 |
| **历史数据 pruning** | scheduler 加 `prune_old_records`：`user_events` / `audit_logs` / `point_transactions` > 180 天定时清理；需先确认保留期符合运营/合规要求 | 1-2 天 |
| ~~**`bot/main.py` 拆分**~~ | ✅ **已完成**：拆为 `bot/app_factory.py` + `bot/routers.py` + `bot/lifecycle.py` + 41 行薄 `bot/main.py`；33 个 router 注册顺序逐行等价；20 个静态测试覆盖；业务行为 0 改变 | 已落地 |
| **异地备份** | `scripts/backup.sh` 完成本机快照后，rclone / rsync 推送到对象存储 / 第二台 VPS；参考 [DEPLOYMENT §14.4.1](DEPLOYMENT.md#1441-异地备份建议) | 半天 |

### 3.2 P3（低优先级，技术债清理）

| 类别 | 任务 |
| --- | --- |
| 死代码 | 线性 `ReviewSubmitStates` 旧 FSM、`promo_links.py` / `source_stats.py`（router 已下线） |
| pytest 扩展 | 把 `_migrate_*` 函数纳入 pytest（依赖 P2 迁移注册器先到位） |
| 测试 | 给 `bot/handlers/` 中纯逻辑 helper 补 pytest |

### 3.3 明确不做

| 项 | 不做原因 |
| --- | --- |
| 迁移 PostgreSQL | 单进程 polling Bot 离 SQLite 瓶颈很远；备份/迁移可观测性才是真正风险，与引擎无关。详见 [MIGRATION-REGISTRY-DESIGN §10](MIGRATION-REGISTRY-DESIGN.md#十为什么不迁移-postgresql) |
| 引入 Alembic | SQL-first 项目，SQLite 表重建仍需手写；详见 [MIGRATION-REGISTRY-DESIGN §9](MIGRATION-REGISTRY-DESIGN.md#九为什么不引入-alembic) |
| Docker 化 | 会破坏 `update.sh` 备份/回滚/healthcheck 的文件路径假设 |
| 拆 microservice | 与项目体量不匹配，会让回滚/可观测性变差 |
| 全量重写 `bot/database.py` | 风险远大于收益；现有 `_migrate_*` 已被验证幂等 |

---

## 四、下一步优先级

按"先做哪个" 排序：

1. **CI**（半天，零风险）
   接入 GitHub Actions 跑 pytest + compileall + bash -n。**强烈建议在做任何 P2 改动前先有 CI**，否则后续改动无法自动回归。

2. **迁移注册器 P2 baseline**（1 天，低风险）
   只新增 `schema_migrations` 表 + baseline 写入。不改动任何现有 `_migrate_*`。完成后，下次再有新 schema 变更才进入 P3 走注册器。

3. **历史数据 pruning**（1-2 天，需要业务确认）
   pruning 涉及"保留多久"的运营决策，先和产品 / 合规确认保留期，再写代码。

4. **`bot/main.py` 拆分**（1-2 天，纯代码重构）
   有了 pytest + CI 之后再做拆分相对安全。

5. **异地备份**（半天）
   依赖外部基础设施（对象存储账号 / 第二台 VPS）。

6. **死代码清理**（半天，零风险）
   有 CI 后做，绿色就合并。

> 不建议跳过 CI 直接动 P2。CI 是后续所有改动的安全网。

---

## 五、本轮没动的东西

记录"本轮**有意**没做"的项，避免下个轮次重复评估：

- **业务代码**：本会话除 `pytest.ini` 调整外，未触碰 `bot/` 任何文件。所有改动都集中
  在 `docs/` 和 `scripts/` 与 `tests/`。这是有意的——本轮目标是"运营/运维基建"，
  不是"功能演进"。
- **`update.sh`**：内部备份逻辑保留现状（已是 WAL-safe）。健康检查相关功能放进了
  `scripts/healthcheck.sh`，与 `update.sh` 解耦。
- **数据库 schema**：未做任何 schema 变更。`MIGRATION-REGISTRY-DESIGN.md` 只是**设计**，
  没有引入 `schema_migrations` 表。
- **告警/监控**：未引入 Prometheus / Sentry / 自定义告警。当前依赖 `journalctl` +
  `healthcheck.sh` + 值守人员主动巡检。如果未来流量上升，再考虑被动监控的成本/收益。

---

## 六、相关文档索引

- 起点审计：[STABILITY-AUDIT-2026-05-18.md](STABILITY-AUDIT-2026-05-18.md)
- 值守手册：[RUNBOOK.md](RUNBOOK.md)
- 部署文档：[DEPLOYMENT.md](DEPLOYMENT.md)（§14 备份 / §15 排错 / §16 验收 Checklist）
- 运营政策：[POLICY-points](POLICY-points.md) / [POLICY-reimbursement](POLICY-reimbursement.md) / [POLICY-lottery](POLICY-lottery.md)
- 迁移设计：[MIGRATION-REGISTRY-DESIGN.md](MIGRATION-REGISTRY-DESIGN.md)
- 项目总览：[README.md](../README.md) §「当前稳定化状态」
- 脚本：[scripts/healthcheck.sh](../scripts/healthcheck.sh) / [scripts/backup.sh](../scripts/backup.sh) / [update.sh](../update.sh)
- 测试：[tests/](../tests/) / [pytest.ini](../pytest.ini)
