# 抽奖参与积分门槛实施记录

> 状态：**✅ 已完成**（2026-05-16）
> Commit：`<commit1>` / `<commit2>`
> 关联：[PHASE-L.4-IMPL.md](./PHASE-L.4-IMPL.md)

---

## 0. 目标

让 admin 在创建/编辑抽奖时配置「参与所需积分」，用户点击参与时自动从积分余额扣除。
免费抽奖（cost=0）完全兼容旧行为；admin 取消活动 active 抽奖时可选择性退还参与者积分。

**用户决策（已采纳）：**
- 用户参与扣分**不**走二次确认（点击即扣，与免费抽奖一致流程）
- admin 取消 active 抽奖时**选择性退款**（二次确认页两个按钮：退积分 / 不退积分）
- 创建 FSM 在 Step 10 确认页加 [💰 设置参与所需积分] 按钮，点击进入数字输入子流程
- 余额不足 → alert + [💰 查看我的积分] 按钮跳转 `user:points`

---

## 1. DB 变更

`lotteries` 表新增 `entry_cost_points INTEGER NOT NULL DEFAULT 0`
（CHECK 0-1000000）。

| 写入路径 | 用法 |
|---|---|
| `create_lottery(..., entry_cost_points=int)` | INSERT 接受新列；默认 0 |
| `update_lottery_fields(lid, entry_cost_points=int)` | active 编辑通过 `LOTTERY_EDITABLE_FIELDS` 白名单 |
| `_migrate_lotteries_entry_cost` | ALTER TABLE if not exists，幂等 |

---

## 2. 创建 FSM 子流程

UI 不增加固定步骤（保持 Step N/10），而是在 Step 10 确认页加入口按钮：

```
🎲 创建抽奖（Step 10/10 确认）
━━━━━━━━━━━━━━━
🏷 名称：xxx
...
💰 参与消耗：免费 / 50 积分
...

[💰 设置参与所需积分]
[✅ 保存草稿]  [❌ 取消]
```

点击 → 进 `LotteryCreateStates.waiting_entry_cost_input` 子状态，等数字输入
（0-1000000）。完成后回到 Step 10 确认页，新值反映在文案中。

文件：
- callbacks `admin:lottery:c_set_cost` / `admin:lottery:c_cost_back`
- handler `cb_lottery_c_set_cost` / `cb_lottery_c_cost_back` / `on_entry_cost_input`
  位于 `bot/handlers/admin_lottery.py`

---

## 3. 用户参与扣分（核心流程）

`bot/handlers/lottery_entry.py:try_enter_lottery`

校验顺序：
```
active 状态 → 时间窗 → 重复参与 → 必关频道 → 积分门槛 → 创建 entry → 扣分 → audit
```

- `entry_cost_points > 0` 时：
  - `get_user_total_points(uid)` 预查余额
  - 不足 → 返回新状态 `need_points`（不扣分、不创建 entry）
  - 足 → 先 `create_lottery_entry`，再 `add_point_transaction(uid, -cost,
    reason='lottery_entry', related_id=lid, note=lottery_name)`
  - 扣分异常时仅 log warning，不阻断；entry 已创建（用户已视为参与成功）
- 私聊回执：`✅ 你已参与`，cost > 0 时多一行 `💰 已扣除：X 积分`

**need_points 渲染**：
```
⚠️ 积分不足，无法参与「xxx」抽奖

参与需要：100 积分
你的余额：50 积分
还差：50 积分

[💰 查看我的积分]  ← callback user:points
```

---

## 4. 取消时选择性退款

`bot/handlers/admin_lottery.py:cb_admin_lottery_cancel` 接受 draft / scheduled / active。
当 `status='active' AND cost > 0 AND entry_count > 0` 时显示「退积分二选一」键盘：

```
⚠️ 确认取消抽奖 #N「xxx」？

当前状态：active
参与人数：3 位
参与消耗：50 积分

如选择「取消并退积分」，将向 3 位参与者各退 50 积分（合计 150 积分）。

取消后状态变为 cancelled，无法恢复（记录保留）。

[✅ 取消并退积分]
[⚠️ 取消但不退积分]
[🔙 不取消]
```

其余情况（草稿/计划/cost=0/0 entries）→ 单按钮 `[⚠️ 确认取消]`，保持原行为。

callback / handler：

| callback | handler | 说明 |
|---|---|---|
| `admin:lottery:cancel_ok:<lid>` | `cb_admin_lottery_cancel_ok` | 无退款 |
| `admin:lottery:cancel_ok_refund:<lid>` | `cb_admin_lottery_cancel_ok_refund` | 退款 |
| `admin:lottery:cancel_ok_norefund:<lid>` | `cb_admin_lottery_cancel_ok_norefund` | 明确不退款 |

三者都委托 `_do_lottery_cancel(refund=bool)`：
1. 先抓 `list_lottery_entries_for_draw` 拿到所有 entries（cancel 前）
2. `cancel_lottery(lid)` → active → cancelled
3. `unschedule_lottery`（容错）
4. `refund=True` 时遍历 entries，每个调 `add_point_transaction(+cost,
   reason='lottery_refund', related_id=lid, note=lottery_name)`；累计 refunded_count
5. audit `lottery_refund` (detail: cost / entries / refunded / total_amount)
6. audit `lottery_cancel` (detail: refund / refunded / cost)
7. alert admin + 回列表

---

## 5. 显示更新

| 位置 | 改动 |
|---|---|
| `bot/utils/lottery_publish.py:render_lottery_caption` | cost > 0 时在「⏰ 开奖时间」后插入「💰 参与消耗：X 积分」；cost=0 不显示 |
| `admin_lottery.py:_render_lottery_detail` | 加「💰 参与消耗：X 积分」行（不论 0/正） |
| Step 10 确认页 | 加「💰 参与消耗：X 积分 / 免费」 |
| `user_points_render.format_points_detail_line` | 新增 `lottery_entry` / `lottery_refund` 两个 reason 分支 |
| `admin_lottery_edit_field_kb` (active 编辑) | 加 [💰 参与所需积分] 按钮（7 字段） |
| `_AUDIT_ACTION_LABELS` | 加 `lottery_refund`: "退还参与积分" |

---

## 6. 兼容性

- 既有抽奖（DB 迁移自动 fill 0）保持免费行为
- L.1-L.4 全部回归通过
- 频道发布模板 `{grouped_teachers}` 等变量无变化
- `lottery_entry` audit detail 字段在 L.2 已存在，本次 detail 增加 `cost` 字段（旧记录无此字段，渲染容错）

---

## 7. Sanity 覆盖

`/tmp/sanity_lottery_cost_v1.py`（10 项 ALL PASS）：
- lotteries.entry_cost_points 字段 / create_lottery 写入 / update_lottery_fields
- render_lottery_caption cost 行条件显示
- format_points_detail_line 两个 reason 分支
- try_enter_lottery cost=0 不扣分 / 余额不足 → need_points / 余额足 → 扣分 + entry
- _EDITABLE_FIELDS / LotteryCreateStates.waiting_entry_cost_input

`/tmp/sanity_lottery_cost_v2.py`（8 项 ALL PASS）：
- admin_lottery_cancel_confirm_kb 单/双按钮形态
- 3 个用户参与扣分 → 余额 150
- show_refund_choice 判定（active+cost>0+entries → True）
- 退款流程：3 位参与者各退 cost → 余额恢复
- cancel_lottery active → cancelled
- cost=0 不弹退款选择 / 0 entries 不弹退款选择
- audit lottery_refund 标签注册

---

## 8. Out of scope

- ❌ 已开奖（drawn）/ no_entries 状态的退款（终态不再处理）
- ❌ 抽奖中途修改 cost 后退款补差（admin 改后新参与者用新 cost；老参与者不补差）
- ❌ 用户撤回参与（UNIQUE 约束，参与即终态）
