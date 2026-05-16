# Phase L.2 实施指南：抽奖频道发布 + 用户参与 + deep link + 计数

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：L.2.1 / L.2.2 / L.2.3 / L.2.4
> 关联 spec：[LOTTERY-FEATURE-DRAFT.md §2 / §4 / §8 / §9](./LOTTERY-FEATURE-DRAFT.md)
> 后续：[PHASE-L.3-IMPL.md](./PHASE-L.3-IMPL.md)（待编写）

---

## 0. 目标

让 L.1 创建的草稿真正发到频道并能让用户参与：

- 抽奖帖渲染（photo+caption / 纯文字 + inline 键盘）
- 立即发布 / 定时发布（APScheduler 调度，bot 重启扫描重注册）
- `/start lottery_<id>` deep link → 关注校验 → 创建 entry
- 口令抽奖私聊文字命中（大小写不敏感）
- 抽奖帖底部 [👥 N 人已参与] 计数（事件驱动 + 60s debounce）
- 详情页加 [📤 立即发布] / 取消计划

**用户决策（已采纳）：**
- 计数：事件驱动 + 60s debounce（用 lotteries.updated_at）
- APScheduler 重注册：on_startup 调 schedule_pending_lotteries
- 拒绝提示：独立按钮（有 username → URL；无 → noop + chat_id）
- caption 超 1024：description 优先截断（200→80→prize 60→硬截）

**不做：**
- 定时开奖 / 中奖通知 / `secrets.SystemRandom` → Phase L.3
- active 编辑 / 客服链接 / 帖删重发 → Phase L.4

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +120 行：6 个 entries/meta CRUD + debounce + scan 方法 |
| `bot/handlers/admin_lottery.py` | +180 行：[📤 立即发布] + 创建保存后立即/定时分支 + cancel 取消 job |
| `bot/handlers/start_router.py` | +20 行：parse_start_args 加 lottery_id + _route_by_role 分支 |
| `bot/handlers/admin_panel.py` | +2 行：audit label lottery_publish / lottery_entry |
| `bot/keyboards/admin_kb.py` | +20 行：admin_lottery_detail_kb 加 [📤 立即发布] + 二次确认 |
| `bot/main.py` | +20 行：注册 lottery_entry_router + on_startup 扫描重注册 |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/utils/lottery_publish.py` | 渲染 + 发布 + 计数更新 | ~230 |
| `bot/utils/lottery_subscribe_check.py` | 抽奖独立的必关校验（实时拿 chat title） | ~90 |
| `bot/handlers/lottery_entry.py` | deep link + 口令命中 + try_enter_lottery | ~190 |
| `bot/scheduler/lottery_tasks.py` | APScheduler 调度 + 启动扫描重注册 | ~170 |

---

## 2. 关键流程

### 2.1 创建保存（更新 L.1.2 行为）

```
[Step 10/10 确认] 选 publish_mode → 保存
  publish_mode=immediate：
    DB status='draft' → publish_lottery_to_channel → status='active'
  publish_mode=scheduled：
    DB status='scheduled' → schedule_lottery_publish 注册定时任务
统一注册 schedule_lottery_draw（L.3 才实际执行）
```

### 2.2 抽奖帖渲染（spec §4.1）

```
🎉 {name}

📋 活动规则
{description}（超 1024 字按 200→80 截断）

🎁 奖品
{prize_description}（兜底截到 60）

🏆 中奖人数：{prize_count}
⏰ 开奖时间：{draw_at}

📌 参与方式：
（button）点击下方 [🎲 参与抽奖] 按钮 → 在私聊完成确认
（code）  在私聊给我发送口令：{entry_code}

📋 参与门槛（请先加入以下频道/群组）：
  · {title} (@{username})
  · {title} (chat_id={cid})  ← 无 username

⚠️ 本次抽奖每人仅可参与 1 次
✳ Powered by @{bot_username}
```

底部 inline：
- button：[🎲 参与抽奖](URL deep link) + [👥 N 人已参与](noop)
- code：仅 [👥 N 人已参与]

### 2.3 用户参与流程

```
入口 1：/start lottery_<id>
入口 2：私聊文字命中 entry_code（find_lottery_by_entry_code 仅 active + 大小写不敏感）
  ↓
try_enter_lottery：
  status 非 active → not_active
  时间窗外 → time_window
  已参与（UNIQUE 防御）→ already_entered
  未关注 → need_subscribe + 链接按钮列表
  通过 → create_lottery_entry → audit + 异步 update_lottery_entry_count
```

### 2.4 计数更新（60s debounce）

```
asyncio.create_task(update_lottery_entry_count(bot, lid))
  ↓
seconds_since_lottery_updated(lid)
  < 60s → 跳过（log debug）
  ≥ 60s → 重渲键盘 + edit_message_reply_markup + touch_lottery
```

force=True 绕过；BadRequest "not modified" 静默；其它 log warning。

### 2.5 APScheduler 调度

```
on_startup（spec §8）：
  scheduler.start() 后调 schedule_pending_lotteries：
    scheduled → 注册 lottery_pub_<lid>
    scheduled/active → 注册 lottery_draw_<lid>（L.3 占位 log）
  过期时间 → run_date=now（misfire_grace_time=3600 容错）

cancel_lottery 成功后 → unschedule_lottery 取消两个 job
```

---

## 3. 实施顺序（4 次 commit）

### Commit L.2.1 — 渲染 + 发布 + [📤 立即发布]
13 项 sanity：create_entry UNIQUE / render 5 用例 / publish happy + 含封面 / debounce / 未发布 silent

### Commit L.2.2 — APScheduler + 启动扫描
8 项 sanity：_parse_db_datetime / schedule pub+draw 注册 / 过期 run_date=now / unschedule / scan 摘要 / publish_job + draw_job 占位

### Commit L.2.3 — 用户参与
14 项 sanity：parse_start_args / check_user_subscribed_to_chats 3 用例 /
render_kb URL vs noop / try_enter 6 用例 / 私聊命令 silent / 不匹配 silent / 口令命中

### Commit L.2.4 — E2E + 文档（本文件）
11 步 E2E：创建+立即发布 / deep link 参与 / 重复拒绝 / 5 entry debounce /
force=True 显示 6 人 / 未关注拒绝 / 口令命中 / scan pub=1+draw=3 / unschedule /
4 种 deep link 共存 / 9.3+P.1+L.1 回归

---

## 4. 验收清单

### 4.1 DB
- [x] create_lottery_entry UNIQUE(lottery_id, user_id) 一人一次
- [x] mark_lottery_published 仅 draft/scheduled → active + 写 channel meta
- [x] touch_lottery + seconds_since_lottery_updated 准确
- [x] list_active_or_scheduled_lotteries 仅返回 scheduled + active

### 4.2 渲染
- [x] caption 含所有字段 + description 优先截断
- [x] button/code 分别提示参与方式
- [x] 必关频道 title + @username / chat_id 标注
- [x] 含封面 → send_photo；无 → send_message

### 4.3 调度
- [x] schedule_lottery_publish/draw 用 lottery_pub_<lid> / lottery_draw_<lid>
- [x] 过期 publish_at → run_date=now
- [x] unschedule_lottery 取消两个 job
- [x] schedule_pending_lotteries on_startup 扫描重注册

### 4.4 参与
- [x] deep link `/start lottery_<id>` 解析
- [x] 私聊口令 F.chat.type=private + F.text 监听
- [x] 不匹配口令 silent skip（让后续 router 处理）
- [x] try_enter_lottery 6 路径完整
- [x] 关注校验失败 + 链接按钮列表（URL / noop）

### 4.5 计数
- [x] 事件驱动 + 60s debounce
- [x] force=True 绕过
- [x] BadRequest "not modified" 静默

### 4.6 兼容
- [x] 9.1-9.6 / P.1-P.3 / L.1 全部回归
- [x] keyword 群组逻辑不受影响（F.chat.type=private 过滤）
- [x] 多 deep link 互斥（lottery / teacher / write / fav）

---

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Telegram 限流 edit_message_reply_markup 频繁 | 60s debounce + "not modified" 静默 |
| 抽奖帖被群管删 | 本 phase 不处理；L.4 实现自动重发 |
| 必关频道 bot 无权限 | check_user_subscribed_to_chats 静默跳过该项（spec §9）|
| 用户先加入再参与中途又退群 | get_chat_member 实时查 → status=left → 拒绝 |
| 大量用户秒杀参与 | DB UNIQUE 防重；create_lottery_entry 冲突返 None |
| 私聊文字误命中口令 | 仅 active 抽奖 + entry_method='code' 才匹配；命令 / 长度过 20 silent |
| 频道未配置 | publish_lottery_to_channel 抛 no_channel |
| bot 重启间隙错过 publish_at | misfire_grace_time=3600 容错 |

---

## 6. 不在本 Phase 范围

- ❌ 定时开奖 + 中奖通知 + secrets.SystemRandom → Phase L.3
- ❌ [👥 查看参与人员] 脱敏列表 → Phase L.4
- ❌ [✏️ 编辑 active 抽奖]（spec §3 §10）→ Phase L.4
- ❌ 客服链接配置（中奖通知用）→ Phase L.4
- ❌ 频道帖被删 → 自动重发 → Phase L.4

---

## 7. 完成后

Phase L.2 完成 → 立即开 Phase L.3（定时开奖 + 中奖通知）。

> Phase L.3 开始前需确认：
> - 开奖触发后 bot 重启的容错（已 drawn 不重复抽）
> - 中奖通知失败（用户屏蔽 bot）的 fallback
> - 频道结果消息渲染（半匿名格式同评价）
> - 客服链接缺失时按钮处理
