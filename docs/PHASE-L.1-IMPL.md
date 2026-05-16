# Phase L.1 实施指南：抽奖 DB + 创建/编辑/列表

> 状态：**✅ 已完成**（2026-05-16）
> 创建：2026-05-16
> 完成 commit：L.1.1 / L.1.2 / L.1.3
> 关联 spec：[LOTTERY-FEATURE-DRAFT.md §1-§3 / §6-§7](./LOTTERY-FEATURE-DRAFT.md)
> 后续：[PHASE-L.2-IMPL.md](./PHASE-L.2-IMPL.md)（待编写）

---

## 0. 目标

C 组抽奖系统第一步（与 A/B 组无依赖）：

- 新表 `lotteries` + `lottery_entries`
- DB CRUD：create / get / list_by_status / update / cancel / find_by_entry_code
- 主面板新增 [🎲 抽奖管理]（仅超管可见，与 [📝 报告审核] / [💰 积分管理] 同层）
- 抽奖列表 + 详情查看（只读）
- 完整 10 步创建 FSM 保存为 `draft`

**不做：**
- 频道发布 / 用户参与 → Phase L.2
- 定时开奖 / 中奖通知 → Phase L.3
- active 状态编辑 / 客服链接 / 帖被删重发 → Phase L.4

---

## 1. 模块清单

### 1.1 修改文件

| 文件 | 改动 |
|---|---|
| `bot/database.py` | +290 行：lotteries + lottery_entries schema + 8 CRUD + 常量 |
| `bot/keyboards/admin_kb.py` | +120 行：main_menu_kb 加 [🎲 抽奖管理] + 4 个管理键盘 + 7 个 FSM 键盘 |
| `bot/states/teacher_states.py` | +18 行：LotteryCreateStates 14 状态 |
| `bot/handlers/admin_panel.py` | +2 行：audit label lottery_create / lottery_cancel |
| `bot/main.py` | +5 行：注册 admin_lottery_router |

### 1.2 新增文件

| 文件 | 用途 | 行数 |
|---|---|---|
| `bot/handlers/admin_lottery.py` | 主入口 + 列表 + 详情 + 取消 + 10 步 FSM | ~680 |

---

## 2. DB 变更

### 2.1 Schema（spec §6）

```sql
CREATE TABLE lotteries (
    id PK, name, description, cover_file_id,
    entry_method ('button'|'code'), entry_code UNIQUE,
    prize_count (1-1000), prize_description,
    required_chat_ids TEXT NOT NULL,  -- JSON list[int]
    publish_at, draw_at, published_at, drawn_at,
    channel_chat_id, channel_msg_id, result_msg_id,
    status DEFAULT 'draft', created_by, created_at, updated_at,
    CHECK entry_method / status / prize_count
);
CREATE INDEX idx_lotteries_status / publish_at / draw_at;

CREATE TABLE lottery_entries (
    id PK, lottery_id FK CASCADE, user_id,
    entered_at, won DEFAULT 0, notified_at,
    UNIQUE(lottery_id, user_id)  -- 一人一次
);
CREATE INDEX idx_lottery_entries_won(lottery_id, won);
```

### 2.2 常量与 CRUD

| 名称 | 说明 |
|---|---|
| `LOTTERY_STATUSES` (6) | draft/scheduled/active/drawn/cancelled/no_entries + 中文 label + emoji |
| `LOTTERY_TERMINAL_STATUSES` | {drawn, cancelled, no_entries} |
| `LOTTERY_EDITABLE_FIELDS` | update_lottery_fields 白名单 |
| `create_lottery(data)` | INSERT；entry_code 冲突 / CHECK 越界 / 缺字段返 None |
| `get_lottery(id)` | 解析 required_chat_ids JSON → list[int] |
| `list_lotteries_by_status / count_lotteries_by_status` | status=None 表全部 |
| `update_lottery_fields(id, **fields)` | 白名单 + list 自动 JSON |
| `cancel_lottery(id)` | 仅 draft/scheduled/active → cancelled |
| `find_lottery_by_entry_code(code)` | 仅 active + LOWER 不敏感（L.2 用）|
| `count_lottery_entries(id)` | 参与人数 |

---

## 3. UI / 流程

### 3.1 主菜单（is_super 段）

```
[📝 报告审核] [💰 积分管理]
[🎲 抽奖管理]                  ← L.1 新增独占一行
```

### 3.2 抽奖管理子菜单

```
🎲 抽奖管理

[➕ 创建新抽奖]
[📋 抽奖列表 (N)]
[🔙 返回主面板]
```

### 3.3 抽奖列表

按 created_at DESC 显示最多 30 条，每条按钮含状态 emoji + 名称（截 25 字）。
顶部含状态分组统计：`📝 草稿 3  🎯 进行中 1  🏆 已开奖 5`。

### 3.4 抽奖详情（只读）

含状态 / 名称 / 规则 / 奖品 / 中奖人数 / 参与方式 / 口令（如有）/
必关频道列表 / 发布与开奖时间 / 创建者 / 已参与人数。

仅 `draft` 状态显示 [❌ 取消草稿] 按钮（active 取消见 L.4）。

### 3.5 创建 10 步 FSM（spec §3.3）

```
[Step 1/10]  名称 (1-30 字)
[Step 2/10]  规则描述 (1-500 字)
[Step 3/10]  封面图（可跳过）
[Step 4/10]  参与方式 [🎲 按键] [🔑 口令]
[Step 4.5]   口令（仅 code，1-20 字，全局唯一）
[Step 5/10]  中奖人数（6 预设 + 自定义 1-1000）
[Step 6/10]  奖品描述 (1-100 字)
[Step 7/10]  必关频道子循环（≥ 1 项，每项调 precheck_required_chat）
[Step 8/10]  发布模式 [⚡ 立即] [⏰ 定时]
[Step 8b]    定时时填 YYYY-MM-DD HH:MM
[Step 9/10]  开奖时间（YYYY-MM-DD HH:MM，必须晚于 publish_at）
[Step 10/10] 确认页（[✅ 保存草稿]）
```

任意步骤 `/cancel` 或点 [❌ 取消] 退出。
本 phase 不实现 [✏️ 修改某项] 跳回（L.2/L.4 视需求补）。

---

## 4. 实施顺序（3 次 commit）

### Commit L.1.1 — DB schema + CRUD + 主入口 + 列表/详情（只读）
- compileall + 15 项 sanity：schema 齐全、状态常量、create happy/缺字段/CHECK/
  entry_code UNIQUE、JSON 解析、list/count by status、白名单 update、cancel 仅未终态、
  find_by_code 仅 active + 不敏感、count_entries 默认 0、main_menu_kb 切换、
  list_kb 状态 emoji、detail_kb 按状态切换取消按钮

### Commit L.1.2 — 创建 10 步 FSM 保存 draft
- compileall + 9 项 sanity：_parse_datetime 边界、完整 happy path、
  name/prize_count 字数边界、draw_at <= publish_at 拒绝、必关 0 项拒绝、
  口令抽奖 Step 4.5、entry_code 全局唯一冲突、/cancel 任意步退出

### Commit L.1.3 — 端到端 + 文档（本文件）
- 11 步 E2E：主菜单 / 子菜单 / 空列表 / 按键抽奖完整 10 步 /
  口令抽奖完整 10 步 / 列表 2 草稿 / 详情含取消按钮 / 取消草稿 /
  cancelled 状态无取消按钮 / find_by_code（仅 active）/ 9.3+P.1 回归

---

## 5. 验收清单

### 5.1 DB
- [x] lotteries / lottery_entries schema 齐 + 4 索引
- [x] CHECK 约束阻止非法 entry_method / status / prize_count
- [x] entry_code UNIQUE
- [x] required_chat_ids JSON ↔ list round-trip
- [x] cancel 仅未终态
- [x] find_by_entry_code 仅 active + 大小写不敏感

### 5.2 主菜单
- [x] is_super=True 含 admin:lottery；False 不含
- [x] 与 admin:points 同层（不冲突）

### 5.3 列表与详情
- [x] 列表按 created_at DESC + 状态分组统计
- [x] 状态 emoji 显示
- [x] 详情 draft 显示 [❌ 取消草稿]；其它状态不显示

### 5.4 创建 FSM
- [x] 10 步走通 → DB 落 draft
- [x] entry_method=code → Step 4.5 收口令 + 全局唯一校验
- [x] entry_method=button → 跳过 Step 4.5
- [x] 必关频道 ≥ 1 + precheck_required_chat 校验
- [x] 立即发布 → publish_at=now
- [x] 定时发布 → 解析 YYYY-MM-DD HH:MM + 不能早于现在
- [x] draw_at > publish_at（等于 / 早于 拒绝）
- [x] /cancel 任意步退出
- [x] 各步字数边界校验（name 30 / description 500 / prize_desc 100 / code 20）
- [x] prize_count 1-1000 越界拒绝

### 5.5 兼容
- [x] 9.1-9.6 / P.1-P.3 全部回归
- [x] 不影响每日 14:00 publish / 评价审核 / 积分管理

### 5.6 静态
- [x] python3 -m compileall bot
- [x] import bot.main OK

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| entry_code 大小写敏感导致用户输错 | find_by_entry_code LOWER 比对（L.2 解析时用） |
| 必关频道 chat_id 输入错误 | precheck_required_chat 校验 bot 是否在场 |
| draw_at 时区错乱 | 用 config.timezone 统一存 'YYYY-MM-DD HH:MM:SS'，bot 重启后解析仍 aware |
| 重复添加同 chat_id | state 内 in 检查 |
| FSM 中途异常 | /cancel 全程可退出；state 自动 5 min 超时（teacher_flow.py 中间件不在本 router） |
| 草稿过多无法回收 | [❌ 取消草稿] 可改 cancelled；DB 仍保留（spec §6 历史不删）|

---

## 7. 不在本 Phase 范围

- ❌ 频道发布 → Phase L.2
- ❌ /start lottery_<id> deep link / 口令命中 / 用户参与 → Phase L.2
- ❌ [👥 N 人已参与] 计数更新 → Phase L.2
- ❌ APScheduler 调度 → Phase L.2 / L.3
- ❌ 定时开奖 / 中奖通知 / 频道追发结果 → Phase L.3
- ❌ active 状态编辑 / 取消 active / [✏️ 编辑抽奖] → Phase L.4
- ❌ 客服链接配置 → Phase L.4
- ❌ "修改某项" 跳回 FSM（L.4 视需求补）

---

## 8. 完成后

Phase L.1 完成 → 开 Phase L.2（频道发布 + 用户参与）。

> Phase L.2 开始前需确认：
> - 抽奖帖渲染（封面图 photo + caption 媒体 vs 纯文字）
> - inline 键盘上 [👥 N 人已参与] 更新策略（事件驱动 vs 60s 定时）
> - APScheduler 调度入口（启动时扫 scheduled/active 重注册）
> - 参与流程中关注校验失败的提示（同评价系统 [📋 必关频道/群组] 风格 vs 独立）
