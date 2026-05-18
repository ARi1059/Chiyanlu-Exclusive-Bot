# DEAD-CODE-AUDIT-2026-05-18.md

> **本文档仅是审查报告，不修改任何代码。**
> 所有"建议"措辞都是**未来阶段**的处置思路，本次不删除任何文件、不重命名
> 任何 callback、不动 router 顺序、不改 FSM、不改业务逻辑。

审查对象：commit `828386f`（main.py 拆分之后）的代码库快照。

---

## 一、审查结论

| 类别 | 数量 | 建议 |
| --- | --- | --- |
| 真正不可达 dead code（无外部入口） | 1 大块 + 2 文件 | P3 阶段加 deprecated 注释，下个稳定化轮次清理 |
| 已下线但保留兼容（router 未注册） | 2 文件 | 保留，已在 [bot/routers.py](../bot/routers.py) 注释说明 |
| 容易误导维护者但实际无 bug | 1 处（noop 双 handler） | 加注释说明分工，**不要**合并 |
| 命名空间潜在污染（不紧急） | 1 处（`edit:` 裸前缀） | 长期建议改为 `teacher:edit:*`，但本轮不动 |
| 未注册 router | 全项目仅 2 个（promo_links / source_stats） | 与下线状态一致，无遗忘 |

总体判断：**当前 dead code 量可控，已知问题都已用注释标注，无紧急清理压力**。
推荐清理顺序见 [§九](#九建议清理路线)。

---

## 二、审查方法

只用静态 grep + 文件枚举，不做动态分析：

```bash
# 1. 所有定义了 router 的 handler 文件
grep -lE "^router\s*=\s*Router\(" bot/handlers/*.py

# 2. routers.py 中实际注册的 handler
grep -E "^from bot\.handlers" bot/routers.py

# 3. 上述两组的差集 = 未注册 router

# 4. ReviewSubmitStates / CardReviewStates 引用
grep -rnE "ReviewSubmitStates|CardReviewStates" bot/

# 5. set_state(ReviewSubmitStates.xxx) 调用点
grep -rnE "set_state\(\s*ReviewSubmitStates" bot/

# 6. noop / edit: callback 前缀
grep -rnE "noop|F\.data.*startswith.*edit:" bot/handlers/

# 7. 单文件内部入口追溯：阅读 review_submit.py:439 cb_review_start
```

证据由 `grep` 输出 + 手工读源码 ([bot/handlers/review_submit.py:439-481](../bot/handlers/review_submit.py))
+ [bot/handlers/review_card.py:277-323](../bot/handlers/review_card.py) 交叉得出。

---

## 三、疑似 dead code 清单

| # | 项 | 文件 / 位置 | 类型 | 当前入口 | 风险等级 | 建议 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **ReviewSubmitStates 旧线性 FSM**（约 600 行 handler + 状态类） | [bot/handlers/review_submit.py](../bot/handlers/review_submit.py) L509-1100 + [bot/states/teacher_states.py:183](../bot/states/teacher_states.py) | StatesGroup + 10+ handler | **无外部入口**。`review:start:*` (L439) 直接 `render_card()` 走 card 流程 | **P3-low** | 保留 + 加 deprecated 注释（[§四](#四reviewsubmitstates-旧线性-fsm)） |
| 2 | `promo_links` router | [bot/handlers/promo_links.py](../bot/handlers/promo_links.py)（9160 字节） | aiogram Router | **未在 routers.py 注册**（已在 L76 注释为"已下线"） | P3-low | 保留，[§五](#五promo_linkspy--source_statspy) |
| 3 | `source_stats` router | [bot/handlers/source_stats.py](../bot/handlers/source_stats.py)（7598 字节） | aiogram Router | **未在 routers.py 注册**（已在 L76 注释为"已下线"） | P3-low | 保留，[§五](#五promo_linkspy--source_statspy) |
| 4 | `promo_links_menu_kb` / `source_stats_menu_kb` / `source_stats_back_kb` | [bot/keyboards/admin_kb.py:168-217](../bot/keyboards/admin_kb.py) | 键盘构造函数 | 入口下线后不再被任何已注册 handler 调用 | P3-low | 保留 |
| 5 | `get_source_stats()` DB 函数 | [bot/database.py:2548](../bot/database.py) | async DB 函数 | 仅 `bot/handlers/source_stats.py` 调用，而该 handler 未注册 | P3-low | 保留 |
| 6 | **`noop` 双 handler** | [bot/handlers/noop_handlers.py:13](../bot/handlers/noop_handlers.py)（`noop:`）+ [bot/handlers/teacher_daily_status.py:386](../bot/handlers/teacher_daily_status.py)（`noop`） | 两个 callback handler | 两者前缀语义不同，**未实际冲突**，但易让维护者困惑 | **P3-low** | 保留 + 加交叉注释（[§六](#六noop-handler)） |
| 7 | **`F.data.startswith("edit:")` 裸前缀** | [bot/handlers/teacher_flow.py:372](../bot/handlers/teacher_flow.py) | callback filter | 当前所有其它 edit 都带子系统前缀（`teacher_self:edit:` / `tprofile:select:edit:` / `card:edit:` / `review:edit:` / `admin:lottery:edit:`），暂无冲突 | **P2-medium** | 未来改为 `teacher_flow:edit:*` 或 `teacher:edit:*`，本轮不动（[§七](#七edit-callback-前缀)） |

---

## 四、ReviewSubmitStates 旧线性 FSM

### 4.1 现状

- **状态类**：[`ReviewSubmitStates`](../bot/states/teacher_states.py#L183) 定义于
  `bot/states/teacher_states.py`，9 个 state：
  `waiting_evidence_media / waiting_rating / waiting_score_humanphoto / ..._appearance /
  ..._body / ..._service / ..._attitude / ..._environment / waiting_summary /
  waiting_reimbursement_choice / waiting_confirm`
- **handler**：约 10 个 `@router.message(ReviewSubmitStates.xxx)` /
  `@router.callback_query(..., ReviewSubmitStates.yyy)` 集中在
  `bot/handlers/review_submit.py` L509-1100
- **内部跳转函数**：`_enter_rating` / `_enter_score_step` / `_enter_summary` /
  `_enter_reimbursement_step` / `_enter_confirm` —— 这些函数内部调用
  `state.set_state(ReviewSubmitStates.xxx)`

### 4.2 入口追溯（关键证据）

```python
# bot/handlers/review_submit.py:439-481  cb_review_start
@router.callback_query(F.data.startswith("review:start:"))
async def cb_review_start(callback, state):
    ...
    # status == "ok" — 卡片渲染
    from bot.handlers.review_card import render_card
    await render_card(callback.message, state, via_edit=True)  # ← 直接走 card
    await callback.answer()
```

**核心入口** `review:start:*` 在校验通过后**直接** `render_card(...)` 进入 card 流程
（`bot/handlers/review_card.py`），完全跳过 ReviewSubmitStates。

`set_state(ReviewSubmitStates.xxx)` 全项目调用：

| 位置 | 调用环境 |
| --- | --- |
| review_submit.py:620 | `_enter_rating()` 内 |
| review_submit.py:766 | `_enter_summary()` 内 |
| review_submit.py:846 | `_enter_reimbursement_step()` 内 |
| review_submit.py:883 | `_enter_confirm()` 内 |

这 4 处**全部在 review_submit.py 内部**；外部 0 引用。这些 `_enter_*` 函数
又只被同文件内 ReviewSubmitStates 的下一步 handler 调用——形成**自封闭循环**：
没有外部入口能让用户首次进入这条循环。

review_card.py 内部用的是 `CardReviewStates`，与 ReviewSubmitStates 完全独立：

```python
# bot/handlers/review_card.py:62-74
_DIM_META: dict[str, dict] = {
    "humanphoto":  {"state": CardReviewStates.editing_humanphoto, ...},
    "appearance":  {"state": CardReviewStates.editing_appearance, ...},
    # ... 全部 CardReviewStates，无 ReviewSubmitStates
}
```

### 4.3 结论

**ReviewSubmitStates 当前不可从用户行为触发**。它是真正的 dead code，但仍被
`review_submit_router` 注册（routers.py L131）：

> 注册位置在 review_submit_router 之前（即更早注册），保证 card:* 优先匹配；
> **实际入口由 review_submit.start_review_flow 重定向到 card 流程**

注释也确认了这一点。

### 4.4 建议

| 阶段 | 动作 | 风险 |
| --- | --- | --- |
| 立刻 | **不做**，保持现状 | 0 |
| P3-A | 在 ReviewSubmitStates 类 docstring + review_submit.py 模块顶部 docstring 加 `⚠️ Deprecated since 2026-05-18 Phase 2，保留兼容但无入口` | 极低 |
| P3-B | 加 pytest 静态断言：`set_state(ReviewSubmitStates.*)` 只在 review_submit.py 内部出现；外部模块（含 review_card.py）不应 import ReviewSubmitStates | 低 |
| P3-C（未来稳定窗口期 ≥ 3 个月后） | 删除 ReviewSubmitStates 及其 10+ handler 与 `_enter_*` 私有函数；保留 `cb_review_start` / `start_review_flow` / `cb_review_cancel`（card 入口） | 中。删除前**必须**走一遍 git log，确认无第三方 PR / 实验分支仍在 `set_state(ReviewSubmitStates...)` |

**删除前需要的测试**：
- 静态：grep 全仓断言无 `ReviewSubmitStates` 引用
- 行为：用 aiogram test client 模拟 `review:start:*` 入口，断言进入 CardReviewStates.card 而非 ReviewSubmitStates
- 数据：检查 MemoryStorage 切换前后兼容性（MemoryStorage 重启即清空，所以无遗留 FSM 风险）

---

## 五、promo_links.py / source_stats.py

### 5.1 现状

| 文件 | 大小 | router name | 注册状态 | 注释 |
| --- | --- | --- | --- | --- |
| [bot/handlers/promo_links.py](../bot/handlers/promo_links.py) | 9160 B | `promo_links`（推断） | ❌ 未在 [bot/routers.py](../bot/routers.py) import | L76 注释 "promo_links / source_stats（Phase 4）：2026-05-18 已下线" |
| [bot/handlers/source_stats.py](../bot/handlers/source_stats.py) | 7598 B | `source_stats` | ❌ 未在 routers.py import | 同上 |

### 5.2 残余引用

```text
bot/keyboards/admin_kb.py:168-217    promo_links_menu_kb / source_stats_menu_kb / source_stats_back_kb（键盘函数，已下线入口的按钮）
bot/keyboards/admin_kb.py:183,192-217 callback_data="admin:promo_links" / "admin:source_stats:*" （键盘按钮 data）
bot/database.py:2548                 async def get_source_stats(...) （DB 查询函数，仅 source_stats.py 内调用）
bot/handlers/source_stats.py:23      from bot.database import get_source_stats（handler 内 import；但 handler 未注册）
```

**关键事实**：
- 键盘函数虽然存在，但**没有任何已注册 handler** 把它们渲染到用户消息里 ——
  这些函数现在是叶子节点，调用者本身已不可达
- `get_source_stats` DB 函数同理 —— 只有未注册的 source_stats handler 调用它

### 5.3 文档现状

- [bot/routers.py:76](../bot/routers.py) 显式注释"已下线"
- [docs/PRUNING-DESIGN.md](PRUNING-DESIGN.md) 表格未单独列；但与 pruning 主题无关
- [README.md](../README.md) 历史「🟡 后续建议补充」表曾列"死代码"项，本会话已基本到位

### 5.4 建议

| 阶段 | 动作 |
| --- | --- |
| 立刻 | **不做** |
| P3-A | 文件顶部 docstring 加 `⚠️ DEAD CODE since 2026-05-18 Phase 4，router 未注册，按钮已从所有键盘移除` |
| P3-B | 删 `promo_links.py` + `source_stats.py` + admin_kb.py 中对应 3 个键盘函数 + database.py 中 `get_source_stats` |
| P3-B 风险 | `get_source_stats` 如果未来想恢复运营报表，可能要从 git 历史拉回——删除前在 P3-A 阶段记一笔到 STABILIZATION-SUMMARY |

---

## 六、noop handler

### 6.1 全清单

```text
[A] bot/handlers/noop_handlers.py:13
    @router.callback_query(F.data.startswith("noop:"))   # 注意：noop:<冒号>
    router 注册位置：routers.py 第 2 条（仅次于 start_router）

[B] bot/handlers/teacher_daily_status.py:386
    @router.callback_query(F.data.startswith("noop"))    # 注意：noop（无冒号）
    router 注册位置：routers.py 第 7 条
```

### 6.2 行为分析

aiogram 按 router 注册顺序匹配，先注册先匹配。

| callback_data 实际值 | A (`noop:`) 匹配？ | B (`noop`) 匹配？ | 实际响应者 |
| --- | --- | --- | --- |
| `"noop:rating"` | ✅ | ✅ | **A**（先匹配） |
| `"noop:page"`（[user_points.py:73](../bot/handlers/user_points.py)） | ✅ | ✅ | **A** |
| `"noop"`（裸字符串） | ❌（不是 `noop:`） | ✅ | **B** |
| `"noop_xxx"` | ❌ | ✅ | **B** |

**结论**：A 处理所有 `noop:*`，B 兜底裸 `noop` 与 `noop_xxx`。当前生产代码只见到
`noop:page` 等 `noop:` 形式，所以**B 当前可能完全不被触发**，但有兜底意义。

### 6.3 风险

- **当前无任何 bug**：两者前缀语义错开
- **未来风险**：如果有人新增 `F.data == "noop"`（无冒号）的按钮，意图让 A 接住，
  实际会落到 B，**容易引发"为什么 noop_handlers 没生效"的排错时间**

### 6.4 建议

| 阶段 | 动作 | 风险 |
| --- | --- | --- |
| 立刻 | **不做** | 0 |
| P3-A | 在 noop_handlers.py + teacher_daily_status.py 两处的 `@router.callback_query` 上方加交叉注释：「**注意**：另一处 noop handler 在 ‹其它文件›，前缀为 ‹...›，分工是 ‹...›」 | 极低 |
| P3-B（可选） | 把 teacher_daily_status 的 noop 兜底**合并**到 noop_handlers.py（改为 `F.data == "noop" or F.data.startswith("noop_")`）；删除 teacher_daily_status 中的 cb_noop | 中。teacher_daily_status 当前注释明确说 noop 是该模块"频道发布键盘"的占位，跨模块挪动需要确认产品对责任划分的预期 |

**不要**做的事：合并成单一 `F.data.startswith("noop")`（无冒号）—— 会把
"noop_anything_else" 一并吃掉，扩大命中范围。

---

## 七、`edit:` callback 前缀

### 7.1 现状

[bot/handlers/teacher_flow.py:372](../bot/handlers/teacher_flow.py)：

```python
@router.callback_query(F.data.startswith("edit:"))
```

全项目所有其它 `edit` 相关 callback 都带子系统前缀：

| handler | filter |
| --- | --- |
| teacher_self.py:262 | `F.data.startswith("teacher_self:edit:")` |
| teacher_profile.py:1024 | `F.data.startswith("tprofile:select:edit:")` |
| review_card.py:277 | `F.data.startswith("card:edit:")` |
| review_submit.py:962 | `F.data.startswith("review:edit:")` |
| admin_lottery.py:817 | `F.data.startswith("admin:lottery:edit:")` |

**所以裸 `edit:` 当前只被 teacher_flow 吃**，无冲突。

### 7.2 风险

- **当前 0 bug**
- **未来风险**：任何人新增 `callback_data="edit:something"`（不带子系统前缀）
  的按钮，会被 teacher_flow 错误接住，引发 KeyError 或更糟的"老师档案修改"逻辑
  错误响应

### 7.3 建议

| 阶段 | 动作 | 风险 |
| --- | --- | --- |
| 立刻 | **不做** | 0 |
| P3-A | teacher_flow.py:372 上方加注释：「**注意**：本 handler 命名空间是裸 `edit:`，新 `edit:*` callback 必须**加子系统前缀**（如 `<module>:edit:`），否则会被本 handler 误接」 | 极低 |
| P3-C（长期） | callback_data 迁移：`edit:<field>` → `teacher:edit:<field>` 或 `teacher_flow:edit:<field>`；同时改键盘构造函数与 handler 的 startswith filter | 中-高。**老师正在用的旧消息按钮** callback_data 仍是 `edit:*`，迁移当天旧按钮全部失效。需要兼容窗口或接受失效 |

**为什么不建议本轮直接改**：
1. 当前 0 bug，不是紧急修复
2. 涉及生产已发送消息的按钮失效（用户体感劣化）
3. 兼容期实现复杂（需要同时支持两个前缀，加双倍维护成本）
4. 本会话已有 main.py 拆分（refactor）改动，再叠加 callback 迁移会让 commit 难以 review

---

## 八、未注册 router 列表

```text
bot/handlers/*.py 中定义 `router = Router(...)` 的文件：35 个
bot/routers.py 实际 register 的：              33 个
差集（未注册）：                                2 个
```

| 文件 | 状态 | 判断 |
| --- | --- | --- |
| `bot/handlers/promo_links.py` | 已下线（routers.py L76 注释） | 保留作为兼容；详见 [§五](#五promo_linkspy--source_statspy) |
| `bot/handlers/source_stats.py` | 已下线（routers.py L76 注释） | 同上 |

**未发现**：
- 忘记注册的 router（无新增 handler 文件孤悬）
- 草稿状态的 router
- 仅供 import 工具函数而无意义 router 定义

[tests/test_router_registration_static.py::test_total_router_count_matches_pre_split](../tests/test_router_registration_static.py)
已锁定"33 条 include_router"这个回归保护，意外少注册一个会立刻红。

---

## 九、建议清理路线

### 9.1 P3-A（仅加 deprecated 注释，零删除）

风险等级：**极低**。所有改动都是注释，业务行为完全不变。

| # | 改动 |
| --- | --- |
| 1 | [bot/states/teacher_states.py](../bot/states/teacher_states.py) `ReviewSubmitStates` 类 + [bot/handlers/review_submit.py](../bot/handlers/review_submit.py) 模块顶部加 `⚠️ Deprecated since 2026-05-18 Phase 2，无外部入口` |
| 2 | [bot/handlers/promo_links.py](../bot/handlers/promo_links.py) + [bot/handlers/source_stats.py](../bot/handlers/source_stats.py) 顶部加 `⚠️ DEAD CODE since 2026-05-18 Phase 4，router 未注册` |
| 3 | [bot/handlers/noop_handlers.py](../bot/handlers/noop_handlers.py) + [bot/handlers/teacher_daily_status.py](../bot/handlers/teacher_daily_status.py) 两处 noop handler 的 `@router.callback_query` 上加交叉注释 |
| 4 | [bot/handlers/teacher_flow.py:372](../bot/handlers/teacher_flow.py) 加注释提醒"裸 `edit:` 前缀，新 `edit:*` callback 须加子系统前缀" |

### 9.2 P3-B（补静态测试 + 删除明确下线文件）

风险等级：**低-中**。

| # | 改动 |
| --- | --- |
| 1 | 加 pytest：`set_state(ReviewSubmitStates.*)` 只在 review_submit.py 内部出现 |
| 2 | 加 pytest：`ReviewSubmitStates` 不被 bot/handlers/review_card.py 等外部模块 import |
| 3 | **稳定窗口 ≥ 3 个月后**：删除 `bot/handlers/promo_links.py` + `bot/handlers/source_stats.py` + admin_kb 中对应 3 个键盘函数 + database.py `get_source_stats` |
| 4 | **同窗口期**：删除 ReviewSubmitStates 类 + 10+ handler + `_enter_*` 私有函数（review_submit.py 大约缩减 600 行） |

### 9.3 P3-C（callback 前缀迁移）

风险等级：**中-高**。涉及生产已发送消息按钮的 callback_data 兼容。

| # | 改动 |
| --- | --- |
| 1 | `edit:<field>` → `teacher_flow:edit:<field>`（或 `teacher:edit:<field>`），同步改键盘构造函数 |
| 2 | 兼容期（推荐 30 天）：teacher_flow handler 同时识别两个前缀；过期后删除老前缀 |
| 3 | 公告生产用户"如旧老师档案按钮失效请重新打开档案"（实际多数老师不会注意到——他们大多数按钮是新发送的） |

---

## 十、明确不做

本次审查报告**只新增** `docs/DEAD-CODE-AUDIT-2026-05-18.md` 一个文档。

- ❌ 不删除任何文件（含 promo_links.py / source_stats.py）
- ❌ 不修改任何 callback_data（含 `edit:*`）
- ❌ 不修改任何 FSM 状态（ReviewSubmitStates 保持原样）
- ❌ 不动 router 注册顺序
- ❌ 不动 noop handler 任何一处
- ❌ 不修改任何业务代码 / 键盘函数 / 数据库函数
- ❌ 不改 README / DEPLOYMENT / RUNBOOK
- ❌ 不加 deprecated 装饰器或注释（即使是"零行为变化"的注释也不加）
- ❌ 不加任何 pytest 用例（包括"future 静态断言"）

如果未来要按 [§九](#九建议清理路线) 推进，请按 P3-A → P3-B → P3-C 顺序，
每一步独立 PR 与独立 CI 验证。**禁止**把 callback 迁移与文件删除合并在同一
commit。

---

## 相关文档

- [STABILIZATION-SUMMARY-2026-05-18.md](STABILIZATION-SUMMARY-2026-05-18.md) §「死代码清理」P3 项
- [MIGRATION-REGISTRY-DESIGN.md](MIGRATION-REGISTRY-DESIGN.md) `_migrate_*` 与本审查无重叠（数据库迁移不属于 dead code）
- [PRUNING-DESIGN.md](PRUNING-DESIGN.md) 历史日志清理（数据层），与 dead code（代码层）完全独立
- [README.md](../README.md) §「当前稳定化状态」🟡 后续建议补充表中"死代码"项
- [bot/routers.py:76](../bot/routers.py) "promo_links / source_stats（Phase 4）：2026-05-18 已下线" 注释
- 实现入口：[bot/handlers/review_submit.py:439](../bot/handlers/review_submit.py) `cb_review_start` → `render_card()`
