# Phase 9.3 实施指南：必关频道校验 + 报告 FSM + DB

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.3.1 / 9.3.2 / 9.3.3 / 9.3.4
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §2/§3/§7.2/§7.4](./REVIEW-FEATURE-DRAFT.md)
> 后续：[PHASE-9.4-IMPL.md](./PHASE-9.4-IMPL.md)（待编写）

---

## 0. 目标

用户在老师详情页点 [📝 写评价] → bot 校验"老师 active + 限频 + 必关频道" →
进入 12 步 FSM（前置 3 步证据 + 9 步评分） → 确认页（含 11 个跳回按钮） →
DB `teacher_reviews` 落 pending + 评价者标记 "评论型用户"。

**用户决策（已采纳）：**
- 确认页"修改某项"：本 phase 实现 11 个跳回按钮
- Step A 选老师：留给 9.5（仅"裸入口"触发；本 phase 唯一入口是详情页按钮）
- 提交后推送超管：留给 9.4
- 限频：纯 DB 查询（4 个索引保证 µs 级）

**不做：**
- 审核 UI / 超管推送 / 审核驳回通知（Phase 9.4）
- 档案帖统计更新 / 讨论群评论 / `/start write_<id>` deep link（Phase 9.5）
- 详情页评价区块展示 / 评价列表分页（Phase 9.6）

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +333 行：2 表 schema + 5 索引 + 8 CRUD + 12 常量 + 1 纯函数 |
| `bot/keyboards/admin_kb.py` | +60 行：system_menu_kb 加 [📋 必关频道/群组] + 5 个 subreq 键盘 |
| `bot/keyboards/user_kb.py` | +110 行：teacher_detail_kb 加 [📝 写评价] + 6 个 review 键盘 |
| `bot/states/teacher_states.py` | +30 行：SubReqAddStates + ReviewSubmitStates |
| `bot/handlers/admin_panel.py` | +4 行：audit label 字典加 subreq_* |
| `bot/main.py` | +6 行：注册 subreq_admin / review_submit router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/utils/required_channels.py` | check_user_subscribed + precheck_required_chat | 74 |
| `bot/handlers/subreq_admin.py` | [📋 必关频道/群组] admin 子菜单 | ~280 |
| `bot/handlers/review_submit.py` | 12 步 FSM + 限频 + 评论型用户标签 | ~460 |

---

## 2. 数据库变更

### 2.1 Schema

`init_db` 内 executescript 新增 2 表（spec §7.2 / §7.4）：

```sql
CREATE TABLE IF NOT EXISTS teacher_reviews (
    id INTEGER PK,
    teacher_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    booking_screenshot_file_id TEXT NOT NULL,    -- Phase 9.3 证据 1
    gesture_photo_file_id      TEXT NOT NULL,    -- Phase 9.3 证据 2
    rating TEXT NOT NULL,                         -- positive/neutral/negative
    score_humanphoto..environment REAL NOT NULL,  -- 6 维 0-10
    overall_score REAL NOT NULL,
    summary TEXT,                                 -- 5-100 字可空
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id, reject_reason,                   -- 9.4 用
    discussion_chat_id, discussion_msg_id,        -- 9.5 用
    created_at, reviewed_at, published_at,
    CHECK (all scores BETWEEN 0 AND 10)
);
CREATE INDEX idx_reviews_teacher_status / status_created / user_created /
              user_teacher_created;

CREATE TABLE IF NOT EXISTS required_subscriptions (
    id INTEGER PK, chat_id INTEGER UNIQUE, chat_type TEXT,
    display_name TEXT, invite_link TEXT,
    sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
    created_at, updated_at
);
CREATE INDEX idx_required_subs_active;
```

### 2.2 新 DB 方法 + 常量（Phase 9.3 区块）

| 名称 | 说明 |
|---|---|
| `REVIEW_DIMENSIONS` (6) / `REVIEW_RATINGS` (3) | 评分维度 / 评级常量 |
| `REVIEW_SCORE_MIN/MAX/DECIMAL_PLACES` | 0.0 / 10.0 / 1 |
| `REVIEW_SCORE_QUICK_BUTTONS_FOR_DIM` / `_OVERALL` | 快捷按钮配置 |
| `REVIEW_SUMMARY_MIN/MAX_LEN` | 5 / 100 |
| `REVIEW_RATE_LIMIT_PER_TEACHER_24H = 3` / `_PER_USER_DAY = 10` / `_PER_USER_60S = 1` | 3 项限频阈值 |
| `parse_review_score(text)` | 纯函数：0.0-10.0 / 最多 1 位小数 → float / None |
| `add_required_subscription` / `list / get / toggle / remove_required_subscription` | required_subscriptions CRUD |
| `create_teacher_review(data)` → review_id | 校验必填 + CHECK 越界返 None |
| `get_teacher_review(rid)` | 单条读 |
| `count_recent_user_reviews(uid, seconds)` | 限频用 |
| `count_recent_user_teacher_reviews(uid, tid, seconds)` | 限频用 |
| `count_pending_reviews` / `list_pending_reviews` | 9.4 用 |

---

## 3. 必关频道校验（`bot/utils/required_channels.py`）

### 3.1 `check_user_subscribed(bot, user_id)` → `(all_joined, missing)`

- 列表为空 → `(True, [])`（spec §3.4 无门槛）
- 已加入判定：`status ∈ {member, administrator, creator}`
- bot 异常（频道不存在 / 没权限）→ 跳过该项 + warning，不计入 missing（spec §9）

### 3.2 `precheck_required_chat(bot, chat_id)` → `(ok, reason, info)`

配置时预校验：`bot.get_chat` + `bot.get_chat_member(bot.id)` 双校验。

---

## 4. UI 设计

### 4.1 admin [📋 必关频道/群组] 子菜单

进入路径：[⚙️ 系统设置] → [📋 必关频道/群组]

| 入口 | 功能 |
|---|---|
| `admin:subreq` | 列表 + 空状态文案 |
| `admin:subreq:add` | 3 步 FSM（含 precheck_required_chat 拦截 bot 不在场） |
| `admin:subreq:item:<id>` | 详情：显示名/类型/chat_id/邀请链接/状态/排序 |
| `admin:subreq:toggle:<id>` | 启停切换 + audit |
| `admin:subreq:remove:<id>` → `:remove_confirm:<id>` | 二次确认删除 + audit |

### 4.2 用户 [📝 写评价] 流程

详情页 `teacher_detail_kb` 第 4 行追加 [📝 写评价]（callback `review:start:<teacher_id>`）。

入口校验顺序：
1. teacher active：停用 → "该老师已停用"
2. 限频：60s/teacher_24h(3)/user_day(10) 任一超阈 → 中文原因
3. `check_user_subscribed` → 缺时展示链接列表 + [🔙 返回主菜单]
4. 通过 → 进 12 步 FSM

### 4.3 FSM 12 步

```
[Step B/12] 上传约课截图（F.photo + file_id 校验）
[Step C/12] 上传现场手势照片
[Step 1/9]  评级：👍/😐/👎
[Step 2/9]  🎨 人照评分（快捷 9 按钮 + 文字 0-10 1 位小数）
[Step 3/9]  颜值
[Step 4/9]  身材
[Step 5/9]  服务
[Step 6/9]  态度
[Step 7/9]  环境
[Step 8/9]  🎯 综合评分（快捷 7 按钮 + 文字）
[Step 9/9]  📝 过程描述（可选 5-100 字 / [⏭ 跳过]）
→ 确认页（11 个 [✏️ 修改:xxx] + [✅ 提交] + [❌ 取消]）
→ create_teacher_review + add_user_tag(评论型用户)
```

### 4.4 修改某项跳回

确认页点 [✏️ 修改:xxx] callback `review:edit:<key>`：
- 设 `state.data["jump_back"] = True`
- 跳回对应状态展示原 prompt + 键盘
- 该步保存后回确认页（不继续下一步）

### 4.5 限频提示文案

| 阈值 | 文案 |
|---|---|
| 60s/用户 ≥ 1 | "提交太频繁，请 1 分钟后再试" |
| 24h/老师 ≥ 3 | "今天该老师已超出限制（3 条/24h）" |
| 24h/用户 ≥ 10 | "今天已超出全平台限制（10 条/24h）" |

---

## 5. 实施顺序（4 次 commit）

### Commit 9.3.1 — DB schema + CRUD + 评价常量
- compileall + 8 项 sanity（parse_review_score 13 边界 / required_subscriptions
  CRUD / create_teacher_review 缺字段 / CHECK 越界 / count_recent_*）

### Commit 9.3.2 — 必关频道校验 + admin 子菜单
- compileall + 8 module import + 12 项 sanity（check_user_subscribed 4 种状态 /
  停用项跳过 / precheck 3 种状态）

### Commit 9.3.3 — 报告 12 步 FSM + 入口 + 限频
- compileall + 9 module import + 7 项 sanity（teacher_detail_kb 含按钮 /
  11 修改按钮 / 12 状态 / 3 项限频拒绝）

### Commit 9.3.4 — 端到端 sanity + PHASE-9.3-IMPL.md（本文件）
- 9 步 E2E：录档案 → 校验空列表 → 校验未加入 → 校验已加入 → 完整 FSM 数据
  → create_review → add_user_tag → 60s 限频 → 24h/teacher 限频 → pending count

---

## 6. 验收清单

### 6.1 DB
- [x] teacher_reviews / required_subscriptions schema 齐 4+1 索引
- [x] 评价常量与 spec §7.5 一致
- [x] CHECK 约束阻止越界评分（11.0 → None）
- [x] parse_review_score 13 边界全过
- [x] count_recent_* 与索引匹配

### 6.2 必关频道
- [x] 列表为空 → 无门槛（True, []）
- [x] 部分未加入 → 拒绝 + missing 列表
- [x] bot 异常 → 跳过该项不计 missing
- [x] 停用项不参与校验
- [x] precheck bot 不在场拒绝（status=left/kicked）

### 6.3 评价 FSM
- [x] [📝 写评价] 入口校验 4 步（active/限频/必关/photo）
- [x] 12 步走通 → DB 落 pending
- [x] 11 个 [✏️ 修改:xxx] 跳回对应状态后回确认页
- [x] 限频 3 项分别生效 + 中文提示
- [x] /cancel 任意步退出
- [x] add_user_tag(评论型用户) 入库

### 6.4 admin 子菜单
- [x] [⚙️ 系统设置] → [📋 必关频道/群组] 可进入
- [x] 3 步 FSM 含 precheck
- [x] toggle/remove 二次确认 + audit log

### 6.5 兼容
- [x] 现有 75 老师不动；Phase 9.1/9.2 全部 FSM / 渲染 / 发布功能正常
- [x] daily 14:00 / 关键词 / 收藏 / 签到等不受影响

### 6.6 静态
- [x] python3 -m compileall bot 通过
- [x] 9 module import 链 OK

---

## 7. 风险与缓解（实际落实）

| 风险 | 缓解 |
|---|---|
| 必关频道列表为空 → 拒绝所有用户 | 空列表视为无门槛（spec §3.4） |
| bot 被踢出某必关频道 → check 一直失败 | 跳过该项 + warning（spec §9） |
| 用户上传非图片消息 → FSM 卡死 | 校验 F.photo + 停留 + 提示重发 |
| caption 超 1024 | Phase 9.1.2 已有截断 |
| 用户在确认页停留过久 → 限频可能在确认时才触发 | submit 时再校验一次限频 |
| CHECK 约束失败 → 入库报错 | create_teacher_review try/except + 返回 None，handler 用 alert 反馈 |

---

## 8. 不在本 Phase 范围

- ❌ 审核 UI / [📝 报告审核] 主面板 / 通过/驳回 → Phase 9.4
- ❌ 审核后档案帖统计更新 / 讨论群评论 / deep link → Phase 9.5
- ❌ 详情页评价区块 / 评价列表分页 → Phase 9.6
- ❌ Step A 选老师 FSM（裸入口时）→ Phase 9.5
- ❌ 用户撤回评价（spec §9 注：Phase 9.x 后续）

---

## 9. 完成后

Phase 9.3 完成 → 立即开 Phase 9.4（超管审核中心 + 私聊通知）。

> Phase 9.4 开始前需确认：
> - 审核详情页消息 1（媒体组 2 张证据图）和消息 2（报告内容 + 按钮）的承载方式
> - 翻页 / [🖼 重看截图] 按钮的实现细节
> - 通过 / 驳回后给评价者发的私聊文本模板
> - 新评价推送给超管的频率：实时？聚合？
