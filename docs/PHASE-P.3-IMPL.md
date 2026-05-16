# Phase P.3 实施指南：超管「积分管理」工具

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：P.3.1 / P.3.2 / P.3.3
> 关联 spec：[POINTS-FEATURE-DRAFT.md §3.2](./POINTS-FEATURE-DRAFT.md)
> 后续：**积分系统（P.1-P.3）全部完成 ✅**

---

## 0. 目标

阶段 III 收官：让超管能在 bot 里手动管理任意用户积分。

- 主面板加 [💰 积分管理]（仅超管可见）
- [🔍 查询用户积分]：输入 user_id 或 @username → 显示总积分 + 最近 10 条明细
- [➕ 手动加分]：4 步 FSM（用户 → 数值 → 原因 → 确认）
  - 加分预设：[+1 P/PP] [+3 包时] [+5 包夜] [+8 包天] [+10] [+20]
  - 扣分预设：[-1] [-3] [-5] [-10]
  - 自定义：-100 至 100 整数
  - 原因预设：[报告审核补加] [活动奖励] [违规扣分] [系统修正] [💬 自定义]
- [📊 积分总览]：持币用户数 / 累计总加分 / TOP 10
- 所有操作 audit log

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +90 行：find_user_by_username / get_top_points_users / count_users_with_points / sum_total_points_earned / POINT_GRANT_REASON_OPTIONS |
| `bot/keyboards/admin_kb.py` | +90 行：积分管理子菜单 + 加分值/扣分/原因/确认 4 个键盘 |
| `bot/states/teacher_states.py` | +18 行：AdminPointsQueryStates + AdminPointsGrantStates(6 状态) |
| `bot/handlers/admin_panel.py` | +2 行：audit label points_query / points_grant |
| `bot/main.py` | +5 行：注册 admin_points_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/handlers/admin_points.py` | 主入口 + 查询 + 加扣分 FSM + 总览 | ~620 |

---

## 2. DB 变更

无 schema 变更（P.1.1 已建 point_transactions）。新方法：

| 方法 | 说明 |
|---|---|
| `find_user_by_username(name)` | 接受 "@xxx"/"xxx"；LOWER 比对，不区分大小写 |
| `get_top_points_users(limit=10)` | total_points > 0；DESC + LIMIT |
| `count_users_with_points()` | total_points > 0 计数 |
| `sum_total_points_earned()` | SUM(delta) WHERE delta > 0 |

新常量 `POINT_GRANT_REASON_OPTIONS` 4 项：audit/event/violate/fix。

---

## 3. UI / 流程

### 3.1 主菜单（is_super 行变 2 列）

```
[📝 报告审核 (M)] [💰 积分管理]      ← 仅 is_super=True 显示
```

### 3.2 积分管理子菜单

```
💰 积分管理

[🔍 查询用户积分]
[➕ 手动加分]
[📊 积分总览]
[🔙 返回主菜单]
```

### 3.3 查询用户积分

```
[Step] 输 user_id 或 @username
  → _resolve_user 数字 / @username 两种解析
  ↓
显示：
  💰 用户积分查询
  👤 小红 (@alice) · uid 90001
  当前余额：85 分
  📈 累计获得：85 分（10 次交易）
  📉 累计消耗：0 分
  📋 最近 10 条（共 N 条）
    1. +5  审核通过：丁小夏（包夜）  2026-05-16 14:23
    ...
  [🔍 再查一个] [🔙 返回积分管理] [🏠 主菜单]
```

### 3.4 手动加扣分 4 步 FSM

```
Step 1：输入 user_id / @username → state 存 target
Step 2：选预设 / [💬 自定义] / [➖ 扣分]
  扣分子页：[-1] [-3] [-5] [-10] [💬 自定义负数] [🔙 返回加分]
  自定义：FSM 等数字 -100~100，越界 / 非数字拒绝
Step 3：选预设原因 / [💬 自定义原因]
  自定义：FSM 等文本 ≤100 字，空 / 过长拒绝
  自定义原因 + delta 正负 → 自动判 reason_db（admin_grant / admin_revoke）
Step 4：确认页
  显示：目标 / 加分值 / 原因 / 余额变化（X → Y）
  [✅ 确认] [❌ 取消]
  确认 → add_point_transaction + audit points_grant
```

任意步骤发 /cancel 或点 [❌ 取消] 退出。

### 3.5 积分总览（spec §3.2）

```
📊 积分总览

💼 总用户数（持币）：5
💰 总加分（累计）：252 分

🏆 TOP 5 用户：
1. 小红 · @alice · uid 90001    90 分
2. 鲍勃 · @bob · uid 90002    72 分
3. 卡罗尔 · @carol · uid 90003    50 分
...
```

仅 total_points > 0 用户参与排行；TOP 10。

---

## 4. 实施顺序（3 次 commit）

### Commit P.3.1 — 主入口 + 查询用户积分
- compileall + 9 项 sanity（main_menu_kb is_super 切换 / 4 入口 /
  find_user_by_username 大小写 + @ + 边界 / _resolve_user / 子菜单渲染 /
  非超管被拒 / 数字/@username 查询 / 找不到保留 state）

### Commit P.3.2 — 手动加扣分 4 步 FSM
- compileall + 5 项 sanity：
  +5 包夜 → 活动奖励 完整链 + audit
  @alice → -3 违规扣分（自动 admin_revoke）
  自定义 +50 + 越界/非数字拒绝 + 自定义原因
  自定义负数 -5 → reason_db=admin_revoke
  [❌ 取消] 中止

### Commit P.3.3 — 总览 + E2E + 文档（本文件）
- 9 步端到端：5 持币 + 1 0 分用户 → 主菜单 / 子菜单 / 查询数字 ID /
  查询 @username / 完整加分链 + audit / 总览 / TOP 仅 >0 + DESC /
  count + sum / 9.3 / P.2 回归

---

## 5. 验收清单

### 5.1 DB
- [x] find_user_by_username 大小写 + @ 前缀
- [x] get_top_points_users 仅 >0 + DESC
- [x] count_users_with_points / sum_total_points_earned 准确

### 5.2 主菜单
- [x] is_super=True 显示 [💰 积分管理]；is_super=False 不显示
- [x] 与 [📝 报告审核] 同一行

### 5.3 查询
- [x] 数字 ID / @username 两种解析
- [x] 找不到 → reply 拒绝 + 保留 state 允许重输
- [x] 找到 → 渲染含余额 + 最近 10 条 + audit

### 5.4 手动加扣分
- [x] Step 1 校验失败保留 state；成功存 target + current_total
- [x] Step 2：6 预设 + [➖ 扣分] 子页 + [💬 自定义]
- [x] 自定义 -100~100 整数；越界 / 非数字拒绝
- [x] Step 3：4 预设 + [💬 自定义原因]
- [x] 自定义原因 ≤100 字；空 / 过长拒绝；正负 delta 自动判 reason_db
- [x] Step 4 确认：显示余额变化 X → Y
- [x] 确认后 add_point_transaction + audit points_grant + 渲染新余额
- [x] 任意步骤 /cancel 退出

### 5.5 总览
- [x] 持币用户数 / 累计加分 / TOP 10 渲染
- [x] TOP 仅 >0；空 TOP 友好显示
- [x] first_name + @username + uid 半显示
- [x] 超过 4000 字截断

### 5.6 兼容
- [x] 9.1-9.6 / P.1 / P.2 全部回归
- [x] _super_admin_required 装饰器拒绝非超管

### 5.7 静态
- [x] python3 -m compileall bot
- [x] import bot.main OK

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| @username 同名（大小写不同）查到错误用户 | LOWER 比对取唯一；users.username 在 upsert_user 维护时未强制 UNIQUE，最早匹配返回 |
| 手动加分时用户被并发 P.1 加分 → current_total 与 confirm 显示不一致 | add_point_transaction COALESCE 增量，最终 total 一致；只是 confirm 页"X → Y" 的 Y 可能偏差几分 |
| 自定义原因含 emoji / 特殊字符 | DB TEXT 字段无限制；UI 不做过滤 |
| TOP 10 用户被删 → user_id 仍出现 | 总览仍读 users 表；删除场景 spec §6 注明保留交易历史 |
| 超大量持币用户 TOP 10 查询慢 | total_points 字段无索引；本期数据量小可接受，未来加 idx |

---

## 7. 不在本 Phase 范围

- ❌ 公开排行榜（仅超管可见 TOP 10）
- ❌ 商城 / 兑换 / 抽奖耦合
- ❌ 撤回 / 修正交易
- ❌ TOP 10 之外的分页
- ❌ 多超管并发锁

---

## 8. 整个积分系统（P.1-P.3）完成 ✅

```
P.1 ✅ 审核加分链路 → P.2 ✅ 我的积分入口 → P.3 ✅ 超管管理工具
└────────  积分系统 100% 闭环  ────────┘
```

完整流程：
- 评价审核通过 → 自动加分（[+1/+3/+5/+8/+0/自定义]）
- 私聊评价者含 "+5 积分（包夜）" + 当前总积分
- 用户主菜单 [💰 我的积分] → 余额 + 累计 + 明细 + 分页
- 超管 [💰 积分管理] → 查询 / 手动加扣分 / 总览 TOP 10

按 IMPLEMENTATION-PLAN 总规划剩余：
- **C 组 抽奖系统**（L.1 → L.2 → L.3 → L.4）—— spec [LOTTERY-FEATURE-DRAFT.md](./LOTTERY-FEATURE-DRAFT.md)
  与积分系统**完全无依赖**，可独立实施。

至此阶段 III 完成；阶段 I (评价 9.1-9.6) + 阶段 II (评价 9.5/9.6) + 阶段 III (积分 P.1-P.3) 均已落地。
