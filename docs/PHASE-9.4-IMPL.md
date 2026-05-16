# Phase 9.4 实施指南：超管审核中心 + 私聊通知

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.4.1 / 9.4.2 / 9.4.3
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §4](./REVIEW-FEATURE-DRAFT.md)
> 后续：[PHASE-9.5-IMPL.md](./PHASE-9.5-IMPL.md)（待编写）

---

## 0. 目标

阶段 I（评价基础闭环 9.1→9.4）最后一环：让超管能审核用户提交的评价，并把结果反馈给评价者。

- 主面板：超管可见 [📝 报告审核 (M)] 入口（普通管理员不显示）
- 审核详情：自动 send_media_group 2 张证据图（约课截图 + 现场手势）+ 文字 + 操作按钮
- 操作：[✅ 通过] / [❌ 驳回] / [🖼 重看约课截图] / [✋ 重看手势照片] / [⬅️ 上一条] / [➡️ 下一条] / [🔙 返回主面板]
- 驳回支持 4 预设原因 + 自定义 FSM + 跳过原因
- 私聊通知评价者：通过 / 驳回（含原因或"未填写"）
- 新报告推送：评价提交时向所有超管推送（媒体组 + 概要 + [前往审核] 按钮）
- 所有动作写 admin_audit_logs

**用户决策（已采纳）：**
- callback 前缀：`rreview:*`（避开旧 admin_review.py 的 `review:*` 和 9.3 review_submit.py 的 `review:*`）
- 翻页时删旧 2 条消息（聊天干净，不堆积）
- 驳回预设：证据不充分 / 内容违规 / 重复提交 / 评分明显不合理
- 推送范围：主超管 + 所有 is_super=1（去重）

**不做：**
- 档案帖统计聚合写入 / discussion_anchor / discussion 评论发布（Phase 9.5）
- 积分加分（Phase P.1；spec §4.4 注：积分上线后修改"通过"流程）
- 撤回 / 软删除 / 重新审核（spec §9）

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +60 行：approve_teacher_review / reject_teacher_review / list_super_admins |
| `bot/keyboards/admin_kb.py` | +60 行：main_menu_kb 加 is_super + 4 个 rreview 键盘 |
| `bot/handlers/admin_panel.py` | +18 行：_build_main_menu_kb(user_id) + audit label 3 条 |
| `bot/handlers/admin_review.py` | +20 行：_build_user_aware_menu 保证超管在该路径也能看到入口 |
| `bot/handlers/start_router.py` | +15 行：管理员 /start 入口按 is_super 渲染主菜单 |
| `bot/handlers/review_submit.py` | +9 行：提交成功 asyncio.create_task 推送超管 |
| `bot/states/teacher_states.py` | +7 行：RReviewRejectStates |
| `bot/main.py` | +6 行：注册 rreview_admin_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/handlers/rreview_admin.py` | 报告审核所有 callback + 翻页 + 驳回 FSM | ~580 |
| `bot/utils/rreview_notify.py` | 私聊评价者 + 推送超管 | ~140 |

---

## 2. DB 变更

无 schema 变更（9.3.1 已建好 teacher_reviews 表）。新方法：

| 方法 | 说明 |
|---|---|
| `approve_teacher_review(rid, reviewer_id)` | pending → approved + reviewer_id + reviewed_at；仅 pending 时 UPDATE（防重复通过） |
| `reject_teacher_review(rid, reviewer_id, reason)` | pending → rejected + reviewer_id + reviewed_at + reject_reason（reason 可空） |
| `list_super_admins()` → `list[int]` | 主超管 + DB is_super=1 去重排序 |

---

## 3. UI / 交互

### 3.1 主面板入口

`main_menu_kb` 签名扩展为 `(pending_count=0, *, pending_review_count=0, is_super=False)`。
仅当 `is_super=True` 时在"数据看板 / 待审核"下方插入：

```
📝 报告审核 (M)   ← M = count_pending_reviews()
```

入口 callback：`rreview:enter`

### 3.2 审核详情页

进入时 bot 发 2 条消息（按 spec §4.2）：

**消息 1 — 媒体组（2 张证据图）**
```
[ 约课记录截图 ]  caption "📸 约课记录"
[ 现场手势照片 ]  caption "✋ 现场手势"
```

**消息 2 — 报告内容 + 操作按钮**
```
[报告审核 1/3]
老师：丁小夏
评价者：****6204 (uid: ****6204)
提交：2026-05-16 12:34:56

📸 审核材料：已在上方 2 张图
────────────────────
评级：👍 好评 · 🎯 综合 8.6
🎨 人照 9.0 | 颜值 9.2 | 身材 8.5
   服务 9.5 | 态度 9.7 | 环境 8.8
📝 过程：非常推荐
────────────────────
[✅ 通过] [❌ 驳回]
[🖼 重看约课截图] [✋ 重看手势照片]
[⬅️ 上一条] [➡️ 下一条]   ← 边界条件控制按钮显示
[🔙 返回主面板]
```

3 个 message_id 暂存 state（`rreview_media_msg_ids` + `rreview_text_msg_id`），
翻页 / 通过 / 驳回时通过 `_cleanup_messages` 删除旧的两条消息。

### 3.3 通过流程

1. `approve_teacher_review(rid, reviewer_id)` UPDATE pending → approved
2. `log_admin_audit(action="rreview_approve")`
3. `notify_review_approved` 私聊评价者
4. 删旧 2 条消息 + 推下一条 / 队列空回主面板

### 3.4 驳回流程

```
[❌ 驳回] → 选项页：
  [证据不充分] [内容违规] [重复提交] [评分明显不合理]
  [📝 自定义原因] [⏭ 跳过原因]
  [🔙 取消]

选预设 → reject(reason=PRESET[i]) → 通知评价者
选自定义 → RReviewRejectStates → 文本 ≤ 200 字 → reject(reason=text)
选跳过 → reject(reason=None) → 通知评价者"未填写"
```

`_do_reject` 统一执行：reject_teacher_review + audit + notify + 清旧 + 推下一条。

### 3.5 重看截图

`rreview:photo:booking:<id>` / `rreview:photo:gesture:<id>` → 单独 send_photo
（caption "📸 约课记录" / "✋ 现场手势"），不破坏当前审核详情视图。

### 3.6 翻页

`rreview:nav:prev:<id>` / `rreview:nav:next:<id>`：
- 重新 list_pending_reviews 拿最新队列
- 查找当前 id 索引；不存在（其他超管已处理）→ 退回第 0 条
- prev/next 计算新索引；越界 → "已到边界" alert
- 否则 `_show_review_at_index` 删旧消息 + 发新 2 条

### 3.7 新评价推送（spec §4.5）

`review_submit.py:cb_review_submit` 在 `create_teacher_review` 成功后：

```python
asyncio.create_task(
    notify_super_admins_new_review(callback.bot, review_id)
)
```

不阻塞用户响应；失败仅 logger.warning。

`notify_super_admins_new_review` 给每个 super_admin 发：
- send_media_group 2 张证据图（与审核详情页相同）
- send_message 概要文字（老师/评价者半匿名/评级/综合/过程）+ [📝 前往审核] 按钮

容错：用户屏蔽 bot / chat 不可达 → 跳过该超管 + warning，不推后续 send_message。

---

## 4. 实施顺序（3 次 commit）

### Commit 9.4.1 — 主菜单入口 + 详情页 + 通过 happy path
- compileall + 9 module import + 12 项 sanity
- main_menu_kb 切换 is_super；approve/reject DB；list_super_admins 去重

### Commit 9.4.2 — 翻页 + 重看 + 驳回 FSM + 私聊评价者
- compileall + 6 module import + 9 项 sanity
- REJECT_PRESETS 4 条 / FSM / reject 3 路径 / notify_approved/rejected /
  TelegramForbiddenError 容错

### Commit 9.4.3 — 推送超管 + audit + 端到端 + PHASE-9.4-IMPL（本文件）
- 10 步 E2E：录档案 → review pending → 推送 2 超管 → 通过 + 私聊 →
  驳回(预设/None) + 私聊 → pending=0 → 9.3 回归 → 屏蔽 bot silent skip →
  9.1/9.2 渲染回归

---

## 5. 验收清单

### 5.1 DB
- [x] approve_teacher_review 仅 pending 时 UPDATE
- [x] reject_teacher_review reason 可空（NULL）
- [x] list_super_admins 主超管 + DB is_super=1 去重

### 5.2 主菜单
- [x] is_super=False 不显示 [📝 报告审核]
- [x] is_super=True 显示，含 (N) 角标
- [x] /start / menu:main / 审核 FSM 退出 / cmd_cancel 全路径 user-aware

### 5.3 审核详情
- [x] 进入时自动 send_media_group + send_message
- [x] 操作按钮 6 类齐全（通过/驳回/重看 2/翻页 2/返回）
- [x] 翻页时删旧 2 条 + 发新 2 条
- [x] 重看截图单独 send_photo 不影响当前视图

### 5.4 通过 / 驳回
- [x] 通过 → status approved + reviewer_id + reviewed_at + audit + 私聊
- [x] 驳回 4 预设：reason=PRESET[idx]
- [x] 驳回自定义：FSM ≤ 200 字 + /cancel 回展示页
- [x] 驳回跳过：reason=None + 私聊"未填写"
- [x] 处理完后清旧 2 条 + 推下一条 / 队列空回主面板

### 5.5 推送超管
- [x] 提交成功后 asyncio.create_task 推送（不阻塞用户响应）
- [x] 媒体组 + 文字 + [前往审核] 按钮
- [x] 用户屏蔽 bot / chat 不可达 → silent skip + 不发后续 send_message
- [x] 主超管 + 所有 is_super=1 去重

### 5.6 兼容
- [x] 9.1 / 9.2 / 9.3 全部回归（parse_basic_info / publish / check_user_subscribed / 渲染）
- [x] daily 14:00 / 关键词 / 收藏 / 签到等不受影响

### 5.7 静态
- [x] python3 -m compileall bot 通过
- [x] 9 module import 链 OK

---

## 6. 风险与缓解（实际落实）

| 风险 | 缓解 |
|---|---|
| 超管被其他超管"抢审"导致 callback 失效 | 翻页 / 通过 / 驳回前再 list_pending_reviews；当前 id 不在 → 回第 0 条 |
| 通过 / 驳回时 DB UPDATE 失败（其他超管已改 status）| 仅 pending 才更新，UPDATE 0 行 → alert 提示 + 不通知评价者 |
| 媒体组发送失败（频道无权限 / file_id 过期）| 文字消息提示 + 不阻塞 + 不写 state |
| 评价者屏蔽 bot → 私聊通知失败 | _safe_send_text 容错，仅 logger.warning |
| 超管也屏蔽 bot → 推送失败 | 跳过该超管 + 不发后续 + 继续推送其他超管 |
| 自定义原因过长 | ≤ 200 字校验 |

---

## 7. 不在本 Phase 范围

- ❌ 通过后写 teacher_channel_posts 聚合统计 / edit_message_caption / 讨论群评论 → Phase 9.5
- ❌ discussion_anchor_id 监听（is_automatic_forward）→ Phase 9.5
- ❌ 积分加分 / 加分子页 → Phase P.1（spec §4.4 注）
- ❌ 详情页评价区块 / 评价列表分页 → Phase 9.6
- ❌ 撤回 / 软删除 / 重新审核 → spec §9 标注 Phase 9.x 后续
- ❌ 审核员之间的并发锁 / 队列分配 → 多超管偶尔抢审已通过列表"消失即跳"容错

---

## 8. 完成后

至此 **阶段 I（评价基础闭环 9.1→9.4）全部完成**。用户即可在系统内完整走通
"写评价 → 超管审核 → 私聊反馈"流程，可向用户**内测**。

但仍缺：
- 通过审核后档案帖统计不自动更新（停留 "0 条车评"）—— Phase 9.5
- 用户在私聊详情页看不到评价 —— Phase 9.6

Phase 9.5 开始前需确认：
- discussion_chat_id 配置：自动捕获 `is_automatic_forward` 还是手动配置全局？
- 讨论群锚消息丢失时的恢复策略：自动重建 vs 告警超管
- 评价聚合统计更新触发：仅通过时 / 还有其他触发？
- `/start write_<teacher_id>` deep link 路由：在 start_router 加分支
