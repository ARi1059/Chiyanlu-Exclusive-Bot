# Phase 9.5 实施指南：档案帖统计自动更新 + 讨论群评论发布

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.5.1 / 9.5.2 / 9.5.3 / 9.5.4
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §4.4 / §6.3 / §10](./REVIEW-FEATURE-DRAFT.md)
> 后续：[PHASE-9.6-IMPL.md](./PHASE-9.6-IMPL.md)（待编写）

---

## 0. 目标

阶段 II（评价完整闭环 9.5 → 9.6）的第一步：让超管审核通过后，频道档案帖统计自动刷新，并在讨论群自动发评论。

- 评价通过时一次性触发：聚合统计 + edit_message_caption + 讨论群发评论
- 监听 `is_automatic_forward` 自动捕获讨论群锚消息 id
- 锚消息丢失 → fallback 发不 reply 的消息 + 告警超管
- 评论 3 个底部按钮：[🔗 联系] / [评级徽章 noop] / [🤖 写评价 deep link]
- 新增 `/start write_<teacher_id>` deep link → 直接进评价 FSM
- noop:rating callback：仅 answer

**用户决策（已采纳）：**
- 锚丢失 → fallback 不 reply + 告警超管
- discussion_chat_id 仅依赖自动捕获（不加 admin 配置入口）
- deep link 未加入必关 → 展示链接列表拒绝（与按钮入口一致）
- noop:rating → 仅 callback.answer()

**不做：**
- 详情页评价区块展示 / 分页（Phase 9.6）
- 积分加分（Phase P.1）
- 撤回 / 修改
- discussion_chat_id admin 手动配置

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +160 行：4 个新方法（recalc 聚合 / discussion 写入 / find by channel_msg） |
| `bot/handlers/rreview_admin.py` | +18 行：approve 后链式触发 recalc + edit_caption + publish_comment |
| `bot/handlers/start_router.py` | +60 行：parse_start_args 加 write_<id> + _route_by_role 分支 |
| `bot/handlers/review_submit.py` | +25 行：抽取 start_review_flow（callback / deep link 共用） |
| `bot/utils/rreview_notify.py` | +18 行：notify_super_admins_anchor_lost |
| `bot/main.py` | +6 行：注册 discussion_anchor_router + noop_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/handlers/discussion_anchor_listener.py` | F.is_automatic_forward 监听 + 锚捕获 | ~90 |
| `bot/utils/review_comment.py` | render_review_comment + publish_review_comment + fallback | ~210 |
| `bot/handlers/noop_handlers.py` | noop:* callback 占位 | ~15 |

---

## 2. DB 变更

无 schema 变更。新方法：

| 方法 | 说明 |
|---|---|
| `recalculate_teacher_review_stats(tid) -> dict` | SELECT approved AVG + 三级 count → UPDATE teacher_channel_posts（无 post 行时仅返回字典） |
| `update_teacher_channel_post_discussion(tid, chat_id, anchor_id) -> bool` | 写讨论群锚消息 id |
| `update_review_discussion_msg(rid, chat_id, msg_id) -> bool` | 评价发布后回写 + published_at |
| `find_teacher_post_by_channel_msg(chat_id, msg_id) -> Optional[dict]` | 监听器用，严格匹配 channel_msg_id（媒体组只取首张） |

---

## 3. 关键流程

### 3.1 审核通过链式触发（cb_rreview_approve）

```
approve_teacher_review (9.4)
  → recalculate_teacher_review_stats (9.5.1)     ← UPDATE 聚合
  → update_teacher_post_caption(force=True) (9.2) ← edit_message_caption
  → publish_review_comment (9.5.3)               ← 讨论群发评论
  → notify_review_approved (9.4.2)               ← 私聊评价者
  → 清旧 2 条审核消息 + 推下一条
```

任一步失败：log warning + 继续后续步骤（不阻塞）。

### 3.2 讨论群锚自动捕获（监听器）

```
Telegram 自动转发频道帖到绑定讨论群
  ↓
@router.message(F.is_automatic_forward.is_(True))
  ↓
extract (forward_chat_id, forward_msg_id)
  ↓ 兼容 forward_origin (新) / forward_from_chat (老)
find_teacher_post_by_channel_msg(chat, msg)
  ↓ 严格匹配 channel_msg_id（仅媒体组首张）
update_teacher_channel_post_discussion(teacher_id, msg.chat.id, msg.message_id)
```

### 3.3 讨论群评论发布

```
get_review + get_teacher + get_post → 缺锚 raise CommentError(no_anchor)
  ↓
render_review_comment → text + kb (3 按钮)
  ↓
send_message(chat=discussion_chat, reply_to=anchor_id)
  ↓ "reply not found"
send_message(chat=discussion_chat, NO reply)   ← fallback
  ↓
notify_super_admins_anchor_lost                 ← 告警重发档案帖
  ↓
update_review_discussion_msg + published_at
```

### 3.4 评论文本 + 3 按钮（spec §6.3）

```
【老师】：丁小夏
【留名】：****6204
【人照】：9
【颜值】：9.2
【身材】：8.5
【服务】：9.5
【态度】：9.7
【环境】：8.8
【综合】：9.21
【过程】：非常推荐

✳ Powered by @ChiYanBookBot
```

按钮（独占一行）：
- `[🔗 联系{name前10字…}]` URL=teacher.button_url
- `[👍 好评]` callback=noop:rating（纯视觉徽章）
- `[🤖 给{name前10字…}写报告]` URL=`t.me/{bot}?start=write_{teacher_id}`

- `name > 20 字符` → 按"前 10 字…"截断
- 6 维评分保留原精度（9 / 8.5）
- 综合固定 2 位小数（9.21）
- summary=None → 【过程】整行省略

### 3.5 /start write_<id> deep link

```
parse_start_args("write_80001") → review_target_id=80001
  ↓ 普通用户分支（管理员 / 老师角色不触发）
_route_by_role 调 start_review_flow（review_submit.py 抽取）
  ↓ 检查 teacher active / 限频 / 必关频道
  ok → 进 ReviewSubmitStates.waiting_booking_screenshot
  rate_limited → "提交太频繁" + 主菜单
  need_subscribe → 链接列表 + "加入后再次点击..."
  inactive / not_found → 主菜单
```

---

## 4. 实施顺序（4 次 commit）

### Commit 9.5.1 — 聚合 + edit caption
- compileall + 6 项 sanity：0 条 / 3 条混合评级 / 有无 post 行 / discussion 写入 / published_at

### Commit 9.5.2 — anchor 监听器
- compileall + 7 项 sanity：forward_origin 新 API / 老 API / 无信息 / 匹配 / 媒体组其它张跳过 / chat 不匹配 / 完全无 forward

### Commit 9.5.3 — 评论发布 + 3 按钮 + noop + fallback
- compileall + 8 项 sanity：边界函数 / 标准 render + 半匿名 + 3 按钮 / summary=None / no_anchor / happy path / fallback 锚丢失 / noop answer

### Commit 9.5.4 — deep link + E2E + 文档
- 9 步端到端：录档案 + post → 模拟自动转发 → 提交 review → approve → recalc + edit_caption +
  publish_comment → parse_start_args("write_<id>") → 锚丢失 fallback → 9.1/9.2/9.3 回归

---

## 5. 验收清单

### 5.1 DB
- [x] recalculate 仅 approved 计入；review_count / 三级 count / 6 维 avg / overall avg 正确
- [x] 无 teacher_channel_posts 行时仅返回字典不抛错
- [x] discussion 写入 round-trip
- [x] find_by_channel_msg 严格 channel_msg_id（忽略媒体组其它张）

### 5.2 监听器
- [x] forward_origin（新 API）+ forward_from_chat（老 API）兼容
- [x] 仅 channel_msg_id 触发，媒体组其它张跳过
- [x] 不匹配 chat / 无 forward 信息 silent skip

### 5.3 评论发布
- [x] 标准 render：【综合】2 位小数 / 6 维原精度 / 半匿名留名
- [x] summary=None 整行省略
- [x] name > 20 字符按前 10 字截断
- [x] 3 按钮：联系 URL / noop:rating / write deep link
- [x] no_anchor → CommentError；happy path 写 published_at
- [x] fallback 锚丢失 → 不 reply 重发 + 告警超管

### 5.4 deep link
- [x] parse_start_args("write_80001") → review_target_id=80001
- [x] 与 teacher_<id> 不冲突
- [x] 普通用户：未加入必关 → 链接列表；限频 → 提示；通过 → 进 FSM
- [x] 管理员 / 老师角色不触发 review flow

### 5.5 链式触发
- [x] approve → recalc + edit_caption + publish_comment + notify 全链通
- [x] 任一步失败 log + 继续，不阻塞通知评价者

### 5.6 兼容
- [x] 9.1 / 9.2 / 9.3 / 9.4 全部回归
- [x] daily 14:00 / 关键词 / 收藏 / 签到不受影响

### 5.7 静态
- [x] python3 -m compileall bot
- [x] 全 module import 链 OK

---

## 6. 风险与缓解（实际落实）

| 风险 | 缓解 |
|---|---|
| Telegram 限流（edit_message_caption / send_message） | 9.2 has 60s debounce；本 phase 调 force=True 显式同步 |
| 锚消息被群管删 | fallback 发不 reply + notify_super_admins 提示重发档案帖 |
| 媒体组多张图都触发 forward 事件 | 严格匹配 channel_msg_id 只取首张那条 |
| bot 不在讨论群（监听不到）| 整链失败 log + 继续；不阻塞评价者通知；admin 需手动拉 bot 进讨论群 |
| caption 渲染 ValueError（必填后被清空）| update_teacher_post_caption 内部 silent skip + log |
| reply_to_message_id 未传 + Telegram 自动 reply 行为 | send_message 不传该参数 → Telegram 不 reply |
| Telegram BadRequest 多种文案 | 用 substring 匹配 "reply" + "not found" / "message to reply" |
| review_target_id 与 teacher_detail_id callback 冲突 | parse_start_args 按前缀 write_ / teacher_ 分别匹配，互斥 |

---

## 7. 不在本 Phase 范围

- ❌ 详情页评价区块 / 分页（Phase 9.6）
- ❌ 积分加分（Phase P.1，spec §4.4 注）
- ❌ 撤回 / 修改 / 软删除
- ❌ 多讨论群配置（spec 假设单频道单讨论群）
- ❌ admin 主动重建锚消息（仅告警，由 admin 重发档案帖触发监听器重写）

---

## 8. 完成后

至此 **阶段 II 第一步完成**。用户能体验"写评价 → 超管审核 → 频道档案帖即时刷新 + 讨论群自动发评论 + 私聊反馈"完整闭环。

Phase 9.6 开始前需确认：
- 详情页统计块的位置（[✨ 相似推荐] 之上 还是 [📩 联系老师] 之下？）
- 最近评价显示几条（3 条 / 5 条 / 按需）
- 评价签名半匿名规则（与讨论群一致？或可独立配）
- 是否启用评价数加权排序（spec §10 标"可选"）
