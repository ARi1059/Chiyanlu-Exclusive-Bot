# 抽奖规则说明

> 本文档面向运营人员、管理员与超管。内容根据当前代码（截至 2026-05-18）整理。所有规则以代码实际行为为准；模糊或未明确处标注 **"需产品确认"**。

---

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

## 十三、相关文档

- 积分规则（扣分 / 退款 / 余额）：[`POLICY-points.md`](POLICY-points.md)
- 报销规则（独立子系统）：[`POLICY-reimbursement.md`](POLICY-reimbursement.md)
- 部署与备份：[`DEPLOYMENT.md`](DEPLOYMENT.md)
- 稳定化审查：[`STABILITY-AUDIT-2026-05-18.md`](STABILITY-AUDIT-2026-05-18.md)
