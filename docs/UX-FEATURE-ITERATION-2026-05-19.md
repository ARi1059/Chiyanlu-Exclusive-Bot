# 功能模块用户体验分析与迭代建议（2026-05-19 轮次）

> 本文档是**功能模块视角**的 UX 现状分析 + 迭代建议，不修改任何代码。
> 撰写过程未触动 `bot/`、`scripts/`、`update.sh`、`tests/`、`README.md` 或任何 `docs/` 下既有文件。
> 所有「建议」均为后续阶段的处置思路，每项必须单独评估、单独 PR、单独 CI 验证。

---

## 0. 文档定位

### 0.1 与已有文档的差异

项目已有三类 UX / 路线文档：

| 文档 | 视角 | 粒度 |
| --- | --- | --- |
| `docs/UX-EFFICIENCY-PLAN.md` | 按**角色**（用户/老师/管理员/超管） | 优化原则 + 共性方向 |
| `docs/ROADMAP-PLAN.md` | 按 **Sprint** 节奏 | 功能演进路线 |
| `docs/POLICY-*.md` | 按**业务域**（抽奖/积分/报销） | 策略与约束 |
| **本文档** | **按 6 个功能模块**（评价/抽奖/报销/关键词/老师录入/管理员） | **现状→痛点→迭代**，每条痛点附 `file:line` |

本文档与上述文档**互补不重复**：
- 已被 `UX-EFFICIENCY-PLAN.md` 立项的方向（如「签到优先」「审核 badge」「子页面返回」），本文不再重写设计，只补**具体代码定位**与**新发现的同类痛点**。
- 已被 `POLICY-*.md` 写入策略的规则（如「不通知未中奖者」「rejected 是终态」），本文不再讨论策略合理性，只指出「从用户体验视角是断点」。
- 本文专注**站在用户面前**的真实路径：从他/她看到的按钮、文案、状态、反馈出发。

### 0.2 不在本文范围

- **不**做代码改动，**不**新增数据库迁移。
- **不**改任何 `callback_data`（避免破坏历史 inline button 快照）。
- **不**给"批量自动通过 / 自动开奖 / 自动报销"开口（与 `UX-EFFICIENCY-PLAN.md §1.4` 红线一致）。
- 不评估业务策略本身的对错（这是 `POLICY-*.md` 的范畴）。

---

## 1. 跨模块共性结论

> 把 6 个模块的分析放在一起看，浮现出 10 条**跨模块共性痛点**。优先级最高的迭代往往是把这些共性问题一次性解决到位，而不是单个模块逐一打补丁。

### C1. 通知文本普遍无 CTA 按钮

- **现象**：评价驳回 / 通过、报销通过 / 驳回、抽奖中奖私聊通知全是**纯文本**，没有 `inline button`。
- **代码位置**：`bot/utils/rreview_notify.py:51-126`、`bot/handlers/admin_reimburse.py:450-454`、`bot/services/lottery_draw.py:303-322`。
- **后果**：用户看完通知无路可走，要回主菜单再走 2-4 步才能"再写一条 / 申诉 / 看抽奖详情"。
- **统一对策**：所有结果性通知都附 `reply_markup`，含 1-3 个 CTA（deep link 跳转或 callback）。

### C2. 空状态都没有引导

- **现象**：评价列表空、抽奖记录空、报销空、搜索零结果——要么 alert 一闪而过，要么纯文本"暂无数据"。
- **代码位置**：`bot/handlers/review_list.py:67-69`、`bot/utils/review_detail_render.py:62-63`、`bot/handlers/keyword.py:613-615`。
- **后果**：把高转化时机（用户主动进来"想找点什么"）浪费成死胡同。
- **统一对策**：所有空状态都给至少 1 个可点击的下一步（已在 `UX-EFFICIENCY-PLAN.md §2.3.E` 立项）。

### C3. 审核完成"下一步"只覆盖了一半

- **现象**：`admin_review_done_next_kb` 组件存在，但**只在自定义 FSM 路径**（如填驳回理由后）会发送；点预设按钮（直接通过、跳过原因）的高频路径**自动推下一条**，没有"返回审核中心 / 切换审核类型"出口。
- **代码位置**：`bot/handlers/admin_review.py:480-485`、`admin_reimburse.py:594-598`、`rreview_admin.py:555-558`。
- **后果**：管理员审完一类后想切到另一类必须先回主菜单。

### C4. 批量操作几乎全缺

- **现象**：报销名单激活、评价通过、queued 清空、必关频道删除——都是逐条点击。
- **后果**：活动结束日积压 30 条 queued，运营要点 30 次。
- **风险约束**：批量必须有二次确认 + 每条 audit log，不可静默。

### C5. 多管理员并发审核无 lock 也无提示

- **现象**：进同一条详情时既不知道别人在看，也无 claim 机制；只在写入时检测 `status != 'pending'` 被动报"已被处理"。
- **代码位置**：`rreview_admin.py:768-774`、`admin_reimburse.py:564-567`、`admin_review.py:300-302`。
- **建议**：内存 cache 5 分钟级 claim，进同一条 alert 提示「@adminX 正在审核」（详见 §7）。

### C6. 静默失败 / 静默跳过

- **现象**：报销资格不足、抽奖参与失败、关键词无匹配 → 都不告知用户原因。
- **代码位置**：`review_submit.py:841-845`（报销资格静默）、`keyword.py:613-615`（关键词静默）、`lottery_subscribe_check.py:73-102`（订阅失败提示无重试按钮）。
- **后果**：用户感受是"机器人坏了"，客服咨询量飙升。
- **统一对策**：可控制的失败给"为什么"+"怎么办"；catch-all 的静默可保留但加埋点。

### C7. FSM 持久化与超时

- **现象**：项目使用 `MemoryStorage`（`bot/app_factory.py:36`），仅 `teacher_flow.py:37-66` 一处接入了超时中间件。
- **代码位置**：`teacher_profile.py`、`review_card.py`、`admin_lottery.py` 等 9 步 / 10 步 FSM 均未挂超时。
- **后果**：服务重启 / 长 FSM 卡死时已上传的 10 张照片、已填的 8 个字段瞬间丢失。
- **建议**：统一 middleware 接入；中期评估 SQLite/Redis storage。

### C8. 配置入口分散，命名重复

- **现象**：
  - 报销 5 个配置入口散在 ⚙️ 系统配置（开关、池子）和 ⚙️ 系统设置（门槛、重置、专用必关）两个二级页。
  - "📋 必关频道/群组"在 `admin_kb.py:142` 与 `admin_kb.py:947` 是**同一个 callback** `admin:subreq`，两处入口指向同一功能（造成"我刚才点过的吗？"困惑）。
  - 关键词响应彻底无独立配置面板，只能间接通过添加老师档案"派生"出关键词。
- **建议**：聚合为「💰 报销系统配置」「🗝 关键词管理」二级页（详见 §4 §5）。

### C9. 状态可视化不足

- **现象**：
  - 老师面板"今日签到"按钮永远显示同一文案，不能一眼看出已签未签（`teacher_self_kb.py:17`）。
  - 抽奖频道帖无"距开奖剩 X 小时"，无时区提示（`lottery_publish.py:90-162`）。
  - 报销月度池接近耗尽时用户主页 / 审核详情页都无红色预警。
- **建议**：所有"状态强相关"按钮 / 标题动态渲染当前状态值。

### C10. 用户视角缺"账户中心"

- **现象**：抽奖记录、报销记录、评价、积分分散在主菜单 13 个一级按钮中（`user_kb.py:81-132`），且**抽奖完全无入口**——用户只能在频道帖反向进入。
- **后果**：用户找不到"我的"位置，主菜单按钮持续膨胀。
- **建议**：建一个「我的记录」二级菜单收纳（已在 `UX-EFFICIENCY-PLAN.md §2.3.D` 立项，本文给出新的代码定位）。

---

## 2. 报告（评价）提交

### 2.1 现状（用户视角）

**用户入口共 3 条**（长度差异极大）：

1. 主菜单 → `📝 写评价`（`user_kb.py:130`）→ 个人评价主页 → `🤖 写车评` → **输入艺名 FSM** → 卡片视图。共 **3 步点击 + 1 次输入**。
2. 老师详情页 → `📝 写评价`（`review:start:<teacher_id>`）→ 直接进卡片。共 **2 步点击**（前提是已在详情页）。
3. 在详情页之外的快捷路径目前没有。

**FSM 流转**（旧线性 FSM 已 deprecated，仅卡片 FSM 生效）：

```
UserReviewsHomeStates.viewing
   ↓ user:reviews:write
WriteReviewLookupStates.waiting_teacher_name  ← 输入艺名查老师
   ↓ get_teacher_by_name 命中 + 限频 + 必关频道
CardReviewStates.card                          ← 9 个字段任意顺序
   ↔ editing_evidence / editing_rating / editing_humanphoto / editing_appearance
   ↔ editing_body / editing_service / editing_attitude / editing_environment / editing_summary
   ↓ card:submit:anon|default（_missing_fields 校验）
（可选）waiting_reimbursement_choice
   ↓ create_teacher_review → state.clear()
```

**主要 callback 命名空间**：

| 命名空间 | 处理者 | 用途 |
| --- | --- | --- |
| `user:write_review` / `user:reviews:*` | `review_submit.py:262` | 个人评价主页 |
| `review:start:<id>` | `review_submit.py:450` | 详情页"写评价" |
| `card:edit:*` / `card:submit:*` / `card:cancel` | `review_card.py` | 卡片 FSM |
| `teacher:reviews:<id>[:page]` | `review_list.py:53` | 详情页"查看全部评价" |
| `rreview:*` | `rreview_admin.py` | 超管对用户评价的审核 |
| `review:*` | `admin_review.py` | **老师资料修改**审核（与"评价审核"不是同一回事） |

### 2.2 痛点

1. **3 条入口长度极不均衡**（[review_submit.py:262-277](bot/handlers/review_submit.py#L262-L277), [user_kb.py:130](bot/keyboards/user_kb.py#L130)）：主菜单进的是"复盘自己评价"的个人评价主页，新写一条要再点 3 次。
2. **艺名精确匹配 + 60 字限制太严**（[review_submit.py:381-435](bot/handlers/review_submit.py#L381-L435)）：失败只给"请检查拼写后重发"，无相似度提示、无候选按钮、无"按 ID 找"备选。
3. **卡片视图无总进度计数**（[review_card.py:128-146](bot/handlers/review_card.py#L128-L146)）：用户看不到"已完成 8/9 项"，提交时才以 alert 形式列出缺项。
4. **重复评价拦截过弱**（[bot/database.py:257](bot/database.py#L257)）：`teacher_reviews` 无 `UNIQUE(teacher_id, user_id)` 约束；24h 内对同一老师**合法可提 3 条**；用户提交前完全无感知。
5. **"未找到老师"会清空整个 FSM**（[review_submit.py:410-432](bot/handlers/review_submit.py#L410-L432)）：用户只能从主菜单完全重来。
6. **过程描述硬阈值 5-100 字**（[review_card.py:465-468](bot/handlers/review_card.py#L465-L468)）：超长时不自动截断也不展示已写内容，用户要么手工删字要么放弃；**无敏感词过滤**，全靠人审。
7. **证据图上传缺可视化反馈**（[review_card.py:374](bot/handlers/review_card.py#L374)）：只回文字 "✅ 已收到 N/2 张"，不回显缩略图，不允许撤回上一张重传。
8. **取消按钮无二次确认**（[review_card.py:223-253](bot/handlers/review_card.py#L223-L253)）：点取消 → 直接 `state.clear()`，辛苦填了 8 项不小心点取消全部丢失。
9. **提交成功页是死胡同**（[review_card.py:712-725](bot/handlers/review_card.py#L712-L725)）：纯文本"✅ 评价 #X 已提交…"，无任何按钮（无"返回详情 / 再写一条 / 查看我的评价"入口）。属共性问题 **C1**。
10. **被驳回 / 通过通知缺 CTA**（[bot/utils/rreview_notify.py:51-126](bot/utils/rreview_notify.py#L51-L126)）：纯文本"驳回原因：xxx"，无"重新提交 / 联系超管 / 查看详情"按钮。属共性问题 **C1**。
11. **管理员审核侧仍是单条串行**（[rreview_admin.py:586-604](bot/handlers/rreview_admin.py#L586-L604)）：通过时还要看 6 个加分套餐子页（`rreview_approve_points_kb`），驳回 2 步进 reject_choice_kb；批量审核完全不存在。属共性问题 **C4**。
12. **详情列表 0 评价时无引导**（[review_list.py:67-69](bot/handlers/review_list.py#L67-L69)）：仅 `callback.answer("该老师暂无评价", show_alert=True)`，浪费"做第一个评价的人"高转化时机。属共性问题 **C2**。

### 2.3 迭代建议

1. **主菜单拆分"个人评价主页"和"写新车评"双入口**：在 `user_main_menu_kb` 同一行加 `🤖 写新车评` 直接到艺名输入或老师选择器。新用户最短链路从 4 步缩到 2 步。
2. **艺名失败时返回 LIKE 模糊候选 3-5 个 inline button**：复用 `search_suggestion_kb` 模式；不强制阻止，仅提供候选。
3. **卡片 header 加进度计数**：`(已完成 N/9 · 可提交：是/否)`，复用已有的 `_missing_fields` 反向计算。纯文案变更。
4. **提交按钮文案动态化**：所有项完成显示 `✅ 提交（匿名）`；未完成显示 `还差 N 项`（按钮可点但 alert 给出第一个未填项）。
5. **过程描述软上限 + 实时计数**：超长改为"建议截断到 100 字"+ 提供"确认截断后提交"按钮；DB 100 字硬限保持不变。
6. **30 天内重复评价软提醒**：在 `start_card_review` 内查 `count_recent_user_teacher_reviews(user_id, teacher_id, 30d)`，有则在卡片 header 显示「💡 你 30 天内已评过该老师，#123 状态：xxx」+「📖 查看上次评价」按钮。**不强制阻止**。
7. **取消改为软取消 + 二次确认**：`cb_card_cancel` 弹"❌ 取消（数据将丢失）"二次确认。后续可考虑草稿恢复表。
8. **提交成功页加 CTA 按钮组**（`[📋 返回老师详情] [📝 我的评价] [🔥 看下一个老师] [🔙 主菜单]`）：跟管理员侧 `admin_review_done_next_kb` 对齐。
9. **驳回 / 通过通知加 deep link CTA**：通知 keyboard 用 URL deep link（如 `t.me/{bot}?start=review_view_{id}`），避免 cross-chat callback 限制。
10. **空评价列表加"📝 写第一条"按钮**：在 `review_list.py:67-69` 和 `review_detail_render.py:62-63` 渲染引导。
11. **管理员审核加"一键通过本批好评"批量按钮**：仅当评级=positive 且评分都 ≥ 8 时显示；二次确认 + 批量上限 10 条 + 每条 audit log；**不属于自动审核**，仍是人工点击。

### 2.4 与已有文档的关系

- 与 `UX-EFFICIENCY-PLAN.md §2.3.C`「下一步动作引导」、`§4.3.D`「审核完成后下一步」一致；本文给出**用户侧通知 CTA**这一对应面（PLAN 仅落地了管理员侧）。
- 建议 1-9 属新维度，可组成 Sprint UX-4「评价提交效率」。

---

## 3. 抽奖

### 3.1 现状

**用户参与**：
- bot 主菜单**完全无抽奖入口**（`user_kb.py:81-132` 13 个按钮无抽奖相关）；用户只能从频道帖反向进入。
- 两种参与方式：
  1. **按键抽奖**：频道帖 [🎲 参与抽奖] → URL deep link `t.me/<bot>?start=lottery_<id>` → `start_router.py:568-583` → `try_enter_lottery`（6 步校验）。
  2. **口令抽奖**：频道帖不展示按钮（仅"N 人已参与"计数 `lottery_publish.py:174-183`）；用户私聊任意 ≤20 字非斜杠文字命中 `entry_code`（大小写不敏感 [database.py:5664-5670](bot/database.py#L5664-L5670)）。
- 成功提示仅一段文字（[lottery_entry.py:166-176](bot/handlers/lottery_entry.py#L166-L176)），无后续按钮。

**管理员创建/发布/开奖**：
- 入口：[🎲 抽奖管理]（仅超管，`admin_kb.py:170`）→ 「➕ 创建新抽奖 / 📋 抽奖列表 / 👨‍💼 抽奖客服链接」。
- 创建 10 步 FSM（[admin_lottery.py:1100-1727](bot/handlers/admin_lottery.py#L1100-L1727)）：name → description → cover → entry_method → (entry_code) → prize_count → prize_description → required_chats → publish_mode → publish_at → draw_at → 确认页。**`entry_cost_points` 不在主线**，只在确认页通过额外按钮设置（[admin_lottery.py:1593-1636](bot/handlers/admin_lottery.py#L1593-L1636)），容易漏配。
- 发布：`publish_mode='immediate'` 立即发；`scheduled` 注册 APScheduler `lottery_pub_<lid>`。
- 开奖：完全自动，`draw_at` 触发 `run_lottery_draw`（[lottery_draw.py:68-158](bot/services/lottery_draw.py#L68-L158)）。**无预览 / 无二次确认 / 无手动触发**。
- 取消：仅 `active+cost>0+entries>0` 才出现「退积分 / 不退」选项（[admin_lottery.py:261-291](bot/handlers/admin_lottery.py#L261-L291)）。

### 3.2 痛点

1. **用户 bot 内无任何"我的抽奖"入口**（[user_kb.py:81-132](bot/keyboards/user_kb.py#L81-L132)）：中奖通知是一次性消息，事后无法回查参与历史。属共性问题 **C10**。
2. **口令模式发现性极差**（[lottery_publish.py:128-132](bot/services/lottery_publish.py#L128-L132)）：频道帖只有一行文字"在私聊给我发送口令：XXX"，**无跳转 bot 私聊的按钮**；首次接触必失败。
3. **必关频道失败后无"已加入，重新尝试"按钮**（[lottery_subscribe_check.py:73-102](bot/services/lottery_subscribe_check.py#L73-L102)）：用户要切应用切频道滚回原帖。属共性问题 **C6**。
4. **频道帖缺剩余时间 / 时区**（[lottery_publish.py:90-162](bot/services/lottery_publish.py#L90-L162)）：只输出固定 `draw_at` 字符串。属共性问题 **C9**。
5. **未中奖用户完全无反馈**（[lottery_draw.py:355-369](bot/services/lottery_draw.py#L355-L369), `POLICY-lottery.md:303-307`）：仅 winners 收到通知，大多数参与者既不知开奖了没、也不知没中。
6. **`entry_cost_points` 在第 10 步才能设置且默认免费**（[admin_lottery.py:1593-1636](bot/handlers/admin_lottery.py#L1593-L1636)）：管理员忘点直接保存，DB 写 0（免费）。无任何 lint / 警示。
7. **开奖前无预览 / 无二次确认 / 无手动触发**（[lottery_tasks.py:70-103](bot/scheduler/lottery_tasks.py#L70-L103)）：开奖即终态，错配无法挽回。
8. **抽奖列表无状态筛选、无分页**（[admin_lottery.py:124-158](bot/handlers/admin_lottery.py#L124-L158)）：硬编码 `limit=30`；超过 30 条历史抽奖只能看最近 30 条。
9. **公告 / 私聊通知失败无重试 / 无 badge**（[lottery_draw.py:266-352](bot/services/lottery_draw.py#L266-L352)）：仅 log warning；管理员侧无 UI 红点。
10. **必关频道无 username 时入口残废**（[lottery_subscribe_check.py:92-98](bot/services/lottery_subscribe_check.py#L92-L98)）：占位按钮 `noop:lottery_chat_no_link`，用户无法加入，整流被堵死且无"联系管理员索取邀请链接"指引。
11. **参与成功无后续 action**（[lottery_entry.py:166-176](bot/handlers/lottery_entry.py#L166-L176)）：无"查看详情 / 设置开奖提醒 / 分享给好友"按钮。属共性问题 **C1**。
12. **active 期间偷偷改 `entry_cost_points` 不触发公告**（[admin_lottery.py:801](bot/handlers/admin_lottery.py#L801), `POLICY-lottery.md:406`）：已警示但无 UI 强制。

### 3.3 迭代建议

1. **主菜单新增「🎁 抽奖中心」入口**：聚合「进行中可参与 / 我已参与 / 已开奖记录（中奖 ✅ / 未中 ⚪）」。复用既有 callback，新增 `user:lottery:*` 命名空间。属共性 **C10** 落地。
2. **频道帖加 [🤖 私聊 bot 报名] 直链按钮**（含口令模式）：URL 仍是 `t.me/<bot>?start=lottery_<id>`；口令模式 deep link 让用户直接进 bot 后渲染"请发送口令"提示。
3. **失败提示加 [🔁 重新尝试] 按钮**：在订阅失败、积分不足提示末尾加 `lottery:retry:<id>` callback，复用 `start_lottery_from_deep_link`。
4. **频道帖渲染"距开奖剩 X"+ 时区**：`lottery_publish.py:120-148` 增加一行 `⏳ 距开奖 X 天 Y 小时（{config.timezone}）`；配合现有 60s debounce edit。
5. **未中奖通知（可配置开关，默认 off）**：`get_config("lottery_notify_losers")`，开启后批量发简短"很遗憾未中奖 → [查看本次结果]"，节流 1/s 避免 flood。
6. **`entry_cost_points` 升为主线 Step**：插入到必关频道 Step 之后，11 步而非 10 步；保留确认页按钮作为返修入口（保持 callback 不破）。
7. **开奖前 10 分钟管理员预警 + 详情页 [⚡ 立即开奖] 按钮**：注册 `lottery_predraw_<lid>` job 私聊预警；详情页 active 时显示立即开奖按钮（二次确认）。**不违反"不自动化高风险"原则**，仍是人工触发。
8. **抽奖列表加状态 tab + 分页**：复用 `LOTTERY_STATUSES` 做 6 个 tab；底部翻页按钮。
9. **管理员侧加"待跟进 ✉️"badge**：SQL 查 `won=1 AND notified_at IS NULL AND draw_at>now-7d`。
10. **active 改 cost 时强制弹"建议公告"提示**：文案级，零业务风险。

### 3.4 与已有文档的关系

- `POLICY-lottery.md §9.4`「不通知未中奖者」属策略约束，本文痛点 5 / 建议 5 把它从"已知策略"提升为"可选 UX 改进"。
- `UX-EFFICIENCY-PLAN.md §2.1` 已把"用户查抽奖记录"列为中频路径但未实现；建议 1（抽奖中心入口）正是该计划 D 项「账户中心」的落地点。
- 建议 7（预警 + 立即开奖）与 `§1.4` "高风险不允许自动化、可以更易找到"对齐——预警是"找到"，立即开奖必须二次确认。

---

## 4. 报销

### 4.1 现状

**用户申请**：报销**不是独立入口**，必须依附于"写评价"。第 10 步条件可见的"💰 报销询问"页（[review_submit.py:856-867](bot/handlers/review_submit.py#L856-L867)）。系统检查 4 道门槛：
1. 评价存在
2. 必关订阅
3. `amount = compute_reimbursement_amount(price) > 0`
4. `points >= reimbursement_min_points`

任一不满足**直接静默跳过**（[review_submit.py:841-845](bot/handlers/review_submit.py#L841-L845)），用户不知道"为什么没看到报销选项"。功能开关 OFF 时合格用户也走静默 queued 路径（[review_submit.py:847-854](bot/handlers/review_submit.py#L847-L854)）。

点 [💰 是，申请 X 元] 后再触发**报销专用必关订阅**校验（[review_submit.py:904-911](bot/handlers/review_submit.py#L904-L911)），未加入则渲染拦截页。

**用户查看记录**：主菜单 [🧾 我的报销]（[user_kb.py:127](bot/keyboards/user_kb.py#L127)）→ 总览页（本周 X/1、本月已通过 / 池上限、累计申请数、最近 5 笔，[user_reimburse.py:65-89](bot/handlers/user_reimburse.py#L65-L89)）→ 可点 [📋 报销明细] 进入分页。**无单条详情页 / 无取消按钮 / 无申诉入口**。

**管理员审批**：[✅ 审核处理] → [💰 报销审核] → 显示首条 pending → 3 个按钮 [✅ 通过] / [❌ 驳回] / [🔄 重置该用户本周]（`admin_kb.py:1668-1678`）。通过先做月池 + 周限校验，通过后进入支付宝口令 FSM：waiting_token → confirming（[admin_reimburse.py:273-292](bot/handlers/admin_reimburse.py#L273-L292)）；先给用户发消息成功才 approve，失败保留 pending（[admin_reimburse.py:421-487](bot/handlers/admin_reimburse.py#L421-L487)）。驳回必填理由（≤200 字）。

**月度池 / 门槛 / 必关配置**：散落 3 处入口，共 5 个相关按钮（[admin_kb.py:950-959](bot/keyboards/admin_kb.py#L950-L959)）。

### 4.2 痛点

1. **资格不足静默跳过**（[review_submit.py:841-845](bot/handlers/review_submit.py#L841-L845)）：4 道资格任一不满足无提示。属共性问题 **C6**。
2. **功能 OFF 时彻底静默**（[review_submit.py:847-854](bot/handlers/review_submit.py#L847-L854), [rreview_admin.py:514-517](bot/handlers/rreview_admin.py#L514-L517)）：评价提交流程、审核通过通知、"我的报销"页都看不到这条记录的存在，直到超管激活后才出现。
3. **用户无法取消 pending、无法补充材料**（`POLICY-reimbursement.md §10.4` 已注明"否"）：手误申请、信息有误只能等驳回。
4. **驳回后无重新审核 / 无申诉入口**（`POLICY §11.3`）：rejected 是终态，用户拿到驳回通知只能私下找客服。
5. **月度池超额 alert 一次后丢失**（[admin_reimburse.py:247-256](bot/handlers/admin_reimburse.py#L247-L256)）：详情页 `_render_reimbursement_detail` 显示 `remaining` 但不标红，超管下次审同一条还要踩同样坑。
6. **queued / pending 语义混乱**：UI 显示"📋 已录入名单（待启用）"（[user_reimburse.py:44](bot/handlers/user_reimburse.py#L44)）但用户既无"启用"动作也不知道"何时启用"；激活后不通知（`POLICY §9.6`）。
7. **"通过 → 输入支付宝口令 FSM"会丢上下文**（[admin_reimburse.py:374-390](bot/handlers/admin_reimburse.py#L374-L390)）：超管中途 [❌ 取消] 后报销保持 pending，已校验的 reset_voucher_id / month_key 丢失；waiting_token 时收到普通文本会被吞为口令（[admin_reimburse.py:301](bot/handlers/admin_reimburse.py#L301)）有安全隐患。
8. **审批批量操作完全缺失**（全文件无 batch / bulk）：每条 pending / queued 都必须逐条点击。属共性问题 **C4**。
9. **报销专用必关 vs 全局必关用户无法感知差异**（[review_submit.py:870-894](bot/handlers/review_submit.py#L870-L894), [reimburse_subreq_admin.py:62](bot/handlers/reimburse_subreq_admin.py#L62)）：拦截页文案与全局必关几乎相同。
10. **详情页信息密度过高，关键提示无视觉区分**（[admin_reimburse.py:124-151](bot/handlers/admin_reimburse.py#L124-L151)）：13 行同字号文本里"本周已批 1/1（有 1 张未消耗 reset voucher）"是决策信息但与无关字段平铺。属共性问题 **C9**。
11. **配置入口分散且命名重复**（[admin_kb.py:950-959](bot/keyboards/admin_kb.py#L950-L959)）：5 个报销相关入口散在 3 行；"💰 报销必关设置"和"📋 必关频道/群组"同名异义。属共性问题 **C8**。
12. **`mark_reimbursement_notified` 仅在口令链路写入**（[admin_reimburse.py:450-454](bot/handlers/admin_reimburse.py#L450-L454)）：驳回链路不写（[admin_reimburse.py:582-592](bot/handlers/admin_reimburse.py#L582-L592)），`POLICY §12.7` 已标注"死字段"问题部分修复但不完整。

### 4.3 迭代建议

1. **资格不足显式提示**：在 `amount<=0 / points<min_pts` 分支增加温和提示「💡 本次评价不符合报销条件（积分差 X / 老师价位 0）」。功能 OFF 时**仍保持静默**避免暗示。
2. **驳回原因前置常用模板**：在 `cb_reimburse_reject` 进 FSM 前先弹"证据不足 / 重复申请 / 价格异常 / 其他"按钮，预填后可改；保留自由输入兜底。
3. **详情页加状态色块**：根据 `month_remaining / week_used / has_reset` 在文本顶部加 1 行 `✅可批 / ⚠️需消耗 voucher / 🛑超月池`。纯文本 emoji 即可。
4. **queued 激活后通知用户**：`cb_reimburse_activate` 成功后 `send_message(user_id, "你之前的报销名单已激活进入审核队列")`。失败仅 logger.warning。
5. **用户侧加"申诉"快捷按钮**：rejected 记录后追加 [📩 联系客服申诉] URL 按钮（复用 `lottery_contact_url` 模式），不引入 reverse approval。属共性问题 **C1** 落地。
6. **月度池预警显示在用户总览页**（[user_reimburse.py:69-71](bot/handlers/user_reimburse.py#L69-L71)）：当 `pool - month_total < 100` 时显示"⚠️ 即将耗尽"。
7. **审批 badge 含"月池将满"红色信号**（已部分实现，[admin_kb.py:20-37](bot/keyboards/admin_kb.py#L20-L37)）：聚合 pending + 月池警戒。
8. **详情页加 [⏭ 跳过此条] 按钮**（[admin_kb.py:1668-1678](bot/keyboards/admin_kb.py#L1668-L1678)）：当前 pending 移到队尾，无需驳回也无需走完口令 FSM。
9. **批量激活 queued**：列表顶部加 [⚡ 全部激活] + 二次确认 + 单次 audit log 记所有 reimb_id；超过 50 条进一步分页 confirm。
10. **报销系统设置二级菜单收纳**：把 5 个入口聚合到「💰 报销系统配置 ›」，统一展示当前 `feature_enabled / monthly_pool / min_points / queued_count`。保留旧 callback 兼容。属共性问题 **C8** 落地。
11. **支付口令 chat type 守卫**：`step_reimburse_payout_token` 开头加 `if message.chat.type != 'private': return reply("请在私聊里粘贴口令")`，防止群里误粘贴泄露。

### 4.4 与已有文档的关系

- `POLICY-reimbursement.md §3 §11.3 §12.7` 中"需产品确认"项与本文痛点 4 / 6 / 12 一一对应。
- `ROADMAP-PLAN.md Sprint 3 §5.2.1` 报销规则只读页与建议 10（二级菜单收纳）天然耦合，二级页是只读页的载体。
- `UX-EFFICIENCY-PLAN.md §4.4` 已禁止"自动通过"，本文所有建议均未涉及自动化。

---

## 5. 关键词回复

### 5.1 现状

**触发机制**：
- 仅响应 `chat.type ∈ {group, supergroup}` 且 `chat.id ∈ response_group_ids` 的群消息；**私聊不走 keyword**（[keyword.py:514-522](bot/handlers/keyword.py#L514-L522)）。
- 响应群组 ID 由超管在 `config` 表里手动以"逗号分隔的负数 chat_id"配置（[admin_panel.py:398-412](bot/handlers/admin_panel.py#L398-L412)）。
- 四级精准等值匹配（**不区分大小写**，SQL `COLLATE NOCASE` [database.py:1248](bot/database.py#L1248)）：
  1. 艺名 → 老师卡片
  2. 个人/系统查询：硬编码 `{"积分", "报销池"}`
  3. 群组快捷词：硬编码 `{菜单, 今日, 热门, 推荐, 筛选}`
  4. 组合搜索：按 token 拆分 + AND/OR 匹配 `tags / region / price`
- **无匹配静默**（[keyword.py:629](bot/handlers/keyword.py#L629)）。
- 三层冷却（进程内 dict）：群 5s / 同关键词 30s / 用户 15s（[group_search.py:60-72](bot/utils/group_search.py#L60-L72)）。

**配置流程**：
- **唯一入口**：📣 频道/群组设置 → 💬 设置响应群组（[admin_panel.py:386-422](bot/handlers/admin_panel.py#L386-L422)）。只配"在哪些群响应"，**不配"响应什么关键词"**。
- 被识别的关键词完全派生自 `teachers` 表的 `display_name / region / price / tags` 字段（[database.py:1310-1327](bot/database.py#L1310-L1327)）；快捷词与个人查询词硬编码不可改。

### 5.2 痛点

1. **无独立"关键词配置表"**（[keyword.py:63-64](bot/handlers/keyword.py#L63-L64), [keyword.py:172-218](bot/handlers/keyword.py#L172-L218)）：要新增"营业时间"之类的运营关键词必须改代码 + 部署。属共性问题 **C8**。
2. **精确匹配 + 无模糊 = 拼写错误零容忍**（[database.py:1243-1254](bot/database.py#L1243-L1254), [database.py:1337-1347](bot/database.py#L1337-L1347)）：少打一字 / 多一空格立刻全静默；用户感受是"机器人坏了"。属共性问题 **C6**。
3. **无匹配静默不可观测**（[keyword.py:544/566/587/610](bot/handlers/keyword.py#L544)）：`_safe_log_event` 仅在成功时埋点；运营无法在面板看到"今天触发了多少次/多少次被静默"。
4. **群内对话流被关键词打断**（[keyword.py:510-511](bot/handlers/keyword.py#L510-L511)）：catch-all 触发，随口说"天府一街"也会被识别为地区关键词。
5. **冷却进程内 dict 不可观测不可配置**（[group_search.py:64-72](bot/utils/group_search.py#L64-L72)）：30s/15s/5s 是常量；多副本部署时不一致。
6. **响应群组配置输入体验差**（[admin_panel.py:402-409](bot/handlers/admin_panel.py#L402-L409)）：手输 `-100xxx,-100yyy` 字符串；错配一个数字 = 整个群静默且无任何反馈。
7. **N=1 与 N≥2 体验断裂**（[keyword.py:466-504](bot/handlers/keyword.py#L466-L504)）：N=1 走带图卡片，N≥2 走纯文本超链接列表；分页按钮**只附在最后一页**（[keyword.py:488-490](bot/handlers/keyword.py#L488-L490)），用户看完第一页可能不知还有更多。
8. **N≥2 搜索每老师 3 次串行 DB 查询**（[keyword.py:386-407](bot/handlers/keyword.py#L386-L407)）：20 位老师即 60 次串行查询，消耗 5s 群组总冷却。
9. **回复不带 bot 显式署名**（[keyword.py:323-330](bot/handlers/keyword.py#L323-L330)）：艺名卡片用 `answer_photo` 非 reply；群成员看到一张图弹出会困惑"谁发的"。

### 5.3 迭代建议

1. **引入独立的 `keywords` 表**：字段 `trigger / response_text / response_buttons_json / scope_group_ids / cooldown_override / valid_from / valid_to / hit_count`。当前硬编码改为表驱动。运营改文案不再发版。
2. **管理面板加二级菜单「🗝 关键词管理」**：含列表/搜索/分页 + 新增 + 编辑 + 停用 + 预览。`channel_menu_kb` 可平移做模板。
3. **响应群组改为"从 bot 已加入的群里选择"**：bot 加群事件落库 → inline keyboard 多选；回显"群名 + 成员数"避免输错。
4. **群内未命中加"轻量未识别提示"开关**：admin 加 `keyword_unrecognized_hint_enabled` 配置；开启时组合搜索 0 命中且有未识别 token 时，用 `disable_notification=True + ttl_delete` 发小提示。默认 off 保留静默。
5. **配置预览按钮**：点 [预览] 直接把 quick_entry / 老师卡片渲染发到 admin 私聊，让运营改文案前看到真实效果。
6. **冷却从进程内 dict 提升为 config-driven + 可观测**：常量改为 `get_config("keyword.cooldown.*")`；引入 `keyword_silenced` 埋点（在 `check_group_cooldown` 返回 False 处加一次 `_safe_log_event`）。
7. **N≥2 列表加显式翻页按钮 + 并发 enrich**：`_enrich_with_today_status` 用 `asyncio.gather` 并发；每页底部都附 `[⬅️ 上页] [下页 ➡️]`。
8. **短词黑名单 / 最短长度阈值**：admin 加 `keyword.min_length` 和 `keyword.blocklist`；保护 catch-all 边界。
9. **群内回复加 "Bot 触发" 署名 + 强制 reply 原消息**：统一改 `reply_to_message_id`，banner 行加"@<bot_username> · 触发词：<kw>"小注。

### 5.4 与已有文档的关系

- `docs/DESIGN.md:252-343` v1 基线"模式 A/B + 精准匹配 + 大小写无关 + 无匹配静默"是当前真实行为；建议 1/2/4/6 是能力扩展，不破坏现契约。
- `docs/FEATURES-v2.md §2.4.4` 明确"零结果一定回复 vs 群组静默"原则；建议 4 须明示"群组仍可选择保持静默"。
- `UX-EFFICIENCY-PLAN.md §683` 第一批 UX 改造刻意"零修改群关键词"保留双跑期；本文建议属下一阶段候选。

---

## 6. 老师信息录入

### 6.1 现状

**老师本人无法发起注册**（[start_router.py:469](bot/handlers/start_router.py#L469)）。/start 时先查 `get_teacher(user_id)`，无记录直接走普通用户引导。注册入口只有：管理员后台 → 👩‍🏫 老师管理 → 老师列表 → ➕ 新增老师（共 3 跳，[admin_kb.py:115/651/666](bot/keyboards/admin_kb.py#L115)）。

**管理员代填 9 步 FSM**（[teacher_states.py:342-376](bot/states/teacher_states.py#L342-L376)）：
- Step 1：转发老师消息自动抓 user_id + username + contact（[teacher_profile.py:212](bot/handlers/teacher_profile.py#L212)）；抓不到降级 1a/1b/1c 手动 3 步。
- Step 2：艺名（≤40 字）。
- Step 3：基本信息 1 行四字段"年龄 身高 体重 罩杯"（需正则解析）。
- Step 4：地区。
- Step 5：价格描述（必填，bot 自动派生 price 排序值 + description 报销档 + DEFAULT_TABOOS）。
- Step 6：服务内容（**唯一可跳过**）。
- Step 7：标签（自动追加 #8P/#9P/#10P）。
- Step 8：跳转链接。
- Step 9：相册 1-10 张（媒体组 600ms debounce）。
- 确认页 → 入 DB。

`button_text` 自动 = "地区 艺名"（[teacher_profile.py:646](bot/handlers/teacher_profile.py#L646)）。

**老师自助 / `teacher_self`**：`/start` 看到主菜单（[teacher_self_kb.py:8-19](bot/keyboards/teacher_self_kb.py#L8-L19)）只有 3 个按钮：✏️ 我的资料 / ✅ 今日签到 / 📅 今日状态。「我的资料」面板（[teacher_self.py:54-61](bot/handlers/teacher_self.py#L54-L61)）**只能改 6 个老字段**：`display_name / region / price / tags / photo_file_id / button_text`，其余 12 个新字段（age/height/weight/bra/description/service_content/price_detail/taboos/contact_telegram/button_url 等）老师无权修改。

**审核**：老师改文字字段**立即写库** + 创建 edit_request → 通知所有管理员（[teacher_self.py:154-203](bot/handlers/teacher_self.py#L154-L203)）。管理员审核驳回**会通知老师**（[admin_review.py:126-159](bot/handlers/admin_review.py#L126-L159)），但**通过审核无任何通知**（[admin_review.py:258-286](bot/handlers/admin_review.py#L258-L286)，`_notify_teacher_approved` 函数不存在 grep 0 命中）。

### 6.2 痛点

1. **零自助入口，全部依赖管理员代填**（[start_router.py:469](bot/handlers/start_router.py#L469)）：管理员要逐位手填 9 步 + 拉转发消息。
2. **录入 FSM 无超时保护 + MemoryStorage**（[app_factory.py:36](bot/app_factory.py#L36)）：`teacher_profile.py` 全程**未挂** `FSMTimeoutMiddleware`（仅 [teacher_flow.py:70-71](bot/handlers/teacher_flow.py#L70-L71) 注册到旧 router）；服务重启 / 长 FSM 卡死时已上传的 10 张照片 file_id 全部丢失。属共性问题 **C7**。
3. **无草稿保存 / 继续上次**（[teacher_profile.py:194-207](bot/handlers/teacher_profile.py#L194-L207)）：入口直接 `set_data({"photos": []})` 覆盖。
4. **老师自助菜单只能改 6 个老字段，与 admin 12 字段不一致**（[teacher_self.py:54-61](bot/handlers/teacher_self.py#L54-L61)）：高频变更的"价格档位"必须先联系管理员。违反 `UX-EFFICIENCY-PLAN §3.3.C`。
5. **「今日签到」按钮无状态可视化**（[teacher_self_kb.py:17](bot/keyboards/teacher_self_kb.py#L17)）：永远显示同一文案，违反 `§3.3.A`。属共性问题 **C9**。
6. **签到入口位置排第二，非第一**（[teacher_self_kb.py:15-19](bot/keyboards/teacher_self_kb.py#L15-L19)）：违反 `§3.3.A` "第一按钮固定为今日签到"。
7. **签到成功无下一步引导**（[teacher_self.py:472-476](bot/handlers/teacher_self.py#L472-L476)）：仅 alert，无"查看今日展示 / 修改资料 / 返回"三选项。违反 `§3.3.B`。
8. **审核通过老师收不到通知**（[admin_review.py:248-286](bot/handlers/admin_review.py#L248-L286)）：仅写 audit log；老师反复刷面板才知。
9. **驳回原因可跳过 → 老师收到"（未填写）"**（[admin_review.py:317/143](bot/handlers/admin_review.py#L317)）：无申诉入口。
10. **图片字段单图限制，无相册管理**（[teacher_self.py:333-367](bot/handlers/teacher_self.py#L333-L367)）：老师自助只能改 `photo_file_id` 首图；admin 侧有 10 张媒体组但老师不可用。
11. **录入校验失败必须重输，无键盘辅助**（[teacher_profile.py:362-365](bot/handlers/teacher_profile.py#L362-L365)）：错误提示后没有"示例 / 跳过 / 取消"按钮。
12. **重复注册 / 启停路径割裂**（[teacher_profile.py:227/275](bot/handlers/teacher_profile.py#L227), [teacher_flow.py:522](bot/handlers/teacher_flow.py#L522)）：admin 重录只能先去列表启用、再 `tprofile:edit` 改字段，无"合并 / 接管"按钮。
13. **无展示页预览**（老师 grep `teacher_self.py` 无 `format_teacher_detail_text`）：老师无法看到"自己在用户侧呈现的样子"。违反 `§3.3.D`。
14. **无最近评价摘要入口**（[teacher_self_kb.py:8-19](bot/keyboards/teacher_self_kb.py#L8-L19)）：违反 `§3.3.E`。
15. **「今日状态」缺主动"可约"按钮**（[teacher_self_kb.py:27-31](bot/keyboards/teacher_self_kb.py#L27-L31)）：只有"已满 / 取消"；老师误标已满后想撤回必须先签到，且对"今日已取消 → 改为可约"无 callback。
16. **管理员审核 + 老师改字段无 lock**（[teacher_self.py:393-418](bot/handlers/teacher_self.py#L393-L418)）：UPDATE 立即生效 + 写 edit_request；高频改 + 高频驳回会导致用户侧展示页"闪烁"。

### 6.3 迭代建议

1. **签到按钮置顶 + 状态文案动态化**：`teacher_self_kb.py:8` 引入 `await is_checked_in()`；按钮显示 `✅ 今日已签到 14:23` 或 `✅ 今日签到`；移到第一行。
2. **签到后展示"下一步三按钮"**：[查看今日展示] / [修改资料] / [返回面板]。
3. **审核通过新增老师通知**：在 [admin_review.py:265-275](bot/handlers/admin_review.py#L265-L275) 通过分支后新增 `_notify_teacher_approved` 函数。属共性问题 **C1** 落地。
4. **图片字段升级为相册管理**：把 `teacher_self:edit:photo_file_id` 改为跳进 `tprofile:album` 风格的子菜单；仍走 edit_request 审核。
5. **新增高频字段快捷入口**：teacher 主菜单加 [💰 改价格] / [📍 改地区] / [📅 改今日状态] 直接进 FSM；把 `price_detail` 加入 `EDITABLE_FIELDS`。
6. **新增「👁 我在用户那看到的样子」按钮**：复用 `format_teacher_private_detail`。
7. **新增「📝 我的评价」入口 + 摘要**：最近 5 条 + 总分 + 加分总数（只读）。
8. **teacher_profile router 接入 FSMTimeoutMiddleware**：30 分钟无动作 clear 并提示。
9. **草稿保存 1 个 slot**：新表 `teacher_draft_states(admin_id, json_blob, updated_at)`；`tprofile:add` 入口检查未完成草稿 → "上次填到 Step 6，恢复？/ 重新开始"。
10. **驳回必填原因 ≥ 5 字 + 申诉按钮**：把 cb_review_reject_skip 改为禁用；老师驳回通知加 [📩 联系管理员申诉]。
11. **「今日状态」加 [✅ 设为可约] 按钮**：覆盖"误标已满 / 已取消后重置"场景。
12. **老师自助申请加入入口**（待运营对齐）：`start_router.py:483` 普通用户分支末尾加 [🎓 我是老师，申请加入]，进 7 步精简 FSM → pending_teacher_apply 表 → 管理员审核后进入正式 9 步。

### 6.4 与已有文档的关系

- `UX-EFFICIENCY-PLAN.md §3.3` 已规划 A 签到优先 / B 签到后下一步 / C 高频字段快捷 / D 展示页预览 / E 评价反馈五个方向。建议 1-2-3-5-6-7 与之对应，**新增具体代码定位证据**便于 PR 评估。
- 第 3 章**未覆盖**：FSM 持久化 / 审核通过零通知 / 驳回可空 / 老师自助申请入口 / 图片字段割裂 / 今日状态缺可约按钮——这 6 项是本次新发现。

---

## 7. 管理员相关功能

### 7.1 现状

**主面板**（[admin_kb.py:16-76](bot/keyboards/admin_kb.py#L16-L76), [admin_panel.py:74-105](bot/handlers/admin_panel.py#L74-L105)）按角色动态渲染：
- 普通管理员：👩‍🏫 老师管理 / 📈 数据分析 / ✅ 审核处理 / 📊 运营看板 / ⚙️ 系统配置。
- 超管增加：🛡 管理员设置 + 🎲 活动运营 + 审核 badge 含报销待审。

**六大分组**（部分子项）：
- 🛡 管理员设置（超管）：管理员管理 / 审计日志。
- 👩‍🏫 老师管理：老师列表与启停 / 热门推荐 / 今日发布状态 / 用户画像。
- ⚙️ 系统配置：必关订阅 / 发布模板 / 频道群组 / 日报周报 / 系统设置 + 报销池设置 / 报销开关。
- 🎲 活动运营（超管）：抽奖管理 / 积分管理。
- ✅ 审核处理：老师资料 / 评价 / 报销 / 报销名单（超管）。
- 📊 运营看板：运营总览 / 报销池状态 / 抽奖状态。

**点击层级**：多数功能 2 层（主菜单 → 二级页 → 功能）；`menu:system` 是 3 层深度（[admin_kb.py:923-965](bot/keyboards/admin_kb.py#L923-L965) 14 行按钮）。

**已有反馈**：
- badge 较完善（[admin_kb.py:38-43](bot/keyboards/admin_kb.py#L38-L43), [admin_kb.py:197-218](bot/keyboards/admin_kb.py#L197-L218), [admin_kb.py:309-342](bot/keyboards/admin_kb.py#L309-L342)）。
- 审核完成 next 按钮 `admin_review_done_next_kb`（[admin_kb.py:234-263](bot/keyboards/admin_kb.py#L234-L263)）。
- 二次确认普遍存在（报销激活、抽奖取消 / 发布、必关删除、池重置、门槛修改、加扣分）。
- audit log 写入广泛（[admin_panel.py:996-1040](bot/handlers/admin_panel.py#L996-L1040) 定义 40+ action 标签）。

### 7.2 痛点

1. **"📈 数据分析"vs"📊 运营看板"命名易混**（[admin_kb.py:58](bot/keyboards/admin_kb.py#L58), [admin_panel.py:1079](bot/handlers/admin_panel.py#L1079)）：主菜单同一行两个相近文案。
2. **审核详情页不显示"谁正在 / 已经审"**（[admin_review.py:53-86](bot/handlers/admin_review.py#L53-L86), [rreview_admin.py:720-747](bot/handlers/rreview_admin.py#L720-L747)）。
3. **多管理员并发审核无 lock**（[rreview_admin.py:768-774](bot/handlers/rreview_admin.py#L768-L774), [admin_reimburse.py:564-567](bot/handlers/admin_reimburse.py#L564-L567), [admin_review.py:300-302](bot/handlers/admin_review.py#L300-L302)）：写入时才检查 `status != 'pending'`。属共性问题 **C5**。
4. **审核完成"下一步"只在自定义 FSM 路径触发**（[admin_review.py:480-485](bot/handlers/admin_review.py#L480-L485), [admin_reimburse.py:594-598](bot/handlers/admin_reimburse.py#L594-L598), [rreview_admin.py:555-558](bot/handlers/rreview_admin.py#L555-L558)）：预设按钮的高频路径走"自动推下一条"，无显式返回 / 切类型按钮。属共性问题 **C3**。
5. **审核空状态返回路径不一致且偏深**（[admin_kb.py:1177-1685](bot/keyboards/admin_kb.py#L1177)）：三个空状态按钮全指向 `menu:main` 不是 `admin:review_tasks`。
6. **审核详情页"返回"也回主菜单**（[admin_kb.py:1162/1210/1677](bot/keyboards/admin_kb.py#L1162)）：误点返回 → 丢失整队上下文。
7. **`menu:system` 入口臃肿无分组**（[admin_kb.py:923-965](bot/keyboards/admin_kb.py#L923-L965)）：14 行按钮混杂；"📋 必关频道/群组"和"📢 必关订阅"指向同一 callback `admin:subreq`。属共性问题 **C8**。
8. **报销配置散落 3 处**（[admin_kb.py:149-150](bot/keyboards/admin_kb.py#L149-L150), [admin_kb.py:954-959](bot/keyboards/admin_kb.py#L954-L959)）：一次"调整报销规则"通常要进 2 个二级页。
9. **审计日志只能看最近 20 条且无筛选**（[admin_panel.py:1119-1147](bot/handlers/admin_panel.py#L1119-L1147)）：写死 `limit=20`。
10. **抽奖开奖无显式手动入口**（`admin_lottery.py` grep 无 `draw_now`）：定时器触发，无手动 / 预演。
11. **手动加扣分 4 步 FSM 偏冗**（[admin_points.py:241-565](bot/handlers/admin_points.py#L241-L565)）：常见的"+5 评价奖"也要 4 次交互；Step 1 不接受 `@username` 搜索。
12. **报销审批"输入支付宝口令"无 chat type 守卫**（[admin_reimburse.py:301-342](bot/handlers/admin_reimburse.py#L301-L342)）：FSM 只看 state 不限制 chat type，群里粘贴口令会泄露。
13. **报销名单激活无批量**（[admin_reimburse.py:684-808](bot/handlers/admin_reimburse.py#L684-L808)）：积压 30 条要点 30 次。属共性问题 **C4**。
14. **配置改完无"当前值 + 上次修改时间"反馈**（[admin_panel.py:870-872](bot/handlers/admin_panel.py#L870-L872), [reimburse_settings_admin.py:192-195](bot/handlers/reimburse_settings_admin.py#L192-L195)）：仅 toast 一次。
15. **"谁在看"信息写入失败**（[rreview_admin.py:680-687](bot/handlers/rreview_admin.py#L680-L687)）：audit log 里 `admin_id=0` 是 placeholder。
16. **「今日发布状态」「用户画像」是只读聚合页**（[user_tags.py:141-154](bot/handlers/user_tags.py#L141-L154)）：纯文本 ID + score；管理员只能"看到"不能直接点某老师跳详情。

### 7.3 迭代建议（按风险/收益排序）

**A 档：文案与导航（低风险高收益）**

1. **数据分析 / 运营看板命名拆分**（[admin_kb.py:58](bot/keyboards/admin_kb.py#L58), [admin_panel.py:1079](bot/handlers/admin_panel.py#L1079)）：主菜单 `dashboard:enter` 文案改"📈 历史分析"或"📈 用户行为"。**只改文案不改 callback**。
2. **统一审核空 / 详情页返回到 `admin:review_tasks`**（[admin_kb.py:1162/1180/1210/1232/1677/1684](bot/keyboards/admin_kb.py#L1162)）：6 个位置全改。审完空队列 / 误点返回都能 1 次回到 `admin:review_tasks`。
3. **审核详情顶部显当前 reviewer 信息**：audit log 近 5 分钟内别人查看过同条 id 时，渲染"⚠️ @adminX 1 分钟前查看过此条"。

**B 档：审核流水线（中风险中收益）**

4. **审核完成快捷按钮所有路径都返回**：让 `cb_review_approve` / `cb_rreview_approve_preset` / `cb_reimburse_payout_confirm` 在自动推下一条**之后**同时附加 `admin_review_done_next_kb(kind)`。
5. **审核 claim 锁（轻量级）**：进 `cb_rreview_enter` 时写内存 cache 5 分钟 `active_reviewer[review_id] = admin_id`；其他 admin 进同一条 alert "@adminX 正在审核，是否强制接管？"。修复痛点 3 + 15。
6. **报销名单批量激活**：`cb_reimburse_queued` 加 "✅ 一键全部激活本页"按钮，调用 `activate_queued_reimbursement` 批量；每条按钮保留。

**C 档：配置 / 看板（中风险中收益）**

7. **报销配置统一聚合页**：`admin:settings` 下新建"💰 报销配置"二级页；`menu:system` 内报销条目改为提示行"⬆️ 报销配置详见 [系统配置 → 💰 报销配置]"。修复痛点 8。属共性问题 **C8** 落地。
8. **配置改完显示"当前值 + 上次修改"**：每次 `set_config` 后 ack 文案加一行"当前生效值：X，上次由 @adminY 在 YYYY-MM-DD 修改"。所需数据已在 `admin_audit_logs`。
9. **审计日志加分页 + 按管理员 / action 筛选**：扩展为带过滤的子菜单。
10. **「今日发布状态」「用户画像」挂跳转**：[user_tags.py:141-154](bot/handlers/user_tags.py#L141-L154) 输出"老师名"做成 inline button 跳 `teacher:view:<id>`。

**D 档：安全 / 高风险（须慎评）**

11. **报销支付口令 chat type 守卫**（[admin_reimburse.py:301-342](bot/handlers/admin_reimburse.py#L301-L342)）：开头加 `if message.chat.type != 'private': return reply(...)`。安全加固，低代码量。
12. **抽奖手动开奖入口**（仅 active 且 entries > 0）：`admin_lottery_detail_kb` 加 [⚡ 立即开奖]，二次确认 + audit log。须先对照 `POLICY-lottery.md` 评估。

### 7.4 与已有文档的关系

- 命名混淆（建议 1）与 `UX-EFFICIENCY-PLAN.md §4.3.A` / `ROADMAP-PLAN.md Sprint 1` 一致，本文补 `file:line`。
- 子页面返回（建议 2）补 `UX-EFFICIENCY-PLAN §4.3.B` 未列出的**审核三类兜底返回位置**（6 个 `kb` 函数）。
- 审核完成下一步（建议 4）发现 `§4.3.D` 只完成了一半（预设路径 / 跳过路径未接入）。
- **PLAN 未覆盖的新发现**：痛点 3+15（多管理员协作 / 谁在看）、痛点 10（无手动开奖）、痛点 12（口令 chat type 守卫）、痛点 13（报销批量）、痛点 7+8（系统设置臃肿）、痛点 11（加扣分 FSM 冗余）。

---

## 8. 落地优先级建议

> 综合 6 个模块的痛点与 10 条跨模块共性，按"风险 × 收益 × 改动量"排序的迭代批次建议。每批可拆为多个独立 PR；批次之间不强制顺序但建议从上到下。

### 8.1 第一批：低风险文案 / 反馈优化（1-2 个 Sprint 可完成）

> 目标：把"用户感受机器人坏了"和"管理员找不到出口"两类高频抱怨先压下去。

1. **统一审核空 / 详情页返回到 `admin:review_tasks`**（§7 建议 2）：6 处 kb 函数文案级改动。
2. **所有结果通知补 CTA 按钮**（共性 **C1** 落地）：评价驳回 / 通过、报销驳回 / 通过、queued 激活、抽奖参与成功 5 类通知都附 inline keyboard。
3. **签到按钮置顶 + 状态动态化**（§6 建议 1）。
4. **审核通过新增老师通知**（§6 建议 3）：补 `_notify_teacher_approved`。
5. **报销资格不足显式提示**（§4 建议 1）。
6. **抽奖频道帖增"距开奖剩 X" + 时区**（§3 建议 4）。
7. **数据分析 / 运营看板命名拆分**（§7 建议 1）。

### 8.2 第二批：用户侧账户中心（中等改动，1-2 个 Sprint）

> 目标：兑现 `UX-EFFICIENCY-PLAN §2.3.D`「我的记录聚合」愿景。

8. **主菜单新增「🎁 抽奖中心」**（§3 建议 1）。
9. **报销系统设置二级菜单收纳**（§4 建议 10）：解决共性 **C8**。
10. **老师高频字段快捷入口**（§6 建议 5）：[💰 改价格] / [📍 改地区] / [📅 改今日状态]。
11. **驳回 / 申诉链路 UI 化**（§4 建议 5 + §6 建议 10）。

### 8.3 第三批：审核流水线提速（中等改动，需小心 audit log）

> 目标：解决共性 **C3 + C4 + C5**。

12. **审核完成快捷按钮全路径接入**（§7 建议 4）。
13. **审核 claim 内存锁**（§7 建议 5）。
14. **报销名单批量激活**（§7 建议 6）。
15. **评价管理员侧"批量好评通过"**（§2 建议 11）。

### 8.4 第四批：状态可视化 + 卡片体验（中改动）

> 目标：解决共性 **C2 + C6 + C9**。

16. **评价卡片进度计数 + 提交按钮动态文案**（§2 建议 3-4）。
17. **报销详情页色块 + 月度池预警**（§4 建议 3 + 建议 6）。
18. **空状态全统一**（评价、抽奖、报销、关键词无匹配统一加引导）。
19. **抽奖未中奖通知 + active 改 cost 提示**（§3 建议 5 + 建议 10）。

### 8.5 第五批：结构性改动（高改动量）

> 目标：消除长期债务，须独立 Sprint + 完整 CI 回归。

20. **独立 `keywords` 表 + 「🗝 关键词管理」面板**（§5 建议 1-2）。
21. **`teacher_profile` router 接入 FSMTimeoutMiddleware + 草稿保存**（§6 建议 8-9）：解决共性 **C7**。
22. **老师自助申请加入入口**（§6 建议 12）：须与运营对齐。
23. **抽奖创建 FSM 把 `entry_cost_points` 升为主线 Step**（§3 建议 6）。
24. **审计日志加分页 + 筛选**（§7 建议 9）。

### 8.6 第六批：安全加固（独立小 PR）

> 目标：解决潜在的安全侧隐患，与 UX 解耦。

25. **报销支付口令 chat type 守卫**（§7 建议 11）。
26. **关键词冷却 config 化 + silenced 埋点**（§5 建议 6）。

---

## 9. 验收原则

每个 PR 提交前**必须**满足（与 `ROADMAP-PLAN.md §2.6` 一致）：

```bash
python3 -m compileall -q bot
python3 -m pytest
bash -n update.sh
bash -n scripts/healthcheck.sh
bash -n scripts/backup.sh
bash -n scripts/prune.sh
```

每个本文涉及的功能 PR 还**应额外**说明：

- 改动的 `callback_data` 列表（若有）—— `UX-EFFICIENCY-PLAN §1.2` 要求旧 callback 至少保留一个 Sprint。
- 改动的 POLICY 文档同步更新清单 —— `ROADMAP-PLAN §2.7` 要求"业务策略变更必须同步 POLICY 文档"。
- 权限边界声明 —— 谁能看到入口？谁能触发动作？谁能查看结果？
- 回滚路径 —— 是否能通过 `update.sh` 退回？

---

## 10. 文档维护

- 本文档与 `UX-EFFICIENCY-PLAN.md`（按角色）+ `ROADMAP-PLAN.md`（按 Sprint）+ `POLICY-*.md`（按业务）**三视图互补**。
- 当本文中某条迭代被实现 / 否决 / 改名，应在对应模块小节末尾加 strikethrough 或注明状态（`[已实现 PR#xxx]` / `[已否决，原因：xxx]`），不要直接删除——保留**为什么这么做 / 没这么做**的决策记录。
- 新一轮 UX 审查时应**新建**类似 `UX-FEATURE-ITERATION-YYYY-MM-DD.md` 而不是覆盖本文，保留时间快照。

---

## 11. 迭代计划决策记录（2026-05-20 对齐）

> 本节记录在 §8 落地优先级建议基础上，与用户对齐后的最终决策。所有决策都遵守 §0.2 共用红线。
> 决策依据见上一轮对话「如何决策上面的决策点，给出参考建议」。

### 11.1 决策清单

| # | 决策点 | 最终决定 | 关键理由 |
|---|---|---|---|
| 1 | UX-5.3 next kb 显示策略 | 仅"队列为空"时显示 next kb；有下一条时只自动推 | 与自动推下一条互补，避免视觉重复；契合 PLAN §1.5 |
| 2 | UX-6.3 老师菜单按钮上限 | 保持主菜单 ≤ 5；高频字段放在「我的资料」子菜单第一行（路径从 4 步缩到 3 步） | 不破 PLAN §3.5 验收标准 |
| 3 | UX-7.3 评价批量好评通过 | **暂不开放**，先做 UX-7.2 报销批量激活观察 4 周后重评估 | 评价直接关联积分，错误成本不对称；当前缺数据 |
| 4 | UX-8.4 未中奖通知默认值 | `lottery_notify_losers` 默认 **off**，运营按需开启 | 不破坏 POLICY-lottery §9.4 既有策略；Telegram 风控友好 |
| 5 | UX-9.4 老师自助申请 | **暂不开放**，先做 UX-6.3 观察一个 Sprint；若运营明确诉求再重评估 | 业务策略问题，超出 UX 范围 |
| 6 | 第一个 PR | **UX-10.1 → UX-4.6 → UX-5.6** | 安全优先 → 校验节奏 → 清 PLAN 历史欠债 |

### 11.2 触发重评估的条件

| 决策 | 重评估条件 |
|---|---|
| UX-7.3（评价批量） | UX-7.2 报销批量上线 4 周后，看好评积压量与误操作率 |
| UX-8.4（未中奖通知） | 单个抽奖粒度 config 落地后，按需打开 |
| UX-9.4（老师自助） | 运营明确"需要扩老师库"，或 ≥ 5% 普通用户主动咨询"我想加入" |

### 11.3 修正后的执行顺序

```
Week 1:    UX-10.1（安全加固，首个 PR）+ UX-4.6（校验节奏）
Week 2:    UX-5.6（看板命名）+ UX-4.1~4.5（5 个通知 CTA）
Week 3-4:  UX-5.1 / 5.2 / 5.3 / 5.4 / 5.5（5 项）
Week 5-6:  UX-6.1（抽奖中心）
Week 7:    UX-6.2 + UX-6.3 + UX-6.4
Week 8:    UX-7.1 + UX-7.4
Week 9:    UX-7.2（报销批量；4 周观察期开始）
Week 10:   UX-8.1 + UX-8.2 + UX-8.3
Week 11:   UX-8.4（默认 off 落地）
Week 12+:  UX-9 单项独立 Sprint；UX-10.2 任意空档
```

### 11.4 与既有计划的变更对比

- §8.6 推荐执行顺序中"UX-10.1 顺便做"提升为**首个 PR**。
- UX-7.3 从 Sprint UX-7 范围移除（仅保留 7.1 / 7.2 / 7.4）。
- UX-9.4 推迟到运营对齐后才进入排程。
- UX-8.4 落地形态明确为"默认 off + 运营开关"。

### 11.5 决策状态追踪

- [ ] UX-10.1（首个 PR，开工中）
- [ ] UX-4.6
- [ ] UX-5.6
- [ ] UX-4.1 / 4.2 / 4.3 / 4.4 / 4.5
- [ ] UX-5.1 / 5.2 / 5.3 / 5.4 / 5.5
- [ ] UX-6.1 / 6.2 / 6.3 / 6.4
- [ ] UX-7.1 / 7.2 / 7.4
- [ ] UX-8.1 / 8.2 / 8.3 / 8.4
- [ ] UX-9.1 / 9.2 / 9.3 / 9.5 / 9.6
- [ ] UX-10.2
- ~~UX-7.3~~（暂不开放，见 11.2 重评估条件）
- ~~UX-9.4~~（暂不开放，见 11.2 重评估条件）
