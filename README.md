# Chiyanlu-Exclusive-Bot

**痴颜录 Telegram 私域运营 Bot** —— 一个面向社区运营的 Telegram 中台。

老师签到 + 每日发布 + 群组关键词为底盘，叠加老师档案、用户中台、卡片化评价、积分、报销、必关订阅、推广追踪、发布模板、日报 / 周报、运营看板。单进程 polling，SQLite WAL 单文件，systemd 直跑。

> 本文档以"功能 → 入口 / 展示 / 操作"为主线，覆盖代码实际能力（截至 2026-05-23 Phase A0）。完整产品设计见 [`docs/DESIGN.md`](docs/DESIGN.md)，运营政策见 [`docs/POLICY.md`](docs/POLICY.md)。

---

## 目录

- [角色与入口](#角色与入口)
- [一、普通用户功能](#一普通用户功能)
- [二、老师功能](#二老师功能)
- [三、群组功能](#三群组功能)
- [四、管理员后台](#四管理员后台)
- [五、超管专属功能](#五超管专属功能)
- [六、自动化与调度](#六自动化与调度)
- [七、Deep Link 速查](#七deep-link-速查)
- [八、技术栈与数据库](#八技术栈与数据库)
- [九、项目结构](#九项目结构)
- [十、部署与运维](#十部署与运维)
- [十一、常见问题](#十一常见问题)
- [相关文档](#相关文档)

---

## 角色与入口

| 角色 | 唤起方式 | 私聊菜单 |
|---|---|---|
| **普通用户** | 私聊 Bot 发 `/start` | 11 按钮 + 1 聚合页（[详见](#一普通用户功能)） |
| **老师** | 私聊 Bot 发 `/start` 或文字「签到」 | 2 按钮（签到 / 我的资料） |
| **管理员** | 私聊 Bot 发 `/admin` 或 `/start` | 6 行后台主菜单（含 pending 角标） |
| **超管** | 同管理员 | 多一组超管专属入口（管理员管理 / 活动运营 / 报销审核 / 报销配置等） |

`/start` 由 [`bot/handlers/start_router.py`](bot/handlers/start_router.py) 根据角色自动分流：管理员 > 老师 > 普通用户。

普通用户**首次** `/start` 看到 4 按钮的新手引导（今日开课 / 热门推荐 / 直接搜索 / 进入主菜单），点击任意一个后标记"已看过"，下次进入直接显示主菜单。

---

## 一、普通用户功能

### 1.1 私聊主菜单

**入口**：私聊 Bot → `/start` → 任意子菜单点 `🔙 返回主菜单`（callback `user:main`）

**展示**：

```
👋 欢迎使用痴颜录 Bot

你想怎么找？

[🔎 找老师]
[📚 今天能约谁] [🎯 帮我推荐]
[🔎 按条件找]   [🔥 热门推荐]
[⭐ 我的收藏]   [🔍 直接搜索]
[💝 收藏开课]   [🔔 我的提醒]
[💰 我的积分]   [🧾 我的报销]
[📝 写评价]
```

**说明**：Phase A0（2026-05-23）已下线 🎁 抽奖中心 / 📜 搜索历史 / 🕘 最近看过 / 📝 我的记录聚合。

---

### 1.2 🔎 找老师（聚合页）

**入口**：主菜单 `[🔎 找老师]`（callback `user:find`）

**展示**：

```
🔎 找老师
请选择找老师方式：

🔥 热门推荐：查看当前热门老师
📚 今天能约谁：查看今日可约老师
🔎 按条件找：按地区 / 价格 / 标签筛选

[🔥 热门推荐] [📚 今天能约谁]
[🔎 按条件找]
[⬅️ 返回主菜单]
```

**操作**：聚合 3 个查找入口，便于把"找老师"集中收口；按钮点击进入对应子模块。

---

### 1.3 📚 今天能约谁

**入口**：主菜单 `[📚 今天能约谁]`（callback `user:today`）

**展示**：当日已签到老师按热度排序的列表，每条 `[艺名]` 按钮直接进详情页（返回按钮智能识别为"返回今日可约"）。

**操作**：点击老师 → 进 1.10 详情页；空列表时引导回主菜单。

---

### 1.4 🎯 帮我推荐

**入口**：主菜单 `[🎯 帮我推荐]`（callback `user:recommend`）

**展示**：基于用户画像（`user_tags`）+ 老师热度评分的个性化列表；底部 `[🔄 换一批]` 在候选池中随机打散。

**操作**：

- 无画像数据时自动回退到"热门推荐"。
- 点 `🔄 换一批` 重新洗牌。
- 短状态文案：今日可约 / 今日已取消 / 今日已满 / 今日暂未开课。

---

### 1.5 🔎 按条件找

**入口**：主菜单 `[🔎 按条件找]`（callback `user:filter`）

**展示**：筛选首页，4 行入口：

```
[📍 地区] [💰 价格]
[🏷 标签]
[📚 今日可约] [🔥 热门] [✨ 最近上新]
[🔙 返回主菜单]
```

**操作**：

1. 选维度 → 展示该维度的可选项（用 FSM 索引避免 callback_data 中文越界）。
2. 选具体值 → 立即出搜索结果（同款详情列表 keyboard）。
3. 命中 0 条 → 自动建议改用其它维度。

筛选状态机：[`bot.states.user_states.FilterStates`](bot/states/user_states.py)。

---

### 1.6 🔥 热门推荐

**入口**：主菜单 `[🔥 热门推荐]`（callback `user:hot`）

**展示**：管理员预置 + 系统计算热度分综合排序的老师列表。

**操作**：列表展示，点老师进详情页（返回按钮文案"返回热门推荐"）。

---

### 1.7 ⭐ 我的收藏（增强版）

**入口**：主菜单 `[⭐ 我的收藏]`（callback `user:favorites`）

**展示**：

```
⭐ 我的收藏

今日可约：3 · 今日未签到：5 · 总收藏：8

📋 #1 老师艺名
[👀 查看详情] [❌ 取消收藏]
📋 #2 ...
...

[📅 只看今日可约]    ← 模式切换
[🔄 刷新] [🔙 返回主菜单]
```

**操作**：

- `📅 只看今日可约` / `📋 查看全部`：两种 mode 切换。
- 每条 `❌ 取消收藏` 立即移除并重绘列表。
- 收藏空时引导 `[🔥 热门推荐] [🔎 条件搜索]`。
- 收藏跨页保留信息密度，无独立分页（性能上限由用户实际收藏数控制）。

实现：[`bot/services/user_favorites.py`](bot/services/user_favorites.py)。

---

### 1.8 🔍 直接搜索

**入口**：主菜单 `[🔍 直接搜索]`（callback `user:search`）

**展示**：进入搜索 FSM：

```
🔍 搜索老师

请输入关键词：
・艺名（精确命中直接返回该老师）
・标签 / 地区 / 价格 的组合（例：御姐 1000P 天府一街）

随时点击下方按钮退出搜索。

[🔙 返回主菜单]
```

**操作**：

- 输入文字 → 走 `search_teachers_smart_and`（多维 AND）。
- 精确命中艺名 → 直接展示详情卡片。
- 命中 1+ 老师 → 列表 keyboard。
- 0 命中 → 推荐键盘：`[📚 今日开课] [🔥 热门老师]` + 系统提示的 N 个相关关键词。
- `/cancel` 或返回按钮退出 FSM。

---

### 1.9 💝 收藏开课 / 🔔 我的提醒

**入口**：

- `[💝 收藏开课]`（callback `user:fav_today`）：仅显示「收藏过且今日已签到」的老师。
- `[🔔 我的提醒]`（callback `user:reminders`）：当前已开启通知的收藏老师；通知关闭时显示 `[🔔 开启通知]` 一键启用。

**展示 / 操作**：列表 + 老师按钮直接进详情页；提醒页可一键打开 `notification_subscriptions.notify_enabled`。

> **Roadmap**：Plan A3/A4 将把这两项并入"我的收藏"的 toggle，目前为独立入口。

---

### 1.10 老师详情页

**入口**：列表中点老师按钮（callback `teacher:view:<id>` 或 `teacher:view:<id>:from:<source>`）

**展示**（单卡片，5 行布局）：

```
[照片 / 相册首图]

📛 艺名
📍 地区 · 💰 价格
🏷 标签
📝 描述（自动派生）
🛎 服务内容
🚫 禁忌

⭐ 评价：M 条 · 平均 X.X / 5
最近 3 条评价摘要

[📩 联系 {老师}]                ← 有 button_url 时显示
[⭐ 收藏 / ✅ 已收藏，点击取消] [🔔 TA 开课提醒 / 🔕 提醒已关闭]
[📖 查看全部评价 (N)]            ← 仅有评价时显示
[✨ 相似推荐]
[📝 写评价]
[🔙 返回 {来源}]                ← 智能返回（主菜单 / 热门 / 今日 / 筛选 / 搜索 / 收藏）
```

**操作**：

- `⭐ 收藏`：toggle，幂等；首次收藏自动开启通知。
- `🔔 / 🔕`：开关 `notify_enabled` 字段（非取消收藏）。
- `📖 查看全部评价`：进入评价分页（每页 5 条）。
- `✨ 相似推荐`：基于地区 / 价格 / 标签的相似老师卡片列表。
- `📝 写评价`：进入卡片化评价 FSM（见 1.13）。

**Phase A0 后**：返回按钮 source 白名单 = `{main, hot, today, filter, search, favorites, similar}`，未知值回退主菜单。

---

### 1.11 💰 我的积分

**入口**：主菜单 `[💰 我的积分]`（callback `user:points`）

**展示**：

```
💰 我的积分

当前余额：N 分
━━━━━━━━━━━━━━━
近期变动概览（条数 / 累计 +X / -Y）
━━━━━━━━━━━━━━━

[📋 积分明细]
[🔙 返回主菜单]
```

**操作**：

- `📋 积分明细` → 分页查 `point_transactions`，每条含：时间 / `+X` 或 `-X` / 原因（review_approved / admin_grant / admin_revoke / 历史 lottery 流水）/ 关联业务（评价 ID / 老师名）。
- 余额权威字段为 `users.total_points`（不重新汇总流水，详见 [`docs/POLICY.md`](docs/POLICY.md) Part I §七）。

---

### 1.12 🧾 我的报销

**入口**：主菜单 `[🧾 我的报销]`（callback `user:reimburse`）

**展示**：

```
🧾 我的报销

本月已批准：X 元 / Y 笔
待审核：Z 笔
━━━━━━━━━━━━━━━

[📋 报销明细]
[📩 联系客服申诉]    ← 仅 admin 配置了 contact_url 时显示
[🔙 返回主菜单]
```

**操作**：

- `📋 报销明细` → 分页显示每条报销：金额 / 状态（待审 / 已通过 / 已驳回 / 已取消 / 已录入名单 queued）/ 时间 / 关联老师与评价。
- 报销关闭期间，新评价仍可触发 `queued` 状态（不通知用户）；开启后超管可单独"激活为待审核"。
- 申诉入口：超管在 `system:reimburse_contact_url` 配置后才显示。

---

### 1.13 📝 写评价（卡片驱动 FSM）

**入口**：

- 主菜单 `[📝 写评价]`（callback `user:write_review`）
- 老师详情页 `[📝 写评价]`（callback `review:start:<id>`）
- Deep link `/start write_<teacher_id>`（讨论群评论"🤖 给 XXX 写报告"按钮）

**第一阶段 · 个人评价主页**：

```
📝 我的评价中心

📊 本人评价统计
  · 通过：M（X%）
  · 待审：N
  · 驳回：K

[⏳ 未审核] [✅ 已审核] [❌ 已驳回]    ← status 三选一过滤
[👍 好评]   [😐 中评]   [👎 差评]    ← rating 三选一过滤（兼作"写车评"预选评级）
[« 首页] [‹ 上页] [📄 X/Y] [下页 ›] [末页 »]
[🤖 写车评（预选 👍）]                ← 若 rating 已选，按钮文案带 emoji
[🔙 返回主菜单]
```

**第二阶段 · 输入艺名查老师**：

```
🔍 输入要评价的老师艺名（精确匹配）：

[❌ 取消]
```

**第三阶段 · 资格预判 + intent 选择**（仅评价资格通过的用户能进入）：

```
💰 是否参与本次报销？

预计金额：100 / 150 / 200 元（按老师价位档）

[✅ 参与报销（预计 100 元）]    ← 必传现场手势照
[❌ 不参与，仅评价]              ← 仅约课截图
[🚫 取消]
```

参与报销时校验报销专用必关订阅（与全局必关分离），失败时给链接 + 重检 / 改为不参与 / 取消三选项。

**第四阶段 · 卡片中心（9 字段任意顺序填写）**：

```
评价卡片（{老师艺名}）

[🖼 出击证明 ✓] [⭐ 评级]
[🎨 人照]       [💅 颜值]
[💃 身材]       [🛎 服务]
[😊 态度]       [🏠 环境]
[📝 过程描述]

[还差 5 项（匿名）] [还差 5 项（默认）]    ← 缺项数动态
[❌ 取消]
```

填齐后按钮变成 `[✅ 提交（匿名）] [✅ 提交（默认）]`：

- 匿名提交：discussion group 显示 `匿*` 隐藏 user_id。
- 默认提交：显示半匿名 `****6789`（user_id 末 4 位）。

**第五阶段 · 摘要与限频**：

- summary 字段长度 50-300 字（[`bot/database.py`](bot/database.py) `REVIEW_SUMMARY_MIN_LEN`/`MAX_LEN`）。
- 限频三项：
  - 60 秒内不能重复提交（任一老师）
  - 24h 内同一老师不能重复评价
  - 24h 内一个用户最多 N 条评价
- 全局必关订阅校验（含报销路径附加的报销专用必关）。

**第六阶段 · 提交 → 超管 rreview 审核**：

- 落库 `teacher_reviews`（pending），通知超管。
- 通过后自动发到讨论群（指定 anchor）+ 创建报销 pending（如选了参与）。
- 驳回时超管可选 4 预设原因 + 自定义 + 跳过。

实现：[`bot/handlers/review_card.py`](bot/handlers/review_card.py) + [`bot/handlers/review_submit.py`](bot/handlers/review_submit.py)。

---

### 1.14 全部评价列表（老师维度）

**入口**：老师详情页 `[📖 查看全部评价 (N)]`（callback `teacher:reviews:<id>`）

**展示**：每页 5 条评价，含评级 emoji + 6 维分 + 摘要 + 半匿名签名；空数据时引导 `[📝 写第一条评价] [🔙 返回老师详情]`。

**操作**：分页按钮 `[⬅️ 上一页] [📄 X/Y] [➡️ 下一页]` + `[🔙 返回老师详情]`。

---

## 二、老师功能

### 2.1 私聊菜单

**入口**：被管理员录入的老师私聊 Bot → `/start`

**展示**：

```
👤 你好，{老师艺名}

你的私聊功能：

[✅ 今日签到 / 今日已签到]     ← 文案根据当日签到状态动态切换
[✏️ 我的资料]
```

---

### 2.2 ✅ 签到

**入口**（任选其一）：

1. 文字签到：私聊发送「签到」二字（StateFilter(None) 保护，不被 FSM 截获）。
2. 按钮签到：主菜单 `[✅ 今日签到]`（callback `teacher_self:checkin`）。

**展示**：

```
✅ 签到成功！

👤 {艺名}
📅 2026-05-23
⏰ 14:00
```

或异常路径：

- 未授权：「您未被授权使用此功能」
- 已停用：「您的账号已被停用，请联系管理员」
- 已截止：「⏰ 今日签到已截止（截止时间 14:00）」
- 已签到：「✅ 今日已签到，无需重复操作」

**截止时间**：`PUBLISH_TIME`（默认 14:00，可由超管配 `system:publish_time`）。

---

### 2.3 ✏️ 我的资料

**入口**：老师私聊菜单 `[✏️ 我的资料]`（callback `teacher_self:profile`）

**展示**：

```
✏️ 你的资料
━━━━━━━━━━━━━━━
🆔 ID: 123456789
📛 用户名: @username
━━━━━━━━━━━━━━━
📝 艺名: ...
📍 地区: ...
💰 价格: ...
🏷️ 标签: ... | ...
🖼️ 图片: 已上传 / （空）
🔠 按钮文本: ...
🔗 链接: ...（不可自助修改）
━━━━━━━━━━━━━━━
点击下方按钮修改对应字段，修改后管理员将审核。

[💰 价格]    [📍 地区]
[🏷️ 标签]   [🖼️ 图片]
[📝 艺名]    [🔠 按钮文本]
[🔗 链接（不可改）]
[🔙 返回主菜单]
```

**操作 / 写入规则**（[`bot/handlers/teacher_self.py`](bot/handlers/teacher_self.py)）：

| 字段 | 行为 |
|---|---|
| 文字字段（display_name / region / price / tags / button_text） | UPDATE teachers 立即生效 + 同步 INSERT edit_request 通知管理员 |
| 图片（photo_file_id） | **不动 teachers**，仅 INSERT edit_request；展示位继续用旧图，审核通过后才切换 |
| 锁定字段（button_url） | 点击提示「该字段需联系管理员修改」 |

可发 `/cancel` 退出 FSM。

---

## 三、群组功能

Bot 加入响应群组（由管理员设置）后，监听 group message 并按下列优先级响应。

### 3.1 老师艺名精准命中

**输入**：群里发某老师的艺名（精确匹配，不区分大小写）

**展示**：精简详情卡片（[`bot.utils.teacher_render.build_teacher_group_card_v2_kb`](bot/utils/teacher_render.py)）：

```
[老师首张照片]

📛 艺名 · 📍 地区 · 💰 价格
🏷 标签
今日状态：今日可约 / 今日暂未开课

[📩 联系老师]       ← URL 按钮
[🔍 私聊详情]       ← Deep link → 私聊跳老师详情
[📝 写评价]         ← Deep link → 私聊直进卡片化评价
```

---

### 3.2 群组组合搜索

**输入**：例如 `御姐 1000P 天府一街`、`#高级 #2000`

**展示**：分页输出符合所有 token AND 关系的老师超链接列表（每页 8 条）；超出 1 页时自动分页。

---

### 3.3 群组快捷词

**输入**：单个关键词，匹配超管在「关键词管理」配置的 trigger

**展示**：自定义 banner + 正文 + 按钮组（URL 或私聊跳转）；常见用于「菜单」「今日」「热门」「推荐」「筛选」等捷径。

**管理**：`/admin` → ⚙️ 系统配置 → 🗝 关键词管理（admin:keywords）。

---

### 3.4 群组内个人 / 系统查询

**输入**：

- 发「积分」 → reply 当前 user 的余额。
- 发「报销池」 → reply 当前月度池余额 + 功能开关状态。

**展示**：

```
💰 @username 你的积分
━━━━━━━━━━━━━━━
当前余额：N 分
━━━━━━━━━━━━━━━
ℹ️ 提交评价并审核通过可获积分。
私聊 bot 点 [💰 我的积分] 查看明细。
```

---

### 3.5 冷却防刷屏

任一关键词响应触发后施加三级冷却：

- 群组总冷却 5s
- 同关键词冷却 30s
- 单用户冷却 15s（艺名精准命中跳过此层）

任一层在冷却中 → **静默**（不发"未找到"），避免影响群消息流。冷却阈值由 `COOLDOWN_SECONDS` 控制。

---

## 四、管理员后台

### 4.1 主面板

**入口**：管理员私聊 `/admin` 或 `/start`（角色分流）

**展示**（Row 数随角色变化）：

```
🔧 痴颜录管理面板

[👩‍🏫 老师管理]  [🛡 管理员设置]    ← 第二个仅超管可见
[📈 数据分析]  [✅ 审核处理 (N)]   ← N = 各类 pending 综合 badge
[💰 活动运营]                       ← 仅超管
[📊 运营看板] [⚙️ 系统配置]
```

✅ 审核处理的 `(N)` badge 由以下相加（仅超管含全部）：

- 老师资料编辑 pending（`teacher_edit_requests`）
- 评价 pending（`teacher_reviews`）
- 报销 pending（`reimbursements`）

---

### 4.2 👩‍🏫 老师管理

**入口**：主面板 `[👩‍🏫 老师管理]`（callback `admin:teachers`）

**二级页**：

```
[👥 老师列表与启停]
[🔥 热门推荐]
[🏷 用户画像]
[⬅️ 返回后台]
```

#### 4.2.1 老师档案管理（menu:teacher → tprofile:menu）

```
[📋 老师档案管理]   ← 9 步详细录入 FSM
[停用老师] [启用老师]
[📋 老师列表]
```

档案录入流程：

1. **入口**：`[➕ 完整档案录入]`，要求"转发该老师的一条消息"作为锚点 → 自动抽取 user_id / username。
2. **9 步必填 / 可选字段**：display_name / region / price / tags / button_text / button_url / basic_info / description / service_content / taboos / contact_telegram / 相册（≥ 1 张）。
3. **草稿恢复**：中途取消可保存草稿，下次 `[➕ 完整档案录入]` 检测到草稿引导 `[▶️ 恢复] [🗑 丢弃]`。
4. **预览 → 频道发布**：录入完成后 `[👁 预览档案 caption]`，点 `[📤 发布档案帖到频道]` 同步到档案频道（`archive_channel_id`）。
5. **后续维护**：`[✏️ 编辑老师档案]` 12 字段选择面板；`[🖼 管理照片相册]` add / remove / replace；`[🔄 同步 caption]` 把后台改动一键刷到频道帖。
6. **老数据迁移**：`[🔄 老数据一键同步]` 批量回填旧档案到完整结构。

#### 4.2.2 🔥 热门推荐管理（admin:hot_manage）

```
[➕ 添加推荐] [✏️ 修改权重] [❌ 取消推荐]
[🔄 重算热度]
[⬅️ 返回老师管理]
```

手动权重叠加 + 系统计算（评价数 / 收藏数 / 签到频率）。

#### 4.2.3 🏷 用户画像（admin:user_tags）

只读看板：展示用户标签分布；`[🔍 查询标签用户]` 输入 user_id / username 查看某用户的全部画像标签来源。

---

### 4.3 ✅ 审核处理

**入口**：主面板 `[✅ 审核处理]`（callback `admin:review_tasks`）

**二级页**（按角色差异化）：

```
[👩‍🏫 老师资料审核 (N)]   ← 所有 admin 可见
[📝 评价审核 (N)]         ← 仅超管
[💰 报销审核 (N)]         ← 仅超管
[📋 报销名单 (N)]         ← 仅超管 + queued > 0 时显示
[⬅️ 返回后台]
```

#### 4.3.1 老师资料审核

**展示**：当前 pending 字段的 before / after 对比 + 老师 ID/username + 操作 `[✅ 通过] [❌ 驳回]` + `[⬅️ 上一条] [➡️ 下一条]`。驳回可填原因（或跳过）。

**审核冲突处理**：另一管理员先打开了同一条 → 提示「另一管理员正在审核此条」+ `[🛡 强制接管 + 进入审核]` 二次确认。

#### 4.3.2 评价审核（rreview，仅超管）

**展示**：

- 媒体组预览（约课截图 + 现场手势照按 intent 决定是否显示「✋ 重看手势」）。
- 6 维评分 + 总均分 + 摘要 + 半匿名签名。
- 操作：`[✅ 通过] [❌ 驳回]` + `[🖼 重看约课截图] [✋ 重看手势照片]` + 导航。

**通过流程**（rreview:approve_p）：必须选积分套餐：

```
[+1 P/PP] [+3 包时]
[+5 包夜] [+8 包天]
[+0 不加分] [💬 自定义]
[🔙 取消通过]
```

**驳回流程**：4 预设原因 / 自定义 / 跳过：

- 证据不充分
- 内容违规
- 重复提交
- 评分明显不合理

**通过后**：

- 落库 approved + 自动加积分 + 通知用户。
- 发布到讨论群指定 anchor（半匿名 / 匿名）。
- 若用户选了参与报销 → 联动创建 `reimbursements.pending` + 提示超管去审。

#### 4.3.3 报销审核（仅超管）

**展示**：用户基本信息 + 报销金额 + 关联评价 + 本周 / 本月配额状态。

**操作**：

```
[✅ 通过] [❌ 驳回]
[🔄 重置该用户本周]      ← 给"超额但合理"的情况开口子
[🔙 返回审核处理]
```

通过后进入**口令发放子流程**：

1. waiting_token：超管输入支付宝口令文本。
2. confirming：预览 + `[✅ 确认发送并完成] [🔁 重新输入] [❌ 取消]`。
3. done：自动 DM 用户口令 + 状态置 approved + `[➡️ 处理下一条] [⬅️ 返回审核处理]`。

#### 4.3.4 报销名单（queued，仅超管）

报销功能关闭期间产生的 `queued` 记录在此分页查看，可单条 `[✅ 激活为待审核]` 转入正常 pending 队列。

---

### 4.4 📈 数据分析（Phase 1 老看板）

**入口**：主面板 `[📈 数据分析]`（callback `dashboard:enter`）

**展示**：基于 `user_events` + `admin_audit_logs` 的 7 日窗口指标：DAU / 评价数 / 报销动作 / 关键 admin 行为；可 `[🔄 刷新]` + `[📜 操作日志]` 进审计日志分页（支持按 action 过滤）。

---

### 4.5 📊 运营看板（admin:dashboard）

**入口**：主面板 `[📊 运营看板]`（callback `admin:dashboard`）

**二级页**：

```
[📊 运营总览]
[💰 报销池状态]
[⬅️ 返回后台]
```

#### 4.5.1 📊 运营总览（admin:overview）

只读聚合：

- 今日签到老师 / 今日新增用户 / 今日新增收藏 / 今日新增评价
- 待审核评价 / 待审核报销 / queued 报销
- `schema_migrations` failed 迁移数（hard / soft 分级）

单点查询失败显示 `N/A`，不影响其它指标。

条件渲染快捷跳转：pending 数 > 0 时显示对应审核入口按钮。

#### 4.5.2 💰 报销池状态（admin:reimbursement_pool）

只读聚合：

- 月度额度 / 本月已批准金额 / 剩余额度（含 ⚠️ 已超额提示，月池 = 0 时显示「不限」）
- pending / queued / 本月已通过 / 本月已驳回
- 本周通过用户数 / 本周通过金额 / 本周 reset voucher 使用次数
- 报销功能开关 / 当前月份与周

实现：[`bot/services/reimbursement_pool.py`](bot/services/reimbursement_pool.py)。

---

### 4.6 ⚙️ 系统配置

**入口**：主面板 `[⚙️ 系统配置]`（callback `admin:settings`）

**二级页**：

```
[📢 必关订阅]              ← 全局必关频道 / 群组
[🧩 发布模板]              ← 每日开课消息文案模板
[🗝 关键词管理]             ← 群组快捷词配置
[📣 频道 / 群组设置]        ← 发布目标 / 档案频道 / 响应群组
[📅 日报 / 周报设置]
[⚙️ 系统设置]              ← 发布时间 / 冷却时间 / 签到提醒 / 品牌等
[💰 报销配置（聚合 6 项）]  ← 仅超管
[⬅️ 返回后台]
```

#### 4.6.1 必关订阅

`/admin` → 系统配置 → 必关订阅：

- 列表 / 添加 / 删除（含二次确认）/ 启停切换。
- 单条信息：友好名（display_name） + chat_id + 邀请链接 + 启停状态。
- bot 异常（频道不存在 / 没权限）自动 skip + warning。

#### 4.6.2 发布模板

- 多模板列表，超管可新建 / 编辑 / 设为默认。
- 默认模板立即生效到调度器。

#### 4.6.3 关键词管理

群组快捷词配置：

```
[➕ 新增关键词]
[✅ 菜单（命中 32）]
  [✏️ 编辑] [⏸ 停用] [🗑 删除]
[✅ 今日（命中 18）]
  [✏️ 编辑] [⏸ 停用] [🗑 删除]
...
```

每条含 4 个可编辑字段：trigger / banner / body / buttons（每行命中数可视化）。

#### 4.6.4 频道 / 群组设置

```
[📌 设置发布目标]    ← publish_chat_ids（可多个）
[📦 设置档案频道]    ← archive_channel_id（老师档案帖）
[💬 设置响应群组]    ← keyword 监听群
[📋 查看当前设置]
```

#### 4.6.5 日报 / 周报设置

调度器定时生成统计（当日签到数 / 发布老师数 / 新增评价数 / 报销动作数等）并推送到指定 chat_id；超管可配 4 个字段（开关 / 时间 / 目标 / 内容选项）。

#### 4.6.6 系统设置（menu:system）

```
[系统状态检查]
[发布预览] [手动发布]
[今日签到统计]
[测试签到发布] [🧪 测试收藏通知]
[签到提醒时间] [签到提醒开关]
[⏰ 修改发布时间]
[⏳ 修改冷却时间]
[📋 必关频道/群组]
[📢 评价 footer 文本] [🔗 评价 footer 链接]
[🏷 档案品牌名]      [📡 档案品牌频道]
```

---

## 五、超管专属功能

### 5.1 🛡 管理员设置

**入口**：主面板 `[🛡 管理员设置]`（callback `admin:admin_settings`，仅超管）

```
[👥 管理员管理]    ← 添加 / 移除 / 列表
[📜 审计日志]      ← admin_audit_logs 最近 20 条
[⬅️ 返回后台]
```

---

### 5.2 💰 活动运营 → 积分管理

**入口**：主面板 `[💰 活动运营]`（callback `admin:operations`）→ `[💰 积分管理]`

**展示**：

```
[📜 积分规则一览（只读）]
[📊 积分对账（只读）]      ← total_points vs 流水汇总差异检测
[🔍 查询用户积分]          ← 按 user_id / @username / first_name
[➕ 手动加分]              ← 4 步 FSM
[📊 积分总览]
[⬅️ 返回活动运营]
```

**手动加扣分 4 步 FSM**：

1. Step 1：输入用户标识。
2. Step 2：选预设套餐 `[+1 P/PP] [+3 包时] [+5 包夜] [+8 包天] [+10] [+20]` 或 `[➖ 扣分] / [💬 自定义]`。
3. Step 3：选预设原因 `[📝 报告审核补加] [🎁 活动奖励] [⚠️ 违规扣分] [🛠 系统修正]` 或自定义。
4. Step 4：确认预览 → 写 `point_transactions` + 累加 `users.total_points` + 审计日志。

---

### 5.3 💰 报销配置（聚合 7 项）

**入口**：系统配置 → `[💰 报销配置（聚合 6 项）]`（callback `admin:reimburse_config`，仅超管）

```
[📜 完整规则一览（只读）]   ← 含「📢 复制公告草稿」一键生成可粘贴文案
[🔛 报销功能开关]
[💰 报销池设置]            ← 月度上限金额
[🔄 重置本月报销池]
[🎚 报销门槛设置]          ← 用户积分门槛（默认 ≥ 5）
[🗓 每周报销上限]          ← 每周允许次数（1-10，默认 1）
[📋 报销必关设置]          ← 报销专用必关（与全局必关分离）
[⬅️ 返回系统配置]
```

**金额规则**（写死在 [`bot/utils/reimburse_eligibility.py`](bot/utils/reimburse_eligibility.py)）：

- 老师价位 ≤ 8P → 100 元
- 老师价位 = 9P → 150 元
- 老师价位 ≥ 10P → 200 元

**Roadmap**：周限 / 月池均已 config 化；金额档位短期不计划改。

---

## 六、自动化与调度

调度器：APScheduler 3.10.4，所有 cron 任务声明在 [`bot/scheduler/tasks.py`](bot/scheduler/tasks.py)。

| 任务 | 触发时间 | 行为 |
|---|---|---|
| 每日发布 | `PUBLISH_TIME`（默认 14:00） | 汇总当日已签到老师 → 发布到所有 `publish_chat_ids` → 自动删除昨日发布消息 |
| 签到提醒 | 发布前 N 分钟（默认 60，可配置） | DM 未签到老师 |
| 收藏开课通知 | 发布后即时 | DM 每位老师的 `notification_subscriptions` 用户（仅 notify_enabled=1） |
| 日报 | 配置时间 | 推送当日统计到指定 chat_id |
| 周报 | 配置时间 | 推送周统计 |

**老师收藏通知**：每张收藏发出独立 DM，按老师维度聚合发送，避免 N×M 爆量。

---

## 七、Deep Link 速查

`/start` 支持多种 deep link 参数（[`bot/handlers/start_router.py`](bot/handlers/start_router.py) `parse_start_args`）：

| 链接 | 行为 |
|---|---|
| `/start` | 角色分流主菜单 |
| `/start activate` | 兼容旧版"激活通知" |
| `/start fav_<id>` | 自动收藏老师 + 进主菜单 |
| `/start fav_<id>_src_channel_<cid>` | 收藏 + 渠道来源记录 |
| `/start teacher_<id>` | 直达老师详情落地页（群卡片"私聊详情"按钮） |
| `/start write_<id>` | 直达卡片化评价 FSM（讨论群"🤖 写报告"按钮） |
| `/start search` | 直接进搜索 FSM |
| `/start q_<base64url>` | 在私聊回放群搜索词 |
| `/start menu` / `today` / `hot` / `filter` / `recommend` | 群内快捷入口落地（Phase 7.3） |
| `/start src_channel_<id>` / `src_group_<id>` / `src_teacher_<id>` / `campaign_<code>` / `invite_<code>` | 来源追踪 → `user_sources` + 画像 |
| `/start <其它>` | 记 `source_type='unknown'` |

所有 deep link 异常**全部吞掉**，绝不阻断用户进入菜单。

---

## 八、技术栈与数据库

### 技术栈

| 组件 | 版本 / 说明 |
|---|---|
| Python | 3.11+ |
| aiogram | 3.13.1（Telegram Bot 异步框架） |
| SQLite | 3.x，**WAL 模式**（`PRAGMA journal_mode=WAL` + `busy_timeout=5000`） |
| aiosqlite | 0.20.0 |
| APScheduler | 3.10.4 |
| python-dotenv | 1.0.1 |
| 部署 | systemd 单进程 polling（不推荐 Docker / Webhook） |

### 数据库分组

SQLite 单文件，默认 `./data/bot.db`，共 23 张表（Phase A0 后 4 张表 `lotteries` / `lottery_entries` / `user_teacher_views` / `teacher_daily_status` **保留无写入**，待 A0.1 PR DROP）。

| 模块 | 主要表 |
|---|---|
| 管理员与配置 | `admins`, `bot_config`, `required_subscriptions`, `publish_templates`, `report_settings` |
| 老师资料与签到 | `teachers`, `checkins`, `teacher_channel_posts`, `teacher_edit_requests` |
| 用户与互动 | `users`, `favorites`, `notification_subscriptions` |
| 来源追踪与画像 | `user_sources`, `user_tags`, `promo_links`, `source_events` |
| 评价 / 报告 | `teacher_reviews`（含 `request_reimbursement` / `anonymous`） |
| 积分 | `point_transactions` + `users.total_points` |
| 报销 | `reimbursements`（5 状态 CHECK）+ `reimbursement_resets` |
| 操作记录 | `admin_audit_logs`, `user_events`, `sent_messages` |
| 迁移注册器 | `schema_migrations`（P2 baseline 已落地，hard/soft 分级） |

DDL 与全部 CRUD 集中在 [`bot/database.py`](bot/database.py)。

---

## 九、项目结构

```
Chiyanlu-Exclusive-Bot/
├── bot/
│   ├── main.py                          # 41 行薄入口
│   ├── app_factory.py                   # Bot/Dispatcher/Scheduler 构造
│   ├── routers.py                       # 30+ router 注册顺序（注释保留）
│   ├── lifecycle.py                     # startup/shutdown 钩子
│   ├── config.py                        # 环境变量加载
│   ├── database.py                      # DDL + 迁移 + 全部 CRUD
│   ├── handlers/                        # 按子系统组织的 router 模块
│   │   ├── start_router.py              # /start 角色分流 + deep link
│   │   ├── admin_panel.py               # 后台主菜单
│   │   ├── admin_review.py              # 老师资料审核
│   │   ├── rreview_admin.py             # 超管评价审核（媒体组预览）
│   │   ├── admin_reimburse.py           # 报销审批 + 口令发放
│   │   ├── admin_points.py              # 积分查询 / 加扣分
│   │   ├── admin_keyword.py             # 群组快捷词配置
│   │   ├── review_card.py               # 卡片驱动评价 FSM
│   │   ├── review_submit.py             # 评价主页 + 入口分流
│   │   ├── review_list.py               # 评价分页列表
│   │   ├── teacher_profile.py           # 9 步详细档案录入 + 一键同步
│   │   ├── teacher_self.py              # 老师自助菜单
│   │   ├── teacher_checkin.py           # 签到（StateFilter 保护）
│   │   ├── teacher_detail.py            # 老师详情页
│   │   ├── teacher_flow.py              # 老师启停 / 简版 CRUD
│   │   ├── user_panel.py                # 用户主菜单 + 找老师聚合
│   │   ├── user_search.py               # 直接搜索 FSM
│   │   ├── user_filter.py               # 按条件找 FSM
│   │   ├── user_recommend.py            # 推荐 / 热门
│   │   ├── user_history.py              # 我的提醒
│   │   ├── user_points.py               # 我的积分
│   │   ├── user_reimburse.py            # 我的报销
│   │   ├── favorite.py                  # 收藏 toggle / 列表
│   │   ├── hot_teachers.py              # 热门推荐管理
│   │   ├── keyword.py                   # 群组关键词 catch-all
│   │   ├── discussion_anchor_listener.py # 讨论群锚消息捕获
│   │   ├── subreq_admin.py              # 全局必关订阅
│   │   ├── reimburse_subreq_admin.py    # 报销专用必关
│   │   ├── reimburse_settings_admin.py  # 报销门槛 / 月池基线
│   │   ├── publish_templates.py         # 发布模板
│   │   ├── report_settings.py           # 报表设置
│   │   ├── user_tags.py                 # 用户画像看板
│   │   └── noop_handlers.py             # noop:* 占位 callback
│   ├── keyboards/                       # admin_kb / user_kb / teacher_self_kb
│   ├── services/                        # admin_overview / reimbursement_pool / points_rules / user_favorites
│   ├── scheduler/tasks.py               # 每日发布 / 签到提醒 / 日报 / 周报
│   ├── states/                          # FSM 状态定义
│   ├── middlewares/                     # 权限 / 日志中间件
│   └── utils/                           # 渲染 / 通知 / 必关校验 / 报销资格
├── data/                                # SQLite 单文件（已 .gitignore）
├── backups/                             # update.sh 自动备份目录（已 .gitignore）
├── docs/                                # DEPLOYMENT / RUNBOOK / POLICY / DESIGN / DELETED-FEATURES
├── scripts/                             # healthcheck / backup / prune
├── tests/                               # pytest 用例（不连真实环境）
├── update.sh                            # 拉代码 + 备份 + 重启 + 健康检查
├── .env.example
└── requirements.txt
```

---

## 十、部署与运维

### 10.1 环境变量

复制 `.env.example` → `.env`：

| 变量 | 必填 | 说明 |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram BotFather 颁发 |
| `SUPER_ADMIN_ID` | ✅ | 超管 Telegram 数字 ID |
| `DATABASE_PATH` | ❌ | 默认 `./data/bot.db` |
| `TIMEZONE` | ❌ | 默认 `Asia/Shanghai` |
| `PUBLISH_TIME` | ❌ | 默认 `14:00` |
| `COOLDOWN_SECONDS` | ❌ | 群组关键词冷却秒数 |

⚠️ `.env` 不可提交（`.gitignore` 已覆盖）。`BOT_TOKEN` 泄露后立即 `/revoke` 重发。

### 10.2 快速开始（开发环境）

```bash
git clone <repo-url>
cd Chiyanlu-Exclusive-Bot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # 填入 BOT_TOKEN / SUPER_ADMIN_ID
python3 -m bot.main           # 首次启动自动初始化数据库
```

启动后超管私聊 Bot 发 `/start` 进后台，依次：发布频道 → 讨论群 → 必关订阅 → 添加老师。

### 10.3 生产部署（systemd）

```ini
[Unit]
Description=Chiyanlu Exclusive Telegram Bot
After=network.target

[Service]
Type=simple
User=chiyanlu
Group=chiyanlu
WorkingDirectory=/opt/Chiyanlu-Exclusive-Bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/Chiyanlu-Exclusive-Bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- `.env` 必须 `chmod 600`。
- 生产建议**独立 chiyanlu 用户**运行（详见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) §9.2）。

### 10.4 日常运维（update.sh）

```bash
./update.sh                 # 拉代码 + 装依赖 + WAL-safe 备份 + 重启 + 日志扫描
./update.sh start           # 仅启动
./update.sh stop            # 仅停止
./update.sh restart         # 仅重启（改 .env 后用）
./update.sh status          # 状态 + 最近 20 行日志
./update.sh rollback        # 紧急回滚：还原备份 + git reset --hard HEAD~1
./update.sh help
```

`update.sh` 安全特性：

- 拉代码前 schema-diff 警告（检测远程含 `_migrate_*` / `ALTER TABLE`）。
- 备份用 `sqlite3 .backup` + `PRAGMA integrity_check`（必须返回 ok），保留最近 10 份。
- 重启后健康轮询 15s + 日志扫描 `Traceback / CRITICAL / 迁移失败` 关键字。
- 检测 `schema_migrations` hard failed → ERR + 提示 rollback（不自动）；soft failed → WARN 不阻断。
- rollback 还原 DB 前清残留 `-wal` / `-shm`。

### 10.5 备份与恢复

⚠️ **WAL 模式下数据库由 3 个文件组成**：`bot.db` / `bot.db-wal` / `bot.db-shm`。

❌ **不要** `cp bot.db`（会丢 WAL 中未 checkpoint 的写入）。

✅ **正确**：

```bash
TS=$(date +%F-%H%M%S)
sqlite3 data/bot.db ".backup '/backup/bot-${TS}.db'"
sqlite3 "/backup/bot-${TS}.db" "PRAGMA integrity_check;"    # 必须返回 ok
```

建议 crontab 每日 03:30 自动备份 + 保留 30 份。详见 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) §14。

### 10.6 健康检查

```bash
./scripts/healthcheck.sh     # 文件 / Python / WAL / integrity / 核心表 / DB 体积 / 迁移 / systemd / Git
./scripts/backup.sh          # 独立 WAL-safe 备份（*.manual.bak）
./scripts/prune.sh --dry-run # 老旧 user_events / user_teacher_views 统计（--confirm/--delete 等参数立即 exit 1）
```

### 10.7 测试

```bash
pip install -r requirements.txt
python3 -m pytest            # 67 用例，1 秒内跑完
python3 -m pytest -v
python3 -m pytest tests/test_start_args.py
```

不连真实 Telegram、不读真实 `.env`、不触碰 `data/bot.db`。CI（GitHub Actions）触发 `compileall + pytest + bash -n scripts/*.sh`。

---

## 十一、常见问题

### Bot 无法启动

- `.env` 存在且 `BOT_TOKEN` / `SUPER_ADMIN_ID` 正确？
- 虚拟环境已激活 + 依赖已装？
- `journalctl -u chiyanlu-bot -n 100 --no-pager`

### 管理员无法打开后台

- 当前 Telegram 用户 ID = `SUPER_ADMIN_ID`？
- 普通管理员需超管在「管理员管理」中添加。

### 定时发布没发消息

- 已设发布频道（`channel:set_publish`）？
- Bot 在频道内且有发送权限？
- 当天有老师签到？（无签到默认跳过）
- 时区 / `PUBLISH_TIME` 正确？

### 群组关键词无响应

- 已设响应群组（`channel:set_response`）？
- Bot 在群组内？
- 是否精确匹配老师艺名 / 标签 / 地区 / 价格？
- 在冷却时间内？（任一层冷却命中静默不回复）

### 升级失败如何回滚

```bash
./update.sh rollback         # 二次确认后还原备份 + git reset --hard HEAD~1
```

### 系统未装 sqlite3 命令

```bash
apt install sqlite3          # Debian/Ubuntu
yum install sqlite           # RHEL/CentOS
```

WAL 模式下 `update.sh` 备份强制要求 sqlite3。

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | 部署 / `update.sh` / WAL / 备份 / 验收 Checklist |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | 值守手册（14 节，事故处理流程） |
| [`docs/POLICY.md`](docs/POLICY.md) | 合并版运营政策：Part I 积分 / Part II 报销（Part III 抽奖随 A0 整体下线已删除） |
| [`docs/DESIGN.md`](docs/DESIGN.md) | 合并版产品设计：Part I v1 原始 / Part II v2 增量 |
| [`docs/INFRASTRUCTURE-DESIGN.md`](docs/INFRASTRUCTURE-DESIGN.md) | 迁移注册器 / 历史数据清理 |
| [`docs/DELETED-FEATURES.md`](docs/DELETED-FEATURES.md) | Phase A0 已下线 5 项功能清单 + 回滚指南 |
| [`docs/ROADMAP-PLAN.md`](docs/ROADMAP-PLAN.md) | 后续迭代计划 |

---

**Issues / PR / 二次开发**：欢迎在仓库 issue 区讨论。业务规则变更建议先在对应 `docs/*-DRAFT.md` 中说明。
