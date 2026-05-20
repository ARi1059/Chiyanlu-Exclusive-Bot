# Chiyanlu-Exclusive-Bot ROADMAP PLAN

> 本文档为 **后续迭代计划**，不是已实现功能列表。
> 文档生成于 plan mode，作者**未**修改任何业务代码、脚本、迁移、测试或已有文档。

---

## 0. 文档声明

1. **本文档是后续迭代计划**，描述的是「可以做、建议做、按什么顺序做」，不是「现在已经做完」。
2. **不代表所有事项必须立即开发**。每个 Sprint 都是独立窗口，可以根据生产观察、用户反馈、运营优先级动态调整顺序。
3. **每一项必须单独 PR / 单独 commit / 单独 CI 验证**。任何将多个 Sprint 合并提交、跨范围一次性大改的做法，都违反本文档的迭代纪律。
4. **本文档不是设计稿**。具体技术方案（callback 命名、表结构、字段命名、UI 文案细节）由对应 Sprint 的实施 PR 自行设计，并同步更新对应 `POLICY-*.md`。
5. **本文档生成于 plan mode**：撰写过程中没有修改 `bot/`、`scripts/`、`update.sh`、`tests/`、`README.md` 或 `docs/` 下任何其它文件，没有新增数据库迁移，没有执行任何功能实现。

---

## 1. 当前基线

> 描述「在本规划开始的那一刻，项目已经具备什么」。后续所有 Sprint 都是在这个基线之上做增量。

### 1.1 稳定化基线

- **CI 自动质量门**：`python3 -m compileall -q bot` + `python3 -m pytest` + `bash -n update.sh`。
- **测试套件**：`tests/` 目录已积累大量测试，覆盖核心服务、handler、迁移等。
- **运维脚本**：
  - `update.sh`：支持更新、备份、回滚，并在启动前检查 `schema_migrations` 中是否存在 hard failed 记录，命中即拒绝继续。
  - `scripts/healthcheck.sh`：基础文件、Python 语法、SQLite 完整性、systemd 服务状态、Git 状态、`schema_migrations` failed 检查、DB 体积阈值检查。
  - `scripts/backup.sh`：WAL-safe 手动备份。
  - `scripts/prune.sh`：只读 `--dry-run` 模式。
- **SQLite 配置**：已启用 WAL 模式。
- **`schema_migrations` 已完成 P1-P5**：
  - P1：设计
  - P2：baseline 注入
  - P3：runner framework（`MIGRATIONS.append(Migration(...))`）
  - P4：healthcheck 检测 failed migration
  - P5：update.sh 检测 failed migration，硬阻断
- **文档瘦身**：冗余 / 过期文档已合并或删除。
- **Dead code 审查**：P3-A 阶段已完成 `# deprecated` 注释标记，但**尚未删除**。

### 1.2 管理员侧基线

- 管理员主菜单已分六大组：
  1. 📊 数据看板 / 运营看板分组
  2. ✅ 审核处理
  3. 🎲 活动运营
  4. ⚙️ 系统配置
  5. 👩‍🏫 老师管理
  6. 🛡 管理员设置
- 已完成三个**只读**运营看板：
  - 📊 运营总览
  - 💰 报销池状态
  - 🎲 抽奖状态
- **当前命名混淆点**（待 Sprint 1 收口）：
  - `dashboard:enter`：旧的「数据看板」，偏用户事件 / 审计 / 历史分析。
  - `admin:dashboard`：新的运营看板入口，承载运营总览 / 报销池状态 / 抽奖状态。
  - 二者按钮文案相似、callback 不同，对运营人员不直观。
  - 建议改名（**只改文案不改 callback**）：
    - `dashboard:enter` 文案 → `📈 数据分析`
    - `admin:dashboard` 文案 → `📊 运营看板`

### 1.3 用户侧基线

- 已完成「用户留存三件套」：
  - 👀 最近看过增强
  - ⭐ 我的收藏增强
  - 📜 搜索历史增强
- **尚未做**用户侧首页整体分组，一级按钮散落，存在后续重组空间。

### 1.4 老师侧基线

- 老师侧**尚未**做面板精简。
- 当前老师侧入口分散、与用户/管理员入口交叉，存在简化空间。

### 1.5 文档与运维基线

- 已落地的 policy / runbook 类文档：
  - `DESIGN.md`（合并版 Part I/v1 + Part II/v2）、`DEPLOYMENT.md`、`RUNBOOK.md`
  - `POLICY.md`（合并版，Part I 积分 / Part II 报销 / Part III 抽奖）
  - `INFRASTRUCTURE-DESIGN.md`（合并版，Part A 迁移注册器 / Part B 历史清理）
- 任何涉及业务策略的 Sprint，必须**同步更新对应 POLICY 文档**，不允许只改代码不更新策略。

---

## 2. 迭代总原则

> 本章是后续所有 Sprint 共用的「红线」。每个具体 Sprint 都默认遵守这些原则，不再重复说明。

### 2.1 小步提交

- 每个功能单独 commit / 单独 PR。
- 禁止把「看板命名优化 + 抽奖对账 + 报销可视化」打包到一个 PR。
- 禁止把一个 Sprint 内的多个子任务（如对账页 + 异常列表 + 文本复制）合并成一个 commit，应按子任务拆开。
- 一个 PR 内**只解决一个明确目标**，附带的小修小补（修注释、补 typo）也应拆出。

### 2.2 先只读，后操作，再配置

所有运营类能力建设按三步走：

1. **第一步：只读看板**。先把数据呈现给运营人员，确认认知一致、口径无误。
2. **第二步：人工操作**。允许触发动作（补偿、退分、调整状态），但必须**二次确认 + 写入 audit log**。
3. **第三步：配置编辑**。允许在 UI 内修改规则参数，必须同步更新 `POLICY-*.md`，并写入 `admin_audit_logs`。

**禁止跳级**：不允许第一版就做"自动修复 + 自动写入 + 后台静默"。

### 2.3 数据库变更原则

所有 schema 变更必须使用：

```python
MIGRATIONS.append(Migration(...))
```

- **禁止**直接在 `init_db()` 中继续追加 `CREATE TABLE` / `ALTER TABLE`。
- **禁止**通过手工 SQL 在生产环境执行变更后再补迁移。
- **禁止**反向操作：跳过 migration runner 用 `executescript` 强写。
- 迁移失败必须留下 `schema_migrations.status = 'failed'`，被 `update.sh` 与 `healthcheck.sh` 检出。
- 详细规则参见 `INFRASTRUCTURE-DESIGN.md` Part A。

### 2.4 旧 callback 兼容

- **不允许随意修改旧 callback 含义**。Telegram 客户端的 inline button 是历史快照，用户点击的是过去发出的按钮。
- 修改菜单时优先**新增 callback**，旧 callback 至少保留一个版本，行为不变或显式跳转新入口。
- 文案修改可以自由进行（只要不改 callback_data）。
- 删除旧 callback 必须先经过至少一个 Sprint 的"双跑"观察期。

### 2.5 权限边界

- 超管 / 普通管理员 / 老师 / 普通用户的入口必须**严格区分**。
- 任何新增管理员功能 PR，必须显式声明：
  - 谁能看到入口？
  - 谁能触发动作？
  - 谁能查看结果？
- 任何「看似只读但展示了敏感字段」的页面（积分流水、用户列表、审核明细），都要走权限校验。
- 老师不应能看见管理员功能；普通管理员不应能看见 super-only 功能。

### 2.6 测试与部署门槛

每次提交前**本地必须通过**：

```bash
python3 -m compileall -q bot
python3 -m pytest
bash -n update.sh
bash -n scripts/healthcheck.sh
bash -n scripts/backup.sh
bash -n scripts/prune.sh
```

生产更新后**必须执行**：

```bash
./update.sh
./scripts/healthcheck.sh
```

并满足：

- `update.sh` 退出码 0，没有 rollback。
- `healthcheck.sh` 0 ERR。
- `schema_migrations` 中无 `status = 'failed'` 记录。
- systemd 服务 active (running)。

任何一项不满足，禁止合并下一个 Sprint。

---

## 3. Sprint 1：收口与验证

### 3.1 目标

- 完成看板命名优化，消除 `dashboard:enter` vs `admin:dashboard` 的认知混淆。
- 在生产上完整验证管理员六大分组的可见性 / 权限边界。
- 在生产上完整验证用户三大留存入口。

### 3.2 范围

- **3.2.1 看板命名优化**
  - `dashboard:enter` 按钮文案 → `📈 数据分析`
  - `admin:dashboard` 按钮文案 → `📊 运营看板`
  - **只改文案，不改 callback_data**。
  - 不修改两个看板内的任何业务逻辑。
- **3.2.2 管理员分组验证**
  - 以超管账号验证：六大入口可见、可点击、内容正常。
  - 以普通管理员账号验证：super-only 入口不可见。
  - 以老师账号 / 普通用户账号验证：管理员入口完全不可见。
  - 历史 inline button（旧文案）仍可点击。
- **3.2.3 用户留存入口验证**
  - 验证「最近看过」入口、列表、空态文案。
  - 验证「我的收藏」入口、列表、空态文案。
  - 验证「搜索历史」入口、列表、空态文案。
  - 不修改三件套的实现。

### 3.3 禁止事项

- 不改任何 callback_data。
- 不新增任何 schema 变更。
- 不调整管理员六大分组的内部结构。
- 不一并把「抽奖对账」「报销可视化」塞进 Sprint 1。

### 3.4 验收标准

- 全部 CI 命令通过（compileall / pytest / bash -n × 4）。
- 生产 `update.sh` 0 退出码，`healthcheck.sh` 0 ERR。
- 超管视角六大入口手动点击均正常。
- 普通管理员、老师、普通用户视角，越权入口均不可见。
- 历史 inline button 仍能正常工作。

---

## 4. Sprint 2：抽奖风控

### 4.1 目标

为抽奖系统建立**只读对账能力**，让管理员能够及时发现「entry / 积分流水 / 中奖」之间的不一致。
**第一版严格只读，不自动修复任何数据。**

### 4.2 范围

- **4.2.1 抽奖参与对账页**
  - 展示字段建议（具体 UI 由实施 PR 决定）：
    - 活动 ID / 活动名称 / 当前状态（进行中 / 已开奖 / 已撤销）
    - `entry_count`（参与人次）
    - `winner_count`（中奖人数）
    - `entry_cost_points`（单次参与扣分配置）
    - 理论应扣积分（`entry_count × entry_cost_points`）
    - 实际扣积分流水汇总（来自 `point_transactions`）
    - 差异金额
    - 异常人数
    - 异常用户列表入口
- **4.2.2 异常用户列表**
  - 展示字段：
    - `user_id`
    - 该用户在该活动的 entry 是否存在
    - 该用户对应 `point_transaction` 是否存在
    - 差异类型（有 entry 无扣分 / 有扣分无 entry / 双向缺失 / 重复扣分）
- **4.2.3 汇总文本复制**
  - 允许管理员一键复制对账汇总文本到剪贴板。
  - **不导出文件**（不生成 csv / xlsx / 不写入磁盘）。
  - 文本格式简洁，方便粘贴到群里同步。

### 4.3 禁止事项

- 第一版**只读**，不提供任何"一键补偿"按钮。
- 不自动补偿差异用户的积分。
- 不自动扣分 / 不自动退分。
- 不修改抽奖开奖逻辑、不修改 entry 写入逻辑。
- 不导出文件、不调用外部接口。
- 不新增数据库迁移（除非确实需要索引才能跑出对账，需另行评审）。

### 4.4 验收标准

- 在测试库构造一个「有 entry 无扣分」的人工异常，能在对账页正确显示。
- 在测试库构造一个「有扣分无 entry」的人工异常，能在对账页正确显示。
- 在正常活动上对账，差异为 0、异常人数为 0。
- 抽奖核心流程（参与、开奖、领奖）未被本 Sprint 影响。
- `POLICY.md` Part III 同步更新「对账口径」一节。
- CI 全绿，生产 healthcheck 0 ERR。

---

## 5. Sprint 3：报销运营

### 5.1 目标

让报销规则可视化、可审计，逐步从「代码里的常量 + POLICY 文档」过渡到「后台可读、可编辑、可追溯」。
**严格按"先只读，后操作，再配置编辑"三步走。**

### 5.2 范围

- **5.2.1 报销规则只读页**（本 Sprint 必做）
  - 展示当前生效的：
    - 报销功能开关（开 / 关）
    - 月度报销池上限
    - 最低积分门槛
    - 每周限制
    - queued 模式（是否启用、当前队列长度）
    - reset voucher 规则
  - 只展示，不编辑。
- **5.2.2 报销规则编辑页**（**下一个 Sprint，不在本 Sprint 范围**）
  - 允许调整月度池
  - 允许开关报销功能
  - 允许调整最低积分门槛
  - **每次编辑必须**：
    - 写入 `admin_audit_logs`（who / when / before / after / reason）
    - 走二次确认弹窗
    - 同步更新 `POLICY.md` Part II
- **5.2.3 报销活动公告文案生成**
  - 基于当前生效配置，生成可粘贴的公告草稿。
  - 不自动发布，不调用 broadcast。

### 5.3 禁止事项

- 第一版只读，**不允许**直接在本 Sprint 加入编辑按钮。
- 不修改报销审核流程（queued、approve、reject、reset voucher 全部维持现状）。
- 不修改 `admin_audit_logs` 表结构（除非有充分评审）。
- 不导出报销明细文件。

### 5.4 验收标准

- 只读页正确展示当前所有配置项。
- `POLICY.md` Part II 与只读页内容口径一致。
- 报销审核 / queued 流程未被影响。
- CI 全绿，生产 healthcheck 0 ERR。

---

## 6. Sprint 4：积分规则

### 6.1 目标

让积分规则清晰、可配置、可审计。
积分是用户权益的核心，**优先做只读、再做对账、最后才做配置编辑**。

### 6.2 范围

- **6.2.1 积分规则只读页**
  - 展示：
    - 评价通过加分
    - 优质评价加分
    - 抽奖门票扣分
    - 报销最低门槛（与 Sprint 3 一致）
    - 活动积分规则（订阅 / 邀请 / 签到等所有当前生效项）
  - 只展示，不编辑。
- **6.2.2 积分规则配置化**
  - **优先使用 `config` 表**承载配置参数。
  - 如果确实需要 schema 变更（新增表 / 加列），**必须**走 `MIGRATIONS.append(Migration(...))`。
  - 每次编辑必须写 `admin_audit_logs`。
  - 编辑后必须同步 `POLICY.md` Part I。
- **6.2.3 积分异常对账**
  - 展示：
    - `users.total_points`
    - `point_transactions` 的累加值
    - 差异用户列表
  - **只读**，不直接修正积分。
  - 修正动作放在更后续的 Sprint，必须二次确认 + audit log。

### 6.3 禁止事项

- 第一版不允许在对账页直接修正用户积分。
- 不允许跳过 `MIGRATIONS` 直接 ALTER TABLE。
- 不修改现有加分 / 扣分入口的业务语义。

### 6.4 验收标准

- 只读页正确展示规则。
- 对账页能在测试库构造的异常用户上正确报出差异。
- `POLICY.md` Part I 与只读页口径一致。
- CI 全绿，生产 healthcheck 0 ERR。

---

## 7. Sprint 5：用户首页重组

### 7.1 目标

降低用户侧一级按钮的复杂度，让用户能更快找到「找老师 / 我的记录 / 活动」。

### 7.2 建议一级菜单

```
🔎 找老师
⭐ 我的收藏
👀 最近看过
📝 我的记录
🎲 活动中心
👤 我的账户
```

### 7.3 范围

- **7.3.1 找老师分组**
  - 包含：热门推荐 / 今日可约 / 条件筛选 / 搜索历史。
- **7.3.2 我的记录**
  - 包含：我的评价 / 我的报销 / 积分流水 / 抽奖记录。
- **7.3.3 活动中心**
  - 包含：抽奖活动 / 积分活动 / 订阅任务。

### 7.4 实施纪律（重要）

- **不要一次性删除旧入口**。先新增分组，再观察至少一个 Sprint。
- **保留旧 callback**：历史 inline button 必须仍能点击，落地到对应新页或显式跳转提示。
- **分阶段上线**：先新增 → 旧入口加「迁移提示」→ 下一个 Sprint 再撤旧入口。

### 7.5 禁止事项

- 不在本 Sprint 删除任何旧用户入口。
- 不修改老师签到 / 评价提交 / 抽奖参与等核心动作的逻辑。
- 不修改三件套（最近看过 / 收藏 / 搜索历史）的实现。

### 7.6 验收标准

- 新增六个一级入口可见、可进入、内容正确。
- 旧入口仍可工作。
- 三件套行为未变。
- CI 全绿，生产 healthcheck 0 ERR。

---

## 8. Sprint 6：老师侧面板精简

### 8.1 目标

让老师侧面板更简单，突出每日最高频的「签到」。

### 8.2 建议入口

```
✅ 今日签到
👤 我的资料
📝 我的评价
📢 发布状态
❓ 帮助
```

### 8.3 范围

- 先做一次老师侧入口审查（清单 + 当前是否仍在使用 + 是否与用户/管理员入口冲突）。
- 基于审查结果再确定精简方案，**不直接改**。
- 审查 PR 与精简 PR 必须**分两个 PR**。

### 8.4 禁止事项

- 不在老师侧引入用户 / 管理员功能。
- **不影响签到路径**。任何老师侧改动都必须保证「点击 → 签到成功」的核心动作可达且语义不变。
- 不删除老师侧任何与签到有关的 callback。

### 8.5 验收标准

- 老师视角入口清晰，按钮数量减少。
- 签到流程未变。
- 老师不会误进入管理员 / 用户专属页面。
- CI 全绿，生产 healthcheck 0 ERR。

---

## 9. Sprint 7：维护清理

### 9.1 Dead code P3-B

- **当前状态**：P3-A 已完成 `# deprecated` 注释标记，但**尚未删除**。
- **候选删除清单**（P3-A `# deprecated` 注释已在代码内标出）：
  - `promo_links.py`
  - `source_stats.py`
  - 旧 `ReviewSubmitStates`
- **要求**：
  - 再次审查（确认调用方为 0，确认没有被新代码偷偷依赖）。
  - **分阶段删除**：每次只删 1 个文件 / 1 个类，单独 PR。
  - **每次删前补测试**：先确认现有测试覆盖到对应路径的「替代实现」。
  - **不一次性全删**。

### 9.2 `prune.sh --confirm`

- **当前状态**：`prune.sh` 只支持 `--dry-run`。
- **目标**：引入 `--confirm` 真正执行删除，但严格限定范围。
- **第一阶段只允许清理**：
  - `user_events`
  - `user_teacher_views`
- **永久禁止清理**（即使 `--confirm` 也不允许）：
  - `point_transactions`
  - `reimbursements`
  - `lottery_entries`
  - `teacher_reviews`
  - `admin_audit_logs`
  - `users`
  - `teachers`
  - `favorites`
- **执行流程**：
  1. **必须先 `scripts/backup.sh`**，备份成功才继续。
  2. **必须先 `--dry-run`**，输出待清理统计。
  3. **必须显式传 `--confirm`** 才真正删除。
  4. 删除后必须 `PRAGMA integrity_check`，结果为 `ok` 才视为成功。
  5. 必须写入运维日志 / `admin_audit_logs`。

### 9.3 禁止事项

- 不在 Dead code 清理 PR 中夹带其它修改。
- 不绕过 `--dry-run` 直接 `--confirm`。
- 不清理权益数据表。
- 不修改 `scripts/backup.sh` 的备份逻辑。

### 9.4 验收标准

- Dead code 每次删除后 CI 全绿。
- `prune.sh --confirm` 在测试库上正确清理 `user_events` / `user_teacher_views`，`integrity_check` 返回 `ok`。
- 权益数据表条数在 prune 前后**完全一致**（必须有自动断言）。
- 生产 healthcheck 0 ERR。

---

## 10. 风险控制

| 风险 | 触发场景 | 防线 |
| --- | --- | --- |
| **callback 破坏** | 改动 callback_data 导致历史 inline button 失效 | 文案与 callback 解耦；旧 callback 保留至少一个 Sprint；新旧入口双跑期；pytest 中覆盖 callback router |
| **权限误暴露** | 管理员功能误对普通用户可见，或老师误进入管理员页 | 每个 PR 显式声明权限边界；多账号手动验证；CI 中维持权限相关测试 |
| **用户权益数据误改** | 自动修复对账差异、误删 point_transactions 等 | 所有对账页**第一版只读**；权益表禁止 prune；任何修正动作必须二次确认 + audit log |
| **迁移失败** | `MIGRATIONS` 中新增的 Migration 在生产挂掉 | runner framework 写入 `schema_migrations.status='failed'`；`healthcheck.sh` 检出；`update.sh` 硬阻断 |
| **菜单入口变动导致用户迷路** | 一次性砍掉旧入口、用户找不到原先的功能 | 用户/老师侧改动遵循"先新增 → 观察 → 再撤旧"；保留旧 callback |
| **删除 dead code 误删 fallback** | 删除标记为 deprecated 但其实仍在被调用的代码 | 分阶段删除；每次只删 1 个；删前补充对替代实现的测试；CI pytest 必须全绿 |

每条风险一旦触发，回退顺序：

1. **代码级**：通过 PR revert。
2. **服务级**：`update.sh` 自带的备份回滚机制。
3. **数据级**：`scripts/backup.sh` 产物 + 手动恢复（最后手段）。

---

## 11. 版本节奏建议

- **Sprint 长度**：每个 Sprint 1-2 周，不强求时长一致。功能越涉及权益，越倾向长 Sprint。
- **commit 拆分**：每个功能单独 commit / 单独 PR，**禁止跨 Sprint 合并提交**。
- **只读页优先**：任何运营 / 风控类需求，第一版只读，编辑能力后置到下一个 Sprint。
- **生产观察期**：每轮生产上线后观察 **24-72 小时**，期间不开下一个 Sprint。观察项：
  - `healthcheck.sh` 仍稳定 0 ERR。
  - `schema_migrations` 无新增 failed 记录。
  - 管理员未上报操作异常。
  - 用户未上报权益数据异常。
- **回滚阈值**：观察期内出现任意一项 ERR 即触发回滚评估，**不带情绪、不带侥幸**。

---

## 12. 当前不做事项

> 明确写出，避免后续讨论时反复绕回。

- **PostgreSQL 迁移**：当前 SQLite + WAL 满足需求，迁移收益不明，迁移成本大。
- **Docker 化**：当前 systemd 直跑稳定，Docker 化会引入新的运维路径。
- **微服务拆分**：当前单体足够，拆分只会增加跨进程复杂度。
- **一次性重写 `bot/database.py`**：必须走小步迁移、`MIGRATIONS` 框架。
- **一次性重做用户 / 老师 / 管理员三端面板**：必须分别走各自 Sprint，禁止合并。
- **自动删除权益数据**：永远不做。任何「自动清理」都必须排除 `point_transactions` / `reimbursements` / `lottery_entries` / `teacher_reviews` / `admin_audit_logs` / `users` / `teachers` / `favorites`。
- **自动 rollback**：保留 `update.sh` 当前的手动回滚机制，不引入"自动判断 → 自动回滚"。
- **异地备份方案**：当前项目不采用。备份仍为本机 `scripts/backup.sh`。

---

## 13. 下一步推荐

- **第一步：看板命名优化**（Sprint 1.3.2.1）
  - `dashboard:enter` 文案 → `📈 数据分析`
  - `admin:dashboard` 文案 → `📊 运营看板`
  - 只改文案、不改 callback。
  - 单独 commit / 单独 PR / CI 全绿 / 生产 healthcheck 0 ERR。
- **第二步：抽奖参与对账页**（Sprint 2）
  - 在上一步完成并稳定运行 24-72 小时之后再启动。
  - 严格只读，不导出文件，不自动修复。

> 后续步骤的优先级由生产观察、运营反馈共同决定，不在本文档锁死。
