# 抽奖功能 - Spec v1.0 final

> 状态：**已锁定，待实施**
> 创建：2026-05-16 ｜ 最终：2026-05-16
> 关联：[POINTS-FEATURE-DRAFT.md](./POINTS-FEATURE-DRAFT.md) 积分系统（本期独立，不耦合）

---

## 0. 一句话目标

超管在 bot 后台配置抽奖活动 → bot 定时发布到频道 → 用户通过按键或口令参与（必须先关注配置的频道/群组）→ 定时到点自动开奖 → 中奖者私聊通知 + 频道公布名单。**全程结果由密码学安全随机数决定，管理员无法干预。**

---

## 1. 核心规则（全部锁定 ✅）

| 维度 | 决策 |
|---|---|
| 创建者 | 仅超级管理员 |
| 参与方式 | 按键抽奖 / 口令抽奖（创建时二选一） |
| 参与门槛 | 必须关注本次抽奖配置的频道/群组（每个抽奖独立配置） |
| 中奖概率 | **每位参与者完全等概率**，使用 `secrets.SystemRandom()` |
| 开奖方式 | **严格定时自动开奖**（基于 APScheduler）；**不允许超管提前触发** |
| 发布频道 | 主公示频道（与每日 14:00 publish 同频道，复用 `publish_target_chat_ids` 配置） |
| 中奖通知 | 私聊中奖者 + 在原抽奖帖追发开奖结果消息 |
| 联系管理员链接 | 由超管在系统设置中配置（用于中奖通知里的客服按钮） |
| 编辑权限 | **active 状态可编辑所有字段**（含时间、中奖人数、必关频道、口令等）|
| 一人一次 | 同一抽奖每用户最多参与 1 次（UNIQUE 约束）|
| 与积分系统耦合 | **本期不耦合**，抽奖不消耗积分 |

---

## 2. 抽奖类型

### 2.1 按键抽奖

抽奖帖底部带 [🎲 参与抽奖] inline 按钮。

用户点击按钮（URL deep link 到 bot 私聊）：
```
https://t.me/{bot_username}?start=lottery_{lottery_id}
```

私聊后 bot 走以下流程：
1. 关注校验（针对本次抽奖配置的必关频道列表）
2. 时间窗校验（必须在 `published_at <= now < draw_at` 之间）
3. 重复校验（用户是否已参与过同一抽奖）
4. 创建 `lottery_entries` 记录
5. 回复 `✅ 你已参与「{lottery_name}」抽奖，开奖时间 {draw_at}，请耐心等待。`

### 2.2 口令抽奖

抽奖帖说明文案中告知用户："在私聊里发送口令 `{entry_code}` 参与"。

用户在私聊给 bot 发送精确口令（区分大小写或不？默认**不区分**）：
1. bot 匹配该口令到对应 lottery（如有多个口令冲突，按创建时间最新的 active 抽奖优先）
2. 同 §2.1 后续流程

> 口令需在所有 active 抽奖中**全局唯一**，配置时校验。

---

## 3. 管理员配置抽奖（FSM）

### 3.1 主面板入口

仅超管可见：

```
[🔧 痴颜录管理面板]
  ...
  [🎲 抽奖管理]                    ← 新增
  ...
```

### 3.2 抽奖管理子菜单

```
🎲 抽奖管理

[➕ 创建新抽奖]
[📋 抽奖列表 (5)]              ← 含状态徽标
[🔙 返回主面板]
```

抽奖列表分 4 个状态：
- 📝 草稿（未发布）
- ⏰ 已计划（已配置 publish_at，等待自动发布）
- 🎯 进行中（已发布，等待 draw_at）
- 🏆 已开奖（已抽出中奖者）
- ❌ 已取消

### 3.3 创建新抽奖 FSM

```
[Step 1/10] 抽奖名称（必填，≤ 30 字）
回复抽奖名称：
[❌ 取消]

[Step 2/10] 活动规则 / 备注（必填，≤ 500 字）
回复规则描述：
[❌ 取消]

[Step 3/10] 上传封面图（可选）
发送一张图片，或点 [⏭ 跳过封面]
[⏭ 跳过封面] [❌ 取消]

[Step 4/10] 参与方式
[🎲 按键抽奖] [🔑 口令抽奖]
[❌ 取消]

[Step 4.5/10] 仅口令抽奖触发：
回复抽奖口令（≤ 20 字，区分中英文）：
（bot 校验全局唯一）
[❌ 取消]

[Step 5/10] 中奖人数（必填，1-100 之间整数）
[1] [3] [5] [10] [20] [50]
或回复整数
[❌ 取消]

[Step 6/10] 奖品描述（必填，≤ 100 字）
描述奖品内容（如"50 米现金"、"老师 PP 代金券"等）
[❌ 取消]

[Step 7/10] 必关频道/群组（≥ 1 项）
请添加本次抽奖要求用户必关的频道/群组。
[➕ 添加（输入 chat_id）]
[✅ 完成添加]
[❌ 取消]

bot 添加每项时自动校验（同 REVIEW §3.3）。

[Step 8/10] 定时发布时间
选择：
[⚡ 立即发布]
[⏰ 定时发布] → 文字输入 YYYY-MM-DD HH:MM
[❌ 取消]

[Step 9/10] 开奖时间（必填，且必须晚于发布时间）
文字输入 YYYY-MM-DD HH:MM：
[❌ 取消]

[Step 10/10] 预览 + 确认
（展示完整抽奖配置）
[✅ 确认保存] [✏️ 修改某项] [❌ 取消]
```

保存后：
- 立即发布 → 写 DB + 调度 draw_at 定时任务 + 立即发频道
- 定时发布 → 写 DB + 调度 publish_at + draw_at 两个定时任务

---

## 4. 抽奖帖在频道发布

**发布频道：复用现有 `publish_target_chat_ids` 配置**（即每日 14:00 publish 用的主公示频道）。

如有多个 publish target，抽奖帖发到**第一个频道**（一般也是主公示频道）。

### 4.1 帖子内容

```
🎉 {lottery_name}

📋 活动规则
{description}

🎁 奖品
{prize_description}

🏆 中奖人数：{prize_count}
⏰ 开奖时间：{draw_at}

📌 参与方式：
（按键抽奖）点击下方按钮 → 在私聊完成确认
（口令抽奖）在私聊给我发口令：{entry_code}

📋 参与门槛
请先加入以下频道/群组：
- {chat_1_name} ([点击加入]({invite_link_1}))
- {chat_2_name} ([点击加入]({invite_link_2}))
...

⚠️ 本次抽奖每人仅可参与 1 次
✳ Powered by @{bot_username}
```

### 4.2 按键抽奖底部 inline 键盘

```
[🎲 参与抽奖]   ← URL = t.me/{bot}?start=lottery_{id}
[👥 N 人已参与]  ← callback noop，定期更新数字
```

`[👥 N 人已参与]` 计数显示：
- 每 60s 后台任务（轻量）edit_message_reply_markup 更新按钮文字
- 或事件驱动：每次有人参与时编辑（限频，避免 Telegram API rate limit）

### 4.3 口令抽奖底部 inline 键盘

无 [🎲 参与抽奖] 按钮（要求用户私聊发口令）。仅 `[👥 N 人已参与]`。

### 4.4 帖子上方媒体（如有封面图）

抽奖帖以 photo + caption 形式发布，photo = `cover_file_id`。无封面则纯文字。

---

## 5. 开奖逻辑

### 5.1 定时触发

APScheduler 在 `draw_at` 时间自动调用 `run_lottery_draw(lottery_id)`：

```python
async def run_lottery_draw(lottery_id: int):
    """开奖：从 entries 中随机抽 prize_count 个用户。"""
    lottery = await get_lottery(lottery_id)
    if lottery["status"] != "active":
        return  # 已开奖 / 已取消，跳过
    
    entries = await list_lottery_entries(lottery_id)
    if len(entries) == 0:
        await mark_lottery_no_entries(lottery_id)
        # 频道帖编辑成"⚠️ 本次抽奖无人参与"
        return
    
    # 关键：用 secrets.SystemRandom 确保公平
    import secrets
    rng = secrets.SystemRandom()
    winner_count = min(lottery["prize_count"], len(entries))
    winners = rng.sample(entries, winner_count)
    
    for w in winners:
        await mark_entry_won(w["id"])
    
    await mark_lottery_drawn(lottery_id)
    await publish_lottery_result(lottery_id, winners)
    await notify_winners(lottery_id, winners)
```

`secrets.SystemRandom` 是 `random.SystemRandom`，使用操作系统 CSPRNG（`/dev/urandom`）。每个 entry 等概率被选中。

### 5.2 不允许超管手动触发

**本期严格只走定时自动开奖**，抽奖详情页**不提供 [🎯 立即开奖] 按钮**，避免任何"管理员可能干预"的怀疑空间。

超管只能：
- 在 draw_at 之前 → [❌ 取消抽奖]（status='cancelled'，无中奖者）
- 等到 draw_at 后 → 系统自动开奖，结果即定

### 5.3 开奖结果发布

bot 在原抽奖帖**追发一条新消息**作为结果（不编辑原帖，保持历史完整）：

```
🏆 {lottery_name} 开奖结果

恭喜以下 {N} 位中奖者：

1. {anonymized_winner_1}
2. {anonymized_winner_2}
3. ...

📦 奖品：{prize_description}
请中奖者于 7 日内在私聊联系管理员领取。

✳ Powered by @{bot_username}
```

中奖名单**默认半匿名**（同评价系统的 `小* (****6204)` 规则）。

### 5.4 中奖通知（私聊）

```
🎉 恭喜你中奖了！

活动：{lottery_name}
奖品：{prize_description}

请于 7 日内联系管理员领取奖品。
[👨‍💼 联系管理员] ← URL = config["lottery_contact_url"]
```

**"联系管理员"链接由超管在系统设置中配置**：

```
[⚙️ 系统设置]
  ...
  [👨‍💼 抽奖客服链接]   ← 新增
```

进入后：
- 输入 t.me/xxxxx 或 @username（自动转 t.me URL）
- 校验 URL 格式合法
- 存入 config 表 `config["lottery_contact_url"]`

未配置时中奖通知不附按钮，文字提示 "请联系频道管理员"。

### 5.5 未中奖用户

**不发私聊**（避免打扰）。用户可去频道帖看完整结果。

---

## 6. 数据模型

### 6.1 新表 `lotteries`

```sql
CREATE TABLE lotteries (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    description             TEXT NOT NULL,
    cover_file_id           TEXT,                          -- 封面图，可空
    entry_method            TEXT NOT NULL,                 -- 'button' / 'code'
    entry_code              TEXT UNIQUE,                   -- 口令抽奖时填，需全局唯一
    prize_count             INTEGER NOT NULL,
    prize_description       TEXT NOT NULL,
    -- 必关频道（JSON list of chat_id）
    required_chat_ids       TEXT NOT NULL,                 -- 至少 1 项
    -- 时间
    publish_at              TEXT NOT NULL,                 -- 计划发布时间（立即则填创建时间）
    draw_at                 TEXT NOT NULL,                 -- 计划开奖时间
    published_at            TEXT,                          -- 实际发布时间
    drawn_at                TEXT,                          -- 实际开奖时间
    -- 频道侧
    channel_chat_id         INTEGER,                       -- 发布频道 chat_id
    channel_msg_id          INTEGER,                       -- 抽奖帖 msg_id
    result_msg_id           INTEGER,                       -- 开奖结果消息 msg_id
    -- 状态
    status                  TEXT NOT NULL DEFAULT 'draft', -- draft/scheduled/active/drawn/cancelled/no_entries
    created_by              INTEGER NOT NULL,              -- 创建超管 id
    created_at              TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at              TEXT DEFAULT CURRENT_TIMESTAMP,
    CHECK (entry_method IN ('button','code')),
    CHECK (status IN ('draft','scheduled','active','drawn','cancelled','no_entries')),
    CHECK (prize_count BETWEEN 1 AND 1000)
);

CREATE INDEX idx_lotteries_status ON lotteries(status);
CREATE INDEX idx_lotteries_publish_at ON lotteries(publish_at, status);
CREATE INDEX idx_lotteries_draw_at ON lotteries(draw_at, status);
```

### 6.2 新表 `lottery_entries`

```sql
CREATE TABLE lottery_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id      INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    entered_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    won             INTEGER DEFAULT 0,             -- 1 表示中奖
    notified_at     TEXT,                          -- 已私聊通知中奖
    UNIQUE(lottery_id, user_id),                   -- 一人一次
    FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
);

CREATE INDEX idx_lottery_entries_won ON lottery_entries(lottery_id, won);
```

---

## 7. 状态机

```
[草稿 draft] 
    → admin 编辑 → 保存到 active 计划 [scheduled]
    OR → admin 选立即发布 → [active]

[scheduled] (已配置 publish_at，等待自动发布)
    → publish_at 到 → 自动发频道 → [active]
    → admin 取消 → [cancelled]

[active] (已发布，可参与)
    → draw_at 到 → 自动开奖 → [drawn] OR [no_entries]
    → admin 取消 → [cancelled]

[drawn] (已开奖) → 终态
[cancelled] (已取消) → 终态
[no_entries] (开奖时无人参与) → 终态
```

---

## 8. 边界情况

| 场景 | 处理 |
|---|---|
| 创建时口令冲突 | 拒绝 + 提示 "口令已被使用，请换一个" |
| 创建时必关频道列表为空 | 拒绝 + 提示 "至少配置 1 个必关频道/群组" |
| 创建时 draw_at <= publish_at | 拒绝 + 提示 "开奖时间必须晚于发布时间" |
| draw_at 时无人参与 | 标记 no_entries + 频道帖追发"⚠️ 本次抽奖无人参与" |
| 中奖人数 > 参与人数 | 全部参与者中奖（不抽满 prize_count） |
| 用户已退出某必关频道再来参与 | get_chat_member 检测出 left → 拒绝并展示链接 |
| 用户尝试在开奖后再点参与按钮 | 显示 "本次抽奖已结束" |
| 用户已参与又来 | 显示 "你已参与本次抽奖" |
| 同一口令绑定到多个 active 抽奖（理论不应发生）| 取最新创建的；下次创建口令时校验唯一性已避免 |
| 频道帖被删除（人为）| 自动重发到原 channel_chat_id，更新 channel_msg_id |
| `secrets.SystemRandom` 失败（操作系统极端）| 回退用 `random.SystemRandom()`，并写 audit log |
| 抽奖期间 bot 重启 | 启动时扫所有 status='scheduled'/'active' 的抽奖，重新注册定时任务 |
| 同一用户在多个 active 抽奖间互不干扰 | UNIQUE 是 (lottery_id, user_id)，跨抽奖独立 |

---

## 9. 与现有系统衔接

| 模块 | 影响 |
|---|---|
| 主面板（超管）| 新增 [🎲 抽奖管理] 入口 |
| `required_subscriptions` 表 | **不复用**，抽奖必关列表独立配置（每个抽奖可不同） |
| APScheduler | 添加抽奖发布 + 开奖定时任务；bot 重启时恢复 |
| `/start lottery_<id>` deep link | 新增；走关注校验后创建 entry |
| `user_events` | 新事件：`lottery_entry / lottery_won / lottery_lost` |
| `admin_audit_logs` | 创建 / 取消 / 提前开奖等动作落审计 |
| 已有的 [📋 必关频道/群组]（评价用）| 独立运行，与抽奖配置不冲突 |

---

## 10. 实施阶段（建议）

### Phase L.1 — DB + 草稿 / 编辑 / 列表

**范围：**
- `lotteries` + `lottery_entries` 两张表
- DB 方法：`create_lottery / get_lottery / list_lotteries_by_status / update_lottery / cancel_lottery`
- 主面板新增 [🎲 抽奖管理]
- 抽奖列表 + 详情查看（只读）
- 创建 FSM（保存为 draft）
- **不做**：频道发布、参与、开奖

**验收：** 超管能完整走完 10 步 FSM 创建抽奖；DB 字段齐全；列表能按状态分组展示。

---

### Phase L.2 — 频道发布 + 用户参与

**范围：**
- 立即发布 / 定时发布（APScheduler 调度）
- 抽奖帖渲染（含封面图 / inline 键盘）
- `/start lottery_<id>` deep link
- 用户参与流程：关注校验 → 时间窗校验 → 创建 entry
- 口令抽奖：私聊文字命中
- 帖子上 [👥 N 人已参与] 计数（定时更新或事件驱动 + 限频）

**验收：** 抽奖能按计划发到频道；用户能通过按键 / 口令参与；重复参与被拒；未关注频道被拒。

---

### Phase L.3 — 定时开奖 + 中奖通知

**范围：**
- APScheduler 在 draw_at 触发 `run_lottery_draw`
- 使用 `secrets.SystemRandom` 随机抽取
- 标记 winners + 抽奖状态变 drawn
- 频道追发开奖结果消息
- 私聊通知中奖者
- 无参与时标记 no_entries

**验收：** 定时开奖能自动执行；中奖结果公平随机；中奖者收到通知；频道发布完整名单。

---

### Phase L.4 — 管理员工具完善

**范围：**
- 抽奖详情页加 [👥 查看参与人员]（脱敏列表 + 分页）
- 抽奖详情页加 [✏️ 编辑抽奖]（**仅 active 状态可编辑所有字段**：名称 / 描述 / 封面 / 中奖人数 / 必关 / 开奖时间 / 口令；不可改的字段只在已开奖后锁定）
- 抽奖详情页加 [❌ 取消抽奖]（仅 active 状态）
- 系统设置加 [👨‍💼 抽奖客服链接] 配置
- 频道帖被删时自动重发
- bot 重启时扫已计划 / 进行中抽奖重注册定时任务

**编辑 active 抽奖的副作用处理：**
- 改 cover_file_id → 删旧帖 + 重发（无法 edit media）
- 改 draw_at → cancel 旧定时任务 + 注册新定时任务
- 改 entry_code → 校验全局唯一性
- 改 prize_count / required_chat_ids / 任何文字字段 → edit_message_caption 更新帖子文案

> ⚠️ **不提供 [🎯 立即开奖] 按钮** —— 严格按定时自动开奖，避免任何"管理员可干预"的疑虑。

---

## 11. 全部决策已确认 ✅

| 问题 | 决策 |
|---|---|
| 发布频道 | 复用现有公示频道 `publish_target_chat_ids` |
| 联系管理员链接 | 超管在系统设置 [👨‍💼 抽奖客服链接] 配置 t.me/xxx |
| 是否允许提前开奖 | **不允许**，严格按 draw_at 自动开奖 |
| 抽奖期间编辑 | active 状态可编辑**所有字段**（含时间、中奖人数、必关、口令等）|

---

## 附录 A：术语对照

| 中文 | 代码 |
|---|---|
| 抽奖 | `lottery` |
| 抽奖参与 | `lottery_entry` |
| 中奖者 | `winner` |
| 按键抽奖 | `entry_method='button'` |
| 口令抽奖 | `entry_method='code'` |
| 必关频道（抽奖独立配置）| `required_chat_ids` (JSON list in lotteries table) |
