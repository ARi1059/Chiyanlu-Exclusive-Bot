# Phase 9.2 实施指南：档案帖自动发布到频道

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.2.1 / 9.2.2 / 9.2.3
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §6.2 + §7.3](./REVIEW-FEATURE-DRAFT.md) / [PHASE-9.1-IMPL.md](./PHASE-9.1-IMPL.md)
> 后续：[PHASE-9.3-IMPL.md](./PHASE-9.3-IMPL.md)（待编写）

---

## 0. 目标

admin 在 [📋 老师档案管理] 选老师 → 进 [👁 预览] → 点 [📤 发布档案帖到频道] → bot `send_media_group` 把"相册 + caption"发到频道；
点 [🔄 重发] 删旧 + 重发；点 [❌ 删除频道帖] 清频道 + 清 DB；
admin 编辑老师任意字段后，bot 自动 `edit_message_caption` 同步（60s debounce）。

**用户决策（已采纳）：**
- 档案频道 → 独立 `archive_channel_id`，未配置时回退 `publish_channel_id` 第一个
- 字段编辑后 → 自动 + 60s debounce（基于 `teacher_channel_posts.updated_at`）
- discussion_anchor 监听 → 不纳入本 phase，留给 9.5

**不做：**
- 评价聚合统计写入 `teacher_channel_posts.review_count / avg_*`（Phase 9.5）
- discussion 群锚消息 (`is_automatic_forward`) 监听（Phase 9.5）
- 批量发布工具 / 老师删除时级联删频道帖

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +166 行：档案帖 CRUD + archive_channel_id 配置 |
| `bot/handlers/admin_panel.py` | +74 行：[📦 设置档案频道] FSM + view 同步显示 + audit label |
| `bot/handlers/teacher_profile.py` | +212 行：预览页发布动作 + 6 个 callback + _finish_edit 钩子 |
| `bot/keyboards/admin_kb.py` | +54 行：channel_menu_kb 加按钮 + 3 个新键盘 |
| `bot/states/teacher_states.py` | +5 行：SetArchiveChannelStates |

### 1.2 新增文件

| 文件 | 用途 |
|---|---|
| `bot/utils/teacher_channel_publish.py` | 发布工具：publish / update_caption / repost / delete + PublishError |

---

## 2. 数据库变更

### 2.1 无 schema 变更

`teacher_channel_posts` 表已在 Phase 9.1.1 建好。本 phase 仅新增 CRUD 函数；
新增配置项 `archive_channel_id` 复用 `config` 表，**无需 migration**。

### 2.2 新 DB 方法（database.py 末尾「档案帖发布 (Phase 9.2)」区块）

| 方法 | 签名 | 说明 |
|---|---|---|
| `set_archive_channel_id` | `(chat_id: int)` | set_config("archive_channel_id", str) |
| `get_archive_channel_id` | `() -> Optional[int]` | 独立配置 → 回退 publish_channel_id 第一个 → None |
| `upsert_teacher_channel_post` | `(teacher_id, chat_id, msg_id, media_group_msg_ids: list[int])` | INSERT 或 UPDATE 4 列；保留 review_count/avg_* |
| `get_teacher_channel_post` | `(teacher_id) -> Optional[dict]` | 解析 media_group_msg_ids JSON → list[int] |
| `touch_teacher_channel_post` | `(teacher_id) -> bool` | 仅 update updated_at |
| `delete_teacher_channel_post` | `(teacher_id) -> bool` | DELETE FROM row |
| `seconds_since_last_caption_edit` | `(teacher_id) -> Optional[float]` | julianday 算秒差，用于 60s debounce |

---

## 3. 发布工具（`bot/utils/teacher_channel_publish.py`）

### 3.1 PublishError

```python
class PublishError(Exception):
    """reason ∈ incomplete / no_channel / no_photos / already_published /
                 not_published / api_error
    """
    def __init__(self, reason: str, message: str, *, missing: list[str] = None): ...
```

### 3.2 主函数

| 函数 | 行为 |
|---|---|
| `publish_teacher_post(bot, teacher_id)` | 校验齐备 + 渲染 + send_media_group + upsert |
| `update_teacher_post_caption(bot, teacher_id, *, force=False)` | 60s debounce + edit + touch；force 绕过 |
| `repost_teacher_post(bot, teacher_id)` | best-effort 删旧 + delete row + publish |
| `delete_teacher_post(bot, teacher_id)` | best-effort 删频道 + delete row |

### 3.3 关键细节

- `_build_media_group` 仅给第一张挂 caption（Telegram 媒体组规则）
- update 时遇 `"message is not modified"` → 视为成功 + touch（避免空 edit 报错）
- 删旧媒体组失败不阻塞 publish/repost（warning + 继续）
- update_caption silent skip 未发布老师（不抛错），仅 force=True 时抛 not_published

---

## 4. UI 设计

### 4.1 [📢 频道设置] 子菜单（admin_kb.py）

```
📢 频道/群组设置
├── 📌 设置发布目标         ← 旧
├── 📦 设置档案频道         ← 新（Phase 9.2）
├── 💬 设置响应群组
├── 📋 查看当前设置        ← 同步显示档案频道三态
└── 🔙 返回主菜单
```

### 4.2 [📦 设置档案频道] FSM

- 进入：展示当前生效值 + 来源（独立配置 / 回退 / 未设置）
- 输入：单个数字 chat_id；回复 `0` 清空独立配置
- 入库：set_config("archive_channel_id", str)，audit `archive_channel_set`

### 4.3 [👁 预览档案 caption] 页面动作按钮

`cb_preview_show` 末尾根据 `is_published` / `can_publish` 切换：

| 状态 | 按钮 |
|---|---|
| 未发布 + 必填齐备 | [📤 发布档案帖到频道] |
| 未发布 + 必填不齐 | （无发布按钮，仅显示缺哪些字段） |
| 已发布 | [🔄 重发档案帖] [🔄 同步 caption] / [❌ 删除频道帖] |
| 任何状态 | [🔙 返回档案管理] |

### 4.4 6 个新 callback

| callback | 行为 |
|---|---|
| `tprofile:publish:<uid>` | 调 publish_teacher_post + audit |
| `tprofile:sync:<uid>` | update_teacher_post_caption(force=True) + audit |
| `tprofile:repost:<uid>` | 二次确认页 |
| `tprofile:repost_confirm:<uid>` | 实际 repost + audit |
| `tprofile:unpublish:<uid>` | 二次确认页 |
| `tprofile:unpublish_confirm:<uid>` | 实际 delete + audit |

失败时 PublishError → `callback.answer(message, show_alert=True)`。

### 4.5 自动 edit caption 钩子（_finish_edit）

```python
# _finish_edit 内，在 message.answer("✅ 已更新…") 之后：
if success:
    try:
        edited = await update_teacher_post_caption(message.bot, target_user_id)
        if edited:
            await message.answer("📡 已同步频道 caption。")
    except Exception as e:
        logger.warning(...)  # 不打断 admin 流程
```

silent skip 条件：未发布 / 60s 内已 edit / 渲染失败（仅 logger）

---

## 5. 实施顺序（3 次 commit）

### Commit 9.2.1 — DB CRUD + 发布工具

**改动**：bot/database.py +166 行、bot/utils/teacher_channel_publish.py 新 269 行

**验收**：
- compileall 通过
- 15 项 sanity：init_db 幂等 / archive_channel_id 三种状态 / publish happy path /
  缺必填/重复发/无频道/未发布/无照片 5 类错误 / 60s debounce 命中 / force 绕过 /
  repost 删 3 重发 3 / delete 链路 / 删旧失败 best-effort

### Commit 9.2.2 — Admin UI + 自动 edit 钩子

**改动**：admin_kb.py / states / admin_panel.py / teacher_profile.py

**验收**：
- compileall + 10 module import 链
- channel_menu_kb 含 channel:set_archive
- teacher_profile_publish_action_kb 三种状态正确
- audit label 字典齐备（5 个新 action）

### Commit 9.2.3 — 端到端 sanity + 文档

**改动**：docs/PHASE-9.2-IMPL.md（本文件）

**验收**：
- 11 步 E2E 流程通过：配置→录入→发布→编辑→debounce→100s 后→sync→repost→delete→边界→9.1 回归
- 旧 phase 回归：parse_basic_info / get_teacher_full_profile / render_teacher_channel_caption 仍工作

---

## 6. 验收清单

### 6.1 DB
- [x] archive_channel_id 优先级：独立 → 回退 publish_channel_id 第一个 → None
- [x] teacher_channel_posts upsert 覆盖发布相关 4 列；保留 review_count / avg_*
- [x] seconds_since_last_caption_edit 在刚 upsert 时 < 2s

### 6.2 发布工具
- [x] publish_teacher_post happy path：send_media_group + upsert
- [x] 已发布 → already_published；未发布 → not_published；缺必填 → incomplete（含 missing 列表）
- [x] 60s debounce：内部 silent skip；force=True 绕过
- [x] repost 删旧失败 best-effort 不阻塞
- [x] "message is not modified" → 视为成功 + touch

### 6.3 Admin UI
- [x] [📢 频道设置] → [📦 设置档案频道] FSM 走通；回复 0 清空；当前值 + 回退说明
- [x] [👁 预览] 页根据已发布/可发布切按钮；缺必填时无发布按钮
- [x] 字段编辑后自动 edit caption（60s debounce）；silent skip 未发布；edited 时回提示
- [x] 6 个 callback：publish / sync / repost(_confirm) / unpublish(_confirm) 均走 audit log

### 6.4 兼容
- [x] daily 14:00 发布、关键词响应、收藏、签到等老功能未受影响
- [x] Phase 9.1 录入/编辑/相册/预览 仍可用，[👁 预览] 末尾追加发布按钮不破坏旧 UX

### 6.5 静态
- [x] python3 -m compileall bot 通过
- [x] 全 module import 链 OK

---

## 7. 风险与缓解（实际遇到的）

| 风险 | 缓解（已落实） |
|---|---|
| send_media_group 失败 / 频道无权限 | PublishError(api_error) 提示原始异常 |
| Telegram 限流 edit_message_caption | 60s debounce + "message is not modified" 兜底 |
| 删旧媒体组部分失败 | best-effort：log warning + 继续发新 |
| 老师必填后来被清空 | update_caption render ValueError → silent skip（log warning）|
| caption 超 1024 字符 | Phase 9.1.2 已有截断逻辑 |
| admin 误删频道帖 | 二次确认页 + 不删老师本身（只删 DB row + 频道消息）|

---

## 8. 不在本 Phase 范围

- ❌ 评价聚合统计写入 teacher_channel_posts.review_count / avg_*（Phase 9.5）
- ❌ discussion_chat_id / discussion_anchor_id 监听（Phase 9.5）
- ❌ 批量发布 / 批量补全工具
- ❌ 老师删除时级联删频道帖（DB 是 ON DELETE CASCADE，但 Telegram 帖保留 —— spec §9）
- ❌ 频道帖软删除 / "⚠️ 已下架"标签（Phase 9.5+）

---

## 9. 完成后

Phase 9.2 完成 → 立即开 Phase 9.3（必关频道校验 + 报告 12 步 FSM + DB）。

> Phase 9.3 开始前需确认：
> - 必关频道列表的初始数据（可空）
> - 必关校验函数的告警渠道（超管私聊？或独立日志频道？）
> - 评价提交频率限制（24h/teacher = 3 次 / 日/用户 = 10 次 / 60s = 1 次）
