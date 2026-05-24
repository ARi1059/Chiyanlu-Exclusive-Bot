# Chiyanlu-Exclusive-Bot ROADMAP PLAN

> 本文档为 **后续迭代计划**，不是已实现功能列表。
> 文档生成于 plan mode，作者**未**修改任何业务代码、脚本、迁移、测试或已有文档。
>
> **2026-05-23 Phase A0 后状态摘要**：本 ROADMAP 撰写于 A0 之前，部分 Sprint 范围已随 A0 下线发生变化，**保留作历史记录**：
>
> - **Sprint 2 §4.2 抽奖对账**：已落地但随抽奖功能整体下线一并退役。
> - **Sprint 5 §7.x「最近看过 / 搜索历史」**：已下线，相关增强不再实现。
> - **Sprint 7 §7.3.2 我的记录聚合菜单**：已下线，主菜单 4 项一级入口（评价 / 报销 / 积分 / 抽奖）回归独立。
> - **Sprint 7 §7.3.3 活动中心**：当前永久暂缓（依赖项目新增业务）。
> - **A0 后下一步规划**：详见根目录 README §"下一步规划" 或最近一次规划综述输出。

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

### 4.5 进度（2026-05）

- **§4.2.1 已落地**：抽奖参与对账页（活动列表 + 单活动汇总）。新增 `bot/services/lottery_reconcile.py`（dataclass + 对账 SQL + 渲染），`bot/keyboards/admin_kb.py` 给 `admin_dashboard_kb` 加 `is_super` 参数并新增 `admin_lottery_reconcile_kb` / `admin_lottery_reconcile_detail_kb`，`bot/handlers/admin_panel.py` 新增 4 个 `@super_admin_required` callback（列表 / 列表刷新 / 详情 / 详情刷新）+ `cb_admin_dashboard` 注入 `is_super`。对账口径：期望 = entry_count × cost；实际 = -SUM lottery_entry delta；退款 = SUM lottery_refund delta；净扣 = 实际 - 退款；差异 = 期望 - 净扣。4 类异常（A 有 entry 无扣分 / B 有扣分无 entry / C 双向缺失=0 / D 重复扣分），异常人数 = |A∪B∪D|。仅对 `cost>0` 且非 `draft` 的活动对账。零修改抽奖核心（`lottery_entry.py` / `admin_lottery.py` / `lottery_tasks`）、零 schema 变更（复用既有 `idx_point_tx_related` 索引）、零导出文件、零修复按钮。契约由 `tests/test_lottery_reconcile_service.py`（22 个 test，含平账 / A / B / D / 三类并集去重 / 退款抵消 / cost=0 跳过 / draft 跳过 / cancelled 计入 / 渲染）+ `tests/test_lottery_reconcile_kb.py`（13 个 test，含超管 / 非超管分支 + callback ≤ 64B + 防御性"无修复按钮"）集中锁定。`POLICY.md` §10.2 扩充三小节（对账口径 / 异常分类 / 后台入口）。
- **§4.2.2 已落地**：异常用户列表（详情页按 `anomaly_users > 0` 条件出现「📋 异常用户列表 (N)」入口）。`bot/services/lottery_reconcile.py` 新增 `LotteryAnomalyUser` / `LotteryAnomalyList` dataclass + `list_lottery_anomalies(lid, page)` + `render_lottery_anomaly_list()`；归类规则按 **D > B > A** 优先级，每个 uid 只归一类（A 与 D/B 必然不相交；B∩D 归 D 并显式标注「无 entry」）。`admin_lottery_reconcile_anomaly_kb(lid, page, total_pages)` 提供分页 + 刷新 + 返回详情；详情页 kb 按 `anomaly_users > 0` 条件渲染入口按钮（含计数角标）。新增 `cb_admin_lottery_reconcile_anomaly` callback（`@super_admin_required`），解析 `admin:lottery_reconcile:anomaly:<lid>:<page>`。每页 20 条（`ANOMALY_PAGE_SIZE`），按 D → B → A 分组展示，每条带具体引用（entry_id / tx_ids / 涉及金额）。零修改业务流程、零 schema 变更、零导出文件、零修复按钮。新增测试 14 个 service test（A/B/D 分类 / D>B 优先级 / D∩B 归 D / 分页越界夹紧 / 渲染分组）+ 6 个 kb test（按钮条件显示 / 分页边界 / 返回详情 / 防御性"无修复按钮"）；PR-1 中两条"防御 §4.2.2 提前实现"测试同步更新为正向断言。`POLICY.md` §10.2.3 扩充异常列表页说明 + 异常归类去重规则。
- **§4.2.3 已落地**：汇总文本复制。`bot/services/lottery_reconcile.py` 新增 `render_lottery_reconcile_copy_text(item)`（无 emoji 装饰、pipe 分隔的紧凑结构，含结论标签 `BALANCED` 或 `DIVERGENT(diff=...,anomaly_users=...)`）+ `wrap_copy_text_html(text)`（统一 HTML escape + `<pre>` 包裹，防止活动名含 `<` `>` `&` 时 parse 失败）。`admin_lottery_reconcile_detail_kb` 给每个详情页加「📋 复制汇总」按钮（不依赖 anomaly 条件）。新增 `cb_admin_lottery_reconcile_copy` callback（`@super_admin_required`），点击后**发新消息**（不 edit 当前页），内容为 `<pre>` 包裹的纯文本，Telegram 客户端长按可全文复制。**不导出文件**：不写磁盘，仅发 Telegram 消息。新增测试 11 个 service test（BALANCED / DIVERGENT 标签 / diff-only / 无 emoji / 全字段含 / N/A 回退 / HTML escape / activity name 注入安全 / pasteable 行数）+ 1 个 kb test（复制按钮在平账与异常详情页都存在）。Sprint 2 §4.2 共三项全部落地。`POLICY.md` §10.2.3 标记 §4.2.3 收尾。

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

### 5.5 进度（2026-05）

- **§5.2.1 已落地**：报销规则只读页。新增 `bot/services/reimbursement_rules.py`（`ReimbursementRulesSnapshot` dataclass + `get_reimbursement_rules_snapshot()` + `render_reimbursement_rules()`），暴露 7 项规则：功能开关 / 月度池上限 + 本月 reset baseline / 最低积分门槛（含默认 5、上限 100）/ 每周 approved 限制（硬编码 1 次 = `WEEKLY_APPROVED_LIMIT`）/ reset voucher 一次性跳过本周校验说明 / queued 名单模式（按 `feature_enabled` 描述触发条件 + 当前队列长度）/ 必关频道 / 群组（总数 + 启用数）。`admin_reimburse_config_kb` 顶部新增「📜 完整规则一览（只读）」按钮（callback `admin:reimburse_rules`），与编辑入口区分。新增 `admin_reimburse_rules_kb`（仅刷新 + 返回报销配置）。新增 `cb_admin_reimburse_rules` + `cb_admin_reimburse_rules_refresh` 两个 `@super_admin_required` handler。零修改报销审核 / queued / reset voucher 流程；零 schema 变更；零编辑按钮（§5.3）。新增测试 34 个 service test（常量 / dataclass 默认 / `_parse_monthly_pool` 边界 / 5 个 `_fmt_*` helper / `render` 含全部章节 + N/A 回退 + reset baseline 渲染 / `get_snapshot` monkeypatch 集成 5 场景含异常容错）+ 3 个新 kb test（只读 kb 限刷新 + 返回 / 防御性"无编辑按钮" / callback ≤ 64B）+ 1 个 `test_reimburse_config_aggregate` 防御契约扩展（新增 `admin:reimburse_rules` 入白名单，按钮总数 6 → 7，并断言只读入口位于第一行）。
- **§5.2.2 报销规则编辑页**：**下一个 Sprint（不在本 Sprint 范围）**。
- **§5.2.3 已落地**：报销活动公告文案生成。`bot/services/reimbursement_rules.py` 新增 `render_reimbursement_announcement_draft(snap)` 生成**面向用户**的纯文本公告（无技术字段、无 emoji 装饰、pipe 分隔），按 `feature_enabled` 三态切换标题（开放 / 暂未开放 / 配置异常）+ 三段内容（标题+日期 / 规则要点 / 用户说明）+ 生成时间戳。`wrap_announcement_html(text)` 统一 HTML escape + `<pre>` 包裹，与 §4.2.3 抽奖对账复制汇总同模式。`admin_reimburse_rules_kb` 顶部新增「📢 复制公告草稿」按钮（callback `admin:reimburse_announce`）。新增 `cb_admin_reimburse_announce` callback（`@super_admin_required`），点击后**发新消息**（不 edit 当前页），Telegram 长按可全文复制。**不自动发布、不调用 broadcast、不写磁盘、不导出文件**。新增测试 16 个 service test（3 个 `_announce_*_line` 分支 + 3 个 feature_enabled 三态标题与首段 + 规则要点全字段含 + weekly_limit 读自常量非硬编码 + 无 emoji 装饰 + 无技术字段 + 时间戳含 + reset voucher 用户向措辞 + 文本长度 < 2000 + `wrap_announcement_html` `<pre>` 包裹 + HTML escape + 完整公告 escape 安全）+ 2 个 kb test 改写（旧"只 2 按钮"断言改为"3 按钮含公告草稿"+ 新增公告按钮独立契约 + 按钮总数 2 → 3）。Sprint 3 §5.2 共两项可做的全部落地（§5.2.2 编辑页按 ROADMAP 明示留待下一 Sprint）。`POLICY.md` §17.5 扩充公告草稿生成口径 + 三态标题映射。

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

### 6.5 进度（2026-05）

- **§6.2.1 已落地**：积分规则只读页。新增 `bot/services/points_rules.py`（`PointsRulesSnapshot` dataclass + `REASON_CATALOG` 5 条 / `MANUAL_GRANT_DELTA_MIN/MAX` ±100 常量 + `get_points_rules_snapshot()` + `render_points_rules()`），暴露 6 段规则：① 5 个 reason 取值映射 ② 评价加分 5 个套餐 + 自定义 0~100 范围 ③ 手动加扣分 4 个原因预设 + 自定义 ±100 + 不校验余额警告 ④ 抽奖积分扣分/退款时机 + 非原子风险（POLICY §5.1）⑤ 报销最低门槛跨页引用 `admin:reimburse_rules`（共用 `get_reimbursement_min_points`）⑥ 余额一致性约束 + §6.2.3 对账占位。`admin_points_menu_kb` 顶部新增「📜 积分规则一览（只读）」按钮（callback `admin:points_rules`，遵循 §6.1 "优先做只读"纪律置于第一行）。新增 `admin_points_rules_kb`（仅刷新 + 返回积分管理）。新增 `cb_admin_points_rules` + `cb_admin_points_rules_refresh` 两个 super-gated handler（沿用 `admin_points._super_admin_required`）。零修改加扣分逻辑（`add_point_transaction` / 既有 FSM）；零 schema 变更；零编辑按钮（§6.3）。新增测试 28 个 service test（常量 / REASON_CATALOG 5 条 + delta_sign 校验 / `_fmt_delta` 三态 / `_fmt_reimburse_min` 三态 / render 含全部 7 章节 + 全 reason 行 + 全 5 套餐 + 余额检查警告 + 非原子风险 + 跨页引用 + N/A 回退 + 只读标记 + 时间戳 / `get_snapshot` monkeypatch 4 场景含异常容错 + 浅拷贝隔离）+ 6 个 kb test（菜单入口位置契约 + 按钮总数 4 → 5 + 规则 kb 仅刷新返回 + 防御性"无加扣分按钮"+ callback ≤ 64B）。`POLICY.md` 新增 §九「积分规则只读总览」段（5 小节：用途 / 字段映射 / 后台入口 / 边界 / 后续计划），旧 §九"用户申诉建议"重编号为 §十。
- **§6.2.2 积分规则配置化**：待后续 PR（需要 audit log + 可能涉及 MIGRATIONS）。
- **§6.2.3 已落地**：积分异常对账（概览 + 异常用户分页列表）。新增 `bot/services/points_reconcile.py`：`PointsReconcileOverview` / `PointsReconcileItem` / `PointsAnomalyList` 3 个 dataclass + `get_points_reconcile_overview()` 全局聚合（total_users / points_users / anomaly_users / higher_users / lower_users / orphan_tx_users / total_balance / total_tx_sum / diff_total）+ `list_points_anomalies(page, page_size)` 分页查询 + `render_*` 2 个渲染函数。对账核心约束：`users.total_points == COALESCE(SUM(point_transactions.delta), 0)`。异常归 2 类：`BALANCE_HIGHER`（balance > tx_sum，常见于历史迁移未回填 / DB 直接 UPDATE）/ `BALANCE_LOWER`（balance < tx_sum，常见于流水写入后 total_points 同步失败，POLICY §7.1 非原子）。孤儿流水（point_transactions 有 user_id 但 users 表无）单独统计，不进异常列表。列表按 `|diff|` 降序排序，每页 `ANOMALY_PAGE_SIZE=20`（与 Sprint 2 §4.2.2 抽奖异常同模式）。`admin_points_menu_kb` 在「📜 积分规则一览」下新增「📊 积分对账（只读）」按钮（callback `admin:points_reconcile`）。新增 `admin_points_reconcile_overview_kb`（anomaly>0 时含「📋 异常用户列表 (N)」入口）+ `admin_points_reconcile_anomaly_kb`（分页 + 返回概览）。新增 3 个 `@_super_admin_required` callback。零修改 `add_point_transaction` / FSM 业务逻辑；零 schema 变更；零修正按钮（§6.3）。新增测试 31 个 service test（常量 / 4 类异常场景含孤儿流水 / 平账 / 显示名 fallback / 排序按 |diff| / 分页 25 条切分 / 越界夹紧 / 排除平账用户 / 渲染含全段含 N/A 含跨页引用 §7.1 / 异常列表分组渲染）+ 12 个新 kb test（菜单入口位置契约 + overview 含/不含异常按钮 + 异常列表 4 分页边界 + 返回概览 + 防御性"无修正按钮"+ callback ≤ 64B）。修正既有 1 个 `test_admin_points_menu_kb_button_count` 从 5 → 6。`POLICY.md` 新增 §十「积分异常对账」段（5 小节：用途 / 异常分类 / 后台入口 / 边界 / 后续计划——其中后续计划明确"修正动作放更后续 Sprint，须二次确认 + audit log + 共用 add_point_transaction 路径"），§十一"用户申诉建议"由 §十重编号。Sprint 4 §6.2 可做项收官（§6.2.2 配置化按 ROADMAP 留待下一 Sprint）。

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

### 7.7 进度（2026-05）

- **§7.3.1 找老师分组**：✅ 已落地（UX-3 第一批 commit `afcfe4c`，2026-05）—— 「🔎 找老师」聚合页含 `user:hot` / `user:today` / `user:filter` / `user:search_history` 4 个入口，主菜单独占首行。
- **§7.3.2 我的记录**：✅ 已落地（本 PR）。`user_main_menu_kb` 末尾新增「📝 我的记录」独占一行（callback `user:my_records`）；新增 `user_my_records_kb` 二级页含 4 个子入口：「📝 我的评价 → user:write_review」/ 「🧾 我的报销 → user:reimburse」/ 「💰 积分流水 → user:points」/ 「🎁 抽奖记录 → user:lottery:joined」+ 返回主菜单。新增 `cb_user_my_records` handler 仅承担导航（state.clear + edit_text）。`bot/handlers/user_panel.py` 与 `bot/keyboards/user_kb.py` 各加一段；零修改子页业务逻辑（write_review / reimburse / points / lottery 任一 handler 都没动）。**§7.4 实施纪律：旧 4 个一级入口在主菜单原位完全保留**（双跑观察期）。新增测试 10 个 kb test（新入口契约 + 末行独占 + 旧入口仍保留 + 4 子入口 + 复用既有 callback 命名空间 + 不引入子命名空间 + 按钮文案 + callback ≤ 64B）+ 改 3 个旧测试（write_review 末行契约 / lottery 末行契约 / 主菜单按钮总数 14 → 15 → 16）。
- **§7.3.3 活动中心**：UX-6.1 已落地「🎁 抽奖中心」（commit `fe7ef44`）。当前项目无独立「积分活动 / 订阅任务」功能，§7.3.3 范围（抽奖活动 / 积分活动 / 订阅任务）实际只能映射到抽奖；继续做"活动中心"将与既有"抽奖中心"重复或引入未实现功能（违反 §7.5 "不修改核心动作逻辑"）。**本 Sprint 不重复实现**；待项目新增积分活动 / 订阅任务时再启动 §7.3.3 重组。

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

### 8.6 进度（2026-05）

- **§8.3 审查 PR 已落地**（本 PR）：产出 [docs/TEACHER-PANEL-AUDIT-2026-05.md](TEACHER-PANEL-AUDIT-2026-05.md)。审查结论：
  1. 老师主菜单当前已 3 按钮（`teacher_self:checkin` / `teacher_self:profile` / `teacher:status`），UX-5.1 已实现"签到置顶 + 动态文案"。§8.5 验收 4 项**当前全部已满足**（入口清晰 / 按钮数减少 / 签到流程未变 / 无误触发 admin-user 入口）。
  2. §8.2 建议入口 5 个**比现状多**，与 §8.5 "按钮数量减少" 冲突；其中"📝 我的评价"和"❓ 帮助"对应**当前项目不存在的业务功能**，新增违反 §8.4 "不引入用户/管理员功能"。
  3. `teacher:*` 命名空间被三角色共用（老师 `teacher:status*` / 管理员 `teacher:list/delete/enable/...` / 用户 `teacher:view/similar/...`），但 handler 级别权限校验完备（`get_teacher` / `admin_required` / 私聊校验），不构成功能错误；大改命名空间会破坏所有历史 inline button，与 §2.4 "旧 callback 兼容" 冲突，故**不推荐**。
  4. 全部 `teacher_self:*` / `teacher:status*` callback 均有 handler 引用，无遗弃路径。
- **§8.3 精简 PR 已落地**：仅做防御性测试与文档约束，**零 keyboard / handler 代码改动**。新增 `tests/test_teacher_main_menu.py`（15 个契约 test），锁定：① 按钮总数 ≤ 3 且当前 == 3（双向约束防漂移）；② 签到 callback 必须在第一行第一个，文案根据 `checked_in` 动态切换；③ callback 必须属于 `teacher_self:*` 或 `teacher:status*` 命名空间；④ 禁止 `user:*` / `admin:*` / `menu:*` 跨角色入口；⑤ 禁止 `teacher:view/similar/list/delete/enable/confirm/select/remind/reviews/toggle_fav` 等用户/管理员 `teacher:*` 子路径；⑥ 签到 callback_data 精确为 `teacher_self:checkin`（防御重命名）；⑦ 资料 + 状态入口存在（防御无意识删除）；⑧ callback_data ≤ 64B。`docs/DESIGN.md` §2.3.5 新增「老师主菜单契约」段（5 项契约表格 + 防御性测试说明 + 审查报告链接）。零业务功能扩展；CI 1625 全绿。
- **Sprint 6 收官**：§8.1 / §8.5 验收 4 项已在 UX-5.1 时代自然满足；本 Sprint 仅把"已达成的简化状态"通过契约固化，防止未来回归。

---

## 9. Sprint 7：维护清理

### 9.1 Dead code P3-B

- **当前状态**：P3-A 已完成 `# deprecated` 注释标记，但**尚未删除**。
- **候选删除清单**（P3-A `# deprecated` 注释已在代码内标出）：
  - ~~`promo_links.py`~~ ✅ 已删除（2026-05-20 Sprint 7 §9.1 第 1 批 commit `<本 PR>`）
  - ~~`source_stats.py`~~ ✅ 已删除（2026-05-20 Sprint 7 §9.1 第 2 批 commit `<本 PR>`）
  - ~~旧 `ReviewSubmitStates`~~ ✅ 已删除（2026-05-20 Sprint 7 §9.1 第 3 批 commit `<本 PR>`）
- **要求**：
  - 再次审查（确认调用方为 0，确认没有被新代码偷偷依赖）。
  - **分阶段删除**：每次只删 1 个文件 / 1 个类，单独 PR。
  - **每次删前补测试**：先确认现有测试覆盖到对应路径的「替代实现」。
  - **不一次性全删**。

#### 9.1.1 第 1 批：promo_links 删除（2026-05）

- **审查**：[docs/TEACHER-PANEL-AUDIT-2026-05.md] 模式同款审查（grep 全项目调用方为 0；未注册到 routers.py；handler 自身明确标 dead code since 2026-05-18）
- **删除清单**：
  - `bot/handlers/promo_links.py`（286 行）
  - `bot/keyboards/admin_kb.py::promo_links_menu_kb` + `promo_cancel_kb`
  - `bot/states/teacher_states.py::PromoLinkStates`
- **保留**：`bot/routers.py` 中的注释（从"已下线 dead code 兼容"改为"已删除"+ 指向 source_stats 待清理）
- **新契约测试**：`tests/test_dead_code_annotations_static.py` 中删除旧 `test_promo_links_marked_dead_code`（文件不在了）；新增 `test_promo_links_module_deleted`（文件不存在 + 模块属性不可 import）+ `test_admin_kb_source_has_no_promo_callbacks`（callback_data 不含 admin:promo）；`test_unregistered_router_diff_unchanged` 差集期望从 `{promo_links, source_stats}` → `{source_stats}`
- **其它测试不需要改**：5 处现有测试只断言 routers.py 源码不含 `promo_links_router` / kb 不含 `admin:promo` —— 删除后这些断言仍然成立
- CI 1626 全绿；零业务行为变化

#### 9.1.2 第 2 批：source_stats 删除（2026-05）

- **审查**：handler 内已标 `DEAD CODE since 2026-05-18 Phase 4`；grep 全项目调用方为 0；未注册到 routers.py；DB 层 4 个 helper（`count_total_source_users` / `get_top_sources_by_type` / `get_user_source_summary` / `get_source_stats`）仅被本 handler 引用 —— **§9.1 纪律「每次只删 1 个文件」，本 PR 仅删 handler 层，DB helper 留待后续 PR 单独清理**
- **删除清单**：
  - `bot/handlers/source_stats.py`（237 行）
  - `bot/keyboards/admin_kb.py::source_stats_menu_kb` / `source_stats_back_kb` / `source_lookup_cancel_kb`（35 行）
  - `bot/states/teacher_states.py::UserSourceLookupStates`（3 行）
- **保留**：`bot/database.py` 中 4 个 source DB helper（约 100 行）+ `user_event_sources` / 相关表（未触动）
- **新契约测试**：`test_dead_code_annotations_static.py`
  - 删 `test_source_stats_marked_dead_code`（文件不在了）
  - 新增 `test_source_stats_module_deleted`：断言文件不存在 + `admin_kb` 无 3 个 `source_stats_*` 属性 + `teacher_states` 无 `UserSourceLookupStates`
  - 新增 `test_admin_kb_source_has_no_source_stats_callbacks`：admin_kb 源码不含 `admin:source_stats` / `admin:user_source` callback_data
  - `test_unregistered_router_diff_unchanged` 差集期望从 `{source_stats}` → `set()`（所有 P3-B handler 全部清理完成）
- **其它测试不需要改**：5 处现有测试只断言 routers.py / kb 源码层面不含 `source_stats_router` / `admin:source_stats` callback —— 删除后这些断言仍然成立
- CI 1627 全绿；零业务行为变化；零 schema 变更

#### 9.1.3 第 3 批：ReviewSubmitStates 删除（2026-05）

- **审查**：旧线性评价 FSM `ReviewSubmitStates` 自 2026-05-18 Phase 2 卡片化重构起已无外部入口；全项目 `set_state(ReviewSubmitStates.*)` 调用都封闭在 `review_submit.py` 私有 `_enter_*` 函数中，外部 0 引用。新评价路径走 `CardReviewStates`（`review_card.py`），有自己的 cb_card_submit / cb_card_reimburse_yes / 限频 / gate 等等价实现。
- **删除清单**：
  - `bot/states/teacher_states.py::ReviewSubmitStates` 类（11 个 State）
  - `bot/handlers/review_submit.py` 中 16 个 ReviewSubmitStates handler / `_enter_*` / `_record_score` / `_compute_overall_avg` / `_check_rate_limit` / `_ack` / `_show`（共约 681 行）
  - 顶部 `_SCORE_FLOW` / `_STEP_BY_KEY` 元数据（仅被删除路径用过）
  - 顶部 deprecated 注释 + 5 个孤立 keyboard import + 6 个孤立 DB helper import + `re` / `StateFilter` 孤立 import
- **保留**：`review_submit.py` 主体（404 行减肥到 ~445 行 → 实际约 517 行）保留以下职责：
  - `start_review_flow()`：[📝 写评价] 入口，重定向到 `review_card.start_card_review`
  - `cb_review_start`：teacher_detail [📝 写评价] callback 入口
  - 个人评价主页相关 handler（`user:write_review` / `user:reviews:*`）
  - `WriteReviewLookupStates` FSM（艺名查老师 → 进卡片）
  - 通用取消 `cb_review_cancel`
- **跨文件清理**：
  - `bot/routers.py`：注释从 `ReviewSubmitStates FSM 状态过滤` 改为 `已于 §9.1 第 3 批清理`
  - `bot/handlers/review_card.py`：docstring 中 `vs ReviewSubmitStates 线性 FSM` 改为 `vs 旧线性 FSM (已清理)`，并去掉 `bot.handlers.review_submit._check_rate_limit / _compute_overall_avg` 的「主要复用」表述（review_card 已有自己的副本）
  - `bot/states/teacher_states.py::WriteReviewLookupStates` docstring 把 `转 ReviewSubmitStates` 改为 `转 CardReviewStates`
- **保留（§9.1 纪律：每次只删 1 个文件）**：
  - `bot/keyboards/user_kb.py` 中 5 个孤立 keyboard 函数（`review_rating_kb` / `review_score_kb` / `review_summary_skip_cancel_kb` / `review_confirm_kb` / `review_reimbursement_choice_kb`）—— 留待**独立 PR** 单独清理
  - `bot/database.py` 中 6 个 review DB 常量 / helper（`REVIEW_DIMENSIONS` / `REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM` 等）—— 同上
  - `bot/database.py` 中 `parse_review_score` —— 同上
- **测试更新**：
  - 新增 `test_review_submit_states_class_deleted` + `test_review_submit_handlers_no_longer_exist`（断言不再 import / set_state / state filter，且 16 个 handler 函数名都不存在）
  - 删 `test_review_submit_has_deprecated_annotation`（旧契约：源码必须含「deprecated」字样 + 旧线性 FSM 概念）—— 文件已不再含旧 FSM
  - 在 4 个 review-submit 相关测试文件（`test_reimburse_ineligibility_hint.py` / `test_reimburse_settings.py` / `test_reimburse_subreq_isolation.py` / `test_reimburse_subreq_user_gate.py`）中删除断言旧 review_submit handler 存在的 9 个测试。所有等价契约已由 review_card 路径上的对称测试覆盖。
- CI 1617 全绿；零业务行为变化（旧 FSM 已无入口）；零 schema 变更

#### 9.1.4 后续清理

- ~~`bot/keyboards/user_kb.py` 中 5 个旧评价 keyboard~~（独立 PR）✅ 已删除（2026-05-20 Sprint 7 §9.1.4 第 1 批 commit `<本 PR>`）
- ~~`bot/database.py` 中旧评价 DB 常量与 helper~~ ✅ 部分已删（§9.1.4 第 2 批，2026-05-20 commit `<本 PR>`）。剩余的 `REVIEW_DIMENSIONS` / `REVIEW_SUMMARY_MIN_LEN` / `REVIEW_SUMMARY_MAX_LEN` / `parse_review_score` 等仍被 `review_card.py` 使用，**非孤儿，保留**
- ~~`bot/database.py` 中 4 个 source DB helper 删除~~ ✅ 已删除（2026-05-20 Sprint 7 §9.1.4 第 3 批 commit `<本 PR>`）

至此 Sprint 7 §9.1 P3-B Dead code 全部清理完成（promo_links / source_stats / ReviewSubmitStates handler / review keyboard / review DB 常量 / source DB helper），共 6 个 PR，累计净删 ~1400 行。

#### 9.1.4.1 第 1 批：5 个孤立评价 keyboard 删除（2026-05）

- **审查**：grep 全项目，5 个 keyboard 仅由自身定义引用，无外部 caller —— 随 §9.1 第 3 批 ReviewSubmitStates 清理后已变为孤儿
- **删除清单**（`bot/keyboards/user_kb.py`，约 100 行）：
  - `review_rating_kb()` —— 旧 Step 1 评级
  - `review_score_kb()` —— 旧 Step 2-7 / 综合评分快捷按钮
  - `review_summary_skip_cancel_kb()` —— 旧 Step 9 过程描述
  - `review_reimbursement_choice_kb()` —— 旧报销意愿询问
  - `review_confirm_kb()` —— 旧确认页（11 个修改跳回）
  - `_REVIEW_EDIT_KEYS` —— 仅被 review_confirm_kb 引用
- **新契约测试**：`test_review_orphan_keyboards_deleted` —— 断言 5 个 keyboard 函数 + `_REVIEW_EDIT_KEYS` 不再可 import；同时检测源码层面不含 `"review:rating:"` / `"review:score:"` / `"review:edit:"` / `"review:submit"` / `"review:reimburse_yes"` / `"review:reimburse_no"` / `"review:summary_skip"` 等 7 个旧 callback_data 字面量（防御函数被删但字面量遗留）
- CI 1618 全绿；零业务行为变化（这些 keyboard 在 §9.1 第 3 批后已无 caller）

#### 9.1.4.2 第 2 批：3 个孤儿评价 DB 常量 + 7 个孤儿 import 删除（2026-05）

- **审查**：grep 全项目，确认随 §9.1 第 3 批 ReviewSubmitStates 删除 + §9.1.4 第 1 批 keyboard 删除后，3 个常量自动变孤儿；同时 `review_submit.py` 中遗留 7 个孤立的 DB import（评价限频常量 / 报销金额 / 用户积分 / 评价计数等）也一并清理
- **删除清单**：
  - `bot/database.py`（3 个孤儿常量）：
    * `REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM` —— 旧 6 维评分快捷按钮
    * `REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL` —— 旧综合评分快捷按钮
    * `REVIEW_SUMMARY_REQUIRED` —— 旧过程描述必填 flag（review_card 中过程始终必填，不需要 flag）
  - `bot/handlers/review_submit.py`（7 个未用 import）：
    * `REVIEW_RATE_LIMIT_PER_TEACHER_24H` / `REVIEW_RATE_LIMIT_PER_USER_DAY` / `REVIEW_RATE_LIMIT_PER_USER_60S` —— review_card 自有副本
    * `compute_reimbursement_amount` / `get_config` / `get_user_total_points` —— 旧报销询问步用
    * `count_recent_user_reviews` / `count_recent_user_teacher_reviews` —— 旧限频检查用
    * `get_teacher` —— 旧 evidence 校验用（review_submit 现仅用 `get_teacher_by_name`）
- **保留**（仍被 `review_card.py` 使用，非孤儿）：
  - `REVIEW_DIMENSIONS` —— 6 维元数据
  - `REVIEW_SUMMARY_MIN_LEN` / `REVIEW_SUMMARY_MAX_LEN` —— 字数校验
  - `REVIEW_SCORE_MIN` / `REVIEW_SCORE_MAX` / `REVIEW_SCORE_DECIMAL_PLACES` —— `parse_review_score` 内部使用
  - `parse_review_score` —— review_card 评分解析
  - 3 个 `REVIEW_RATE_LIMIT_*` —— review_card 限频检查
- **新契约测试**：
  - `test_review_orphan_db_constants_deleted` —— 断言 3 个常量不再可从 `bot.database` import
  - `test_review_submit_stale_db_imports_cleaned` —— 检测 review_submit.py 源码不含 7 个已删除 import 名
- CI 1620 全绿；零业务行为变化（这些常量与 import 已无 caller）

#### 9.1.4.3 第 3 批：4 个 source DB helper 删除（2026-05）

- **审查**：grep 全项目，确认随 §9.1 第 2 批 source_stats handler 删除（commit 0a84708）后，4 个 helper 仅由 database.py 自身定义，无外部 caller。`user_sources` 表本身保留（仍由 `/start` 时来源追踪写入），仅删除查询接口
- **删除清单**（`bot/database.py`，约 92 行）：
  - `get_source_stats(limit)` —— 渠道统计 TOP 来源
  - `get_top_sources_by_type(source_type, limit)` —— 按类型 TOP source_id
  - `get_user_source_summary(user_id)` —— 单用户首次/最近/全量来源
  - `count_total_source_users()` —— 来源覆盖去重用户数
- **同步更新注释**：`bot/keyboards/admin_kb.py` 中"留待后续 PR 单独清理"改为"已于 Sprint 7 §9.1.4 第 3 批一并清理"
- **新契约测试**：`test_source_stats_db_helpers_deleted` —— 断言 4 个 helper 不再可从 `bot.database` import
- CI 1621 全绿；零业务行为变化（这些 helper 已无 caller）；零 schema 变更（`user_sources` 表保留）

### 9.2 `prune.sh --confirm`

- **当前状态**：✅ 已落地（2026-05-20 Sprint 7 §9.2 commit `<本 PR>`）。
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

#### 9.2.1 实现要点（2026-05）

- **三重防线**：
  1. **CLI 双确认**：`--confirm` 必须显式带 `--days N`（即便用默认 180 也得显式 `--days 180`）；与 `--dry-run` 互斥
  2. **Backup 强制**：当天必须存在 `backups/bot.db.YYYYMMDD-*.manual.bak`，否则 exit 1
  3. **5 秒安全倒计时**：进 DELETE 前 stderr 倒计数 5→1，可 Ctrl-C 中止
- **PERMANENT_FORBIDDEN_TABLES** 在脚本顶部声明 8 张权益表；启动时做 WHITELIST × FORBIDDEN 双层 for 循环交集检查（编程错误防护，防止有人不慎扩展 WHITELIST）
- **每表独立事务**：`BEGIN TRANSACTION / DELETE / COMMIT`；单表 DELETE 失败 → `ROLLBACK` 不影响其它表
- **完整性校验**：DELETE 后 `PRAGMA integrity_check`，非 `ok` 立即 `exit 2` 提示从 backup 恢复
- **Bash 直写 admin_audit_logs**：`INSERT INTO admin_audit_logs (admin_id=0, action='prune_confirm', target_type='database', target_id=DB_PATH, detail JSON 含 days/tables/total_deleted/backup)`，不引入 Python 依赖
- **退出码语义**：`0` 全成功；`1` 参数错误 / 缺备份 / 部分表 DELETE 失败；`2` integrity_check 异常（要求 backup 恢复）
- **不引入 VACUUM**：SQLite WAL 模式 VACUUM 锁库，留作后续单独维护窗口工作
- **测试**：30 个 test 覆盖（13 个旧 dry-run 路径分支检测 + 17 个新 confirm 路径，含 11 个 A 类静态契约 / 6 个 B 类集成场景；B 类用临时 SQLite + sqlite3 .backup 真生成 backup 文件，覆盖 dry-run 不改库 / 无备份拒绝 / 完整删除 / 缺 days 拒绝 / dry-run+confirm 互斥 / 0 命中跳过删除 + 权益表 prune 前后行数 == 核心安全断言）
- 文档：`INFRASTRUCTURE-DESIGN.md` Part B §五 / §六 / §十从「P3 未启动」改为「✅ 已完成」；`RUNBOOK.md` §6.3.1 新增「prune --confirm 操作流程」段含失败处理。
- CI 1639 全绿（1618 → +21 测试）；零业务行为变化；零 schema 变更。

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
