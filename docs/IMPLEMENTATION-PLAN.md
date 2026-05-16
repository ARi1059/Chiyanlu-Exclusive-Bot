# Phase 9.x 实施总计划

> 状态：v1.0
> 创建：2026-05-16
> 关联 spec：[REVIEW](./REVIEW-FEATURE-DRAFT.md) · [POINTS](./POINTS-FEATURE-DRAFT.md) · [LOTTERY](./LOTTERY-FEATURE-DRAFT.md)

---

## 0. 全景

13 个独立可发布的 phase，按业务依赖归为 3 组：

```
A 组（评价系统）  9.1 → 9.2 → 9.3 → 9.4 → 9.5 → 9.6
B 组（积分系统）                       ↘ P.1 → P.2 → P.3
C 组（抽奖系统） L.1 → L.2 → L.3 → L.4    （完全独立）
```

| Phase | 内容 | 主要依赖 | 估算 commit 数 |
|---|---|---|---|
| **9.1** | 老师档案数据扩展 + 后台录入 FSM + 预览 | — | 4 |
| **9.2** | 档案帖自动发布到频道（媒体组 + caption） | 9.1 | 3 |
| **9.3** | 必关频道校验 + 报告 12 步 FSM + DB | 9.1 | 4 |
| **9.4** | 超管审核中心 + 私聊通知 + 证据图发送 | 9.3 | 3 |
| **9.5** | 档案帖统计块自动更新 + 讨论群评论发布 | 9.2 + 9.4 | 4 |
| **9.6** | 私聊详情页评价展示 + 分页 | 9.5 | 2 |
| **P.1** | 积分 DB + 审核加分子页 | 9.4 | 2 |
| **P.2** | 用户「我的积分」入口 | P.1 | 2 |
| **P.3** | 超管「积分管理」工具 | P.1 | 3 |
| **L.1** | 抽奖 DB + 创建/编辑/列表 | — | 3 |
| **L.2** | 频道发布 + 用户参与 (button/code) | L.1 | 4 |
| **L.3** | 定时开奖 + 中奖通知 | L.2 | 3 |
| **L.4** | 管理员工具完善 + 客服链接配置 | L.3 | 2 |

合计约 **39 次 commit**，每次 commit 都需通过 `python3 -m compileall bot`。

---

## 1. 依赖图

```mermaid
9.1 ──┬──> 9.2 ──┐
      │          │
      └──> 9.3 ──> 9.4 ──┬──> 9.5 ──> 9.6
                          │
                          └──> P.1 ──┬──> P.2
                                     │
                                     └──> P.3
L.1 ──> L.2 ──> L.3 ──> L.4
```

**关键路径**：9.1 → 9.3 → 9.4 → 9.5 → 9.6（评价闭环最长链）
**最小可用**：9.1 → 9.2 → 9.3 → 9.4（用户能写报告 + 超管能审；档案帖不自动更新）

---

## 2. 推荐执行顺序（4 阶段分批上线）

### 阶段 I — 评价基础闭环（9.1 → 9.4）

**目标**：admin 能录入老师档案；用户能写报告；超管能审核。

阶段 I 结束后即可向用户内测，但缺：
- 通过审核后档案帖不自动更新（停留在"0 条车评"）
- 用户在私聊详情页看不到评价

### 阶段 II — 评价完整闭环（9.5 → 9.6）

**目标**：审核通过 → 档案帖统计实时更新 + 讨论群评论区自动发布 + 私聊详情页同步展示。

### 阶段 III — 积分集成（P.1 → P.2 → P.3）

**目标**：审核通过加分；用户能看自己的积分；超管能手动加/扣分。

### 阶段 IV — 抽奖独立功能（L.1 → L.4）

**目标**：超管能创建抽奖，定时发布到频道，定时自动开奖。

> 💡 阶段 IV 与 I-III 完全无依赖，**可以与阶段 I 并行**（如有人力）。但单人开发建议串行，专注度更高。

---

## 3. 风险与缓解

### 3.1 Telegram API 相关

| 风险 | 影响 | 缓解 |
|---|---|---|
| `send_media_group` 限流（>10 张/秒）| 档案帖发不出 | 限流：每次发布间隔 ≥ 1s |
| `edit_message_caption` 频次限制 | 统计块更新延迟 | 用 debounce：60s 内同一帖最多 edit 1 次 |
| 媒体组 caption 1024 字符上限 | 老师介绍超长 | 字段优先级截断（描述 > 服务 > 价格 > 禁忌）|
| bot 在讨论群权限不足 | 评论发不出 | 启动时自检 + 配置时校验 |
| 频道未绑定讨论群 | 9.5 阶段评论功能 ko | 优雅降级：仅 DB + 详情页可用，频道发布跳过 |
| file_id 在不同环境失效 | 极少见 | bot 仅在自己上传的 file_id 用，安全 |
| 锚消息被讨论群管理员误删 | 评论发不出 | 自动重建 + 告警超管 |

### 3.2 数据模型相关

| 风险 | 影响 | 缓解 |
|---|---|---|
| 现有 75 老师数据 | 新字段全 NULL，档案帖发不出 | 兼容：DB 层 NULL OK；admin 需逐个补全后才发频道 |
| `photo_file_id` 字段保留 | 老数据迁移 | 新逻辑读 `photo_album`，空时回退 `photo_file_id` |
| `UNIQUE(teacher_id, user_id)` 在评价表 | 用户能否多评一人 | 已决策 = 不限次，**无 UNIQUE 约束** |
| 历史评价老师下架 | 已发布评价是否保留 | 保留，档案帖加 "⚠️ 已下架" 标签 |

### 3.3 业务流程相关

| 风险 | 影响 | 缓解 |
|---|---|---|
| 用户上传非图片消息 | FSM 卡死 | 校验类型 + 停留当前步 + 提示重发 |
| 关注校验时 bot 不在某频道 | 永远拒绝用户 | 配置时校验 + 运行时该项跳过 |
| 超管审核积压 | 用户长时间无反馈 | [📝 报告审核 (M)] 徽标可视化 + 7 天告警 |
| 抽奖随机性被质疑 | 用户不信任 | 使用 `secrets.SystemRandom`（CSPRNG）+ 文档化 |
| 抽奖配置后改动 | 用户不公平 | active 状态可编辑所有字段，但每次修改写 audit log |

---

## 4. 提交节奏与规范

### 4.1 单 phase 内 commit 拆分

每个 phase 拆 2-4 次 commit，**每次都能独立部署**：

| Commit 类型 | 内容 | 验收 |
|---|---|---|
| `commit-1: DB` | schema migration + 新方法 + sanity test | compileall + import 验证 + 端到端简单测试 |
| `commit-2: 后端` | handlers / FSM / utils | compileall + 手工触发 FSM 测试 |
| `commit-3: UI` | keyboards / 文案 | compileall + 真实 bot 走一遍 |
| `commit-4: 集成` | 端到端流程 + 修复 + 文档 | 关闭 phase |

### 4.2 commit message 规范

```
feat: Phase 9.1.<step> <简短描述>

详细变更点...

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

例：
- `feat: Phase 9.1.1 老师档案 DB 字段扩展 + 迁移`
- `feat: Phase 9.1.2 完整录入 FSM 11 步`
- `feat: Phase 9.1.3 [📋 老师档案管理] 子菜单 + 字段编辑`
- `feat: Phase 9.1.4 档案 caption 预览 + 端到端 sanity`

### 4.3 部署前必做

每次推送到 GitHub 前：
```bash
# 1. 语法 + import 检查
python3 -m compileall bot
BOT_TOKEN=dummy SUPER_ADMIN_ID=1 python3 -c "
import importlib
mods = ['bot.config', 'bot.database', 'bot.main', ...]
for m in mods:
    importlib.import_module(m)
"

# 2. 端到端 sanity check（在 /tmp 临时 db 上跑）
BOT_TOKEN=dummy SUPER_ADMIN_ID=1 DATABASE_PATH=/tmp/sanity.db python3 -c "
# 主要数据库方法的 happy path + 边界
"
```

---

## 5. 测试策略

每个 phase 完成后，按以下顺序验证：

1. **静态检查**：`compileall` + import 所有 modules
2. **数据库层**：在 `/tmp/sanity.db` 上跑 DB 方法的 happy path / 边界
3. **本地 import 链**：`python3 -c "from bot.main import *"` 顺利
4. **真实 bot 验证**：服务器 `./update.sh` 后手动测：
   - happy path 至少 1 个
   - error path 至少 2 个（不合法输入 / 越界）
5. **回归测试**：随机点几个老旧功能（签到 / 收藏 / 搜索），确保未坏

---

## 6. 回滚策略

每次 commit 都需保证可回滚：

- **DB migration 幂等**：所有 ALTER TABLE 都先 `PRAGMA table_info` 检测
- **旧字段绝不删除**：`photo_file_id` 与 `photo_album` 并存
- **旧 callback 兼容**：新 callback 命名空间用新前缀（如 `tprofile:` / `review:` / `lottery:`）
- **新功能可灰度**：必关频道列表为空 → 视为无门槛，本期等同关闭

如果某 phase 上线后发现严重 bug：
1. 立即 `systemctl stop chiyanlu-bot`
2. `git revert <commit-hash>`
3. `git push`
4. `./update.sh restart`

DB schema 变更**不回滚**（向后兼容设计已经允许 NULL）。

---

## 7. 接下来

✅ [PHASE-9.1-IMPL.md](./PHASE-9.1-IMPL.md) — Phase 9.1 详细实施指南已就绪
⏳ 后续每个 phase 开工前会写对应的 PHASE-X.X-IMPL.md

---

## 附录 A：phase 命名规范

- `9.1` ~ `9.6` — 评价系统
- `P.1` ~ `P.3` — 积分系统
- `L.1` ~ `L.4` — 抽奖系统

实施文档命名：`PHASE-<id>-IMPL.md`（如 `PHASE-9.1-IMPL.md` / `PHASE-P.1-IMPL.md`）

## 附录 B：每个 phase 估算工作量

| Phase | LoC（估算） | DB 改动 | 新文件 | 难度 |
|---|---|---|---|---|
| 9.1 | ~600 | 10 列 + 1 表 | 2-3 | ★★★ |
| 9.2 | ~400 | 1 表（已建）| 1 | ★★★★ |
| 9.3 | ~500 | 2 表 | 2 | ★★★ |
| 9.4 | ~400 | — | 1 | ★★ |
| 9.5 | ~500 | — | 1 | ★★★★ |
| 9.6 | ~250 | — | 0 | ★★ |
| P.1 | ~200 | 1 列 + 1 表 | 0 | ★ |
| P.2 | ~200 | — | 1 | ★ |
| P.3 | ~300 | — | 0 | ★★ |
| L.1 | ~400 | 2 表 | 2 | ★★ |
| L.2 | ~500 | — | 0 | ★★★★ |
| L.3 | ~300 | — | 0 | ★★★ |
| L.4 | ~250 | — | 0 | ★★ |
| **总计** | **~4800** | **13 列 + 6 表** | **8-10** | — |

★ 难度参考：
- ★ 简单：单表 CRUD + 1-2 个 handler
- ★★ 中等：多步 FSM 或多模块集成
- ★★★ 较难：跨模块依赖 / 异步定时任务
- ★★★★ 难：Telegram API 边界（媒体组、评论锚消息、限流）
