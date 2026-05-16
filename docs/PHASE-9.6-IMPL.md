# Phase 9.6 实施指南：私聊详情页评价区块 + 分页

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：9.6.1 / 9.6.2
> 关联 spec：[REVIEW-FEATURE-DRAFT.md §5 / §10](./REVIEW-FEATURE-DRAFT.md)
> 后续：**整个评价系统（9.1-9.6）已全部完成 ✅**

---

## 0. 目标

阶段 II 第二步（也是评价系统最后一步）：让用户在私聊老师详情页看到该老师的车评统计 + 最近 3 条评价，并支持分页查看全部。

- 详情页底部加统计块（review_count / 三级 % / 6 维 + 综合 avg）+ 最近 3 条评价
- [📖 查看全部评价 (N)] 按钮 → 分页（10 条/页）
- 评价签名：first_name 首字 + `*`，无 first_name → `匿*`
- 0 条评价时整段省略（按钮也不显示）

**用户决策（已采纳）：**
- 统计块位置：[✨ 相似推荐] 之上（spec §5）
- 显示条数：3 条
- 半匿名格式：first_name 首字 + `*`
- 不启用评价数加权排序（spec §10 标"可选"）

**不做：**
- 评价加权排序 / hot_score 调整
- 撤回 / 修改评价
- 群组卡片层级显示评价

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +60 行：list_approved_reviews / count_approved_reviews / get_users_first_names |
| `bot/handlers/teacher_detail.py` | +30 行：_build_detail_payload 末尾追加评价区块 |
| `bot/keyboards/user_kb.py` | +60 行：teacher_detail_kb 加 review_count 参数 + review_list_pagination_kb |
| `bot/main.py` | +6 行：注册 review_list_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/utils/review_detail_render.py` | 详情页统计块 + 最近评价渲染 + 半匿名 + 异步取数 | ~150 |
| `bot/handlers/review_list.py` | teacher:reviews:<id> / :<id>:<page> 分页 callback | ~100 |

---

## 2. DB 变更

无 schema 变更。新方法：

| 方法 | 说明 |
|---|---|
| `list_approved_reviews(tid, limit, offset)` | 按 created_at DESC, id DESC；仅 approved |
| `count_approved_reviews(tid)` | 仅 approved 计数 |
| `get_users_first_names(uids)` | 批量取 users.first_name（一次 SQL） |

---

## 3. UI / 文本

### 3.1 详情页评价区块（spec §5）

在 [✨ 相似推荐] 之上插入：

```
📊 35 条车评，综合评分 9.21
好评 100.0% | 人照 9.08 | 服务 9.07
中评   0.0% | 颜值 9.27 | 态度 9.63
差评   0.0% | 身材 8.94 | 环境 9.15

最近评价：
────────────────────
小* · 👍 好评 · 🎯 8.6
📝 非常推荐，下次还会再约
— 2026-05-16

匿* · 👍 好评 · 🎯 9.2
📝 可以再约
— 2026-05-15

群* · 😐 中评 · 🎯 6.5
📝 （无总结）
— 2026-05-14
────────────────────
```

按钮组（变更）：

```
[📩 联系老师]
[⭐ 收藏] [🔔 提醒]
[📖 查看全部评价 (35)]    ← Phase 9.6 新增（review_count > 0 时显示）
[✨ 相似推荐]
[📝 写评价]
[🔙 返回主菜单]
```

### 3.2 半匿名签名规则

```python
anonymize_signer("小红")     → "小*"
anonymize_signer("Alice")    → "A*"
anonymize_signer("")         → "匿*"
anonymize_signer(None)       → "匿*"
anonymize_signer("   ")      → "匿*"
```

### 3.3 分页页面（10 条/页）

```
📖 丁小夏 的评价列表
共 35 条 · 第 2/4 页

────────────────────
小* · 👍 好评 · 🎯 8.6
📝 非常推荐
— 2026-05-16
...（10 条）
────────────────────

[⬅️ 上一页] [📄 2/4] [➡️ 下一页]
[🔙 返回老师详情]
```

边界：
- page=0：无 [⬅️ 上一页]
- 末页：无 [➡️ 下一页]
- 中间 [📄 N/M] 用 callback `noop:page`（仅 answer，9.5.3 noop 路由已就绪）
- 0 条评价：callback 直接 alert "该老师暂无评价"（不进列表页）
- page 超界：clamp 到末页

---

## 4. 实施顺序（2 次 commit）

### Commit 9.6.1 — 详情页评价区块
- compileall + 6 module import + 10 项 sanity
- anonymize_signer 6 边界 / stats_block 0 条返回 "" + 35 条标准格式 /
  list_approved DESC + 仅 approved / fetch_signer_names 批量 / summary=None /
  teacher_detail_kb 0 不显示 / >0 显示 / _build_detail_payload 端到端

### Commit 9.6.2 — 分页 + E2E + 文档（本文件）
- compileall + 10 步 E2E：
  录 12 条 → recalc 8+3+1 → 详情页拼 12 / 最近 3 / 按钮 (12) →
  _parse_callback 边界 → page 0 [10 条+下一页] → page 1 [2 条+上一页] →
  0 条老师无统计 + alert / 老师不存在 alert / page 超界 clamp / 9.1/9.3/9.5 回归

---

## 5. 验收清单

### 5.1 DB
- [x] list_approved_reviews 仅 approved + created_at DESC
- [x] count_approved_reviews 仅 approved
- [x] get_users_first_names 批量取

### 5.2 渲染
- [x] anonymize_signer 中文/英文/空/纯空白 6 边界
- [x] format_review_stats_block 0 条返回 "" / 标准 35 条 4 行格式
- [x] format_recent_reviews_block 多条间空行 + ─ 分隔
- [x] summary=None → "（无总结）"
- [x] 日期 created_at 截取前 10 字符

### 5.3 详情页
- [x] _build_detail_payload 拼接评价区块（异常容错不破坏详情展示）
- [x] teacher_detail_kb 按 review_count 切换 [📖 查看全部评价] 按钮
- [x] 与 [📝 写评价] / [✨ 相似推荐] 共存

### 5.4 分页
- [x] _parse_callback 解析 teacher:reviews:<id> / :<id>:<page>
- [x] page=0 无 [⬅️ 上一页]
- [x] 末页无 [➡️ 下一页]
- [x] page 超界 clamp 到末页
- [x] 0 条评价 alert 拒绝进列表

### 5.5 兼容
- [x] 9.1 / 9.2 / 9.3 / 9.4 / 9.5 全部回归
- [x] daily 14:00 / 关键词 / 收藏 / 签到不受影响

### 5.6 静态
- [x] python3 -m compileall bot
- [x] 全 module import 链 OK

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 评价区块拼接失败 → 详情页无法展示 | try/except 容错 + warning log，不阻塞详情主体 |
| 长 summary 多条 → 单消息超 4096 字符 | format 后再截断（review_list 内 4000 字限制） |
| 评论编辑同样文本（noop:page 等）触发 BadRequest | edit_text try/except 安全忽略 |
| edit_text 同样内容（用户翻页到当前页）→ "message is not modified" | 忽略异常 + callback.answer |
| 0 评价时按钮误显示 | review_count=0 时跳过按钮渲染 |
| first_name 含 emoji 或不可见字符 | 取首字符即可，不做特殊处理（Telegram 渲染容错） |

---

## 7. 不在本 Phase 范围

- ❌ 评价加权排序（spec §10 标"可选"）
- ❌ hot_score 调整
- ❌ 撤回 / 修改 / 软删除评价
- ❌ 群组卡片层级显示评价（仅私聊详情页）
- ❌ 详情页"我的评价"个人视图

---

## 8. 整个评价系统（9.1-9.6）完成

至此 **评价系统 6 个 phase 全部完成**：

| Phase | 内容 | 状态 |
|---|---|---|
| 9.1 | 老师档案数据扩展 + 后台录入 FSM | ✅ |
| 9.2 | 档案帖自动发布到频道 | ✅ |
| 9.3 | 必关频道校验 + 报告 12 步 FSM | ✅ |
| 9.4 | 超管审核中心 + 私聊通知 | ✅ |
| 9.5 | 档案帖统计自动更新 + 讨论群评论发布 | ✅ |
| 9.6 | 私聊详情页评价区块 + 分页 | ✅ |

闭环：
- admin 录档案 → 发频道（媒体组）
- 用户在详情页点 [📝 写评价] → 12 步 FSM → 提交 pending
- 超管审核通过 → 频道统计自动刷新 + 讨论群评论自动发 + 私聊评价者
- 用户在详情页看统计块 + 最近 3 条 + 分页查看全部

按 IMPLEMENTATION-PLAN 总规划，下一组：
- **B 组 积分系统**（P.1 / P.2 / P.3）—— spec [POINTS-FEATURE-DRAFT.md](./POINTS-FEATURE-DRAFT.md)
- **C 组 抽奖系统**（L.1 / L.2 / L.3 / L.4）—— spec [LOTTERY-FEATURE-DRAFT.md](./LOTTERY-FEATURE-DRAFT.md)

两组互不依赖；可并行或串行实施。
