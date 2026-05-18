# 积分规则说明

> 本文档面向运营人员、管理员与超管。内容根据当前代码（截至 2026-05-18）整理。所有规则以代码实际行为为准；模糊或未明确处标注 **"需产品确认"**。

---

## 一、积分系统定位

积分是 Bot 平台内部的**用户权益记录**，用于：

- 作为活动 / 抽奖参与门槛
- 评价通过后的奖励
- 记录用户在平台中的累计贡献

**积分不是现金，也不等同于提现余额。** 除非产品明确发布公告说明可兑换权益，否则积分不可直接换钱、不构成对用户的金钱承诺。涉及报销（积分门槛）等真实权益的具体规则请见 [`POLICY-reimbursement.md`](POLICY-reimbursement.md)。

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

详见 [`POLICY-lottery.md` §十](POLICY-lottery.md)。

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

## 十、相关文档

- 报销规则（积分门槛、月池、周限额）：[`POLICY-reimbursement.md`](POLICY-reimbursement.md)
- 抽奖规则（积分门票、退款）：[`POLICY-lottery.md`](POLICY-lottery.md)
- 部署与备份：[`DEPLOYMENT.md`](DEPLOYMENT.md)
- 稳定化审查：[`STABILITY-AUDIT-2026-05-18.md`](STABILITY-AUDIT-2026-05-18.md)
