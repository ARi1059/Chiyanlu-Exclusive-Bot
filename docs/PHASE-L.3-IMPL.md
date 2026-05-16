# Phase L.3 实施指南：抽奖定时开奖 + 中奖通知

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：L.3.1 / L.3.2 / L.3.3
> 关联 spec：[LOTTERY-FEATURE-DRAFT.md §5 / §8](./LOTTERY-FEATURE-DRAFT.md)
> 后续：[PHASE-L.4-IMPL.md](./PHASE-L.4-IMPL.md)（待编写）

---

## 0. 目标

让 L.2 已发布的 active 抽奖在 draw_at 时自动开奖：

- APScheduler 在 draw_at 调 draw_job → run_lottery_draw
- `secrets.SystemRandom` (CSPRNG /dev/urandom) 等概率抽 winners
- 标记 winners (`won=1`) + status → drawn / no_entries
- 频道追发结果消息（reply 到原抽奖帖，半匿名名单）
- 私聊通知中奖者（含 [👨‍💼 联系管理员] 按钮，或文字 fallback）
- 防重抽：已 drawn / cancelled / no_entries silent skip

**用户决策（已采纳）：**
- bot 重启过期 draw_at → 立即开奖（L.2 misfire_grace_time + 本 phase status 防重）
- 中奖通知失败 → silent skip + log（Forbidden / BadRequest 容错）
- 客服链接缺失 → 文字 fallback "请联系频道管理员"
- 半匿名格式："{首字}* (****uid 后 4)"

**不做：**
- [✏️ 编辑 active 抽奖] / [👥 查看参与人员] → Phase L.4
- 客服链接配置入口 → Phase L.4
- 频道帖被删自动重发 → Phase L.4

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +130 行：6 个开奖 DB 方法 |
| `bot/scheduler/lottery_tasks.py:draw_job` | 替换占位 → run_lottery_draw |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/utils/lottery_draw.py` | secrets 抽签 + 频道追发 + 私聊通知 | ~400 |

---

## 2. DB 变更

### 2.1 新方法

| 方法 | 说明 |
|---|---|
| `list_lottery_entries_for_draw(lid)` | 按 id 取所有 entries |
| `mark_lottery_entries_won(ids)` | 批量 won=1 |
| `mark_lottery_drawn(lid, result_msg_id?)` | 仅 active → drawn + drawn_at |
| `mark_lottery_no_entries(lid)` | 仅 active → no_entries |
| `mark_lottery_entry_notified(entry_id)` | notified_at 时间戳 |
| `update_lottery_result_msg(lid, msg_id)` | drawn 后补回 result_msg_id |

---

## 3. 关键流程

### 3.1 开奖触发链

```
APScheduler @ draw_at
  ↓
draw_job(bot, lid)
  ↓
run_lottery_draw(bot, lid):
  1. get_lottery + 校验 active（非 active silent skip 防重抽）
  2. list_lottery_entries_for_draw
     0 条 → mark_no_entries + _try_publish_no_entries
  3. ≥1 条 → _pick_winners (CSPRNG sample) → mark_entries_won
  4. mark_lottery_drawn（仅 active 才改，并发安全）
  5. _try_publish_result：频道追发 reply_to=channel_msg_id
  6. _try_notify_winners：批量私聊中奖者
  返回 {winners_count, total_entries, result_msg_id, notified}
```

### 3.2 CSPRNG 抽签（spec §5.1）

```python
rng = secrets.SystemRandom()  # /dev/urandom CSPRNG
winners = rng.sample(entries, min(prize_count, len(entries)))
```

容错：失败回退 random.SystemRandom + log；再失败兜底前 n 个 + audit。

### 3.3 频道结果消息（spec §5.3）

```
🏆 {lottery_name} 开奖结果

恭喜以下 {N} 位中奖者：

1. 小* (****6204)
2. A* (****8901)
3. 匿* (****0123)

📦 奖品：{prize_description}
请中奖者于 7 日内在私聊联系管理员领取。

✳ Powered by @{bot_username}
```

通过 `send_message(reply_to_message_id=channel_msg_id)` 挂在原抽奖帖下；
write back lottery.result_msg_id。

### 3.4 私聊中奖通知（spec §5.4）

```
🎉 恭喜你中奖了！

活动：{lottery_name}
奖品：{prize_description}

请于 7 日内点击下方按钮联系管理员领取奖品。
[👨‍💼 联系管理员]    ← 仅 config.lottery_contact_url 配置时
```

- 客服 URL 缺失：去掉按钮，文字 "请于 7 日内联系频道管理员"
- TelegramForbiddenError（用户屏蔽 bot）→ silent skip + log（不标记 notified_at）
- 成功 → mark_lottery_entry_notified

### 3.5 防重抽（spec §8）

- run_lottery_draw 入口 status 校验：非 active → return skipped
- mark_lottery_drawn 仅 active 可改（并发场景兼容）
- bot 重启时 schedule_pending_lotteries（L.2）+ misfire_grace_time=3600
- 已开奖的抽奖被重新触发：silent skip + log info

---

## 4. 实施顺序（3 次 commit）

### Commit L.3.1 — secrets 抽签 + 状态变更
13 项 sanity：_pick_winners 4 边界 + CSPRNG 等概率（2000 次） /
6 DB 方法 / run_lottery_draw 状态机（已 drawn / not_found / 0 entries / 完整 / 全员）

### Commit L.3.2 — 频道结果发布 + 私聊通知 + draw_job 接入
10 项 sanity：_anonymize_winner 6 边界 / render 2 个 / _build_keyboard 有无 URL /
_notify_one_winner happy + Forbidden + notified_at / _try_publish_result reply_to /
_try_publish_no_entries / 客服 URL 有/无 fallback / run_lottery_draw 完整链

### Commit L.3.3 — E2E + 文档（本文件）
11 步 E2E：完整链 3→2 winners / 频道追发 reply + 2 私聊 / 重复触发 silent /
prize>entries 全员 / 0 entries no_entries / 屏蔽 silent skip + 其它仍通知 /
客服缺失 fallback / draw_job 实际触发 / draw_job 异常容错 / CSPRNG 等概率 /
9.x+P.x+L.1+L.2 回归

---

## 5. 验收清单

### 5.1 DB
- [x] mark_lottery_drawn 仅 active 可改（并发安全）
- [x] mark_lottery_no_entries 仅 active 可改
- [x] list_entries_for_draw / mark_entries_won / mark_entry_notified

### 5.2 抽签
- [x] _pick_winners 用 secrets.SystemRandom CSPRNG
- [x] k > len → 全选；k=0 → []；空 entries → []
- [x] 无重复（sample 保证）
- [x] CSPRNG 失败回退 random.SystemRandom + log

### 5.3 频道追发
- [x] reply_to_message_id=channel_msg_id 让结果挂原帖下
- [x] 半匿名格式（首字* + uid 后 4）
- [x] 0 entries → "⚠️ 本次无人参与"
- [x] result_msg_id 写回 lotteries 表

### 5.4 私聊通知
- [x] 有客服 URL → [👨‍💼 联系管理员] 按钮
- [x] 客服 URL 缺失 → 文字 fallback "请联系频道管理员"
- [x] Forbidden / BadRequest silent skip + log
- [x] 成功 → mark_lottery_entry_notified

### 5.5 防重抽
- [x] 已 drawn / cancelled / no_entries → silent skip
- [x] 并发场景：mark_lottery_drawn 仅 active 才改
- [x] bot 重启过期 draw_at → run_date=now + misfire_grace_time（L.2）

### 5.6 调度集成
- [x] draw_job 替换 L.2 占位 → 实际 run_lottery_draw
- [x] LotteryDrawError / 通用异常仅 log（不让定时任务异常）

### 5.7 兼容
- [x] 9.1-9.6 / P.1-P.3 / L.1 / L.2 全部回归
- [x] schedule_pending_lotteries 已自动注册 draw job（L.2）

### 5.8 静态
- [x] python3 -m compileall bot
- [x] import bot.main OK

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 频道 send_message 失败（频道被删 / bot 权限丢失）| log warning + 不阻塞流程；DB 仍 drawn |
| 私聊 send_message 用户屏蔽 bot | silent skip + 不标记 notified_at；频道公布名单仍可见 |
| Telegram BadRequest（reply 锚消息丢失） | send_message 失败 → log；result_msg_id 仍 None；可手动 publish_result 重试 |
| 并发开奖（同时两个 worker 调）| mark_lottery_drawn 仅 active 才改，第二个 UPDATE 0 行 |
| secrets.SystemRandom 失败（极端 OS）| 回退 random.SystemRandom + log；再失败兜底前 n 个 + warning |
| 中奖者批量过多 / Telegram rate limit | 当前顺序 send_message；如需限流可在 _try_notify_winners 加 sleep |
| 客服链接配置后改 / 删 | 通知发送时实时读 config，新中奖者用新值 |
| bot 启动时大量过期抽奖 | misfire_grace_time=3600；超时不补发；admin 手动处理 |

---

## 7. 不在本 Phase 范围

- ❌ [👥 查看参与人员] 脱敏列表 → Phase L.4
- ❌ [✏️ 编辑 active 抽奖] → Phase L.4
- ❌ 客服链接配置入口（[👨‍💼 抽奖客服链接] in 系统设置） → Phase L.4
- ❌ 频道帖被删自动重发 → Phase L.4
- ❌ 中奖通知限流 / 重试机制
- ❌ 公开排行榜 / 商城 / 兑换

---

## 8. 完成后

Phase L.3 完成 → 立即开 Phase L.4（管理员工具完善）。

> Phase L.4 开始前需确认：
> - [👥 查看参与人员] 列表显示几条 / 分页
> - 客服链接配置 UI（系统设置入口 vs 抽奖管理入口）
> - 帖被删检测策略（定时 polling vs 编辑失败时检测）
> - active 编辑哪些字段（cover / draw_at / required_chats / entry_code 等）
