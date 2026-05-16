# Phase L.4 实施指南：抽奖管理工具完善

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：L.4.1 / L.4.2
> 关联 spec：[LOTTERY-FEATURE-DRAFT.md §10 L.4](./LOTTERY-FEATURE-DRAFT.md)
> 上一阶段：[PHASE-L.3-IMPL.md](./PHASE-L.3-IMPL.md)

---

## 0. 目标

L.1-L.3 已让抽奖完整闭环（创建 → 发布 → 参与 → 开奖 → 通知），但 admin 在
详情页只能查看 + 取消草稿。L.4 给 active 抽奖详情页加 3 个工具入口 + 配置入口：

- [👥 查看参与人员]：20 条/页 + 半匿名 + 🏆 中奖 + ✉ 已通知标记（active/drawn/no_entries 可见）
- [🔄 重发抽奖帖]：active 状态手动重发（频道帖被删 / bot 权限丢失后修复）
- [✏️ 编辑抽奖]：active 状态可编辑 6 个字段（不含 cover / entry_method / entry_code）
- [👨‍💼 抽奖客服链接]：双入口（系统设置 + 抽奖管理）配置中奖通知按钮 URL

**用户决策（已采纳）：**
- 参与列表 20 条/页 + 半匿名 + 中奖标记
- 帖被删检测：仅 admin 手动 [🔄 重发]（不 polling）
- active 编辑范围：name / description / prize_description / prize_count /
  required_chat_ids / draw_at（cover/entry_method/entry_code 不可改）
- 客服链接：系统设置 + 抽奖管理双入口（callback 复用 `_enter_contact_url_fsm`）

**不做：**
- 公开抽奖排行榜 / 商城 / 兑换
- entry_method / entry_code 编辑（active 改会让用户私聊命中旧口令失败）
- cover 编辑（需 repost 整帖；可通过 [🔄 重发] 间接达到）
- 帖删自动 polling / 重发
- 撤销已开奖 / 重抽（终态不变）

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +17 行：`list_lottery_entries_paged` 分页方法 |
| `bot/keyboards/admin_kb.py` | +106 行：`admin_lottery_detail_kb` 扩 active/drawn 按钮组；新增 `admin_lottery_entries_pagination_kb`、`admin_lottery_repost_confirm_kb`、`lottery_contact_cancel_kb`、`admin_lottery_edit_field_kb`、`lottery_edit_cancel_kb`；`system_menu_kb` + `admin_lottery_menu_kb` 加 [👨‍💼 抽奖客服链接] |
| `bot/states/teacher_states.py` | +14 行：`LotteryContactUrlStates`、`LotteryEditStates` |
| `bot/handlers/admin_lottery.py` | +500 行：参与列表、重发、客服链接 FSM、编辑 FSM |
| `bot/handlers/admin_panel.py` | +11 行：`system:lottery_contact` 入口（共享 FSM）+ 3 个 audit label |
| `bot/utils/lottery_publish.py` | +56 行：`refresh_lottery_channel_caption`（编辑后刷新频道帖） |

### 1.2 无新文件

---

## 2. DB 变更

### 2.1 新方法

| 方法 | 说明 |
|---|---|
| `list_lottery_entries_paged(lid, limit=20, offset=0)` | 参与人员按 entered_at DESC 分页 |

### 2.2 复用现有

- `update_lottery_fields`（L.1）— 编辑写入 + 重发改 channel_msg_id
- `get_lottery` / `count_lottery_entries` / `mark_lottery_published`
- `log_admin_audit` — `lottery_repost` / `lottery_contact_set` / `lottery_edit`
- `set_config("lottery_contact_url", url)` — 客服链接持久化

---

## 3. 关键流程

### 3.1 参与人员分页（L.4.1）

callback：`admin:lottery:entries:<lid>` / `:<lid>:<page>`

```
👥 抽奖 #42 参与人员
━━━━━━━━━━━━━━━
总参与: 25 人 | 中奖: 3 人
━━━━━━━━━━━━━━━

1. 🏆 ****6204 ✉ 已通知
2. 🏆 ****8901 ✉ 已通知
3. 🏆 ****0123（未通知）
4. ****1145
...
━━━━━━━━━━━━━━━
📄 1/2  [⬅️ 上一页]/[➡️ 下一页]
[🔙 返回详情]
```

- `_anon_uid_short`：`****<uid 后 4>`，<5 位 uid 直接 `****`
- ✉ 已通知 = `notified_at` 非空（仅中奖者 + 私聊未屏蔽）
- 分页三态键盘仿 9.6 / P.2

### 3.2 重发抽奖帖（L.4.1）

callback：`admin:lottery:repost:<lid>` → 二次确认 → `repost_ok:<lid>`

```python
# 实现关键：临时改 status='draft' 让 publish_lottery_to_channel 通过校验
await update_lottery_fields(lid, status="draft")
try:
    result = await publish_lottery_to_channel(bot, lid)
    # publish_lottery_to_channel 内部已调 mark_lottery_published → 自动恢复 active
except LotteryPublishError as e:
    # 回滚 status
    await update_lottery_fields(lid, status="active")
    await callback.answer(f"❌ {e}", show_alert=True)
    return
```

完成后 audit `lottery_repost`，detail = {chat_id, msg_id}。

### 3.3 客服链接配置（L.4.1）— 双入口共享 FSM

| 入口 | callback | handler |
|---|---|---|
| 系统设置 → [👨‍💼 抽奖客服链接] | `system:lottery_contact` | `cb_set_lottery_contact_from_system`（admin_panel.py） |
| 抽奖管理 → [👨‍💼 抽奖客服链接] | `admin:lottery:contact` | `cb_admin_lottery_contact`（admin_lottery.py） |

两者都调 `_enter_contact_url_fsm(message, state, edit=True)`，统一进
`LotteryContactUrlStates.waiting_url`。

输入处理（`on_lottery_contact_url`）：

- `/cancel` → 退出
- `0` → 清空 config，中奖通知不带按钮（文字 fallback "请联系频道管理员"）
- `@username` → 自动转 `https://t.me/{name}`
- `normalize_url` + 必须 `t.me` 域名（http/https）
- 通过 → `set_config("lottery_contact_url", url)` + audit `lottery_contact_set`

### 3.4 active 编辑 FSM（L.4.2）

callback 链：

```
admin:lottery:edit:<lid>           ← [✏️ 编辑] 入口（仅 active）
  → 显示 6 字段选择键盘
admin:lottery:edit_field:<lid>:<field>
  → 显示当前值 + 提示输入新值，进 LotteryEditStates.waiting_new_value
on_lottery_edit_value  ← 文本消息
  → 按字段类型校验 → update_lottery_fields → 副作用 → 显示详情
```

#### 字段元数据 `_EDITABLE_FIELDS`

| field | type | 校验 |
|---|---|---|
| name | str | ≤ 30 字，非空 |
| description | str | ≤ 500 字，非空 |
| prize_description | str | ≤ 100 字，非空 |
| prize_count | int_range | 1-1000 整数 |
| required_chat_ids | chat_ids | 逗号分隔；`0` 清空；每个 `precheck_required_chat` |
| draw_at | datetime | `YYYY-MM-DD HH:MM`，必须晚于 now |

#### 副作用

- 改 `draw_at` → `unschedule_lottery` + `schedule_lottery_draw`（重注册定时任务）
- 改任意一个 → `refresh_lottery_channel_caption`（重渲染频道帖 caption + keyboard，
  edit_message_caption 或 edit_message_text，按是否有 cover 分支）
- 一律 `log_admin_audit("lottery_edit", detail={"field", "old", "new"})`

---

## 4. 实施顺序（2 次 commit）

### Commit L.4.1 — 参与人员列表 + 重发抽奖帖 + 客服链接配置

10 项 sanity：
1. `list_lottery_entries_paged` 25 条分页 + won 标记位置
2. `admin_lottery_entries_pagination_kb` 三态（首/中/末/单页）
3. `admin_lottery_detail_kb` 4 状态按钮组合（draft/active/drawn/no_entries）
4. `admin_lottery_repost_confirm_kb` 二次确认 callback 正确
5. `lottery_contact_cancel_kb`
6. `system_menu_kb` 含 [👨‍💼 抽奖客服链接]
7. `admin_lottery_menu_kb` 含 [👨‍💼 抽奖客服链接]
8. `normalize_url` 5 边界（t.me / non-url / scheme 错 / 空 / @ 转换）
9. `update_lottery_fields` 重发模拟 channel_msg_id 更新
10. `lottery_contact_url` config set/get/clear

### Commit L.4.2 — active 编辑 FSM + 端到端 + 本文档

10 项 sanity：
1. `admin_lottery_edit_field_kb` 6 字段 + 返回
2. `lottery_edit_cancel_kb`
3. `_EDITABLE_FIELDS` 元数据（字段集合 + min/max）
4. `_format_current_value` 各分支（必关空列表 / 未设置）
5. `_parse_datetime_input` 容错（空 / 非法 / 合法）
6. `update_lottery_fields` 多字段（name / prize_count / chat_ids / draw_at）写入
7. `refresh_lottery_channel_caption` 未发布 → False（不调 edit_*）
8. `refresh_lottery_channel_caption` 已发布无 cover → `edit_message_text`
9. `refresh_lottery_channel_caption` 已发布有 cover → `edit_message_caption`
10. `log_admin_audit("lottery_edit")` 写入 + 读回

---

## 5. 验收清单

### 5.1 参与人员列表
- [x] 半匿名 `****<uid 后 4>`
- [x] 🏆 中奖 + ✉ 已通知 双标记
- [x] 20 条/页 + 三态分页
- [x] active / drawn / no_entries 详情页都可访问

### 5.2 重发抽奖帖
- [x] 仅 active 状态可见 [🔄 重发抽奖帖]
- [x] 二次确认 → 实际重发（临时 draft → publish → 恢复 active）
- [x] 重发失败回滚 status='active'
- [x] audit `lottery_repost`

### 5.3 客服链接配置
- [x] 双入口（系统设置 + 抽奖管理）共享 FSM
- [x] @username 自动转 t.me/xxx
- [x] `0` 清空（中奖通知文字 fallback）
- [x] `normalize_url` + t.me 域名校验
- [x] audit `lottery_contact_set`

### 5.4 active 编辑
- [x] 仅 active 状态可编辑（其它状态 alert 拒绝）
- [x] 6 字段校验（含越界 / 格式错 / 早于 now / 重复 / bot 不在场）
- [x] `draw_at` 改 → reschedule_lottery_draw
- [x] 任意改 → refresh_lottery_channel_caption
- [x] audit `lottery_edit` detail={field, old, new}

### 5.5 兼容
- [x] 9.1-9.6 / P.1-P.3 / L.1-L.3 回归
- [x] `python3 -m compileall bot`
- [x] `import bot.main`

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 重发时 publish 失败 → status 卡在 draft | try/except 回滚 `update_lottery_fields(status="active")` |
| 编辑 required_chat_ids 时某个 chat bot 不在场 | 逐个 precheck，失败显示原因列表，整体拒绝（不部分写入） |
| draw_at 改到很近的将来 → 调度器 misfire | L.3 已设 `misfire_grace_time=3600`；超时仍能补发 |
| draw_at 改后 reschedule 异常 | log warning + 提示 "请检查日志"；DB 仍已更新 |
| refresh_lottery_channel_caption 失败（频道删 / 权限丢失）| log warning + 提示 "频道刷新异常"；DB 仍已更新 |
| 客服链接 t.me 域名外的 URL（如 https://example.com）| 强制 `t.me/` 前缀，否则拒绝 |
| 双入口客服 FSM 状态污染 | 用 `_enter_contact_url_fsm` 统一 + 取消按钮回 admin:lottery |
| 用户屏蔽 bot 后 admin 改名重发 | refresh 用 edit 而非 send，原 msg_id 不变；通知逻辑独立 |

---

## 7. 不在本 Phase 范围

- ❌ 公开抽奖排行榜 / 商城 / 兑换
- ❌ entry_method / entry_code / cover 编辑（需新建抽奖）
- ❌ 帖删 polling / 自动重发
- ❌ 撤销已开奖 / 重抽（终态不变）
- ❌ 多 bot 实例并发编辑冲突检测

---

## 8. 完成后

C 组（抽奖系统）Phase L.1-L.4 全部完成。整体闭环：

```
[创建草稿 L.1] → [发布 L.2] → [参与 L.2] → [开奖 L.3] →
[通知 L.3] → [管理工具 L.4]
```

下一步可考虑：
- Phase L.5（可选）：批量管理 / 模板 / 导出 csv
- 或回到 A/B 组扩展功能
