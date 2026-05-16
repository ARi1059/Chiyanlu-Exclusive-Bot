# 报销子系统实施记录（积分换报销）

> 状态：**✅ 已完成**（2026-05-17）
> Commit：DB 基建 / 评价 FSM 联动 / 用户报销页 + E2E
> 关联：[PHASE-P.1-IMPL.md](./PHASE-P.1-IMPL.md)（积分系统）

---

## 0. 目标

提交评价的成员若满足积分门槛（≥5），可在评价提交时勾选申请按老师价档报销
（100/150/200 元）。admin 人工审核报销；周限 1 次（admin 可单独重置）；
可配置月度报销池总预算。

**用户决策（已采纳）：**
1. 申请入口：评价提交 FSM 内（满足条件的成员被询问"是否申请本次报销"）
2. 审批模式：admin 人工审核（pending → approved/rejected）
3. 价格源：绑定该评价的老师 `teacher.price`（一个评价仅可报销 1 次，UNIQUE review_id）
4. 频率：周自动重置 + admin 可单独重置某用户当周配额（reset 当作一次性 voucher）

**金额规则**（按 displayed price = `raw_digits // 100`）：
- displayed ≤ 8P → 100 元
- displayed == 9P → 150 元
- displayed ≥ 10P → 200 元
- 0 / 无法解析 → 不报销

**资格规则：**
- `user.total_points >= reimbursement_min_points`（config，默认 5）
- 当周（ISO week）approved count < 1 + 可用 reset_vouchers 数
- 当月（YYYY-MM）approved total + amount ≤ `reimbursement_monthly_pool`（0 = 不限）

---

## 1. DB schema

### 新表 1：`reimbursements`

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER | 申请者 |
| review_id | INTEGER UNIQUE | 绑定的评价（一评价一报销） |
| teacher_id | INTEGER | 评价的老师 |
| amount | INTEGER | 金额（元） |
| status | TEXT | pending / approved / rejected / cancelled |
| week_key | TEXT | 'YYYY-Www' ISO 周（查重 + 重置） |
| month_key | TEXT | 'YYYY-MM'（池统计） |
| created_at | TEXT | |
| decided_at / decided_by | TEXT / INTEGER | admin 审核时间 + 操作者 |
| reject_reason | TEXT | 驳回原因 |
| notified_at | TEXT | 用户通知时间戳 |

索引：`(user_id, week_key)` / `(status)` / `(month_key)`

### 新表 2：`reimbursement_resets`

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER | |
| granted_by | INTEGER | 操作 admin |
| granted_at | TEXT | |
| consumed | INTEGER | 0/1，是否已被某次 approve 消耗 |
| consumed_at | TEXT | |
| consumed_reimb_id | INTEGER | 消耗时绑定的 reimbursement id |

索引：`(user_id, consumed)`

### `teacher_reviews` 字段扩展

`request_reimbursement INTEGER NOT NULL DEFAULT 0`（用户提交时勾选的报销意愿）

### config 项（写 bot_config）

- `reimbursement_monthly_pool`：月度池总额（元），默认 `0` = 不限
- `reimbursement_min_points`：申请门槛积分，默认 `5`

---

## 2. 关键流程

### 2.1 用户提交评价（含报销选择）

```
评价 12 步 FSM ... → Step 9 (summary) → [报销选择]* → Step 10 (confirm) → 提交
                                          ↑ 条件可见
```

`_enter_reimbursement_step`（[review_submit.py](../bot/handlers/review_submit.py)）：
- 算 `amount = compute_reimbursement_amount(teacher.price)`
- 取 `points = get_user_total_points(user_id)` 和 `min_pts = config(reimbursement_min_points)`
- `amount > 0 AND points >= min_pts` → 显示 `[💰 是，申请 X 元] [否，不申请]`
- 否则透传到 `_enter_confirm`（`request_reimbursement=0`）

确认页文案：
```
... 评分行 ...

💰 报销申请：✅ 是，200 元（待超管审核）
━━━━━━━━━━━━━━━
```

### 2.2 admin 审核评价 → 联动创建 reimbursement

`rreview_admin._do_approve_inner`（评价审核通过链）：
1. `approve_teacher_review`
2. `add_point_transaction`
3. `log_admin_audit(rreview_approve)`
4. **报销联动**：若 `review.request_reimbursement=1` 且 `amount>0` 且 `new_total>=min_pts`
   → `create_reimbursement(week_key, month_key)` + `log_admin_audit(reimburse_created)`
5. 评价相关：recalc / caption / 讨论群评论
6. `notify_review_approved(reimb_amount, reimb_pending)` → 文案附加「报销申请已提交：X 元」
7. 队列推下一条

### 2.3 admin 审核报销

callback：`reimburse:enter` → 显示首条 pending

详情页（[admin_reimburse.py](../bot/handlers/admin_reimburse.py:_render_reimbursement_detail)）：
```
💰 报销申请 #N
━━━━━━━━━━━━━━━
📌 状态：⏳ 待审核
🙋 申请者：xxx (@username)  uid: 99001
👩‍🏫 老师：测试老师（价格 1000P）
📝 评价 ID：#5
💰 报销金额：200 元
━━━━━━━━━━━━━━━
🗓 周 key：2026-W20
   本周已批：0/1
📅 月 key：2026-05
   本月已批总额：0 元
   本月池预算：300 元（剩余 300）
━━━━━━━━━━━━━━━

[✅ 通过] [❌ 驳回]
[🔄 重置该用户本周]
[🔙 返回主菜单]
```

#### 通过流程
1. 月池校验：`month_used + amount > pool` → alert "本月池余额 X 元，不足"
2. 周配额校验：`week_used >= 1` → 找未消耗 voucher → 无 → alert "本周已批过，请点 [🔄 重置]"
3. `approve_reimbursement` + 消耗 voucher（如有）+ audit `reimburse_approve`
4. 私聊用户："✅ 你的报销申请 #N 已通过 / 金额：X 元 / 请联系客服领取"
5. 推下一条 pending

#### 驳回流程
- 进 `ReimburseRejectStates.waiting_reason`，超管输入原因 → `reject_reimbursement` + audit + 私聊用户

#### 重置流程
- 二次确认 → `grant_reimbursement_reset(user_id)` → 一张未消耗的 voucher → 下次 approve 时可消耗

### 2.4 用户「我的报销」

callback：`user:reimburse` / `user:reimburse:list[:page]`（[user_reimburse.py](../bot/handlers/user_reimburse.py)）

总览页：
```
🧾 我的报销
━━━━━━━━━━━━━━━
本周已通过：1/1 笔
本月已通过总额：200 元（池 300 元）
累计申请：3 笔
━━━━━━━━━━━━━━━

最近 5 笔：
  · #3 测试老师 200 元 ❌ 已驳回
    驳回：证据存疑
  · #2 测试老师 200 元 ✅ 已通过
  · #1 测试老师 200 元 ✅ 已通过

💡 提交评价时若满足积分门槛 + 老师价位 > 0，可勾选申请报销。
```

明细页 10 条/页 + 三态分页。

---

## 3. callback 命名空间

| callback | handler |
|---|---|
| `review:reimburse_yes` / `review:reimburse_no` | review_submit |
| `reimburse:enter` | admin_reimburse |
| `reimburse:item:<id>` | admin_reimburse |
| `reimburse:approve:<id>` | admin_reimburse |
| `reimburse:reject:<id>` | admin_reimburse |
| `reimburse:reset:<user_id>:<rid>` | admin_reimburse |
| `reimburse:reset_ok:<user_id>:<rid>` | admin_reimburse |
| `user:reimburse` | user_reimburse |
| `user:reimburse:list[:page]` | user_reimburse |
| `system:reimburse_pool` | admin_panel |

---

## 4. audit 标签

| action | 中文 |
|---|---|
| reimburse_created | 自动创建报销申请（审核评价时联动） |
| reimburse_approve | 通过报销 |
| reimburse_reject | 驳回报销 |
| reimburse_reset | 重置周报销配额（发放 voucher） |
| reimburse_pool_set | 设置报销池 |

---

## 5. Sanity 覆盖

`/tmp/sanity_reimburse_v1.py`（14 项 ALL PASS）：DB 基建 + 工具函数 + CRUD

`/tmp/sanity_reimburse_v2.py`（9 项 ALL PASS）：评价 FSM + 审核联动

`/tmp/sanity_reimburse_v3.py`（10 项 ALL PASS）：用户页 + 端到端
- 完整链路：申请 → 评价审核 → reimbursement pending → admin 通过 → user 查到 approved
- 周限：第 2 次 block / admin 重置后可继续
- 月度池超额检测
- 驳回流程

---

## 6. 兼容性

- 老 review（无 `request_reimbursement` 字段）默认 0 → 审核通过不会创建 reimbursement
- 老师 price 字段无法解析 / 空 → `compute_reimbursement_amount` 返 0 → 不显示步骤
- `notify_review_approved` 旧调用方式（不传 reimb_*）默认 `reimb_pending=False`，文案与旧行为一致

---

## 7. Out of scope

- ❌ 实际打款流程（bot 仅记录意图，admin 线下/客服联系用户支付）
- ❌ 已批准的报销撤回 / 退款（终态不变）
- ❌ 多 admin 并发批准的强并发控制（DB UNIQUE review_id 兜底）
- ❌ 用户主动取消申请（pending 状态不允许用户改）
- ❌ 月度池接近用完时的自动告警（仅在 admin approve 时检查）
- ❌ 历史评价补申请（不支持，UNIQUE review_id）
