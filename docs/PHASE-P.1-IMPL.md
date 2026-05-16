# Phase P.1 实施指南：积分 DB + 审核通过加分子页

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：P.1.1 / P.1.2
> 关联 spec：[POINTS-FEATURE-DRAFT.md §1 / §3.1 / §4 / §7](./POINTS-FEATURE-DRAFT.md)
> 后续：[PHASE-P.2-IMPL.md](./PHASE-P.2-IMPL.md)（待编写）

---

## 0. 目标

B 组积分系统第一步：让超管审核通过时根据**审核材料推断套餐**给评价者加分，并把积分信息合并到原有审核通过流程中。

- `users` 表加 `total_points` 字段 + 新表 `point_transactions`
- 9.4 的 [✅ 通过] 流程改为先进**加分子页**（6 套餐预设 + 自定义 0-100）→ 一次性 commit
- 私聊通知评价者文案附本次积分 + 当前总积分

**不做（明确）：**
- [💰 我的积分] 用户入口 → Phase P.2
- [💰 积分管理] 超管入口 → Phase P.3
- 扣分功能（DB 层接受 negative delta 但 UI 不开放）
- 排行榜 / 商城 / 抽奖耦合

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +195 行：point_transactions schema + _migrate_users_total_points + 6 个 CRUD + 常量 |
| `bot/handlers/rreview_admin.py` | 重构 cb_rreview_approve + 3 个新 callback + _do_approve_inner 统一执行链 |
| `bot/utils/rreview_notify.py` | notify_review_approved 扩签名加 delta/new_total/package_label |
| `bot/keyboards/admin_kb.py` | +30 行：rreview_approve_points_kb |
| `bot/states/teacher_states.py` | +6 行：RReviewApprovePointsStates |

### 1.2 新增文件

无（所有改动放进现有模块）

---

## 2. DB 变更

### 2.1 Schema

`init_db` executescript 内追加 `point_transactions`：
```sql
CREATE TABLE IF NOT EXISTS point_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    related_id INTEGER,
    operator_id INTEGER,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_point_tx_user_time ON point_transactions(user_id, created_at);
CREATE INDEX idx_point_tx_related   ON point_transactions(reason, related_id);
```

新 _migrate_users_total_points 走 PRAGMA 检测 + ALTER（与 user_source / onboarding 模式一致）。

### 2.2 常量与 CRUD（spec §1.2 / §4.3）

| 名称 | 说明 |
|---|---|
| `POINT_PACKAGE_OPTIONS` (5 项) | P/PP +1 / 包时 +3 / 包夜 +5 / 包天 +8 / 不加分 0 |
| `POINT_CUSTOM_MIN=0` / `POINT_CUSTOM_MAX=100` | 自定义范围 |
| `add_point_transaction(uid, delta, reason, *, related_id, operator_id, note)` | INSERT OR IGNORE users 兜底 + INSERT tx + UPDATE total_points |
| `get_user_total_points(uid)` | 不存在 / NULL → 0 |
| `get_user_points_summary(uid)` | {total, earned, spent, tx_count} |
| `list_user_point_transactions / count_user_point_transactions` | DESC + 分页 |

---

## 3. 关键流程：审核通过加分子页

### 3.1 原流程（9.4）

```
[✅ 通过] → approve_teacher_review → recalc → edit_caption → publish_comment → notify
```

### 3.2 P.1 改造（spec §3.1）

```
[✅ 通过] → 进加分子页
  ↓
显示：当前用户总积分 80
  [+1 P/PP]   [+3 包时]
  [+5 包夜]   [+8 包天]
  [+0 不加分] [💬 自定义]
  [🔙 取消通过，返回审核]
  ↓ 选预设 or 自定义输入 0-100
_do_approve_inner（顺序）：
  1. approve_teacher_review (9.4)
  2. add_point_transaction(reason="review_approved", related_id=rid,
                          operator_id=超管, note=套餐标签)
  3. log_admin_audit(action="rreview_approve", detail+={delta, package, new_total})
  4. recalculate_teacher_review_stats + update_teacher_post_caption(force) (9.5)
  5. publish_review_comment (9.5)
  6. notify_review_approved(delta, new_total, package_label)
  7. 清旧消息 + 推下一条 / 队列空回主面板
```

任一步失败：log warning + 继续；不阻塞通知评价者。

### 3.3 私聊通知文案变化（spec §2.3）

旧：
```
✅ 你的评价已通过审核。
老师：丁小夏
评级：👍 好评 · 🎯 综合 8.6
感谢你的反馈！
```

新（含积分）：
```
✅ 你的评价已通过审核。

老师：丁小夏
评级：👍 好评 · 🎯 综合 8.6

本次获得：+5 积分（包夜）
当前总积分：85

感谢你的反馈！
```

### 3.4 callback 命名

| callback | 行为 |
|---|---|
| `rreview:approve:<rid>` | 入口，展示加分子页（之前直接 commit，现改为 edit_text 子页） |
| `rreview:approve_p:<rid>:<key>` | key ∈ {p,hour,night,day,zero}，直接 _do_approve |
| `rreview:approve_custom:<rid>` | 进 RReviewApprovePointsStates 等待文本 |
| `rreview:show:<rid>` | 取消加分子页，回审核详情（9.4.1 已就绪） |

---

## 4. 实施顺序（2 次 commit）

### Commit P.1.1 — DB schema + CRUD
- compileall + 10 项 sanity：
  init_db 幂等 / 5 项常量 / schema 列齐备 / +5 同步 total / 连续 4 笔 (+5/+3/+0/-2) /
  summary {6,8,2,4} / list DESC + 分页 / 不存在 user 兜底 /
  无效输入 None / 空 user summary all zeros

### Commit P.1.2 — 加分子页 + 通知 + E2E + 文档（本文件）
- 9 步 E2E：录档案 → review pending → [✅ 通过] 展示加分子页 →
  [+5 包夜] 通过 + tx +5 + total=5 + 私聊 "+5 积分（包夜）" →
  [+0 不加分] tx 写 0 total 不变 → [💬 自定义] FSM → 收 "8" → total=13 →
  越界/非数字拒绝 + review 仍 pending → 9.3 回归

---

## 5. 验收清单

### 5.1 DB
- [x] _migrate_users_total_points 幂等（已有列跳过）
- [x] add_point_transaction 三态：成功 / 用户不存在兜底 / 无效输入 None
- [x] users.total_points 与 SUM(delta) 一致（应用层维护，spec §4.1）
- [x] get_user_points_summary 含 total/earned/spent/tx_count
- [x] list/count 按 DESC + 分页

### 5.2 加分子页
- [x] [✅ 通过] callback 改为展示加分子页（不直接 commit）
- [x] 6 套餐按钮 + 取消
- [x] 自定义 FSM：0-100 整数；越界 / 非数字拒绝 + 停留
- [x] /cancel 回审核详情页
- [x] [+0 不加分] 仍写 tx delta=0（spec §6 便于追溯）

### 5.3 链式触发
- [x] _do_approve_inner 顺序：approve → tx → audit → 9.5 链 → notify → 清旧 + 推下一条
- [x] tx 写入 reason=review_approved + related_id=rid + operator_id=reviewer + note=套餐标签
- [x] audit detail 含 delta + package + new_total
- [x] notify 文案含 "+N 积分（包夜）" + "当前总积分：M"
- [x] 9.5 链失败仅 warning，不阻塞通知

### 5.4 兼容
- [x] 9.1 / 9.2 / 9.3 / 9.4 / 9.5 / 9.6 全部回归
- [x] users 表 total_points 默认 0 不破坏现有 SELECT * 调用
- [x] 旧 callback rreview:approve:* 路径仍工作（只是行为改变）

### 5.5 静态
- [x] python3 -m compileall bot
- [x] import bot.main OK

---

## 6. 风险与缓解（实际落实）

| 风险 | 缓解 |
|---|---|
| add_point_transaction 失败 → review 已 approved 但用户未加分 | log warning + 继续；private notify 仍发（new_total 仍读 DB；可能为旧值）|
| users.total_points 与 tx 累计不一致 | 应用层维护；get_user_points_summary 双轨核对（total 取 users.total_points 优先）|
| user 从未走过 /start | INSERT OR IGNORE users 兜底 |
| 老数据 total_points 为 NULL | COALESCE(total_points, 0) + delta 容错 |
| callback startswith 冲突 (`approve:` vs `approve_p:`) | 分别 startswith 严格匹配，靠 `:`/`_` 区分 |
| 自定义 FSM clear 后调 _do_approve_inner 没 state | _do_approve_from_message 传 state=None；_send_review_at_index 跳过 store |

---

## 7. 不在本 Phase 范围

- ❌ [💰 我的积分] 用户入口 → Phase P.2
- ❌ [💰 积分管理] 超管入口 / 查询用户积分 / 手动加分 / TOP 10 → Phase P.3
- ❌ 排行榜 / 商城 / 抽奖耦合
- ❌ 扣分 UI（DB 层接受 negative delta，P.3 才放开）
- ❌ 通过后改驳回 / 撤回（spec §6 明确 approved 是终态）

---

## 8. 完成后

Phase P.1 完成 → 立即开 Phase P.2（用户「我的积分」入口）。

> Phase P.2 开始前需确认：
> - 主菜单第 6 行独占布局（spec §2.1）
> - 我的积分页是否含累计数据 vs 仅余额
> - 明细分页 [⬅️ ➡️] 边界 + 单页条数
