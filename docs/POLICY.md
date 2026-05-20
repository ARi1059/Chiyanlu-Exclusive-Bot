# 运营政策

> 本文档面向运营人员、管理员与超管。合并自原三份子系统政策（积分 / 报销 / 抽奖）。
> 内容根据当前代码整理；以代码实际行为为准；模糊或未明确处标注 **"需产品确认"**。
>
> **2026-05-20**：由 POLICY-points / POLICY-reimbursement / POLICY-lottery 合并而成；各部分内部章节编号保持原结构以减少改动量。

## 目录

- [Part I：积分规则](#part-i积分规则) — `users.total_points` / `point_transactions` / 加扣分流程 / 一致性
- [Part II：报销规则](#part-ii报销规则) — `reimbursements` / 资格 / 周限 / 月池 / 口令红包 / 必关订阅 / 门槛与重置
- [Part III：抽奖规则](#part-iii抽奖规则) — `lotteries` / 创建 / 参与 / 开奖 / 通知 / 取消退款

---

# Part I：积分规则

## 一、积分系统定位

积分是 Bot 平台内部的**用户权益记录**，用于：

- 作为活动 / 抽奖参与门槛
- 评价通过后的奖励
- 记录用户在平台中的累计贡献

**积分不是现金，也不等同于提现余额。** 除非产品明确发布公告说明可兑换权益，否则积分不可直接换钱、不构成对用户的金钱承诺。涉及报销（积分门槛）等真实权益的具体规则请见 [Part II：报销规则](#part-ii报销规则)。

---

## 二、积分余额

每个用户的当前积分余额存储在 `users.total_points` 字段（INTEGER，默认 0）。

- 用户私聊主菜单「💰 我的积分」展示余额（callback `user:points`）
- 超管「[admin:points]」可查询任意用户余额
- 余额数值通过累加 / 累减 `point_transactions.delta` 维护

**重要：余额数值的权威来源是 `users.total_points` 字段，而非流水汇总。** 报表 / 渲染层若发现两者不一致，以 `users.total_points` 为准（详见 [§七 一致性](#七积分一致性)）。

---

## 三、积分流水（point_transactions）

每一次积分变动都必须形成流水记录，便于审计与追溯。

| 字段 | 含义 |
|---|---|
| `user_id` | 积分归属用户 |
| `delta` | 整数变动，**正数 = 加分，负数 = 扣分** |
| `reason` | 来源类型（见下表） |
| `related_id` | 关联业务 ID（review_id / lottery_id 等） |
| `operator_id` | 操作管理员的 Telegram ID；**系统自动产生时为 NULL**（如抽奖参与扣分） |
| `note` | 备注文本（如套餐名 / 自定义原因 / 活动名） |
| `created_at` | 流水时间戳，默认 `CURRENT_TIMESTAMP` |

### 当前已知的 reason 取值

| reason | 含义 | 来源场景 |
|---|---|---|
| `review_approved` | 评价 / 报告审核通过 | 超管在「报告审核」点通过时按所选套餐加分 |
| `admin_grant` | 管理员加分 | 超管「积分管理」手动 + 分 |
| `admin_revoke` | 管理员扣分 | 超管「积分管理」手动 - 分 |
| `lottery_entry` | 抽奖参与扣分 | 用户成功进入抽奖后扣 `entry_cost_points` |
| `lottery_refund` | 抽奖取消退款 | 超管取消抽奖并勾选「退还参与积分」 |

---

## 四、积分获得方式

### 4.1 评价 / 报告审核通过（reason=`review_approved`）

超管在「📋 报告审核」点 [✅ 通过] 时**必须选择加分套餐**。当前预设：

| 套餐 key | 默认分值 | 含义 |
|---|---|---|
| `p` | +1 | P / PP（基础） |
| `hour` | +3 | 包时 |
| `night` | +5 | 包夜 |
| `day` | +8 | 包天 |
| `zero` | 0 | 不加分 |

超管可选「自定义」输入数值，范围 **0 ~ 100**（不允许此处扣分）。

加分对象 = 评价的提交者（`teacher_reviews.user_id`），关联 `related_id = review_id`，`note = 套餐名` 或 `自定义`，`operator_id = 超管 id`。

### 4.2 抽奖取消退款（reason=`lottery_refund`）

仅当超管取消处于 `active` 状态、`entry_cost_points > 0` 且有参与者的抽奖时，会出现「退还参与积分」选项。勾选后：

- 对**每一位**参与者退还**完整 `entry_cost_points`**（不区分该用户当时实际是否扣分成功）
- `operator_id = 操作超管 id`，`note = 抽奖名`

详见 [Part III：抽奖规则](#part-iii抽奖规则) §十。

### 4.3 管理员手动加分

见 [§六 管理员调整积分](#六管理员调整积分)。

---

## 五、积分消耗方式

### 5.1 抽奖参与（reason=`lottery_entry`）

当抽奖 `entry_cost_points > 0` 时，用户成功进入抽奖会扣除该数额积分：

1. **预校验**：参与前检查 `current_points >= entry_cost_points`，余额不足直接拒绝（`need_points`），**不创建 entry，不扣分**
2. **扣分时机**：先在 `lottery_entries` 表写入参与记录，**之后**再调 `add_point_transaction(delta=-cost)`
3. `operator_id = NULL`（系统自动），`note = 抽奖名`

⚠️ **运营注意：扣分与 entry 写入不是原子操作。** 若扣分调用失败（DB 异常等），entry 已写入但积分未扣；代码当前仅写 warning 日志，**不回滚 entry**。出现此情况时该用户会"白嫖"一次参与。

> **需产品确认**：扣分失败时是否需要回滚 entry，或事后由超管人工核对补扣？

### 5.2 管理员手动扣分

见 [§六](#六管理员调整积分)。

### 5.3 其它扣分场景

代码中**没有**其它自动扣分场景。所有非抽奖的积分减少都必须通过超管手动操作。

---

## 六、管理员调整积分

### 6.1 权限

**仅超级管理员可调整积分。** 普通管理员看不到 / 用不了「积分管理」入口（代码强制 `_super_admin_required`）。

### 6.2 入口

`/admin` →「📋 积分管理」（callback `admin:points`），含：
- 「🔍 查询积分」：按 user_id / @username / first_name 查询，显示余额 + 最近 10 条流水
- 「⚖️ 手动加扣分」：4 步 FSM
- 「📊 持币概览」：TOP 10 + 累计统计

### 6.3 手动加扣分流程（4 步）

1. **目标用户**：输入 user_id / @username
2. **数值**：可选预设按钮或「自定义」输入
   - **加分预设**：+1 (P/PP) / +3 (包时) / +5 (包夜) / +8 (包天) / +10 / +20
   - **扣分预设**：-1 / -3 / -5 / -10
   - **自定义范围**：**-100 ~ +100**（含 0）
3. **原因**：
   - 预设：`audit`（报告审核补加，记为 admin_grant）/ `event`（活动奖励，记为 admin_grant）/ `violate`（违规扣分，记为 admin_revoke）/ `fix`（系统修正，记为 admin_grant）
   - 自定义：≤ 100 字；自动按 delta 正负决定 reason（`admin_grant` 或 `admin_revoke`）
4. **确认**：显示完整 diff 后确认；提交后写入 `point_transactions` + 更新 `users.total_points` + 写 `admin_audit_logs`（action=`points_grant`，含完整 detail）

### 6.4 边界与注意

- ⚠️ **手动扣分不检查余额**：可能产生负余额。是否允许负余额取决于运营策略。
  > **需产品确认**：是否需要在 UI 层禁止扣到负数？
- ⚠️ **预设原因与 delta 符号无强制对应**：可以选 `violate`（默认 admin_revoke）但同时给 +5 delta。代码不阻止。
  > **需产品确认**：是否需要校验 `violate` 必须 < 0、`event` 必须 > 0 等？
- ⚠️ **加分预设的 +10 / +20 是按钮硬编码**，不走 `POINT_PACKAGE_OPTIONS` 配置。如需调整需改代码。

### 6.5 审计

每次手动加扣分都写 `admin_audit_logs`：
- `action`：`points_grant`（含 +/-）
- `target_type`：`user`
- `target_id`：被操作用户 ID
- `detail`：包含 `delta` / `reason` / `note` / `new_total` / `tx_id`

查询操作也会写审计（`action=points_query`），便于追溯"是谁在查谁"。

---

## 七、积分一致性

### 7.1 数据存放

- **余额**：`users.total_points`（权威）
- **流水**：`point_transactions`（审计）

每次 `add_point_transaction` 调用都会**同时**写流水 + 更新 `users.total_points`，但**不在单一事务**中（注意此限制）。

### 7.2 一致性约束

- `users.total_points` 应当 ≈ `SUM(delta)` 在该用户的所有流水上
- 代码层面**没有自动对账工具**：若由于并发写、DB 异常或人工 SQL 改库导致两者不一致，**应用层不会自动修复**

### 7.3 运营约定

- ⛔ **不要直接 UPDATE `users.total_points` 改余额**：会破坏与流水的一致性
- ⛔ **不要直接 INSERT 到 `point_transactions`**：会导致余额未同步更新
- ✅ **所有人为调整必须通过「⚖️ 手动加扣分」UI**

### 7.4 已知问题

- `_migrate_users_total_points` 迁移加 `total_points` 字段时**不回填**：即如果某用户在迁移之前已有 `point_transactions` 流水，迁移后 `total_points = 0`，并不会自动汇总。
  > **需产品确认**：是否需要一次性回填脚本？

- 并发写无显式锁：当两个操作几乎同时修改同一用户的 `total_points` 时，依赖 SQLite 写串行化保证最终一致；理论上**存在丢失更新风险**，目前未观察到生产事故。
  > **需产品确认**：高并发场景（抽奖开抢瞬间）是否需要补强事务隔离？

---

## 八、异常处理

### 8.1 重复加分

代码层面**没有防重复加分逻辑**。同一个 review 如果被超管点击两次 [✅ 通过]，DB 层 `approve_teacher_review` 仅在 `status='pending'` 才更新（防重审），因此正常流程下不会重复加分。

⚠️ 若超管手动加分时输入了相同的 user_id 多次确认，**会重复加分**。建议每次操作前确认目标用户与最近流水。

### 8.2 重复扣分

抽奖参与有 `UNIQUE(lottery_id, user_id)` 约束：DB 层防止同一用户对同一抽奖的双重 entry，因此也防止双重扣分。

### 8.3 余额不足

- **抽奖**：硬拒绝（`need_points` 提示），不创建 entry
- **管理员手动扣分**：**不检查**（见 6.4）
- **其它**：无其它消耗场景

### 8.4 抽奖扣分失败

参见 [§5.1](#51-抽奖参与reasonlottery_entry)。entry 已创建但扣分失败时**不回滚**。运营建议：
- 定期对账：把 `lottery_entries` 中的 entries 与 `point_transactions` 中的 `lottery_entry` 流水按 `(lottery_id, user_id)` 对照
- 发现差异由超管人工补扣

### 8.5 审核回退 / 误操作

代码**不支持**自动撤销已通过的评价 / 已写入的流水。如发现误操作（误加分 / 误扣分 / 误审核）：

1. 超管在「⚖️ 手动加扣分」**反向操作**抵消：例如误加 +5，手动 -5，原因填「系统修正」并备注误操作 ID
2. 不要直接删除原流水
3. `admin_audit_logs` 会记录两次操作，便于事后追溯

### 8.6 人工修正

如必须直接修改 DB（不推荐），步骤：

1. 停服 `systemctl stop chiyanlu-bot`
2. 备份 DB（`sqlite3 .backup`）
3. 用 SQL 同时改 `users.total_points` 和 `point_transactions`
4. 在 `admin_audit_logs` 表手动插入一条记录说明本次人为修正
5. 起服

⚠️ 此操作**绕过审计 UI**，请在 RUNBOOK 中详细记录原因与执行人。

---

## 九、用户申诉建议

用户对积分有异议时，应在群组 / 私聊中**提供以下材料**，便于运营核对：

1. **Telegram 用户 ID 或 @username**（user_id 优先，可在「我的积分」页查到）
2. **相关业务编号**：
   - 评价加分有异议 → review_id（在「写评价」反馈中 / 私聊审核结果通知中）
   - 抽奖扣分有异议 → lottery_id（在抽奖参与确认消息中）
   - 手动调整有异议 → 调整时间 + 大致数值
3. **预期值 vs 实际值**：预期加 X / 扣 Y 分，实际为 Z
4. **截图**：积分明细页 / 通知消息 / 抽奖确认 等
5. **时间窗**：申诉应在异议事件发生后**及时**提出，时间越久越难还原

运营在「积分明细」+「审计日志」中查询 `user_id` / `related_id` 即可还原全部历史。

> **需产品确认**：是否对申诉受理设定有效期（如事件发生后 30 天内）？目前代码无时限。

---

# Part II：报销规则

## 一、报销系统定位

报销系统将符合条件的**评价 / 报告**自动转为待审核的报销申请，由超级管理员二次审核后由人工 / 客服线下发放权益。

⚠️ **报销涉及真实金钱权益**，所有规则应以**频道公告 + 后台配置**为准。代码内的规则（金额映射、积分门槛、周限、月池）随时可能由超管在后台调整。运营人员应：

- 不擅自承诺审批结果
- 不公开后台配置细节（如月池余额）
- 不通过群组私聊承诺金额
- 所有发放必须留痕

---

## 二、报销申请来源

### 2.1 字段

`teacher_reviews.request_reimbursement` 是一个 INTEGER：

| 取值 | 含义 |
|---|---|
| `0` | 用户未申请 / 不合格 |
| `1` | 用户明确勾选了「申请报销」（功能 ON 状态下） |
| `2` | 用户合格但功能 OFF —— 静默录入名单（queued） |

### 2.2 触发流程

1. 用户在写评价的卡片 FSM 中点 [✅ 提交]
2. 系统检查 [资格](#四报销资格) 决定 `request_reimbursement` 值
3. **不在此时**创建 `reimbursements` 记录
4. 评价进入审核队列，超管点 [✅ 通过] 时**才**创建 `reimbursements` 记录（status = pending 或 queued）

**关键：报销记录的唯一创建入口在 `rreview_admin.py` 评价审核通过时。代码没有其它创建报销的路径。**

---

## 三、报销状态

`reimbursements.status` 共 5 个枚举值（DB CHECK 约束）：

| 状态 | 中文 | 写入时机 |
|---|---|---|
| `pending` | ⏳ 待审核 | 用户勾选申请 + 评价过审 + 功能 ON |
| `approved` | ✅ 已通过 | 超管在「💰 报销审核」点 [✅ 通过] 且周/月配额校验通过 |
| `rejected` | ❌ 已驳回 | 超管在「💰 报销审核」点 [❌ 驳回] 并填写原因 |
| `queued` | 📋 已录入名单（待启用） | 用户合格 + **功能 OFF** + 评价过审；admin 可后续手动激活转 pending |
| `cancelled` | 🚫 已取消 | ⚠️ 当前代码无任何写入点 |

> **需产品确认：** `cancelled` 状态在 DDL 中保留但**代码全无写入路径**（既无 admin 取消按钮，也无 user 取消接口）。是预留位 / 计划中功能 / 还是只能手工 SQL？目前 cancelled 仅作为可选 UI 状态文案展示，实际不会出现。

---

## 四、报销资格

### 4.1 提交评价时的资格校验（决定 `request_reimbursement` 取值）

校验顺序：

1. **必须有评价**：报销绑定 review，无评价不会询问
2. **必须通过必关订阅校验**（继承评价提交的前置条件）：用户必须已加入 `required_subscriptions` 中全部 active 频道/群组
3. **老师价位 > 0**：`compute_reimbursement_amount(teacher.price) > 0`（金额规则见 [§五](#五报销金额)）
4. **积分门槛**：`user.total_points >= reimbursement_min_points`（**默认 5**，可在后台 config 调整）
5. **功能开关**：`reimbursement_feature_enabled == "1"`

校验结果：

| 1 + 2 + 3 + 4 | 5 (功能开关) | 用户体验 | request_reimbursement |
|---|---|---|---|
| ❌ 任一不满足 | 任意 | 不弹询问，直接进入确认页 | `0` |
| ✅ 全部满足 | OFF | 不弹询问，静默录入 | `2` |
| ✅ 全部满足 | ON | 弹「💰 是否申请本次报销 X 元？」 | `1` 或 `0`（看用户选择） |

### 4.2 评价审核通过时的二次校验（决定是否真的创建 reimbursement）

超管点 [✅ 通过] 时再次重算：

1. 实时 `compute_reimbursement_amount(teacher.price)`
2. 实时读 `reimbursement_min_points`
3. **使用审批后的新积分余额**（含本次评价加分）
4. 仅当 `amount > 0 AND new_total_points >= min_pts` 时才真正写入 `reimbursements` 表

⚠️ **审批阶段不校验周限制和月池**。周/月校验只在超管点 [✅ 通过] 报销那一刻进行（见 [§九](#九审核流程)）。

> **需产品确认：** `reimbursement_feature_enabled` 配置项默认值（即 DB 中未设置时）按代码逻辑视为非 `"1"` → 默认 OFF → 默认走 queued 路径。这是否符合产品预期？运营首次部署时若未在后台启用，所有合格用户都会落入 queued，不进入审核队列。

---

## 五、报销金额

由 `compute_reimbursement_amount(teacher.price)` 计算。规则：

1. 取老师的 `price` 字段（字符串，如 `"800P"` / `"1000P"`）
2. 提取所有数字字符拼接（去除 P / 中文 / 空格 等）
3. 整除以 100 得 `hundreds`
4. 按下表映射金额：

| price 显示档位（hundreds） | 报销金额 |
|---|---|
| 0（无数字 / 解析为 0） | 0 元（不可申请） |
| 1 ~ 8 | **100 元** |
| 9 | **150 元** |
| 10 及以上 | **200 元** |

### 示例

| 老师 price | hundreds | 报销金额 |
|---|---|---|
| `"500P"` | 5 | 100 元 |
| `"800P"` | 8 | 100 元 |
| `"900P"` | 9 | 150 元 |
| `"1000P"` | 10 | 200 元 |
| `"2500P"` | 25 | 200 元 |
| `"P"` / `"免费"` / 空 | 0 | 不可申请 |

⚠️ **金额由老师 price 决定，不由用户评分 / 评价类型决定。** 同一老师所有用户的报销额度一致。

⚠️ **如果运营修改了老师 price**，后续新发起的报销金额会按新值计算；**已 pending 的报销金额已固定，不随老师 price 变化重算**（amount 字段在创建时即落库）。

---

## 六、每周限制

### 6.1 默认规则

**每用户每 ISO 周最多 1 次 approved 报销**（硬编码）。

- 统计字段：`reimbursements.week_key`，格式 `YYYY-Www`，如 `"2026-W20"`
- 周以 ISO 标准：周一为第 1 天，跨年时归属去年最后一周或新年第 1 周
- 时区按 `config.timezone`（默认 Asia/Shanghai）

> **需产品确认：** 周限制目前是代码硬编码 `>= 1`，不走 config。若运营需要调整（如改成 2 次 / 周），需修改代码。是否需要纳入 config 配置项？

### 6.2 reset voucher（额外审批券）

`reimbursement_resets` 表用于记录"额外审批券"。语义：

- **每张 voucher = 一次性"跳过本次周校验"**
- **不是** "+1 永久额度"
- **不是** "把当周已批数归零"
- 一名用户可同时持有多张 voucher（多次重置 = 多张）

### 6.3 voucher 操作流程

- **发放**：超管在某条报销的详情页点 [🔄 重置该用户本周] 二次确认后，调 `grant_reimbursement_reset(user_id, admin_id)`，写一条 `consumed=0` 的记录
- **消耗**：下次该用户**任何一次** approved 操作时，若 `week_used >= 1`，系统自动取**最早一张** 未消耗 voucher 标记 `consumed=1, consumed_at, consumed_reimb_id`
- **审计**：发放写 `admin_audit_logs(action="reimburse_reset")`

### 6.4 运营注意

- 发放 voucher 等于"对该用户解锁一次本周额外审批"，请慎重
- voucher 永久有效，不过期；如发放后用户长期不申请，可能积压
- 不存在批量发放 / 批量回收 UI，所有发放需逐次操作

---

## 七、月度报销池

### 7.1 配置

- 配置项：`reimbursement_monthly_pool`（写入 `bot_config` 表）
- 单位：元
- **默认值**：未设置 / 解析失败 → `pool = 0` → **不限**
- 入口：超管在「⚙️ 系统设置」→「💰 报销池设置」中输入数字保存

### 7.2 统计

- 统计字段：`reimbursements.month_key`，格式 `YYYY-MM`，如 `"2026-05"`
- 时区按 `config.timezone`
- 统计基数：**当月所有 status=approved 的 reimbursements 的 amount 求和**（全局池，所有用户共享）

### 7.3 校验时机

**仅在超管点 [✅ 通过] 时校验**。流程：

1. 读 `pool`，若 `pool <= 0` 视为不限 → 直接放行
2. 否则计算 `month_used = SUM(amount)` 当月已批准的报销
3. 若 `month_used + 本次申请 amount > pool` → 弹「⚠️ 本月池余额 X 元，不足以批准本次 Y 元」并**阻止本次审批**（记录仍为 pending）

### 7.4 注意

- 月池**不阻止用户提交申请**，只阻止超管审批通过
- 月池不足时**没有自动排队 / 自动顺延到下月**逻辑，pending 记录就停在那里，需要超管主动延后处理或驳回
- 用户主页「🧾 我的报销」可见当月池余额（信息透明），运营若希望对用户隐藏可在后续版本控制显示

> **需产品确认：** 月底未批的 pending 记录跨月时如何处理？目前代码无自动结转。

---

## 八、queued 状态

### 8.1 触发场景

`request_reimbursement = 2` 时（用户合格 + 功能 OFF），评价审核通过时 reimbursement 落库为 `status='queued'`。

含义：**"此用户原本符合报销资格，但活动当时未对外开放报销功能，先录入名单留底"**。

### 8.2 用户侧体现

- 用户提交评价时**不会弹询问**（静默录入）
- 评价通过通知中**不提及**报销（避免暗示用户可申请）
- 用户「🧾 我的报销」明细页会看到「📋 已录入名单（待启用）」状态

### 8.3 后续处理

超管在「💰 报销审核」→「📋 报销名单」查看 queued 记录（按 `created_at ASC` 排序，每页 10 条），可对单条点 [⚡ 激活] 转 `pending`，进入正常审批队列。

⚠️ **激活操作不会重新校验资格**：
- 不重算 amount
- 不重读积分余额
- 不检查 `reimbursement_feature_enabled` 当前状态

这是有意设计："只要曾经合格，就保留名单上的资格"。运营如不希望此行为应在激活前人工核对。

### 8.4 运营注意

- queued 是"名单留底"机制；若运营决定从此不再补发，可让 queued 永久停留不激活
- 不存在「批量激活」按钮，所有激活逐条进行
- queued 状态不计入周限 / 月池统计

> **需产品确认：** queued 记录若长期不激活，是否应有过期清理策略？目前代码无清理逻辑。

---

## 九、审核流程

### 9.1 入口

`/admin` →「💰 报销审核」（仅超管可见，普通管理员无权限）。两个子页：

- **[👀 待审核]**：按 `created_at ASC` 显示最早一条 pending，逐条审批
- **[📋 报销名单]**：分页查看 queued 列表（每页 10 条）

### 9.2 详情页内容

每条 pending 详情显示：
- 报销编号 `#id`
- 用户（半匿名 `*****6789`，鉴于隐私）
- 老师名 + 老师 price + 计算所得 amount
- 关联 review_id + 评价证据照片预览
- `week_key` + 本周已批数 `X/1`
- `month_key` + 本月已用池金额
- 当前持有的 reset voucher 数量

### 9.3 通过流程

点 [✅ 通过] 后：
1. 校验状态必须为 `pending`，否则拒绝
2. 校验月池（见 [§七](#七月度报销池)），失败显示 alert 中止
3. 校验周限（见 [§六](#六每周限制)），失败：
   - 用户**无** voucher → 显示 alert，提示「本周已批过」
   - 用户**有** voucher → 继续，事后消耗
4. `UPDATE ... SET status='approved', decided_at=NOW, decided_by=admin_id`
5. 若用了 voucher，标记消耗
6. 写 `admin_audit_logs(action="reimburse_approve")`
7. 私聊通知用户「✅ 你的报销申请 #X 已通过」（含金额、客服联系提示）
8. 推下一条

### 9.4 驳回流程

点 [❌ 驳回] 后进入 `ReimburseRejectStates.waiting_reason` FSM：

- 要求输入驳回原因
- **必填，不可为空，≤ 200 字**
- 写入 `reject_reason` 字段
- 通知用户「❌ 你的报销申请 #X 未通过」+ 原因

### 9.5 reset voucher 重置

详情页 [🔄 重置该用户本周] → 二次确认 → 发放 voucher（见 [§六](#六每周限制)）。

### 9.6 激活 queued

「📋 报销名单」分页 → 点单条 [⚡ 激活] → 状态 `queued → pending`，写 `admin_audit_logs(action="reimburse_activate")`，**不通知用户**（用户下次看「🧾 我的报销」会自然看到状态变化）。

### 9.7 审计标签

| action | 含义 | 关键 detail |
|---|---|---|
| `reimburse_approve` | 通过报销 | user_id / amount / week_key / month_key / reset_consumed |
| `reimburse_reject` | 驳回报销 | user_id / reason |
| `reimburse_reset` | 重置周配额 | user_id / voucher_id |
| `reimburse_activate` | 激活 queued | user_id / amount |
| `reimburse_created` | （联动）评价通过时自动创建 | review_id / amount / status |
| `reimburse_queued` | （联动）功能 OFF 时静默录入 | review_id / amount |

---

## 十、用户侧展示

### 10.1 入口

用户私聊主菜单「🧾 我的报销」（callback `user:reimburse`）。

### 10.2 总览页内容

- 本周已通过：`X/1 笔`
- 本月已通过总额：`X 元`（池 N 元 / 池不限）
- 累计申请：`X 笔`
- **最近 5 笔**：编号、老师、金额、状态；驳回的额外显示原因前 30 字
- 提示文案：「💡 提交评价时若满足积分门槛 + 老师价位 > 0，可勾选申请报销」

### 10.3 明细分页

callback `user:reimburse:list[:page]`，每页 10 条，按 `created_at DESC` 排，显示完整驳回原因。

### 10.4 用户能否取消 pending

**否**。用户无任何取消 / 修改报销的 UI。所有操作权在超管侧。

---

## 十一、驳回与申诉

### 11.1 驳回后用户的可见信息

- 私聊收到「❌ 你的报销申请 #X 未通过」+ 完整原因
- 「🧾 我的报销」中状态变为 ❌ 已驳回，原因永久可见

### 11.2 用户申诉应提供的材料

如用户认为驳回有误，应在客服群组 / 私聊提供：

1. **报销编号 `#X`**（在「我的报销」中可见）
2. **关联评价 / 报告编号**（review_id）
3. **约课截图 + 现场手势照** 原图（原图比 Telegram 压缩后清晰）
4. **与老师的相关聊天记录截图**（如时间确认）
5. **申诉说明**：明确异议点是金额、资格、还是审核误判
6. **预期处理结果**：希望复核 / 补审 / 部分批 / 不接受驳回

### 11.3 运营受理流程建议

1. 在审计日志中按 user_id 查到驳回操作的超管 + 原因
2. 与该超管核对决策依据
3. 如确属误驳：超管可在「⚖️ 手动加扣分」补偿用户积分（视情况），并在 `admin_audit_logs` 留备注；目前代码**不支持**将已 rejected 的记录复原为 pending（一旦驳回即终态）
4. 如属用户理解偏差：耐心解释规则
5. 重要：**不要承诺"下次一定批"**——审批权限在超管，运营人员不可替超管承诺

> **需产品确认：** 是否需要补充"已驳回报销重新审核"功能？目前 rejected 是终态，唯一补救途径是补偿积分。

### 11.4 申诉时限建议

代码无时限。运营建议：申诉应在驳回后 **30 天内**提出，时间越久越难还原决策依据（评价证据照片可能已失效）。

> **需产品确认：** 是否对申诉受理设定明确有效期？

---

## 十二、运营注意事项

### 12.1 与频道公告同步

- 频道公告中提及的"参与条件 / 报销金额 / 周限制 / 月池"必须与后台配置一致
- 后台调整 `reimbursement_min_points` / `reimbursement_monthly_pool` 时应**同步更新公告**
- 不要在公告中承诺代码未实现的功能（如"已驳回可申诉重审"）

### 12.2 月池定期核对

- 月初核对 `reimbursement_monthly_pool` 配置值是否与运营计划一致
- 月中关注「我的报销」总览页显示的「本月已通过总额」，避免月底突然耗尽
- 月池耗尽期间：所有合格报销停留在 pending，**主动通知用户延后审批**

### 12.3 审核前检查清单

超管批准每条报销前应确认：

- [ ] 评价已通过审核（status=approved）
- [ ] 评价证据照片真实有效（约课截图 + 现场手势）
- [ ] 老师 price 字段未被恶意篡改
- [ ] 用户积分余额满足门槛
- [ ] 本周该用户未超额 / 已发 voucher
- [ ] 本月池足够覆盖本次金额
- [ ] 用户未在黑名单 / 异常行为标记

### 12.4 ⛔ 不直接改数据库

资金相关数据严禁直接 UPDATE `reimbursements` 表：
- 会绕过审计
- 会导致 `users.total_points` 与积分流水不一致（如手动改 amount 但不补积分）
- 会丢失 `decided_at` / `decided_by` / `reject_reason` 等关键追溯信息

### 12.5 ⛔ 不绕开 UI 发放

线下转账 / 微信转账 / 红包 等真实权益发放必须**对应** approved 报销记录。运营禁止线下发放但 Bot 中不写记录，会导致：
- 财务对不上
- 月池统计失真
- 用户重复申请同一笔被拒后投诉

### 12.6 备份频率

- `update.sh` 在每次更新前自动备份（含 reimbursements 表）
- 强烈建议另设 crontab 每日 3:30 调用 `scripts/backup.sh` 做 WAL-safe 备份 → 见 [`DEPLOYMENT.md` §14.4](DEPLOYMENT.md)
- 资金相关数据丢失等于真实赔付风险，备份不可省

### 12.7 通知失败

`notified_at` 字段当前**不写入**（`mark_reimbursement_notified` 函数已定义但无调用方）。即所有用户都"显示已通知"。

⚠️ **如果 send_message 失败**（用户屏蔽 bot / 未启动 bot），代码仅记 warning，用户不会收到任何通知，但报销状态已变更。运营建议：

- 用户突然消失（屏蔽 bot）的 pending 报销，运营可主动通过其它渠道告知结果
- 大量批量审批后留意 journalctl 中的「send_message 失败」warning

> **需产品确认：** 是否需要在 send_message 成功后调用 `mark_reimbursement_notified` 以便追溯？目前是死字段。

---

## 十三、报销专用必关频道 / 群组（2026-05 新增）

### 13.1 定位与边界

- **与全局必关订阅独立**：项目原有"必关频道/群组"（`required_subscriptions` 表 + `admin:subreq:*` callback）服务于**写评价入口**校验；本节描述的"报销专用必关"是**独立**配置，**仅影响报销准入**。
- **不强制**：未配置任何报销必关项时，报销流程**不强制订阅检查**，与改造前行为一致。
- **不影响**：用户浏览老师 / 搜索 / 收藏 / 最近看过 / 评价提交主流程（除"勾选申请报销"那一步外）/ 抽奖 / 签到等流程**完全不受影响**。

### 13.2 数据存储

复用 `config` 表，独立 key：

| 配置 key | 值格式 |
| --- | --- |
| `reimbursement_required_chats` | JSON array of `{chat_id, chat_type, display_name, invite_link, enabled}` |

不新增表 / 不新增 schema 迁移。空 key / JSON 解析失败时安全返回空列表（=不拦截）。

### 13.3 后台配置入口

| 路径 | callback | 权限 |
| --- | --- | --- |
| `/admin` → ⚙️ 系统配置 → ⚙️ 系统设置 → 💰 报销必关设置 | `system:reimburse_subreq` | **仅超管** |

子动作：
- `system:reimburse_subreq:add` — 添加（3 步 FSM + 二次确认）
- `system:reimburse_subreq:delete:<idx>` — 删除询问
- `system:reimburse_subreq:confirm_delete:<idx>` — 删除二次确认
- `system:reimburse_subreq:add_confirm` — 添加最终确认

添加流程：输入 `chat_id` → bot 调 `precheck_required_chat` 校验 → 输入展示名（≤60 字符）→ 输入邀请链接（必须 `https://t.me/` 开头）→ 确认页 → 写入 config + `log_admin_audit(action="reimburse_subreq_add")`。

删除流程：列表点击 → 二次确认 → 删除 + `log_admin_audit(action="reimburse_subreq_remove")`。

**所有写操作必须写 `admin_audit_logs`**。

### 13.4 用户准入校验触发点

仅在用户**勾选「✅ 申请报销」**时触发——具体两个 callback：
- `review:reimburse_yes`（`bot/handlers/review_submit.py:cb_review_reimburse_yes`）
- `card:reimburse:yes`（`bot/handlers/review_card.py:cb_card_reimburse_yes`）

判定逻辑：`bot/utils/reimburse_subreq.check_user_subscribed_for_reimburse(bot, user_id)`
- 遍历 `enabled=True` 的项
- 对每项调 `bot.get_chat_member(chat_id, user_id)`
- 已加入判定：`status ∈ {member, administrator, creator}`
- bot API 抛异常的项：跳过 + warning，**不计入** missing（容错与全局 subreq 一致）

### 13.5 用户拦截页

未通过时，把消息 edit 为：

```
💰 报销资格校验

申请报销前，请先加入以下频道 / 群组：
1. 频道 A
2. 群组 B

完成后点击下方按钮重新检查。
```

按钮组（含 `invite_link` 的项渲染 `📢 加入：{display_name}` URL 按钮）：
- `📢 加入：{name}` → URL（用户加入入口）
- `✅ 我已加入，重新检查` → `reimburse:subreq:recheck:<context>`
- `⬅️ 返回` → `reimburse:subreq:back:<context>`（视为"不申请报销"，继续进入评价确认页）

其中 `<context>` 为 `submit`（评价 FSM 主路径）或 `card`（卡片 FSM 路径），保证 recheck/back 回到正确的 FSM 状态。

### 13.6 隔离性保证

| 触发场景 | 是否触发报销 subreq 校验 |
| --- | --- |
| 用户浏览老师 / `teacher:view` | 否 |
| 搜索 / 条件筛选 / 热门 / 今日 | 否 |
| 收藏 / 最近看过 / 我的记录 | 否 |
| 评价提交（不勾选申请报销） | 否 |
| **评价提交（勾选 ✅ 申请报销）** | **是** |
| 抽奖参与 / 开奖 | 否 |
| 签到 | 否 |
| 全局必关订阅检查（写评价入口） | 不变，与本节无关 |

### 13.7 安全 / 兼容性

- 不修改 `compute_reimbursement_amount` / 积分发放 / 抽奖逻辑。
- 不修改 `required_subscriptions` 表与 `subreq_admin.py` handler。
- 不新增 schema migration。
- callback `reimburse:subreq:*` 与既有 `reimburse:enter` / `reimburse:approve:*` / `reimburse:reject:*` / `reimburse:queued:*` / `reimburse:reset:*` 等命名空间独立，不冲突。
- 既有报销审核 / queued 名单 / reset voucher 流程**完全未受影响**。

### 13.8 运营提示

- **空配置时**，旧逻辑保留：所有用户都能继续勾选申请报销。如果运营希望"立刻关闭报销准入要求"，把配置清空即可（删除所有项）。
- **配置错误时**（如 bot 无权访问 chat / chat_id 无效），添加步骤会被 `precheck_required_chat` 拒绝，不会写入 config。
- **bot 失去管理员**时，相关项的 `bot.get_chat_member` 调用可能失败 → 被跳过（按容错策略），导致用户被放行。此时建议配合定期 health check 监控 bot 自身的频道权限状态。

---

## 十四、支付宝口令红包发放流程（2026-05 新增）

### 14.1 总览

报销审核**不再**直接完成——同意报销后必须经过"输入支付宝口令红包口令 → 确认页 → 发送给用户 → 才标记完成"的完整流程。同时报告审核通过创建报销时，会通知所有超管及时审核。

### 14.2 完整时序

```
用户在评价 FSM 中勾选 ✅ 申请报销
  ↓
rreview_admin._do_approve_inner 审核评价通过
  ↓
create_reimbursement(status="pending"|"queued")  ← 老逻辑
  ↓
notify_supers_reimburse_pending(...)             ← 新增：通知所有超管
  ↓
（超管收到 Bot 私聊：💰 有新的报销申请待审核 + 跳转按钮）
  ↓
超管点 reimburse:enter → 进入报销审核
  ↓
超管点详情页 ✅ 同意报销 (reimburse:approve:<id>)
  ↓
admin_reimburse.cb_reimburse_approve：月池 / 周配额 / reset voucher 校验
  ↓
进入 ReimbursePayoutStates.waiting_token
（消息变成：💰 请输入支付宝口令红包口令）
  ↓
超管输入口令 → step_reimburse_payout_token
  - 校验：≥ 4 字符 / ≤ 200 字符 / 非空
  ↓
进入 ReimbursePayoutStates.confirming
（消息变成：💰 确认发送支付宝口令红包 + 完整口令展示）
  ↓
超管选择：
  ✅ 确认发送并完成 → cb_reimburse_payout_confirm
  🔁 重新输入       → cb_reimburse_payout_retry  (回 waiting_token)
  ❌ 取消            → cb_reimburse_payout_cancel (清 FSM，报销保持 pending)
  ↓
确认路径：
  1. safe_send_user_payout(bot, user_id, token, amount)
  2. 成功后才 approve_reimbursement(rid, admin_id)  ← pending → approved
  3. consume reset voucher（如有）
  4. mark_reimbursement_notified(rid)               ← 用 notified_at 记录发送时间
  5. log_admin_audit(action="reimburse_payout_sent", detail={..., token_masked})
  6. state.clear() 清理 FSM（含 token）
  7. 展示完成提示 + 「处理下一条 / 返回审核处理」按钮
```

### 14.3 不改 schema 的关键设计

- 复用既有 `reimbursements.status` 枚举（pending / approved / rejected / cancelled / queued）；不引入 `paid` / `completed` 新值。
- 复用既有 `notified_at` 字段表示"口令已发送"。
- 口令仅在 FSM `state.data` 临时持有，state.clear() 后释放；**不写入数据库**。
- audit log 仅记录 `mask_token(token)` 脱敏值（例如 `AB***GH`），完整口令不入库。

### 14.4 文案与页脚

所有报销相关通知统一带页脚：

```
✳ Powered by @CDCChiYanLog
```

文案集中在 `bot/utils/reimburse_notify.py`，包括：
- `format_supers_pending_text(...)` — 超管收到的待审核通知
- `format_payout_waiting_token_text()` — 等待输入口令的提示
- `format_payout_confirm_text(...)` — 确认页（含完整口令，仅 FSM 期间展示）
- `format_user_payout_message(token, amount)` — 给用户的口令红包消息
- `format_payout_done_text(...)` — 超管收到的完成总结

`POWERED_BY_FOOTER` 常量定义在 `bot/utils/reimburse_notify.py`，避免到处硬编码。

### 14.5 权限边界

| 动作 | 权限 |
| --- | --- |
| 收到"待审核报销"通知 | 所有 super_admin（`list_super_admins()`） |
| 点击 ✅ 同意报销（进入 FSM） | 仅超管 |
| 输入口令 / 重新输入 / 取消 | 仅超管（@_super_admin_required） |
| 确认发送 | 仅超管 |
| 用户接收口令 | 用户本人（只读，不能操作审核） |

普通管理员即便手动构造 callback，也会被 `@_super_admin_required` 装饰器拒绝。

### 14.6 失败 / 取消语义

| 场景 | 行为 |
| --- | --- |
| 给用户 `send_message` 失败 | 报销 **保持 pending**；FSM 状态保留；超管可重试或取消；不写 audit log |
| 用户已屏蔽 bot | 同上（不会"假装完成"）|
| 超管点 ❌ 取消 | FSM 清理；报销保持 pending；audit log 不写 |
| 超管点 🔁 重新输入 | 回到 `waiting_token`，原 token 清掉，需重新输入 |
| `approve_reimbursement` 调用失败（极端） | 仅 logger.warning（用户消息已发出，无法回滚）|

### 14.7 audit log 字段

```
{
    "admin_id": <超管 id>,
    "action": "reimburse_payout_sent",
    "target_type": "reimbursement",
    "target_id": "<reimb_id>",
    "detail": {
        "user_id": <user_id>,
        "amount": <int>,
        "token_masked": "AB***GH",  ← 仅脱敏值
        "reset_consumed": <reset_voucher_id 或 null>
    }
}
```

**完整口令永不出现在 audit log / DB / 日志文件中**。

### 14.8 兼容性保证

- `reimburse:reject:*` / `reimburse:queued:*` / `reimburse:reset:*` / `reimburse:activate:*` 全部 callback 含义不变
- `approve_reimbursement` / `reject_reimbursement` / `consume_reimbursement_reset` / `mark_reimbursement_notified` DB 函数体不变
- `compute_reimbursement_amount` / 积分流水 / 抽奖 / 评价加分逻辑不变
- 报销专用必关订阅 `reimbursement_required_chats` 配置 + gate 不受影响
- 全局必关订阅 `required_subscriptions` 不受影响
- schema_migrations baseline 仍 9 条；MIGRATIONS 仍空

### 14.9 运营注意事项

- **超管私聊 Bot 必须可达**：否则收不到"待审核报销"通知。建议每个 super_admin 至少与 Bot 私聊过一次（不被 Bot 限制）。
- **多超管同时操作**：FSM 是 per-user-state，每个超管有独立 FSM 上下文，互不干扰。但同一报销若被一个超管 approve 后另一个超管再点同意，会得到 alert "已是 approved"。
- **口令重发**：如用户消息丢失（如用户后续屏蔽 bot），audit log 中可见 `token_masked` + 发送时间，但完整口令无法恢复——需运营手动联系。

---

## 十五、报销积分门槛配置（2026-05 新增）

### 15.1 用途

超管可在后台调整"用户申请报销前所需的最低积分门槛"。

- 0 表示**不启用**积分门槛——任意积分都允许申请报销
- 默认值 5（与历史硬编码一致；首次部署 / 配置缺失 / 解析失败均回落 5）
- 上限 `REIMBURSE_MIN_POINTS_MAX = 100`（防止误操作输入过大值）

### 15.2 数据存储

复用既有 `config` 表 key：`reimbursement_min_points`（整数字符串）。
2026-05 起统一通过 `get_reimbursement_min_points()` 读取，避免散落硬编码。

### 15.3 后台入口

| 路径 | callback | 权限 |
| --- | --- | --- |
| `/admin` → ⚙️ 系统配置 → ⚙️ 系统设置 → 🎚 报销门槛设置 | `system:reimburse_min_points` | **仅超管** |

子动作：
- `system:reimburse_min_points:edit` — 进入 FSM 输入新门槛
- `system:reimburse_min_points:confirm` — 二次确认后写 config

修改流程：输入整数 → 校验（≥0, ≤100, 整数）→ 确认页 → 写 config + `log_admin_audit(action="reimburse_min_points_set")`。

### 15.4 生效范围

| 触发点 | 行为 |
| --- | --- |
| `review_submit._enter_reimbursement_step` | 用户勾选申请报销前判断积分；不够则直接跳过报销分支 |
| `review_card._enter_reimbursement_step` | 同上 |
| `rreview_admin._do_approve_inner` | 评价审核通过、创建 reimbursement 前再判一次（防止用户在审核期间扣分了） |

**门槛只影响"申请报销"分支**：用户提交评价本身不受影响（评价仍可提交，只是不能附带报销请求）。

### 15.5 门槛 = 0 的行为

代码用 `min_pts == 0 or effective_pts >= min_pts` 形式判定。0 时跳过积分检查，**任何积分**的用户都允许申请报销。

---

## 十六、本月报销池手动重置（2026-05 新增）

### 16.1 用途

超管可手动重置"本月报销池已使用额度"的计算基线，用于：
- 月内追加预算
- 月内重新分配预算
- 月内做活动消耗后想"清零开始"
- 不需要等到下个月自动重置

### 16.2 关键设计原则

- **不删除**历史 reimbursements 记录
- **不修改**任何报销 status（`approved` / `pending` / `queued` / `rejected` / `cancelled` 都保持原样）
- **不清空**notified_at / decided_at 等任何字段
- **通过 baseline 间接重置**：当月已使用额度的计算 = `max(0, raw_used - reset_baseline)`
- **本月范围**：只影响当前 month_key；下个月不受影响

### 16.3 数据存储

新 config key：`reimbursement_monthly_pool_reset_baselines`，值是 JSON object：

```json
{
  "2026-05": {
    "baseline_amount": 1200,
    "reset_at": "2026-05-19 12:00:00",
    "admin_id": 123456789,
    "reason": "本月活动追加预算，重置报销池"
  }
}
```

每个月份独立一项；下月用 `month_key=2026-06` 自动建独立条目，旧月份不受新月份操作影响。

### 16.4 唯一 effective_used 口径

DB 层提供 **`get_reimbursement_monthly_pool_usage(month_key) -> dict`**：

```python
{
    "raw_used": <SUM(amount) for approved>,      # 直接 SQL 查询
    "reset_baseline": <config baseline 或 0>,     # 从 reset baselines dict
    "effective_used": max(0, raw_used - baseline)  # 唯一审批 / 状态页口径
}
```

**审批月池校验** ([admin_reimburse.cb_reimburse_approve](../bot/handlers/admin_reimburse.py)) 与 **报销池状态页** ([reimbursement_pool.get_reimbursement_pool_stats](../bot/services/reimbursement_pool.py)) **必须使用同一个 helper**，避免口径漂移。

### 16.5 后台入口

| 路径 | callback | 权限 |
| --- | --- | --- |
| `/admin` → ⚙️ 系统配置 → ⚙️ 系统设置 → 🔄 重置本月报销池 | `system:reimburse_pool_reset` | **仅超管** |

子动作：
- `system:reimburse_pool_reset` — 入口，展示当前 raw / baseline / effective 用量 + 提示输入原因
- `system:reimburse_pool_reset:confirm` — 二次确认后写 config + audit

### 16.6 完整流程

1. 超管点 🔄 重置本月报销池
2. Bot 展示当前 month_key / 月度池 / raw_used / 现有 baseline / effective_used / remaining
3. Bot 提示输入重置原因（必填，≤200 字符）
4. 超管输入原因
5. Bot 展示最终确认页（月份 / baseline 值 / 原因）
6. 超管点 ✅ 确认重置
7. 写入 config + `log_admin_audit(action="reimburse_pool_reset")`
8. 展示完成提示 + 「💰 返回报销池设置 / 📊 查看报销池状态 / ⬅️ 返回系统设置」

### 16.7 audit log 字段

```
{
    "admin_id": <超管 id>,
    "action": "reimburse_pool_reset",
    "target_type": "config",
    "target_id": "reimbursement_monthly_pool_reset_baselines",
    "detail": {
        "month_key": "2026-05",
        "baseline_amount": 1200,
        "prev_effective_used": 1200,
        "reason": "本月活动追加预算",
        "reset_at": "2026-05-19 12:00:00"
    }
}
```

### 16.8 重置场景示例

| 时间点 | 操作 | raw_used | baseline | effective_used |
| --- | --- | --- | --- | --- |
| 月初 | 无 | 0 | 0 | 0 |
| 月中（积累了几次审批） | — | 1200 | 0 | 1200 |
| **超管重置** | reset baseline=1200 | 1200 | 1200 | 0 |
| 重置后再批准 500 | — | 1700 | 1200 | 500 |
| 月末 | — | 1700 | 1200 | 500 |
| 下月初（自动换 month_key） | — | 0 | 0 | 0 |

`reimbursement_monthly_pool` 上限校验在 `cb_reimburse_approve` 中始终用 `effective_used + new_amount > pool` 判断——这意味着：
- raw_used 已超过 pool，但 effective_used + new_amount ≤ pool → **允许批准**
- effective_used + new_amount > pool → **拒绝批准**

### 16.9 兼容性保证

- 不修改 `reimbursements` 表 schema / 任何字段
- 不修改 `compute_reimbursement_amount`
- 不修改支付宝口令红包发放流程（`reimburse:payout:*` 全部 callback / audit / mask 都未变）
- 不修改报销专用必关订阅（`reimbursement_required_chats` config）
- 不修改全局必关订阅（`required_subscriptions` 表）
- 不修改积分流水 / 抽奖 / 评价加分逻辑
- `SCHEMA_MIGRATIONS_BASELINE` 仍 9 条；`MIGRATIONS` 仍空

### 16.10 运营注意事项

- **必须填写原因**：审计可追溯，禁止无原因重置
- **重置只针对当前月份**：如果运营想"重置上个月"基本无意义（下月已经自动切换 month_key）
- **多次重置**：可叠加——每次重置都把当时的 raw_used 设为新 baseline；常见场景是同一个月内多次"清零"
- **想取消重置**：可通过 `set_config("reimbursement_monthly_pool_reset_baselines", "{}")` 清空，或手动改 JSON 删除某月份。但建议保留审计记录，让 baseline 留下；下月自然失效

---

## 十七、报销规则只读总览（2026-05 新增，Sprint 3 §5.2.1）

### 17.1 用途

为超管提供 **一页式只读** 报销规则总览，无需在多个编辑面板间切换或翻 POLICY 文档。展示口径与本文档 Part II §6 / §7 / §15 / §16 / §13 完全一致；服务函数 `services/reimbursement_rules.py::get_reimbursement_rules_snapshot()` 是唯一聚合口径，避免漂移。

### 17.2 展示字段

| 段落 | 字段 | 来源 |
| --- | --- | --- |
| 功能开关 | feature_enabled (开 / 关 / N/A) | `config.reimbursement_feature_enabled` |
| 月度报销池 | monthly_pool + 本月 reset baseline | `config.reimbursement_monthly_pool` + `reimbursement_monthly_pool_reset_baselines` |
| 积分门槛 | min_points + 默认 5 + 上限 100 | `config.reimbursement_min_points` |
| 每周限制 | 1 次/周 approved（硬编码） | `WEEKLY_APPROVED_LIMIT = 1` |
| reset voucher | "一次性跳过本周校验" 说明 | 硬编码文案，与 §6.2 一致 |
| queued 名单模式 | 触发条件 + 当前队列长度 | `feature_enabled` + `count_queued_reimbursements()` |
| 必关频道/群组 | 总数 + 启用数 | `get_reimburse_required_chats()` |

### 17.3 后台入口

| 路径 | callback | 权限 |
| --- | --- | --- |
| `/admin` → ⚙️ 系统配置 → 💰 报销配置 → 📜 完整规则一览（只读） | `admin:reimburse_rules` | **仅超管** |

子动作：
- `admin:reimburse_rules` — 入口
- `admin:reimburse_rules:refresh` — 刷新当前 snapshot

### 17.4 边界

- **严格只读**：本页**不**提供任何编辑入口；编辑请用 `admin:reimburse_config` 聚合页里的 5 个 `system:reimburse_*` 入口
- **不写表 / 不写 audit log**：纯展示
- **N/A 容错**：任一字段查询失败 → 显式 N/A，不影响其它字段

### 17.5 公告草稿生成（Sprint 3 §5.2.3）

只读规则页含「📢 复制公告草稿」按钮，callback `admin:reimburse_announce`：

- **生成**：基于当前 `ReimbursementRulesSnapshot` 渲染面向**用户**的纯文本公告（无技术字段如 `month_key` / `week_key`）
- **三态标题**：
  - `feature_enabled=True` → 「【报销规则公告】YYYY-MM-DD」+ 开放语气
  - `feature_enabled=False` → 「【报销暂未开放】YYYY-MM-DD」+ 队列说明
  - `feature_enabled=None` → 「【报销规则公告 · 配置异常】」+ "不应直接发布" 警告
- **送达方式**：Bot 发**新消息**含 `<pre>` HTML 包裹（与 Sprint 2 §4.2.3 抽奖对账复制汇总同模式），Telegram 客户端长按消息体可全文复制
- **不自动发布**：纯文本生成在 Bot 与超管私聊；运营手动复制后自行决定发往何处
- **不调用 broadcast / 不写磁盘 / 不导出文件**

实现：`services/reimbursement_rules.py::render_reimbursement_announcement_draft` + `wrap_announcement_html`；`handlers/admin_panel.py::cb_admin_reimburse_announce`。

---

# Part III：抽奖规则

## 一、抽奖系统定位

抽奖系统用于**运营活动**，由超级管理员创建、配置与开奖。

⚠️ **抽奖不保证所有用户均可参与。** 参与资格由后台配置（必关频道、积分门槛）和单次活动公告决定，超管完全控制下列字段：

- 谁能看到（频道发布范围）
- 谁能进入（必关频道、积分门槛、按键/口令）
- 中几个（`prize_count`）
- 何时开奖（`draw_at`，定时任务自动执行）

⚠️ **抽奖涉及公平性承诺**。开奖结果一旦写入数据库（status = `drawn`）即为终态，**不可重抽**。运营人员应：

- 不擅自承诺中奖结果
- 不公开未开奖时的参与名单（详情页可看，但不要外传）
- 公告中的奖品 / 人数 / 开奖时间应与后台配置一致
- 中奖名单一律以频道追发的开奖结果为准

---

## 二、抽奖创建字段

抽奖记录存储在 `lotteries` 表，由超管「🎲 抽奖管理」→「➕ 创建新抽奖」10 步 FSM 录入。

| 字段 | 类型 | 含义 / 取值范围 |
|---|---|---|
| `name` | TEXT, 1-30 字 | 抽奖名称（必填） |
| `description` | TEXT, 1-500 字 | 活动规则 / 备注（必填） |
| `cover_file_id` | TEXT, 可选 | Telegram 图片 file_id（封面图，可跳过） |
| `entry_method` | TEXT | `button` = 按键抽奖 / `code` = 口令抽奖（必填） |
| `entry_code` | TEXT, ≤ 20 字 | 口令字符串，**仅 `code` 方式必填，全局唯一**（active 状态下大小写不敏感唯一） |
| `prize_count` | INTEGER, 1-1000 | 中奖人数（CHECK 约束） |
| `prize_description` | TEXT, 1-100 字 | 奖品文字描述（必填） |
| `required_chat_ids` | JSON list | 必关频道/群组 chat_id 列表，**至少 1 项**（创建时强制） |
| `entry_cost_points` | INTEGER, 0-1000000 | 参与所需积分；0 = 免费（CHECK 约束） |
| `publish_at` | TEXT | 发布时间 `YYYY-MM-DD HH:MM:SS`（必填） |
| `draw_at` | TEXT | 开奖时间 `YYYY-MM-DD HH:MM:SS`，必须晚于 `publish_at` |
| `status` | TEXT | 见 [§三 抽奖状态](#三抽奖状态) |
| `created_by` | INTEGER | 创建超管的 Telegram ID |

附带的运行时字段（系统自动写入）：

| 字段 | 含义 |
|---|---|
| `published_at` | 实际发布到频道的时间戳 |
| `drawn_at` | 实际开奖（或 no_entries 关闭）的时间戳 |
| `channel_chat_id` / `channel_msg_id` | 频道抽奖帖坐标，用于刷新按钮 / 追发结果 |
| `result_msg_id` | 开奖结果消息 ID |

⚠️ **时区：** `publish_at` / `draw_at` 按 `config.timezone` 解析；默认是亚洲/上海。请勿手动写库时混入 UTC 字符串。

---

## 三、抽奖状态

抽奖状态机由 `lotteries.status` 字段表达（CHECK 约束的合法取值）：

| status | 中文 | 含义 | 可参与 |
|---|---|---|---|
| `draft` | 📝 草稿 | 已保存但未发布到频道 | ❌ |
| `scheduled` | ⏰ 已计划 | 已注册定时发布任务，等待 `publish_at` 到达 | ❌ |
| `active` | 🎯 进行中 | 已发布到频道，开奖前可被用户进入 | ✅ |
| `drawn` | 🏆 已开奖 | 终态：已完成抽签 + 频道追发 | ❌ |
| `cancelled` | ❌ 已取消 | 终态：超管主动取消 | ❌ |
| `no_entries` | ⚪ 无人参与 | 终态：到 `draw_at` 时 0 人参与，自动关闭 | ❌ |

**终态：** `drawn` / `cancelled` / `no_entries` 不可再变更（代码层面 `LOTTERY_TERMINAL_STATUSES`）。`cancel_lottery` 也只接受 `draft` / `scheduled` / `active`。

状态迁移路径：

```
draft ──(立即发布)──> active ──(开奖时有人)──> drawn
   │                       │                  │
   └──(定时发布)──> scheduled ──(开奖时无人)──> no_entries
                                              
任意非终态 ──(超管取消)──> cancelled
```

---

## 四、参与方式

`entry_method` 字段决定用户如何参与（创建时二选一，**不可后续修改**）。

### 4.1 按键抽奖（`button`）

- 频道帖底部出现 [🎲 参与抽奖] 按钮
- 按钮 URL 是 deep link：`https://t.me/<bot_username>?start=lottery_<id>`
- 用户点击 → 跳转到 bot 私聊 → 发 `/start lottery_<id>`
- bot 在 `start_router` 解析参数后调用 `start_lottery_from_deep_link`

### 4.2 口令抽奖（`code`）

- 频道帖**不显示**参与按钮（只显示「N 人已参与」计数）
- 文案提示用户「在私聊给我发送口令：XXX」
- 用户私聊任意文字命中 `entry_code`（大小写不敏感）即视为参与
- 监听 handler 在 `lottery_entry.on_private_text_maybe_code`：
  - 仅在用户**不在任何 FSM 状态**时尝试匹配
  - `/` 开头的命令不当口令
  - 字符长度 > 20 直接跳过
  - 未匹配 → 静默放行，留给其它路由

⚠️ 口令全局唯一仅对 `active` 状态校验。理论上 `drawn` / `cancelled` 历史口令释放后，新抽奖可以复用同样口令字符串；但**强烈不建议**：会让历史用户误以为旧活动重启。

---

## 五、参与条件

用户成功进入抽奖的统一校验链（`try_enter_lottery`，按顺序）：

| 顺序 | 检查 | 失败结果 |
|---|---|---|
| 1 | `status == 'active'` | `not_active` |
| 2 | 当前时间在 `[publish_at, draw_at)` 区间内 | `time_window`（"未到发布时间" 或 "抽奖已结束"） |
| 3 | 用户未参与过该抽奖（`get_lottery_entry`） | `already_entered` |
| 4 | 加入了**全部** `required_chat_ids`（status ∈ member/administrator/creator） | `need_subscribe`（附 missing chat 链接） |
| 5 | `total_points >= entry_cost_points` | `need_points`（附差额提示） |
| 6 | `create_lottery_entry`（UNIQUE 约束保护并发） | `already_entered`（并发冲突） |
| 7 | 扣分（仅 cost > 0） | 写 warning，不回滚 entry |

注意点：

- **必关频道判定**：`bot.get_chat_member` 异常（bot 不在群、群已删等）**视为静默通过**（不计入 missing）。该容错是 spec §9 明确要求的，避免单点故障拒掉所有人。
- **用户必须已经启动 bot**：deep link 模式下 `/start lottery_<id>` 即为启动；口令模式下用户必须先与 bot 有过私聊（否则 bot 无法收到口令消息）。
- **重复参与硬阻塞**：`UNIQUE(lottery_id, user_id)` 是 DB 级约束，无法绕过。

---

## 六、积分门票

### 6.1 字段

`entry_cost_points` 表示参与一次抽奖扣除的积分（INTEGER，0-1000000）。

- **0 = 免费**（不写入扣分流水）
- **> 0** = 进入抽奖时扣 `entry_cost_points` 积分

### 6.2 扣分时机

代码顺序（`lottery_entry.try_enter_lottery`）：

1. **预校验**：参与前检查 `total_points >= entry_cost_points`，余额不足直接 `need_points` 拒绝
2. **创建 entry**：先 `INSERT INTO lottery_entries`
3. **扣分**：之后才 `add_point_transaction(delta=-cost, reason='lottery_entry', related_id=lid, note=name)`
4. **operator_id = NULL**（系统自动扣）

⚠️ **扣分与 entry 写入不是原子操作。** 若 step 3 失败（DB 异常等），entry 已写入但积分未扣；代码仅写 warning 日志，**不回滚 entry**。出现此情况时该用户会"白嫖"一次参与。

> **需产品确认**：扣分失败时是否需要回滚 entry / 由超管人工核对补扣？目前依赖运营事后对账。

### 6.3 余额不足

预校验阶段就阻断 —— 不创建 entry，不扣分。提示文字包含「参与需要 / 你的余额 / 还差 X 积分」，附 [💰 查看我的积分] 按钮跳转 `user:points`。

### 6.4 退款（仅取消时）

仅当超管取消处于 `active` 状态、`entry_cost_points > 0` 且有参与者的抽奖时，会出现「取消并退积分」选项：

- 对**每一位**参与者退还**完整 `entry_cost_points`**
- `reason = 'lottery_refund'`，`operator_id = 操作超管 id`，`note = 抽奖名`
- 写入 `admin_audit_logs`，action = `lottery_refund`
- 含 `entries / refunded / total_amount` 等明细
- **不**判断该用户当时是否实际扣分成功；统一按 `cost × entry_count` 退

⚠️ 这意味着：若 [§6.2](#62-扣分时机) 描述的扣分失败用户存在，他们仍会获得退款 = 净赚 `cost` 积分。运营如发现明显异常，**先对账再点退款**。

---

## 七、定时任务

`bot/scheduler/lottery_tasks.py` 用 APScheduler 注册两类 job：

| job_id | 触发时间 | 行为 |
|---|---|---|
| `lottery_pub_<lid>` | `publish_at` | 调 `publish_lottery_to_channel`，发抽奖帖到频道，status `scheduled` → `active` |
| `lottery_draw_<lid>` | `draw_at` | 调 `run_lottery_draw`，从 entries 抽 winners、发结果、私聊通知 |

### 7.1 注册时机

- **立即发布** (`publish_mode='immediate'`)：保存为 `draft` 后立即调 `publish_lottery_to_channel`；开奖任务正常注册。
- **定时发布** (`publish_mode='scheduled'`)：保存为 `scheduled` + 注册 `lottery_pub_<lid>` + `lottery_draw_<lid>` 两个 job。
- **draw_at 编辑**（仅 active）：先 `unschedule_lottery` 再 `schedule_lottery_draw` 重注册（job id 相同，`replace_existing=True`）。
- **取消抽奖**：`unschedule_lottery` 清掉两个 job。

### 7.2 bot 重启恢复

`bot.main` 启动钩子调用 `schedule_pending_lotteries`，扫描所有 `status IN ('scheduled', 'active')` 抽奖：

- `scheduled` → 重注册发布任务 + 开奖任务
- `active` → **只**重注册开奖任务（已发布，不能再次发布）

如果 bot 停机期间 `publish_at` / `draw_at` 已过，`run_date` 会被强制改为 `now`，配合 `misfire_grace_time=3600`（1 小时）补发。**超过 1 小时的错过仍会补**，因为代码用的是"如果过期则立即跑"，不是依赖 misfire grace。

⚠️ **DB 备份 vs APScheduler 状态：** APScheduler job 状态默认是**内存**的（无 jobstore 持久化）。重启后唯一恢复路径是 `schedule_pending_lotteries`。如果该函数报错（log warning `不阻断启动`），定时任务**全部丢失**直到下次重启或手动重发。

> **需产品确认**：是否需要为 APScheduler 配 SQLAlchemyJobStore，避免重启依赖应用层扫描？

---

## 八、中奖逻辑

`bot/utils/lottery_draw.py` 中的 `run_lottery_draw` 在 `draw_at` 触发时执行。

### 8.1 抽取算法

```python
rng = secrets.SystemRandom()  # CSPRNG，/dev/urandom
winners = rng.sample(entries, min(prize_count, len(entries)))
```

- 用 `secrets.SystemRandom`（密码学安全随机数发生器）等概率抽取
- 失败时回退到 `random.SystemRandom`（同样 CSPRNG）
- 两个都失败时取前 N 个（极端兜底；代码标注"不应发生"）
- 每个 entry **等权重**，无加权
- **不允许重复抽中**（`sample` 是无重复采样）

### 8.2 prize_count 越界

- `len(entries) < prize_count` → 全部参与者中奖（不报错、不补足）
- `len(entries) == 0` → 走 [§8.4 无人参与](#84-无人参与)

### 8.3 标记顺序与并发防重

代码顺序：

1. 取 entries（按 id 排序，仅供后续核对，CSPRNG 不依赖顺序）
2. 抽 winners → `mark_lottery_entries_won` 设 `won=1`
3. `mark_lottery_drawn`：status `active` → `drawn`（仅 `active` 状态生效，**防并发重抽**）
4. 频道追发结果消息 → 拿到 `result_msg_id` → `update_lottery_result_msg`
5. 私聊通知每个 winner

**并发场景：** 若 step 3 失败（另一进程已 drawn），刚才的 `won=1` 标记保留作历史，仅 log warning。运营如需复核，对照 `lottery_entries.won` 与 `lottery_result_msg_id` 即可判定真实开奖。

### 8.4 无人参与

`total_entries == 0` 时：

- status `active` → `no_entries`（终态）
- 频道追发「⚠️ 「XXX」本次抽奖无人参与，已自动结束」
- **不**私聊任何用户（无对象）

### 8.5 抽奖跳过（防重）

`status != 'active'` 时 `run_lottery_draw` 直接返回 `skipped=True`：

- 已 `drawn` / `cancelled` / `no_entries`：silent skip
- 还在 `draft` / `scheduled`：理论上不该到这里（定时任务应在 publish 之后才会 fire），但代码做了兜底

---

## 九、用户通知与领奖

### 9.1 参与成功通知

用户成功进入抽奖后，bot **立即**在私聊回复：

```
✅ 你已参与「<name>」抽奖

💰 已扣除：<cost> 积分        ← 仅 cost > 0 时
开奖时间：<draw_at>
请耐心等待，中奖会私聊通知。
```

### 9.2 失败原因提示

按 [§五 参与条件](#五参与条件) 中的 status 给不同提示：

- `not_active`：「⚠️ 抽奖「X」当前状态为 Y，无法参与」
- `time_window`：「⚠️ 「X」未到发布时间」/「⚠️ 「X」抽奖已结束」
- `already_entered`：「⚠️ 你已参与「X」，每人仅可参与 1 次」
- `need_subscribe`：列出未关注的频道 + 跳转按钮（@username 可点；纯 chat_id 只显示提示）
- `need_points`：差额提示 + [💰 查看我的积分] 按钮

### 9.3 中奖通知（私聊）

`_notify_one_winner` 给每个 winner 发：

```
🎉 恭喜你中奖了！

活动：<name>
奖品：<prize_description>

请于 7 日内点击下方按钮联系管理员领取奖品。
```

按钮区：

- 若已配置 `lottery_contact_url` config（超管在「👨‍💼 抽奖客服链接」设置）→ 显示 [👨‍💼 联系管理员] 按钮，URL 跳转配置值
- 若未配置 → 无按钮，文案改为「请于 7 日内联系频道管理员领取奖品」

通知失败（用户拉黑 bot / Forbidden / BadRequest）→ log warning 跳过；**不重试**。`lottery_entries.notified_at` 字段仅在成功时写入，运营可据此识别未送达用户。

⚠️ **「7 日内领取」是中奖通知 + 频道结果追发的硬编码文案**（`_notify_one_winner` / `render_lottery_result_text`）。代码**没有自动过期处理**，超过 7 日仍可线下补发；这只是**文案**而非系统约束。

### 9.4 未中奖通知

代码**不**通知未中奖者。未中奖用户可以通过开奖后频道追发的结果消息看到名单（半匿名形式：`X* (****1234)`）。

> **需产品确认**：是否需要给未中奖者发"很遗憾"私聊？目前无此功能。

### 9.5 频道结果追发

`_try_publish_result` 在频道 reply 到原抽奖帖：

```
🏆 <name> 开奖结果

恭喜以下 N 位中奖者：

1. X* (****1234)
2. Y* (****5678)
…

📦 奖品：<prize_description>
请中奖者于 7 日内在私聊联系管理员领取。

✳ Powered by @<bot_username>
```

半匿名规则：first_name 首字 + uid 后 4 位。如用户未设 first_name → 显示 `匿`；uid 长度 ≤ 4 → 显示 `(****)`。

如果频道发送失败（`channel_chat_id` 失效、bot 被踢等），仅 log warning 不抛错；`result_msg_id` 留空，但开奖状态已写入 DB。**运营需手动 reply 一份结果到频道**。

---

## 十、异常处理

### 10.1 重复参与

- `UNIQUE(lottery_id, user_id)` DB 约束阻断
- 并发场景（同一用户同一抽奖几乎同时两次点击）→ 第二次返回 `already_entered`，**不扣分**

### 10.2 扣分失败

参见 [§6.2](#62-扣分时机)。entry 已创建但扣分失败时**不回滚**。运营建议：

- 定期对账：把 `lottery_entries` 中的 entries 与 `point_transactions` 中的 `lottery_entry` 流水按 `(lottery_id, user_id)` 对照
- 发现差异由超管人工补扣，原因填「系统修正 lid=X 漏扣」

#### 10.2.1 对账口径（Sprint 2 §4.2.1，2026-05）

仅对 `lotteries.entry_cost_points > 0` 且 `status != 'draft'` 的活动对账：

| 指标 | SQL 口径 |
|---|---|
| 期望扣分 | `entry_count × entry_cost_points`，其中 `entry_count = COUNT(lottery_entries WHERE lottery_id=L)` |
| 实际扣分 | `-SUM(delta)` FROM `point_transactions` WHERE `reason='lottery_entry' AND related_id=L`（delta 为负，取负号变正） |
| 退款 | `SUM(delta)` FROM `point_transactions` WHERE `reason='lottery_refund' AND related_id=L`（delta 为正） |
| 净扣分 | `实际扣分 - 退款` |
| 差异 | `期望扣分 - 净扣分`，>0 少扣（漏扣 / 退款过多）；<0 多扣（重复扣 / 误扣）；=0 平账 |

`entry_cost_points = 0`（免费活动）或 `status='draft'` 跳过对账。
`status='cancelled'` 仍计入（验证取消退款是否完整）。

#### 10.2.2 异常分类

| 代号 | 名称 | 检测口径 |
|---|---|---|
| A | 有 entry 无扣分 | `lottery_entries` 有 `(uid, L)`，`point_transactions` 无 `(uid, 'lottery_entry', L)` |
| B | 有扣分无 entry | `point_transactions` 有 `(uid, 'lottery_entry', L)`，`lottery_entries` 无 `(uid, L)` |
| C | 双向缺失 | SQL 视角不可能出现（两边都无记录就不在比对域），常量 0，不展示 |
| D | 重复扣分 | 同 `(uid, L)` 在 `point_transactions` 'lottery_entry' 出现 ≥ 2 次 |

异常人数 = `|A ∪ B ∪ D|` distinct user_id。

#### 10.2.3 后台入口（仅超管）

`📊 运营看板 → 📊 抽奖对账`（callback `admin:lottery_reconcile`）：

- **列表页**：展示积分门票活动数 / 有差异活动数 / 最近活动对账概览（每条带 ✅ 平账 或 ⚠️ 差异/异常 标记）
- **单活动详情页**：8 项完整指标（期望 / 实际 / 退款 / 净扣 / 差异 / A / B / D / 异常人数）。每个详情页都含「📋 复制汇总」按钮（§4.2.3）；**当 anomaly_users > 0 时**额外含「📋 异常用户列表 (N)」按钮（§4.2.2）。
- **异常用户列表页**（§4.2.2，callback `admin:lottery_reconcile:anomaly:<lid>:<page>`）：按 D → B → A 顺序分组展示，每 20 人一页；含上/下页 + 刷新 + 返回详情。每条异常带具体引用：A 类显示 `entry_id`；B 类显示 `tx_id` + 扣分；D 类显示 `entry_id`（或「无 entry」）+ `tx_ids` 列表 + 共扣金额。
- **复制汇总**（§4.2.3，callback `admin:lottery_reconcile:copy:<lid>`）：点击后 Bot 发**新消息**，内容是 `<pre>` 包裹的纯文本对账汇总（无 emoji，pipe 分隔的紧凑结构，含结论标签 BALANCED / DIVERGENT(...)），Telegram 客户端长按消息体即可全文复制。**不导出文件**：不生成 csv / xlsx / 不写入磁盘，只发 Telegram 消息。

**严格只读**：不导出文件、不提供"一键补偿/修复"按钮。Sprint 2 §4.2 共三项全部落地。

**异常归类去重**：同 uid 在多类时按 **D > B > A** 优先级归到最高一类。A 与 D / B 必然不相交（A 要求 0 条 tx）；B ∩ D（无 entry 且 ≥2 条 tx）归 D，渲染时显式标注「无 entry」以与 D∩A 区分。

实现：`bot/services/lottery_reconcile.py` / `bot/keyboards/admin_kb.py` / `bot/handlers/admin_panel.py`。

### 10.3 用户未满足必关频道

- 拒绝参与，附 missing 频道列表
- **不**自动续期：用户加入频道后必须**重新点参与按钮**或重新发口令
- bot.get_chat_member 异常（bot 不在群）→ **视为通过**（容错），不会因运维问题阻断所有用户

### 10.4 无人参与

到 `draw_at` 时 0 人 → 自动进入 `no_entries` 终态，频道追发提示。

### 10.5 定时任务重启恢复

参见 [§7.2](#72-bot-重启恢复)。失败时 `schedule_pending_lotteries` log warning **不阻断启动**，定时任务可能丢失。建议运营在每次 bot 重启后检查所有 `scheduled` / `active` 抽奖是否仍有 APScheduler job。

### 10.6 抽奖取消（含 active）

`draft` / `scheduled` / `active` 均可取消（终态除外）：

- **draft / scheduled / cost=0 / 0 entries**：单确认按钮，直接 status → `cancelled`
- **active + cost > 0 + entries > 0**：二选一确认（取消并退积分 / 取消不退）
- 不论选项，定时任务都会被 `unschedule_lottery` 清掉
- 写入 `admin_audit_logs`，action = `lottery_cancel`（含 `refund / refunded / cost`）

⚠️ 取消后**不可恢复**（终态），但记录保留（参与人员可继续查看）。

### 10.7 中奖后用户不可达

- 私聊通知 `TelegramForbiddenError` / `TelegramBadRequest` → 跳过 + log
- `lottery_entries.notified_at` 留空（运营可据此识别）
- **代码不重试**

运营应：
- 定期查 `lottery_entries WHERE won=1 AND notified_at IS NULL`
- 通过其它渠道（用户名 → Telegram 搜索 / 频道管理员告知 / 公告寻人）线下联系

### 10.8 重发抽奖帖（仅 active）

若原帖在频道被删 / channel_chat_id 改了 / msg_id 失效：

- 超管「[🔄 重发抽奖帖]」可临时把 status 改回 `draft` → 调 `publish_lottery_to_channel` → status 回 `active`
- **不会**删除可能仍存在的旧帖
- **会**覆盖 `channel_msg_id`（旧 msg_id 丢失，按钮刷新会落到新帖上）
- 适用场景：频道清理误删、bot 临时失权后重得权

### 10.9 active 抽奖编辑

`status='active'` 时可编辑以下字段（`_EDITABLE_FIELDS`）：

- `name` / `description` / `prize_description`（≤ 30 / 500 / 100 字）
- `prize_count`（1-1000）
- `entry_cost_points`（0-1000000）
- `required_chat_ids`（chat_id 列表，bot 必须已加入）
- `draw_at`（必须晚于现在）

**不可编辑：** 封面图 / 参与方式 / 口令。如需大改建议新建抽奖。

编辑 `draw_at` 会触发 `reschedule draw`；其它字段会触发频道帖 caption 刷新。每次编辑都写 `admin_audit_logs`，action = `lottery_edit`，detail 含 `field / old / new`。

⚠️ **编辑 `entry_cost_points` 不影响已参与用户**：已扣的不会找补，新参与按新值扣。如运营在 active 期间提高 cost 或降低 cost，请同步发布频道公告说明。

---

## 十一、运营注意事项

### 11.1 创建前

- **频道发布目标**：必须先在「📢 频道设置」配置 `publish_channel_id`，否则发布会失败（`no_channel` 错误）
- **必关频道 bot 必须在场**：创建 FSM 的 Step 7 会逐个 `precheck_required_chat` 校验 bot 是否已加入；失败的 chat_id 不允许添加
- **奖品 / 人数 / 时间** 必须与对外公告一致

### 11.2 创建中

- **`entry_cost_points` 提前公告**：积分扣减活动应在频道公告中明示"参与需要 X 积分"，避免用户开抢瞬间发现扣分起争议
- **`draw_at` 留余量**：开奖时刻是定时任务触发的，不是按下按钮的时刻。如希望"晚上 8 点准时开奖"，建议设置为 19:59 留 1 分钟给定时器排队
- **publish_at 立即 / 定时** 一旦保存后不可改（只能取消重建）

### 11.3 发布后

- **不要直接改数据库**：参与计数、状态机、扣分流水都通过 UI 走，DB 直改会破坏一致性
- **抽奖结果应保留记录**：开奖后频道追发消息建议**置顶 / 截图存档**，特别是涉及金额 / 实物奖品的活动
- **重发慎用**：会让频道出现两条帖；只在原帖确实失效（被删 / 不可见）时用

### 11.4 资金 / 实物奖品

- **客服链接** (`lottery_contact_url`) 应指向真实有人值守的账号 / 群
- **领奖时限 7 日是文案约束**，运营可酌情延长但应公告
- **大额奖品** 建议在审批流程外加二次确认（截图 / 客服核对）

### 11.5 备份

- 每次 cancel / 重大编辑前**手动备份 DB**（`sqlite3 .backup`）
- 抽奖中奖名单 `lottery_entries WHERE won=1` 是不可重建的历史，**特别注意保护**

### 11.6 公平性承诺

⚠️ **运营对外不应承诺**：

- "100% 中奖"（除非 prize_count ≥ entries 已能确认）
- 提前公布中奖结果（开奖前任何 leak 都会引发争议，即便后台可看）
- 修改已 drawn 的结果（终态不可逆，承诺也无法兑现）

---

## 十二、用户申诉建议

用户对抽奖参与 / 中奖有异议时，应在群组 / 私聊中**提供以下材料**：

1. **Telegram 用户 ID 或 @username**（user_id 优先）
2. **抽奖编号 lottery_id**（在抽奖参与确认消息中 / 频道帖 deep link）
3. **争议类型**：
   - 没扣分但提示"已参与" → 提供参与确认截图 + 当时余额截图
   - 扣分了但提示"未参与" → 提供扣分流水截图 + 期望参与时间
   - 中奖但没通知 → 提供 user_id + lottery_id
   - 未中奖质疑公平性 → 提供 user_id + lottery_id（运营可在 admin_audit_logs 中核对开奖时间与算法日志）
4. **截图**：抽奖帖 / 参与确认 / 积分明细 / 中奖通知 等
5. **时间窗**：申诉应**及时**提出。开奖后超过 7 日的中奖申诉，可能因领奖时限文案而被驳回（但代码无强制）

运营在「[👥 查看参与人员]」+「积分明细」+「审计日志」中查询 `lottery_id` / `user_id` 即可还原全部历史。

> **需产品确认**：是否对申诉受理设定有效期？目前代码无时限。

---

## 附录：相关文档

- 部署与备份：[`DEPLOYMENT.md`](DEPLOYMENT.md)
- 值守手册：[`RUNBOOK.md`](RUNBOOK.md)
