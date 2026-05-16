# 老师档案 + 用户评价（车评）功能 - 最终 Spec v1.1

> 状态：**已敲定，待实施**
> 创建：2026-05-16 ｜ 最终：2026-05-16
> 别名：用户评价 / 用户报告 / 车评 / Review / Report（管理员后台用"报告审核"）

---

## 0. 一句话目标

本期实现 **三个互相关联的能力**：

1. **老师档案帖**：bot 后台录入老师完整资料 → bot 自动在公示频道发布"老师档案帖"
2. **用户车评提交**：用户在私聊提交评价（3 级评级 + 6 维度数值评分 + 综合评分 + 可选总结）
3. **超管审核 + 闭环**：超管审核通过 → 实时更新档案帖统计块 + 在讨论群档案帖评论区发布该评论

---

## 1. 全部决策（已锁定 ✅）

| 维度 | 决策 |
|---|---|
| **6 大评价维度** | 🎨 人照 / 颜值 / 身材 / 服务 / 态度 / 环境 |
| **维度形态** | 每维**纯数值评分 0.0-10.0**（1 位小数），无文字描述 |
| **评级** | 3 级 — 👍 好评 / 😐 中评 / 👎 差评 |
| **综合评分** | 用户提交，0.0-10.0（1 位小数），独立于 6 维分 |
| **总结** | 可选自由文本，5-100 字 |
| **提交资格** | 必须关注后台配置的指定频道/群组 |
| **提交次数** | 不限次，同用户多条独立显示 |
| **限频** | 60s × 1 / 同老师 24h × 3 / 全平台 24h × 10 |
| **署名** | 半匿名：`小* (id ****6204)` |
| **审核者** | 仅超级管理员 |
| **审核入口** | 超管主面板独立项「📝 报告审核 (M)」 |
| **新报告推送** | 仅超管立即私聊推送 |
| **通过通知** | 私聊 + 附「查看评价」按钮跳频道档案帖 |
| **频道发布形态** | bot 自动维护每位老师的**完整档案帖**（相册 + 资料 + 服务 + 价格 + 禁忌 + 统计块 + 标签）|
| **统计块更新** | 审核通过后实时编辑档案帖 caption |
| **评论区** | 讨论群档案帖的评论区，bot reply 锚消息 |
| **私聊详情页** | 底部展示统计块 + 最近 3 条评价 + 「查看全部」按钮 |
| **实施节奏** | 6 个 phase 缓慢推进 |

---

## 2. 用户提交评价流程

### 2.1 入口

私聊老师详情页底部新增 [📝 写评价] 按钮：

```
[📩 联系老师]
[⭐ 收藏] [🔔 提醒]
[✨ 相似推荐]
[📝 写评价]           ← 新增
[🔙 返回主菜单]
```

### 2.2 关注校验（提交第一道关卡）

点击后 bot 先用 `get_chat_member` 检查用户是否加入了**全部**配置的必关频道/群组。任一未加入 → 拒绝并展示链接列表：

```
⚠️ 提交评价前请先加入：

📺 痴颜录公示频道 [点击加入](https://t.me/...)
👥 痴颜录讨论群 [点击加入](https://t.me/...)

加入后回来重新点 [📝 写评价]。
[🔙 返回老师详情]
```

### 2.3 12 步 FSM（前置 3 步证据 + 9 步评分内容）

> **新增前置 3 步（A/B/C）作为反刷评证据链**：选老师 + 约课记录截图 + 现场手势照片。审核管理员将以这些材料作为审核依据。

```
[Step A/12] 选择老师（仅非按钮入口才触发）
请输入要提交报告的老师艺名（如：丁小夏）：
👇 回复老师艺名

bot 解析（**仅按艺名匹配，不接受数字 ID** —— 数字 ID 对用户获取太麻烦）：
- 先做精确匹配（不区分大小写）：`get_teacher_by_name(query)`
  → 命中唯一老师 → 展示确认页：
    `你要为 {display_name} 写报告吗？  [✅ 是的] [❌ 取消]`
    用户确认后跳到 Step B
- 精确匹配无果 → 模糊匹配（`display_name LIKE '%query%'`）
  → 命中 1 位 → 同上确认页
  → 命中多位（≤ 6）→ 展示候选按钮列表让用户点选
  → 命中超 6 位 → 提示 "找到 N 位匹配的老师，请输入更完整的艺名"
- 完全未找到 → 提示 "未找到该老师，请检查艺名是否正确后重发"，停留 Step A
- 找到但 is_active=0 → 提示 "该老师已停用，无法提交报告"

[❌ 取消]

> 📌 **Step A 仅在用户从"裸入口"进入时触发**（如未来加的主菜单 [📝 写报告]
>   按钮 / 私聊文字命令）。从以下入口进入时**老师已确定，直接跳过 Step A**：
>   - 老师详情页 [📝 写报告] 按钮
>   - `/start write_<teacher_id>` deep link
>   - 频道评论区 [🤖 给{name}写报告] 按钮（最终也走 deep link）

[Step B/12] 上传约课记录截图（必填）
请上传你和该老师的约课记录截图（一张图片）：
👇 直接发送图片
[❌ 取消]

校验：
- 必须是 photo 消息（不接受 document / video / sticker / 文字）
- 文件 size 上限 20MB（Telegram 限制）
- 仅取最大尺寸版本的 file_id 存库
- bot 在私聊回复"✅ 截图已收到"避免用户疑惑

[Step C/12] 上传现场手势照片（必填）
请上传你在见到老师后的现场手势照片（如比心/竖大拇指/伸 3 根手指等）。
这张照片仅作为审核证据，不会公开展示。
👇 直接发送图片
[❌ 取消]

校验：同 Step B

────────── 以下进入评分内容 ──────────

[Step 1/9] 评级（必填）
请选择你对老师的整体印象：
[👍 好评] [😐 中评] [👎 差评]
[❌ 取消]

[Step 2/9] 🎨 人照评分（照片真实度）（必填）
请打分 0.0 - 10.0：
[6.0] [7.0] [8.0] [9.0] [10.0]
[6.5] [7.5] [8.5] [9.5]
或回复数字（可带 1 位小数）
[❌ 取消]

[Step 3/9] 颜值评分（必填）
（同样的快捷按钮 + 文字输入）

[Step 4/9] 身材评分（必填）
[Step 5/9] 服务评分（必填）
[Step 6/9] 态度评分（必填）
[Step 7/9] 环境评分（必填）

[Step 8/9] 🎯 综合评分（必填）
请打个综合分 0.0 - 10.0：
[7.0] [7.5] [8.0] [8.5]
[9.0] [9.5] [10.0]
或回复数字
[❌ 取消]

[Step 9/9] 📝 过程描述（可选，5-100 字）
最后说一句你的整体感受 / 过程描述，会显示在评论区。
[⏭ 跳过] [❌ 取消]
```

**评分输入校验（Step 2-8）：**
- 必须能解析为浮点数；非数字 → "请输入 0-10 之间的数字"
- 范围：0.0 ≤ score ≤ 10.0
- 小数位 > 1 位（如 `8.55`）→ "最多 1 位小数"
- 校验通过 → `round(value, 1)` 归一化存储

**Step 9 过程描述校验：**
- 可跳过；若填写：长度 5-100 字
- 非文字（图片/贴纸）→ "请用文字回复"

**前置 3 步说明：**
- **Step A 只接受老师艺名，不接受数字 ID**（数字 ID 对用户获取太麻烦）
- Step A 仅在非按钮入口（如未来主菜单 [📝 写报告] / 私聊文字命令）触发；按钮 / deep link 入口已知 teacher_id，跳过 Step A 直接到 Step B
- Step B / C 的图片 file_id 存入 `teacher_reviews.booking_screenshot_file_id` / `gesture_photo_file_id`，必填
- 审核环节会将这两张图作为审核材料发给超管

### 2.4 确认页

```
你的报告预览：

老师：丁小夏
📸 约课截图：✅ 已上传
✋ 现场手势：✅ 已上传

评级：👍 好评 · 🎯 综合 8.6

🎨 人照：9.0
颜值：9.2
身材：8.5
服务：9.5
态度：9.7
环境：8.8

📝 过程：非常推荐，下次还会再约

[✅ 提交审核]
[✏️ 修改：约课截图] [✏️ 修改:手势照片]
[✏️ 修改：评级] [✏️ 修改:综合]
[✏️ 修改：人照] [✏️ 修改:颜值]
[✏️ 修改：身材] [✏️ 修改:服务]
[✏️ 修改：态度] [✏️ 修改:环境]
[✏️ 修改：过程]
[❌ 取消]
```

### 2.5 提交后反馈

```
✅ 评价已提交，等待管理员审核。
通常 24 小时内有结果，审核结果会私聊通知你。
[🔙 返回老师详情]
```

### 2.6 限频

| 阈值 | 触发后行为 |
|---|---|
| 同用户对同老师 24h > 3 条 | 拒绝 + 提示"今天该老师已超出限制" |
| 同用户全平台 24h > 10 条 | 拒绝 + 提示"今天已超出全平台限制" |
| 同用户 60s 内 > 1 条 | 拒绝 + 提示"提交太频繁，稍后再试" |

---

## 3. 必关频道/群组校验

### 3.1 管理员配置

系统设置新子页 [📋 必关频道/群组]：增删改查（chat_id / display_name / invite_link / is_active）。

### 3.2 校验函数

```python
async def check_user_subscribed(user_id: int) -> tuple[bool, list[dict]]:
    """对每个 active 配置项调 bot.get_chat_member(chat_id, user_id)。
    状态在 member/administrator/creator 视为已加入。"""
```

### 3.3 配置项添加时的预校验

bot 自动验证：
- chat_id 格式（数字，-100 前缀表示频道/超群）
- bot 已加入该频道/群组（`get_chat` 成功）
- bot 能查询成员（`get_chat_member(bot_id)` 成功）

任一失败 → 拒绝添加 + 提示原因。

### 3.4 列表为空 → 视为无门槛，跳过校验

---

## 4. 超管审核流程

### 4.1 主面板入口

仅 `is_super=1` 的管理员能看到：
```
[🔧 痴颜录管理面板]
  [📊 数据看板]
  [📝 待审核 (N)]          ← 老师改资料（已存在）
  [📝 报告审核 (M)]        ← 用户评价（新增，仅超管）
  ...
```

### 4.2 审核详情页

**进入审核时，bot 自动发送 2 条消息给超管：**

**消息 1：审核材料（media group 2 张图）**
- 第 1 张：约课记录截图（caption "📸 约课记录"）
- 第 2 张：现场手势照片（caption "✋ 现场手势"）

**消息 2：报告内容 + 审核按钮**

```
[报告审核 1/3]
老师：丁小夏
评价者：小* (uid: ****6204)
提交：2 分钟前

📸 审核材料：已在上方 2 张图
────────────────────
评级：👍 好评 · 🎯 综合 8.6
🎨 人照 9.0 | 颜值 9.2 | 身材 8.5
   服务 9.5 | 态度 9.7 | 环境 8.8
📝 过程：非常推荐，下次还会再约
────────────────────
[✅ 通过] [❌ 驳回]
[🖼 重看约课截图] [✋ 重看手势照片]
[⬅️ 上一条] [➡️ 下一条]
[🔙 返回主面板]
```

**审核交互细节：**
- 进入审核详情时一次性 send_media_group 发 2 张证据图
- 翻页时同样自动发新的证据图（每条 pending 都重发）
- [🖼 重看约课截图] / [✋ 重看手势照片] 按钮用于审核员需要再次细看时
- 评价通过/驳回不影响这两张图的保留（DB 记录 file_id，不主动删图）

### 4.3 驳回流程

点 [❌ 驳回] → 选原因（4 预设 + 自定义 + 跳过）→ DB status='rejected' + 私聊通知评价者。

### 4.4 通过流程

> ⚠️ **本流程会在积分系统 Phase P.1 上线后修改**：点 [✅ 通过] 后**先进入加分子页**（套餐选项），超管选完加分值再一次性 commit。详见 [POINTS-FEATURE-DRAFT.md](./POINTS-FEATURE-DRAFT.md) §3.1。

点 [✅ 通过] → 一次性触发：
1. `teacher_reviews.status = 'approved'` + reviewer_id + reviewed_at
2. 写 admin_audit_logs
3. **（积分系统就位后）写 point_transactions + users.total_points += delta**
4. **重算 teacher_channel_posts 缓存的聚合统计**
5. **edit_message_caption 更新频道档案帖**
6. **send_message 到讨论群（reply 档案帖锚消息）发布该评价**
7. 私聊通知评价者（含「查看评价」跳转按钮 + 本次积分增量）

### 4.5 新报告推送

bot 收到新提交后立即推送给超管（一组 media + 一条文字消息）：

**Media Group**：约课截图 + 手势照片（同审核详情页）

**文字消息**：
```
🆕 有新报告待审核

老师：丁小夏
评价者：小* (uid: ****6204)
评级：👍 好评 · 🎯 8.6/10
📝 过程：非常推荐

[前往审核] ← 跳 [📝 报告审核]
```

仅超管收到。普通管理员不会收到。

---

## 5. 私聊详情页评价区块

老师详情页底部增加（在 [✨ 相似推荐] 之上）：

```
👤 丁小夏
... (Phase 7.1 详情结构不变)
📌 适合：...

📊 35 条车评，综合评分 9.21
好评 100% | 人照 9.08 | 服务 9.07
中评 0.0% | 颜值 9.27 | 态度 9.63
差评 0.0% | 身材 8.94 | 环境 9.15

最近评价：
────────────────────
小* · 👍 好评 · 🎯 8.6
📝 非常推荐，下次还会再约
— 2026-05-16

匿* · 👍 好评 · 🎯 9.2
📝 可以再约
— 2026-05-15

群* · 😐 中评 · 🎯 6.5
（无总结）
— 2026-05-14
────────────────────
[📖 查看全部评价 (35)]

[📩 联系老师]
[⭐ 收藏] [🔔 提醒]
[✨ 相似推荐]
[📝 写评价]
[🔙 返回主菜单]
```

「查看全部评价」→ 分页（10 条/页）。

---

## 6. 频道侧：老师档案帖

### 6.1 帖子结构

bot 在公示频道为每位 active 老师发布一条永久档案帖：

**形式**：媒体组（1-10 张照片）+ caption 附在第一张照片上。

**caption 完整模板**（详见附录 D）：

```
👤 {display_name}

{description}

📋 基本资料
{age}岁 · 身高{height}cm · 体重{weight}kg · 胸{bra_size}

📋 服务内容
{service_content}

💰 价格
{price_detail}

🚫 禁忌
{taboos}

📊 {review_count} 条车评，综合评分 {avg_overall:.2f}
好评 {pos_pct:>5} | 人照 {avg_humanphoto:>5} | 服务 {avg_service:>5}
中评 {neu_pct:>5} | 颜值 {avg_appearance:>5} | 态度 {avg_attitude:>5}
差评 {neg_pct:>5} | 身材 {avg_body:>5} | 环境 {avg_environment:>5}

☎ 联系方式
电报：{contact_telegram}

🏷 分类标签
{hashtags joined with space}

✳ Powered by @{bot_username}
```

无评价时统计块用占位符：
```
📊 0 条评价，综合评分 0.00
好评 ----  | 人照 ----  | 服务 ----
中评 ----  | 颜值 ----  | 态度 ----
差评 ----  | 身材 ----  | 环境 ----
```

### 6.2 发布与更新

- **首次发布**：admin 在后台录完档案 + 上传照片 → 点击"📤 发布档案帖到频道" → bot `send_media_group`，记录返回的第一条 message_id 到 `teacher_channel_posts.channel_msg_id`
- **资料编辑**：admin 改了任意字段 → bot `edit_message_caption` 更新 caption
- **照片增删**：照片无法 edit_media_group，需要 admin 显式点"🔄 重发档案帖" → 删旧媒体组 + 重新 send_media_group
- **评价通过后自动更新统计块**：bot 重算聚合 + edit_message_caption

### 6.3 评论区（讨论群侧）

频道绑定讨论群后，每条频道帖会自动在讨论群创建对应"锚消息"。

bot 通过监听 `message.is_automatic_forward=True` 的事件捕获锚消息 id，存入 `teacher_channel_posts.discussion_anchor_id`。

审核通过后 bot 在讨论群发：
```
bot.send_message(
    chat_id=discussion_chat_id,
    text=<format_review_comment>,
    reply_markup=<3 个底部按钮>,
    reply_to_message_id=discussion_anchor_id,
)
```

**每条评论的格式**（使用 `【...】` 中括号风格 + 3 个底部按钮）：

```
【老师】：{display_name}
【留名】：{anonymized_name}
【人照】：{score_humanphoto}
【颜值】：{score_appearance}
【身材】：{score_body}
【服务】：{score_service}
【态度】：{score_attitude}
【环境】：{score_environment}
【综合】：{overall_score:.2f}
【过程】：{summary}

✳ Powered by @{bot_username}
```

**底部 3 个按钮**（inline keyboard，每个独占一行）：

```
[🔗 联系{display_name}]          ← URL = teacher.button_url
[{rating_emoji} {rating_label}]   ← callback "noop"，仅可视化评级
[🤖 给{display_name}写报告]       ← URL = t.me/{bot}?start=write_{teacher_id}
```

**展示规则：**
- 6 维度分数：保留用户输入精度（如 `9` 或 `8.5`，不强制 2 位小数）
- `【综合】`：固定保留 **2 位小数**（如 `9.83`）
- `【过程】` = `teacher_reviews.summary`；用户跳过总结时整行省略
- `display_name` 在 `联系...` / `写报告` 按钮文字过长时（> 20 字符）截断为 `联系{name前10字}...`
- 中间按钮 `[{rating_emoji} {rating_label}]` 是纯视觉徽章，callback 仅 answer 不做事

**新增 deep link：** `/start write_<teacher_id>` → 已加入必关频道的用户直接进入该老师的报告提交 FSM；未加入则正常走关注校验拦截。

---

## 7. 数据模型

### 7.1 `teachers` 表扩展（在 init_db 中通过 _migrate 函数 ALTER）

新增字段（全部 NULLABLE，已有老师可逐步补全）：

```sql
ALTER TABLE teachers ADD COLUMN age INTEGER;
ALTER TABLE teachers ADD COLUMN height_cm INTEGER;          -- 身高 cm
ALTER TABLE teachers ADD COLUMN weight_kg INTEGER;          -- 体重 kg
ALTER TABLE teachers ADD COLUMN bra_size TEXT;              -- A/B/C/D/E/...
ALTER TABLE teachers ADD COLUMN description TEXT;           -- 个性/风格简介
ALTER TABLE teachers ADD COLUMN service_content TEXT;       -- 服务内容详述
ALTER TABLE teachers ADD COLUMN price_detail TEXT;          -- 价格详述
ALTER TABLE teachers ADD COLUMN taboos TEXT;                -- 禁忌列表
ALTER TABLE teachers ADD COLUMN contact_telegram TEXT;      -- 电报 username 如 @lvluo520
ALTER TABLE teachers ADD COLUMN photo_album TEXT;           -- JSON list of file_ids（媒体组）
```

> 旧的 `photo_file_id` 保留兼容，新逻辑读 `photo_album`；若空则回退 `photo_file_id`。

### 7.2 `teacher_reviews`

```sql
CREATE TABLE teacher_reviews (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id                  INTEGER NOT NULL,
    user_id                     INTEGER NOT NULL,
    -- 审核证据（前置 3 步收集，必填）
    booking_screenshot_file_id  TEXT NOT NULL,        -- 约课记录截图 Telegram file_id
    gesture_photo_file_id       TEXT NOT NULL,        -- 现场手势照片 Telegram file_id
    -- 3 级评级
    rating                      TEXT NOT NULL,        -- positive / neutral / negative
    -- 6 个维度的数值评分
    score_humanphoto            REAL NOT NULL,        -- 人照 0-10
    score_appearance            REAL NOT NULL,        -- 颜值
    score_body                  REAL NOT NULL,        -- 身材
    score_service               REAL NOT NULL,        -- 服务
    score_attitude              REAL NOT NULL,        -- 态度
    score_environment           REAL NOT NULL,        -- 环境
    -- 综合评分（用户自己打的总分）
    overall_score               REAL NOT NULL,        -- 0-10
    -- 可选过程描述（公开展示）
    summary                     TEXT,                 -- NULL or 5-100 字
    -- 状态机
    status                      TEXT NOT NULL DEFAULT 'pending',
    reviewer_id                 INTEGER,
    reject_reason               TEXT,
    -- 频道侧消息
    discussion_chat_id          INTEGER,              -- published 后存
    discussion_msg_id           INTEGER,
    created_at                  TEXT DEFAULT CURRENT_TIMESTAMP,
    reviewed_at                 TEXT,
    published_at                TEXT,
    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE,
    CHECK (
        score_humanphoto BETWEEN 0 AND 10 AND
        score_appearance BETWEEN 0 AND 10 AND
        score_body BETWEEN 0 AND 10 AND
        score_service BETWEEN 0 AND 10 AND
        score_attitude BETWEEN 0 AND 10 AND
        score_environment BETWEEN 0 AND 10 AND
        overall_score BETWEEN 0 AND 10
    )
);

-- 不限次提交 → 无 UNIQUE 约束
CREATE INDEX idx_reviews_teacher_status ON teacher_reviews(teacher_id, status);
CREATE INDEX idx_reviews_status_created ON teacher_reviews(status, created_at);
CREATE INDEX idx_reviews_user_created ON teacher_reviews(user_id, created_at);
```

### 7.3 `teacher_channel_posts`

```sql
CREATE TABLE teacher_channel_posts (
    teacher_id              INTEGER PRIMARY KEY,
    channel_chat_id         INTEGER NOT NULL,
    channel_msg_id          INTEGER NOT NULL,         -- 档案帖（媒体组第一条）id
    media_group_msg_ids     TEXT,                     -- JSON list: 全部 media_group 消息 id
    discussion_chat_id      INTEGER,                  -- 绑定的讨论群（可能 NULL）
    discussion_anchor_id    INTEGER,                  -- 讨论群里对应锚消息 id
    -- 聚合统计（基于 approved reviews，每次审核通过后重算）
    review_count            INTEGER DEFAULT 0,
    positive_count          INTEGER DEFAULT 0,
    neutral_count           INTEGER DEFAULT 0,
    negative_count          INTEGER DEFAULT 0,
    avg_overall             REAL DEFAULT 0,
    avg_humanphoto          REAL DEFAULT 0,
    avg_appearance          REAL DEFAULT 0,
    avg_body                REAL DEFAULT 0,
    avg_service             REAL DEFAULT 0,
    avg_attitude            REAL DEFAULT 0,
    avg_environment         REAL DEFAULT 0,
    created_at              TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at              TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES teachers(user_id) ON DELETE CASCADE
);
```

### 7.4 `required_subscriptions`

```sql
CREATE TABLE required_subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL UNIQUE,
    chat_type    TEXT NOT NULL,           -- channel / group / supergroup
    display_name TEXT NOT NULL,
    invite_link  TEXT NOT NULL,
    sort_order   INTEGER DEFAULT 0,
    is_active    INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 7.5 配置常量

```python
# bot/database.py
REVIEW_DIMENSIONS = [
    {"key": "humanphoto",   "label": "🎨 人照",   "column": "score_humanphoto"},
    {"key": "appearance",   "label": "颜值",      "column": "score_appearance"},
    {"key": "body",         "label": "身材",      "column": "score_body"},
    {"key": "service",      "label": "服务",      "column": "score_service"},
    {"key": "attitude",     "label": "态度",      "column": "score_attitude"},
    {"key": "environment",  "label": "环境",      "column": "score_environment"},
]
REVIEW_RATINGS = [
    {"key": "positive", "emoji": "👍", "label": "好评"},
    {"key": "neutral",  "emoji": "😐", "label": "中评"},
    {"key": "negative", "emoji": "👎", "label": "差评"},
]

REVIEW_SCORE_MIN = 0.0
REVIEW_SCORE_MAX = 10.0
REVIEW_SCORE_DECIMAL_PLACES = 1
REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM = [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0]
REVIEW_SCORE_QUICK_BUTTONS_FOR_OVERALL = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0]

REVIEW_SUMMARY_MIN_LEN = 5
REVIEW_SUMMARY_MAX_LEN = 100
REVIEW_SUMMARY_REQUIRED = False             # 可跳过

REVIEW_RATE_LIMIT_PER_TEACHER_24H = 3
REVIEW_RATE_LIMIT_PER_USER_DAY = 10
REVIEW_RATE_LIMIT_PER_USER_60S = 1
```

---

## 8. 与现有系统的衔接

| 模块 | 影响 |
|---|---|
| `teachers` 表 | 新增 10 个 NULLABLE 列 |
| `teacher_flow.py`（老师录入 FSM） | 扩展：增加新字段的录入步骤 |
| `admin_panel.py` | 主面板对超管新增 [📝 报告审核 (M)]；老师管理子菜单加 [📋 老师档案管理] |
| `daily publish (scheduler/tasks.py)` | **不变** — 14:00 每日列表帖照常发，独立于档案帖 |
| `teacher_detail.py` | 详情页底部加评价区块 + [📝 写评价] |
| `user_events` | 新事件：review_submit / approve / reject / view / subscription_check_fail |
| `user_tags` | 提交者 +"评论型用户"画像 |
| `admin_audit_logs` | 每次审核动作落审计 |
| 系统设置 | 新子页 [📋 必关频道/群组] + [💬 评价讨论群绑定] |

---

## 9. 边界情况

| 场景 | 处理 |
|---|---|
| 老师档案数据不完整 | 缺字段处显示"（未填写）"；档案帖只在所有必填字段齐备后才允许发布 |
| 老师停用 | 已发档案帖不删除；新评价拒绝提交（"该老师已停用"）|
| 老师删除 | ON DELETE CASCADE 评价 + 软删除档案帖（caption 加"⚠️ 已下架"） |
| 老师改照片 | 媒体组无法 edit_media，admin 需手动点"🔄 重发档案帖" |
| 老师改文字字段 | bot 自动 edit_message_caption 更新档案帖 |
| 用户无权写评价（未关注） | 拒绝 + 链接列表 |
| 用户撤回 | Phase 9.x 才支持；目前仅 pending 可由 admin 删除 |
| 评论锚消息丢失 | 自动重建 + 告警超管 |
| 频道未绑定讨论群 | 档案帖照发；评价通过仍存 DB；跳过讨论群 reply；admin 配置后追溯发布 |
| 必关列表为空 | 视为无门槛 |
| bot 不在某必关频道 | 配置时拒绝；运行时该项跳过 + 告警 |
| 用户限频 | 拒绝 + 提示剩余次数 / 冷却时间 |
| 综合评分 vs 6 维平均的差异 | 综合评分是用户主观打的总分，可与 6 维平均有差异，不强制一致 |
| 档案帖 caption 超 1024 字符 | 在生成时截断老师描述/服务内容（保统计块完整）|
| 上传图片消息体过大 (>20MB) | Telegram 自动拒收，bot 在文字消息提示用户压缩后重发 |
| 用户上传非图片消息（文字 / 视频 / 文件 / 贴纸）| 停留当前步 + 提示 "请上传一张图片"，FSM 状态不前进 |
| 上传图片 file_id 失效（极少见）| 提交时正常存；若审核员重看时拉不到图，回退为提示 "图片已过期"，但不阻塞审核 |
| 选老师 Step A 输入无法匹配 | 提示 "未找到该老师"，停留 Step A，允许重试或 [❌ 取消] |

---

## 10. 实施阶段拆分（6 phase）

### Phase 9.1 — 老师档案数据扩展 + 后台录入 FSM

**范围：**
- `teachers` 表扩展 10 个字段（迁移函数幂等，新增字段对老数据为 NULL）
- 扩展 `teacher_flow.py`：**新建老师走完整 FSM，必填字段必须全部录完才能完成**（不允许半成品）
- 新增 admin 子菜单 [📋 老师档案管理]：
  - ➕ **添加新老师**（完整 FSM —— 详见下方"新建老师 FSM"）
  - ✏️ 编辑字段（每字段单独修改，给老数据用）
  - 🖼 上传/替换照片相册（最多 10 张）
  - 👁 预览档案（生成 caption 显示但不发频道）
- **不做**：频道发布；评价表；评论区

**必填 vs 可选 字段定义：**

| 字段 | 必填？ | 备注 |
|---|---|---|
| display_name | ✅ 必填 | 沿用现有 |
| age | ✅ 必填 | 新增 |
| height_cm | ✅ 必填 | 新增 |
| weight_kg | ✅ 必填 | 新增 |
| bra_size | ✅ 必填 | 新增 |
| price_detail | ✅ 必填 | 新增（与现有 price 字段并存，price 用于排序/筛选）|
| contact_telegram | ✅ 必填 | 新增（如 `@lvluo520`）|
| photo_album | ✅ 必填，至少 1 张 | 新增（JSON list of file_ids）|
| region | ✅ 必填 | 沿用现有 |
| price | ✅ 必填 | 沿用现有 |
| tags | ✅ 必填，至少 1 个 | 沿用现有 |
| button_url | ✅ 必填 | 沿用现有 |
| ─ 以下可选 ─ | | |
| description | ⏭ 可选 | 缺失时档案帖该段省略 |
| service_content | ⏭ 可选 | 缺失时档案帖该段省略 |
| taboos | ⏭ 可选 | 缺失时档案帖该段省略 |
| button_text | ⏭ 可选 | 沿用现有 |
| photo_file_id | ⏭ 兼容字段 | 老数据；photo_album 优先 |

**新建老师 FSM 步骤（一次性走完 8 步 + 照片上传）：**

```
Step 1/9: 艺名 (display_name) — 文字
Step 2/9: 基本信息 — 一行填齐：年龄 / 身高 / 体重 / 罩杯
          例："25 172 90 B"
          bot 解析为 age=25, height_cm=172, weight_kg=90, bra_size='B'
Step 3/9: 简介 (description) — 文字，可填"跳过"
Step 4/9: 服务内容 (service_content) — 文字，可填"跳过"
Step 5/9: 价格详述 (price_detail) — 文字
Step 6/9: 禁忌 (taboos) — 文字，可填"跳过"
Step 7/9: 联系电报 (contact_telegram) — 必须以 @ 开头
Step 8/9: 地区 / 价格 (排序用) / 标签 / 跳转链接 / 按钮文字
          (复用现有 teacher_flow.py 的 7-步原录入流程)
Step 9/9: 📸 上传照片（最多 10 张）
          发送 1-10 张图片即组成相册；发送"完成"结束本步
```

完成后展示档案预览 + [✅ 保存] / [✏️ 修改] / [❌ 取消]。

**现有 75 位老师的处理：**

迁移后 NULL 字段不影响既有功能（daily 14:00 publish / 群组关键词响应 / 收藏等照旧）。但**档案帖发布需要补全必填字段**：
- admin 进入 [📋 老师档案管理] → 选老师 → 走 ✏️ 编辑字段逐项补全
- 必填字段全部齐备后，admin 才能点 [📤 发布档案帖到频道]

**验收：**
- admin 能录完整老师档案（新建一次性走完）
- 现有老师数据保留，新字段为 NULL
- caption 预览符合截图格式
- 必填字段未齐备时拒绝发布档案帖并提示缺哪些字段

---

### Phase 9.2 — 档案帖自动发布到频道

**范围：**
- 新表：`teacher_channel_posts`
- admin 子菜单加 [📤 发布档案帖] / [🔄 重发档案帖] / [✏️ 编辑后更新]
- bot 实现 `publish_teacher_post(teacher_id)`：
  - 校验必填字段齐备
  - `send_media_group` 发布（caption 在第一条）
  - 记录 `channel_msg_id` + `media_group_msg_ids`
- bot 实现 `update_teacher_post_caption(teacher_id)`：
  - 重算或读 cached stats
  - 生成 caption
  - `edit_message_caption`
- bot 实现 `repost_teacher_post(teacher_id)`：删旧 + 发新
- admin 编辑字段后自动触发 `update_teacher_post_caption`
- **不做**：评价 / 评论区

**验收：** admin 点"📤 发布"后频道出现完整档案帖；编辑字段后档案帖自动更新；统计块显示 `0 条车评 ... ----` 占位符。

---

### Phase 9.3 — 必关校验 + 报告 FSM + DB

**范围：**
- 新表：`required_subscriptions` + `teacher_reviews`（含 2 个证据 file_id 字段）
- 系统设置新子页 [📋 必关频道/群组]
- 报告 FSM：关注校验 → **前置 3 步（选老师 / 上传约课截图 / 上传手势照片）** → 9 步评分 → 确认页 → DB pending
  - 入口已带 teacher_id 时跳过 Step A 选老师
  - 图片上传步骤校验 file_size + photo 消息类型
- 评价者画像 +"评论型用户"标签
- 限频校验
- **不做**：审核 UI；档案帖更新；详情页展示

**验收：**
- 未关注用户被拒；已关注用户能完整 12 步走完
- 约课截图 / 手势照片正确存 file_id（DB 字段非空）
- 上传非图片消息（文字 / 视频 / 文件）被拒并停留当前步
- DB 正确存评价（2 个 file_id + rating + 7 个 score + summary）
- 限频生效

---

### Phase 9.4 — 超管审核中心 + 私聊通知

**范围：**
- 主面板对 super_admin 新增 [📝 报告审核 (M)]
- 进入每条审核时**自动 send_media_group 发 2 张证据图**（约课截图 + 手势照片）
- 审核详情消息（接在 media group 之后）：
  - 完整报告内容（评级 + 7 个 score + 过程描述）
  - 按钮：[✅ 通过] [❌ 驳回] [🖼 重看约课截图] [✋ 重看手势照片] [⬅️ 上一条] [➡️ 下一条] [🔙 返回]
- [🖼 重看...] 按钮 callback 单独发该 file_id 的图
- 翻页（上一条 / 下一条）时自动发新的证据图
- 驳回原因 FSM
- 通过 / 驳回后私聊评价者
- 新评价立即推送超管（推送消息含 2 张证据图 + 报告概要）
- 写 admin_audit_logs
- **不做**：档案帖统计更新；评论区发布

**验收：**
- 超管进入每条审核都能看到 2 张证据图
- 普通管理员看不到入口
- 评价者收到结果通知
- 超管收到每条新报告推送（含证据图）
- 翻页时证据图正确切换

---

### Phase 9.5 — 档案帖统计块自动更新 + 讨论群评论发布

**范围：**
- 通过审核时一次性触发：
  1. 重算 `teacher_channel_posts` 缓存的聚合统计（review_count / 三级 count / 6 维 + 综合的平均）
  2. `edit_message_caption` 更新档案帖
  3. 监听 `is_automatic_forward` 捕获讨论群锚消息 id（首次老师档案帖创建时一并捕获）
  4. `send_message(reply_to_message_id=anchor)` 发评论（按附录 E 文本格式）
  5. 附 3 个底部 inline 按钮：[🔗 直连{name}] / [{rating_emoji} {rating_label}] / [🤖 给{name}写车评]
  6. 存 `discussion_chat_id` + `discussion_msg_id`
- 新增 `/start write_<teacher_id>` deep link 路由（必关校验 → 直接进 ReviewSubmissionStates Step 1）
- 新增 callback handler `noop:rating`（仅 answer，不动作）
- 锚消息丢失自动重建 + 告警

**验收：**
- 通过的评价立即出现在档案帖评论区，文本按 `【...】` 中括号格式渲染
- 3 个底部按钮可点击并跳转到正确目标
- `/start write_<teacher_id>` 能直达评价 FSM
- 档案帖统计块实时更新；好评/中评/差评 % 与各维度平均分计算正确

---

### Phase 9.6 — 私聊详情页展示

**范围：**
- 详情页底部加统计块（同档案帖格式）+ 最近 3 条评价
- 新 callback `teacher:reviews:<id>` 分页全部评价
- 半匿名签名渲染
- **可选**：评价数 / 平均分纳入推荐排序加权

**验收：** 详情页统计块格式正确；最近 3 条评价行展示符合规范；分页可翻完。

---

## 11. 全部决策已确认 ✅

所有设计决策已敲定，可作为 Phase 9.x 工单依据：
- 老师档案数据：扩展 10 个字段
- 6 维度评价：纯数值评分 0-10 + 综合评分 + 3 级评级 + 可选总结
- 频道侧：完整档案帖（媒体组 + 综合 caption） + 评论区评价
- 审核：仅超管 + 实时更新档案帖统计块
- 实施：6 个独立 phase 缓慢推进

---

## 附录 A：术语对照

| 中文 | 代码 |
|---|---|
| 用户评价 / 车评 / 报告 | `review` |
| 评级（好评/中评/差评） | `rating` |
| 6 维度评分 | `score_<dim>` (humanphoto/appearance/body/service/attitude/environment) |
| 综合评分 | `overall_score` |
| 老师档案帖 | `teacher_channel_post` |
| 必关频道/群组 | `required_subscription` |
| 半匿名签名 | `anonymized_name` |
| 评价 FSM | `ReviewSubmissionStates` |
| 老师录入 FSM | `TeacherAddStates` (扩展) |

## 附录 B：驳回原因预设模板

1. 内容不符合社区规范
2. 疑似刷评 / 重复内容
3. 包含敏感信息（联系方式 / 链接 / 暴露隐私）
4. 评分明显失实
5. 自定义原因（FSM 输入）

## 附录 C：半匿名签名规则

```python
def anonymize_name(user: dict) -> str:
    """规则：first_name 首字 + '*'，加 (id 后 4 位) 后缀

    Examples:
        first_name='小明' user_id=12876204 → '小* (****6204)'
        first_name=''     user_id=12876204 → '匿* (****6204)'
        first_name='A'    user_id=12876204 → 'A* (****6204)'
    """
```

## 附录 D：老师档案帖完整 caption 模板

```
👤 {display_name}

{description}

📋 基本资料
{age}岁 · 身高{height_cm}cm · 体重{weight_kg}kg · 胸{bra_size}

📋 服务内容
{service_content}

💰 价格
{price_detail}

🚫 禁忌
{taboos}

📊 {review_count} 条车评，综合评分 {avg_overall:.2f}
好评 {pos_pct:>5} | 人照 {avg_humanphoto:>5} | 服务 {avg_service:>5}
中评 {neu_pct:>5} | 颜值 {avg_appearance:>5} | 态度 {avg_attitude:>5}
差评 {neg_pct:>5} | 身材 {avg_body:>5} | 环境 {avg_environment:>5}

☎ 联系方式
电报：{contact_telegram}

🏷 分类标签
{hashtags}

✳ Powered by @{bot_username}
```

**占位符规则（无评价时）：**
- `review_count` = 0
- `avg_overall` = `"0.00"`
- 所有 percentage / 各维度均值 = `"----"`

**格式细节：**
- 各维度平均分保留 **2 位小数**（如 `9.08`）
- 好评/中评/差评 百分比保留 **1 位小数 + %**（如 `100.0%`）
- 字段缺失（如老师没有 description）→ 整段省略，不显示空标题
- caption 总长度超 1024 字符 → 截断 description / service_content / price_detail / taboos（按优先级从前往后保留 + 末尾 `...`）

## 附录 E：评论区单条评价格式（讨论群发布）

文本部分（中括号 `【...】` 风格）：

```
【老师】：{display_name}
【留名】：{anonymized_name}
【人照】：{score_humanphoto}
【颜值】：{score_appearance}
【身材】：{score_body}
【服务】：{score_service}
【态度】：{score_attitude}
【环境】：{score_environment}
【综合】：{overall_score:.2f}
【过程】：{summary}

✳ Powered by @{bot_username}
```

底部 inline keyboard（每按钮独占一行）：

| 按钮 | 类型 | 目标 |
|---|---|---|
| `🔗 联系{display_name}` | URL | `teacher.button_url`（normalize_url 后）|
| `{rating_emoji} {rating_label}` | callback `noop:rating` | 纯视觉徽章，answer 不弹任何提示 |
| `🤖 给{display_name}写报告` | URL | `t.me/{bot}?start=write_{teacher_id}` |

**展示规则补充：**
- 6 维度分数：原样保留用户输入精度（整数或 1 位小数）
- `综合`：固定 2 位小数
- `summary` 为空：`【过程】` 这一行整行省略，不留空
- `button_url` 无效（normalize_url 返回 None）：第一个按钮整行不渲染
- 按钮文字 `联系{name}` / `给{name}写报告` 超 20 字符时截断 `name` 至 10 字 + `...`
- `noop:rating` callback handler 仅 `await callback.answer()`，不弹消息

**新增 deep link：** `/start write_<teacher_id>` → 报告提交快捷入口
- 普通用户：走关注校验 → 命中则直接进入该老师的报告提交 FSM（从 Step B 上传约课截图开始；跳过 Step A 选老师）
- 管理员 / 老师：忽略此参数，正常显示自己的菜单
- teacher_id 不存在 / 已停用：跳主菜单 + 提示 "该老师暂不可写报告"
