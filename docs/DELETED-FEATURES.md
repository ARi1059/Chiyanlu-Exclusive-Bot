# Phase A0 已下线功能清单

> **执行日期**：2026-05-23
> **PR 范围**：方案 A v2 / 方案 B v2 共享的 Phase 0（功能删除）
> **目的**：完整记录 Phase A0 删除的 5 大产品功能，含原因、回滚指南、留存数据说明。

---

## 1. 总览

Phase A0 共下线 **5 项功能**：

| 功能 | 涉及 callback | 涉及 DB 表 | 删除 LOC（代码） | 删除 LOC（测试） |
|---|---|---|---|---|
| 抽奖系统（用户参与 + 管理员管理 + 调度） | `user:lottery*` / `admin:lottery*` / `admin:lottery_status` / `admin:lottery_reconcile` | `lotteries` / `lottery_entries` | ~6,000 | ~5,000 |
| 搜索历史 | `user:search_history*` | （查 `user_events`） | ~700 | ~400 |
| 最近看过 | `user:recent*` / `user:continue_last` | `user_teacher_views` | ~500 | ~600 |
| 我的记录聚合菜单 | `user:my_records` | -（仅 UI 聚合） | ~120 | ~280 |
| 老师今日状态 | `teacher:status*` / `admin:today_status` | `teacher_daily_status` | ~580 | ~400 |
| **小计** | | | **~7,900** | **~6,700** |

**实际工程效果**：bot/ 目录 LOC -~10K，tests/ -~7K，共 -~17K。

---

## 2. 删除清单

### 2.1 删除的文件

**Handlers**：
- `bot/handlers/admin_lottery.py`
- `bot/handlers/user_lottery.py`
- `bot/handlers/lottery_entry.py`
- `bot/handlers/teacher_daily_status.py`

**Services**：
- `bot/services/lottery_status.py`
- `bot/services/lottery_reconcile.py`
- `bot/services/recent_views.py`
- `bot/services/search_history.py`

**Scheduler**：
- `bot/scheduler/lottery_tasks.py`

**Utils**：
- `bot/utils/lottery_draw.py`
- `bot/utils/lottery_publish.py`
- `bot/utils/lottery_subscribe_check.py`

**Tests（13 个文件）**：
- `tests/test_lottery_*.py` × 8
- `tests/test_user_lottery_center.py`
- `tests/test_recent_views.py`
- `tests/test_search_history.py`
- `tests/test_user_my_records_menu.py`
- `tests/test_dead_code_annotations_static.py`
- 部分 admin 测试（admin_dashboard / admin_operations / admin_overview / admin_status_shortcuts / admin_overview_shortcuts / admin_points_entry / admin_teachers_menu / admin_teachers_return_paths / admin_dashboard_return_paths / admin_operations_return_paths）
- `tests/test_teacher_checkin_top_dynamic.py` / `tests/test_teacher_main_menu.py` / `tests/test_teacher_detail_return_source.py` / `tests/test_user_find_menu.py`

### 2.2 修改的文件（部分删除 / 引用更新）

| 文件 | 改动 |
|---|---|
| `bot/routers.py` | 取消注册 4 个 router（admin_lottery / user_lottery / lottery_entry / teacher_daily_status） |
| `bot/lifecycle.py` | 移除 `schedule_pending_lotteries` 启动调用 |
| `bot/states/teacher_states.py` | 删除 3 个 lottery FSM 类 + TeacherDailyStatusStates |
| `bot/states/user_states.py` | 删除 SearchHistoryStates |
| `bot/database.py` | 删除 23 个 lottery DB 函数 + 4 个 daily_status 函数 + 2 个 recent_views 函数 + get_user_search_history（**保留** DDL 表 + `_migrate_lotteries_entry_cost` 迁移，便于将来 DROP TABLE） |
| `bot/handlers/admin_panel.py` | 删除 7 个 lottery handlers + system:lottery_contact handler；移除 lottery action labels + 菜单文案 |
| `bot/handlers/user_panel.py` | 删除 `cb_user_my_records`；主菜单 keyboard 移除 4 项；docstring 更新 |
| `bot/handlers/user_history.py` | 删除 search_history + continue_last 段；reminders 简化（移除 daily_status 依赖） |
| `bot/handlers/teacher_detail.py` | 删除 `cb_user_recent` / `cb_user_recent_refresh` / `_render_user_recent` / `record_teacher_view` 调用；`daily_row` 恒置 None |
| `bot/handlers/start_router.py` | 删除 lottery deep link 解析 / dispatch；删除「欢迎回来 + 继续看上次」（依赖 user_teacher_views） |
| `bot/handlers/keyword.py` | 移除 `get_teacher_daily_status` 调用，`daily_status` 始终视为 None |
| `bot/keyboards/admin_kb.py` | 删除 ~24 个 lottery keyboard 函数 + `admin_today_status_kb`；`admin_dashboard_kb` / `admin_operations_kb` / `admin_teachers_kb` 移除 lottery / today_status 入口；`admin_overview_kb` 移除 lottery 快捷跳转 |
| `bot/keyboards/user_kb.py` | 删除 `user_my_records_kb` / `user_lottery_menu_kb` / `user_lottery_back_kb` / `recent_views_*` × 3 / `search_history_*` × 2；`user_main_menu_kb` 移除 4 项；`user_find_kb` 移除「搜索历史」；`_BACK_BUTTON_BY_SOURCE` 移除 `history` / `recent` |
| `bot/keyboards/teacher_self_kb.py` | `teacher_main_menu_kb` 移除「📅 今日状态」按钮；删除 `teacher_status_kb` / `cancel_reason_kb` |
| `bot/services/admin_overview.py` | 移除 lottery 字段查询 / 渲染（保留字段定义兼容旧 caller） |
| `bot/services/user_favorites.py` | inline `format_viewed_at_relative`（原依赖 `recent_views.py`） |
| `bot/services/points_rules.py` | 移除 `lottery_entry` / `lottery_refund` REASON_CATALOG 条目 + 渲染段 |

### 2.3 数据库表（**保留**，不 DROP）

为安全起见，Phase A0 **不执行 DROP TABLE**。以下 4 张表仍存在但无写入：
- `lotteries`
- `lottery_entries`
- `user_teacher_views`
- `teacher_daily_status`

`user_events` 表内 `event_type='search'` 历史数据保留（搜索历史功能下线，但事件埋点继续记录其它类型）。
`point_transactions` 内 `reason='lottery_entry' / 'lottery_refund'` 历史数据保留（不可追溯下线前的扣分原因）。

> **后续 PR（A0.1）**：在生产稳定 ≥ 30 天后，可独立 PR 通过 `MIGRATIONS.append(Migration(...))` 注册 `DROP TABLE` 迁移彻底清除。

---

## 3. 删除决策原因

引自方案 B v2 §B.1.4 + 用户反馈：

1. **抽奖系统**：维护成本高（10 步 FSM 创建、积分对账、调度失败重试）；近期使用频次低；产品决定下线。
2. **搜索历史**：使用率极低；空间 / 查询开销 vs 用户价值不对等；下线节省 ~700 LOC。
3. **最近看过**：与「我的收藏」职能重叠；多数用户依赖收藏；下线减少认知负担。
4. **我的记录聚合**：原本是为统一「评价 / 报销 / 积分 / 抽奖记录」入口而设；抽奖下线后聚合价值减半，且双跑期冗余按钮增加主菜单复杂度。
5. **老师今日状态**：使用率低（多数老师只签到，不设状态）；签到本身已能表达「今日可约」语义。

---

## 4. 回滚指南

### 4.1 完全回滚（不推荐）

如需恢复 Phase A0 删除的功能：

```bash
# 1. 找到 Phase A0 之前的 commit
git log --oneline | grep -B1 "Phase A0"

# 2. 回滚整个 PR
git revert <Phase A0 commit hash>

# 3. 启动 bot 验证
python3 -m bot.main
```

由于 4 张 DB 表（lotteries / lottery_entries / user_teacher_views / teacher_daily_status）在 Phase A0 中**保留未 DROP**，历史数据完整。回滚后所有数据可直接复用。

### 4.2 部分恢复（仅恢复某项功能）

各功能在删除前位于以下 commit（参见 git log）：
- 抽奖系统：删除前最后一次有效 commit
- 搜索历史：同上
- 最近看过：同上
- 我的记录聚合：同上
- 老师今日状态：同上

```bash
# 例：仅恢复抽奖
git checkout <Phase A0 commit>^ -- \
  bot/handlers/admin_lottery.py \
  bot/handlers/user_lottery.py \
  bot/handlers/lottery_entry.py \
  bot/scheduler/lottery_tasks.py \
  bot/services/lottery_status.py \
  bot/services/lottery_reconcile.py \
  bot/utils/lottery_draw.py \
  bot/utils/lottery_publish.py \
  bot/utils/lottery_subscribe_check.py

# 还需手动恢复：
# - bot/routers.py 内 4 个 import + 4 个 include_router
# - bot/lifecycle.py 内 schedule_pending_lotteries
# - bot/states/teacher_states.py 内 3 个 lottery FSM 类
# - bot/database.py 内 23 个 lottery DB 函数
# - bot/keyboards/admin_kb.py 内 ~24 个 lottery keyboard
# - bot/handlers/admin_panel.py 内 7 个 lottery handler
```

> 部分恢复较繁琐；如确需恢复某项，建议完全 revert 后再删其它。

---

## 5. 验证清单（Phase A0 上线时使用）

- [x] `python -m compileall -q bot/` 0 错误
- [x] 所有 callback handler 不引用已删除模块
- [x] `python -m pytest` 在 Linux CI 0 失败（Windows 本地 10 个失败仅是 .sh 脚本无法执行的环境差异）
- [ ] **生产上线前必做**：`sqlite3 data/bot.db ".backup '/backup/bot-pre-a0.db'"` + integrity_check + 保留 ≥ 30 天
- [ ] 上线后观察 24-72h：bot 启动日志 0 ERR、关键功能（签到 / 评价 / 报销 / 群关键词）正常
- [ ] 监控老消息 inline button 点击：已删 callback 走 noop fallback，不抛 KeyError

---

## 6. 已知问题

1. **历史 inline button**：用户老消息中的「🎁 抽奖中心」「🕘 最近看过」「📜 搜索历史」「📝 我的记录」「📅 今日状态」按钮点击后无响应（callback handler 不存在）。aiogram 默认会在日志记录 warning 但不抛错。如需更友好的兜底提示，需要在 `bot/handlers/noop_handlers.py` 中加入对应 callback 的 silent answer。
2. **point_transactions 历史**：reason='lottery_entry' / 'lottery_refund' 的旧记录仍可查；积分流水页（user:points:list）会显示但 reason 在新 REASON_CATALOG 中找不到 → 渲染时显示 raw reason 字符串。
3. **DB 表 lotteries / lottery_entries / user_teacher_views / teacher_daily_status**：表存在但无写入，占用磁盘空间。后续 A0.1 PR 可 DROP。

---

## 7. 相关文档

- `docs/POLICY.md` — Part III 抽奖章节（待手动删除，后续 PR）
- `docs/DESIGN.md` — 抽奖相关章节（待手动删除）
- `docs/ROADMAP-PLAN.md` — 抽奖相关 Sprint（待手动删除）
- 方案文档 — `C:\Users\Administrator\.claude\plans\linked-wobbling-dusk.md`（方案 A v2 § A.4 Phase A0 / 方案 B v2 § B.4 Phase 0）

---

# A0 后续下线（2026-06-13）：热门老师 / 帮我推荐 / 按条件找

> **执行日期**：2026-06-13
> **目的**：下线面向用户的「热门老师 / 推荐老师 / 筛选老师」三项私聊功能，并移除群内对应关键词自动回复。**保留「今日开课」**。

## 下线范围

| 功能 | 涉及 callback | 处理 |
|---|---|---|
| 热门老师（用户侧列表） | `user:hot` | 删 `hot_teachers.py` 的 `cb_user_hot` 及独占 helper `get_hot_teachers`；**保留后台 `admin:hot_manage` 推荐位管理**（`is_featured` 仍是全站排序基础设施） |
| 帮我推荐 | `user:recommend` / `user:recommend:refresh` | 删整文件 `user_recommend.py` + DB `get_recommended_teachers_for_user` |
| 按条件找 | `user:filter*` | 删整文件 `user_filter.py` + DB `get_filter_options` / `search_teachers_by_filter` + FSM `FilterStates` |
| 群组快捷词 | 群内发「启动/热门老师/推荐老师/筛选老师」 | 删 `_QUICK_ENTRY_CONFIG` / `_QUICK_ENTRY_SEED` 四项 + 迁移 `20260613_002` 删 DB seeded 行；**保留「今日开课」** |

## 删除 / 修改的文件

**删除**：`bot/handlers/user_recommend.py`、`bot/handlers/user_filter.py`

**修改**：
- `bot/routers.py` — 取消 `user_filter_router` / `user_recommend_router` 注册（留注释），router 总数 33 → 31
- `bot/handlers/hot_teachers.py` — 删用户侧 `cb_user_hot`，保留后台管理段
- `bot/database.py` — 删 4 个独占 helper；`_QUICK_ENTRY_SEED` 仅留「今日」；新增迁移 `_migrate_005`
- `bot/handlers/keyword.py` — `_QUICK_ENTRY_CONFIG` 仅留「今日」（按钮精简为仅「打开今日开课」）
- `bot/handlers/start_router.py` — deep link 删 `hot`/`filter`/`recommend`，保留 `menu`/`today`
- `bot/keyboards/user_kb.py` — 主菜单 / 找老师 / 空收藏 / 新手引导删按钮，死按钮改向 `user:today` / `user:search`
- `bot/handlers/user_panel.py` — 删 `cb_onboarding_hot`
- `bot/handlers/user_history.py` / `teacher_detail.py` — 空态死按钮改向今日开课
- `bot/states/user_states.py` — 删 `FilterStates`

## 迁移

- `20260613_002_remove_quick_entry_keywords`（kind=soft）：`DELETE FROM quick_entry_keywords WHERE seeded=1 AND trigger NOT IN ('今日','今日开课')`。抗运营改名（`seeded=1` 护栏绝不误删运营手建行）。
- 附：`20260613_001_teacher_is_deleted`（kind=hard）为同批「老师软删除」功能新增列，详见 README 老师管理章节。

## 留存数据 / 回滚

- `quick_entry_keywords` 表保留（仅删 seeded 行）；`teachers.is_featured` 等推荐位列保留（后台仍用）。
- 历史老消息中的 `user:hot` / `user:recommend` / `user:filter` 按钮点击后无响应（aiogram 默认 warning，不抛错），与 Phase A0 一致，不动 `noop_handlers.py`。
- 回滚：恢复上述文件 + 删迁移 `20260613_002` 注册即可；推荐位 / 今日开课数据未受影响。

## 保留（易混淆，明确不动）

- 后台「🔥 热门推荐管理」`admin:hot_manage`（推荐位 `is_featured`）。
- 搜索 0 结果推荐子页 `search:suggest:today` / `search:suggest:hot`（搜索功能内置，独立于 `user:hot`）。
- 「今日开课」全部（私聊 `user:today` / 群组「今日」快捷词 / deep link `today`）。
