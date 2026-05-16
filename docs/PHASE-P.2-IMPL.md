# Phase P.2 实施指南：用户「我的积分」入口

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：P.2.1 / P.2.2
> 关联 spec：[POINTS-FEATURE-DRAFT.md §2 / §7](./POINTS-FEATURE-DRAFT.md)
> 后续：[PHASE-P.3-IMPL.md](./PHASE-P.3-IMPL.md)（待编写）

---

## 0. 目标

阶段 III 第二步：让用户主动查看自己的积分。

- 用户主菜单第 6 行独占新增 [💰 我的积分]
- 积分页：余额 + 累计获得 + 累计消耗 + tx_count
- 明细分页：20 条/页（spec §2.2）；每条 `+5 审核通过：丁小夏（包夜）  2026-05-16 14:23`
- 仅在 [💰 我的积分] 页面展示（spec §1.4：不在详情页 / 评论区）

**不做：**
- 超管「积分管理」工具 → Phase P.3
- 排行榜 / 商城 / 兑换
- 撤回 / 修正交易

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/keyboards/user_kb.py` | user_main_menu_kb 加第 6 行 + 新增 user_points_menu_kb |
| `bot/database.py` | +20 行：get_teachers_by_ids 批量取 |
| `bot/main.py` | 注册 user_points_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/utils/user_points_render.py` | 总览页 / 明细行 / 反查老师名 | ~140 |
| `bot/handlers/user_points.py` | user:points / user:points:list / :list:<page> | ~100 |

---

## 2. UI / 文本

### 2.1 主菜单（spec §2.1）

```
[📚 今天能约谁] [🎯 帮我推荐]
[🔎 按条件找]   [🔥 热门推荐]
[⭐ 我的收藏]   [🕘 最近看过]
[🔍 直接搜索]   [💝 收藏开课]
[🔔 我的提醒]   [📜 搜索历史]
[💰 我的积分]                    ← P.2 新增（第 6 行独占）
```

### 2.2 积分总览页（spec §2.2）

```
💰 我的积分

当前余额：85 分

📈 累计获得：85 分（10 次报告通过）
📉 累计消耗：0 分
```

按钮：
```
[📋 积分明细]
[🔙 返回主菜单]
```

0 数据时追加 "ℹ️ 暂无积分记录。提交并通过审核的报告会自动加分。"

### 2.3 积分明细页（每页 20 条）

```
📋 积分明细（共 25 条 · 第 1/2 页）

1. +5  审核通过：丁小夏（包夜）  2026-05-16 14:23
2. +1  审核通过：小桃（P/PP）   2026-05-15 22:10
3. 0   审核通过：晚柠（不加分）  2026-05-14 19:05
...

[⬅️ 上一页] [📄 1/2] [➡️ 下一页]
[🔙 返回积分]
[🏠 主菜单]
```

reason 渲染规则：
- `review_approved` → "审核通过：{teacher_name}（{note}）"
- `admin_grant` → "管理员加分：{note}"
- `admin_revoke` → "管理员扣分：{note}"
- 其它 → "{reason}：{note}"

delta 显示：+5 / 0 / -3。
时间截取前 16 字符（YYYY-MM-DD HH:MM）。

---

## 3. 关键流程

### 3.1 反查老师名

```
list_user_point_transactions(20, offset)
  ↓
fetch_teacher_names_for_txs(txs):
  txs 中 reason=review_approved 的 related_id（review_id）
    → get_teacher_review(rid) → teacher_id
    → 批量 get_teachers_by_ids → display_name
  → 返回 (teachers_map, review_teacher_map)
  ↓
format_points_detail_block(txs, teachers_map, review_teacher_map,
                            start_idx=offset+1)
```

### 3.2 分页边界

- page=0 末页：无 [⬅️] [➡️]，仅 [📄 1/1]
- page=0 含下页：有 [➡️ 下一页]
- 末页：有 [⬅️ 上一页]
- page 超界：clamp 到 total_pages - 1
- 0 条数据：跳过分页 + 显示空状态文案

---

## 4. 实施顺序（2 次 commit）

### Commit P.2.1 — 主菜单 + 总览页 + 明细分页（一次性完整实现）
- compileall + 6 module import + 11 项 sanity：
  user_main_menu_kb 第 6 行独占 / 积分页键盘 / 0 与含数据总览 /
  get_teachers_by_ids / detail_line 4 种 reason / +0 / -3 / start_idx /
  fetch_teacher_names 反查 / cb_user_points 渲染

### Commit P.2.2 — 端到端 + 文档（本文件）
- 10 步 E2E：
  1. 3 条混合套餐 review → tx 入库 → total=6
  2. 总览页：余额 6 / 累计 6（3 次） / 消耗 0
  3. 明细 page 0：3 条含老师名 + 套餐
  4. page=0 末页：无翻页
  5. 25 条数据 → page 0：20 条 + [下一页]
  6. page 1：5 条 + [上一页] + 无下一页
  7. page 超界 → clamp
  8. 0 积分用户：空状态 + 明细空状态
  9. 参数错误 alert
  10. 9.3 / P.1 回归

---

## 5. 验收清单

### 5.1 主菜单
- [x] 第 6 行独占 [💰 我的积分]
- [x] callback `user:points` 与现有 `user:*` 不冲突

### 5.2 总览页
- [x] 渲染含余额 / 累计获得（含 tx_count）/ 累计消耗
- [x] 0 数据空状态友好提示

### 5.3 明细页
- [x] 4 种 reason 中文映射（review_approved / admin_grant / admin_revoke / 其它）
- [x] +N / 0 / -N 显示
- [x] 时间截取前 16 字符
- [x] review_approved 反查老师名 + 套餐标签（note）

### 5.4 分页
- [x] page=0 末页无翻页按钮
- [x] 25 条 → page 0/1 边界正确
- [x] page 超界 clamp
- [x] start_idx 跨页递增（21 起，不重置）

### 5.5 兼容
- [x] 9.1-9.6 / P.1 全部回归
- [x] 0 积分用户能进入查看（不报错）

### 5.6 静态
- [x] python3 -m compileall bot
- [x] import bot.main OK

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 老师已删除 → 明细页"丁小夏（包夜）"显示问题 | get_teachers_by_ids 不含的 id → 显示 "审核通过（包夜）"（无老师名） |
| review_approved 但 related_id 为 NULL | fetch_teacher_names_for_txs 过滤 None |
| 用户从未走过 /start | get_user_points_summary 返回 all zeros |
| edit_text 同样内容 BadRequest | try/except 安全忽略 |
| 长 note → 单行过长 | 当前未截断（一行 < 100 字符可控）|

---

## 7. 不在本 Phase 范围

- ❌ [💰 积分管理] 超管入口 → Phase P.3
- ❌ 排行榜 / 商城 / 兑换
- ❌ 自定义筛选 / 时间范围查询
- ❌ 撤回 / 修正交易

---

## 8. 完成后

Phase P.2 完成 → 立即开 Phase P.3（超管「积分管理」工具）。

> Phase P.3 开始前需确认（spec §3.2）：
> - 查询用户积分输入方式（user_id / @username 两种）
> - 手动加扣分预设值（+10 / +20 / -1 / -3 / -5 / -10 / 自定义）
> - 加分原因选项（报告审核补加 / 活动奖励 / 违规扣分 / 系统修正 / 自定义）
> - 总览 TOP 10 排序规则（按 total_points DESC？）
