# 老师侧面板入口审查（Sprint 6 §8.3 审查 PR）

> **2026-05-23 Phase A0 后状态**：本审查文档撰写于 2026-05-20，当时老师主菜单为 3 按钮（签到 / 资料 / 📅 今日状态）。Phase A0 已下线「老师今日状态」功能，主菜单实际剩 **2 按钮**（签到 / 资料），原"≤ 3 按钮 + 签到置顶"契约自然加强为"≤ 2 按钮"。`teacher:status*` 命名空间随 `teacher_daily_status` 表一并退役。本文 §1.1 / §2.2 / §6 中对 📅 今日状态 / `teacher:status*` 的描述以**历史快照**对待。
>
> 本文档为 ROADMAP-PLAN.md §8 Sprint 6「老师侧面板精简」纪律要求的**审查 PR 产出**。
> §8.3 明示「审查 PR 与精简 PR 必须**分两个 PR**」—— 本 PR 仅产出审查清单，**不修改任何 keyboard / handler 代码**。
> 审查时间：2026-05-20

---

## 0. TL;DR

**结论：老师主菜单当前已 3 按钮（签到 / 资料 / 状态），已达成 §8.1 "突出签到"和 §8.5 "按钮数量减少" 验收目标；§8.3 精简 PR 实际无需启动 keyboard 改动**。

唯一可做的 Sprint 6 后续工作：
1. 在测试中加防御性契约，锁定老师主菜单按钮数 ≤ 3，防止未来无意识扩张
2. 不引入 §8.2 建议的「📝 我的评价」「❓ 帮助」入口 —— 当前项目无对应业务功能，强行新增违反 §8.4

详见 §6「精简方案建议」。

---

## 1. 老师主菜单现状

### 1.1 keyboard 定义

`bot/keyboards/teacher_self_kb.py::teacher_main_menu_kb`：

| 按钮文案 | callback_data | 行 | 功能 |
| --- | --- | --- | --- |
| ✅ 今日签到 / 今日已签到 | `teacher_self:checkin` | 1 | 签到（UX-5.1 置顶，文案根据 `checked_in` 动态） |
| ✏️ 我的资料 | `teacher_self:profile` | 2 | 自助资料管理（6 字段编辑 + 链接锁定） |
| 📅 今日状态 | `teacher:status` | 3 | 当日开课状态（标记已满 / 取消今日） |

**总计 3 按钮**，每行 1 按钮（垂直布局）。

### 1.2 入口路径

| 入口 | 触发 | 渲染 |
| --- | --- | --- |
| `/start` | 老师私聊 | `teacher_main_menu_kb(checked_in=is_checked_in())` |
| `teacher_self:menu` callback | 资料 / 状态子页返回 | 同上 |
| 文字消息 `签到` | teacher_checkin.py | 直接走签到流程，不显示主菜单 |

---

## 2. 老师侧 callback 命名空间全清单

### 2.1 `teacher_self:*` — 完全归属老师私聊

| callback | 含义 | handler | 权限校验 |
| --- | --- | --- | --- |
| `teacher_self:menu` | 回到主菜单 | `teacher_self.py:210` | `_is_teacher_chat`（私聊） |
| `teacher_self:checkin` | 按钮签到 | `teacher_self.py:440` | 私聊 + `get_teacher` + `is_active` |
| `teacher_self:profile` | 进资料字段面板 | `teacher_self.py:233` | 私聊 |
| `teacher_self:edit:{display_name\|region\|price\|tags\|photo_file_id\|button_text}` | 单字段编辑 FSM | `teacher_self.py:265` | 私聊 |
| `teacher_self:locked:button_url` | 链接锁定提示（不可改） | `teacher_self.py:251` | 无（仅 answer） |

### 2.2 `teacher:status*` — 老师私聊（与 `teacher:*` 三角色共用空间，但 status 子路径专属老师）

| callback | 含义 | handler | 权限校验 |
| --- | --- | --- | --- |
| `teacher:status` | 今日状态主页 | `teacher_daily_status.py:139` | 私聊 + `get_teacher` |
| `teacher:status:mark_full` | 标记今日已满 | `teacher_daily_status.py:181` | 私聊 + `get_teacher` |
| `teacher:status:cancel` | 取消今日开课入口 | `teacher_daily_status.py:206` | 私聊 + `get_teacher` |
| `teacher:status:cancel_skip` | 跳过原因 | `teacher_daily_status.py:234` | 私聊 + `get_teacher` |

### 2.3 `teacher:*` 其它子路径 — 非老师角色（关键发现：命名空间被三角色共用）

| callback | 角色 | 用途 |
| --- | --- | --- |
| `teacher:list` | 管理员 | 老师列表（admin_kb.py） |
| `teacher:delete` / `teacher:confirm_delete:{id}` | 管理员 | 停用老师 |
| `teacher:enable` / `teacher:confirm_enable:{id}` / `teacher:enable_select:{id}` | 管理员 | 启用老师 |
| `teacher:remind:{id}` | 管理员 | 催签到 |
| `teacher:select:{id}` | 管理员 | 选老师 |
| `teacher:view:{id}` / `teacher:view:{id}:from:{source}` | 用户 | 查看老师详情（UX-3 第二批支持来源） |
| `teacher:similar:{id}` | 用户 | 相似老师推荐 |
| `teacher:toggle_fav:{id}` | 用户 | 收藏切换 |
| `teacher:reviews:{id}` / 分页 | 用户 | 查看老师评价 |

**风险评估**：虽然 `teacher:*` 命名空间被三角色共用，但每个 handler 都有独立权限校验（`get_teacher` / `admin_required` / 无校验但仅查看）——**不构成功能错误**，仅是命名空间的语义模糊。若做大改造（拆分为 `teacher_admin:*` / `teacher_view:*` / `teacher_self:*`）会破坏所有历史 inline button，**强烈不推荐**。

---

## 3. ROADMAP §8.2 建议入口 vs 现状对比

| §8.2 建议 | 现状 | 缺口 / 建议 |
| --- | --- | --- |
| ✅ 今日签到 | ✅ 已有（UX-5.1 置顶动态文案） | 无缺口 |
| 👤 我的资料 | ✅ 已有（✏️ 我的资料） | 仅图标差异；§8.5 "按钮数量减少" 不要求改图标 |
| 📝 我的评价 | ❌ 无 | 当前项目无"老师收到评价"专属入口；**新增将违反 §8.4 "不引入用户/管理员功能"** |
| 📢 发布状态 | ✅ 已有（📅 今日状态） | 仅文案差异；不强求改名 |
| ❓ 帮助 | ❌ 无 | 当前项目无 `/help` 命令 handler；**新增属于业务扩展**，应另开 Sprint 单独评估 |

---

## 4. §8.5 验收标准核查

| 验收项 | 当前状态 |
| --- | --- |
| 老师视角入口清晰 | ✅ 3 按钮 + 子页全部明确隶属 `teacher_self:*` 或 `teacher:status*` |
| **按钮数量减少** | ✅ 已 3 按钮（最简化），§8.2 建议 5 按钮反而**多于现状** |
| 签到流程未变 | ✅ 现状即基线；本审查 PR 不修改任何 callback 含义 |
| 老师不会误进入管理员 / 用户专属页面 | ✅ handler 级 `get_teacher` 校验 + 私聊校验 |

**结论**：§8.5 全部 4 项**当前已满足**，无需精简 PR 推进。

---

## 5. 与 admin / user 入口的冲突识别

### 5.1 命名空间共用（已识别，无功能风险）

`teacher:*` 命名空间被三角色共用（§2.3 已列）。每个 handler 独立权限校验，不构成漏洞。

### 5.2 入口归属（无误触发风险）

| 入口位置 | 渲染上下文 | 老师能否误触发 admin/user 入口？ |
| --- | --- | --- |
| `teacher_main_menu_kb` | `/start`（老师私聊） | ❌ 仅 3 个老师 callback |
| 管理员 admin_kb.py 的 `teacher:list/delete/...` | admin 后台 | ❌ 老师 `/start` 不会渲染 admin 入口 |
| 用户 user_kb.py 的 `teacher:view/similar/...` | 用户主菜单 + 搜索结果 | ❌ 老师 `/start` 渲染老师主菜单，不渲染用户主菜单 |

老师视角**不可能**误进入管理员 / 用户专属页面（除非显式从其它角色场景跳转，例如老师**同时是**超管 —— 此场景属于角色叠加，不在审查范围）。

### 5.3 历史残留 / 遗弃路径

| 检查项 | 结果 |
| --- | --- |
| 已删除但仍被引用的 callback | 无（grep 全清单全部有 handler） |
| 与 `teacher_daily_status.py` 注释「可约时间段相关流程已移除」一致 | ✅ `time:*` / `set_time` / `custom_time` 已全部清理 |
| 旧 `teacher_checkin.py`（文字 `签到`）与新 `teacher_self:checkin`（按钮）并存 | ✅ 双触发设计，文档 `teacher_self.py:442` 明示 "v1 teacher_checkin.on_checkin" |

---

## 6. 精简方案建议（Sprint 6 §8.3 精简 PR 范围）

### 6.1 推荐：**精简 PR 不启动 keyboard 改动**

理由：
- 现状已 3 按钮，§8.5 "按钮数量减少" 已自然满足
- §8.2 建议入口 5 个比现状多 → 若做反而违反 §8.5
- §8.2 中"📝 我的评价"和"❓ 帮助"对应**当前项目不存在的业务功能** → 新增违反 §8.4 "不在老师侧引入用户/管理员功能"

### 6.2 推荐：精简 PR 仅做"防御性测试 + 文档约束"

| 行动 | 文件 | 内容 |
| --- | --- | --- |
| 新增防御性 kb 测试 | `tests/test_teacher_main_menu.py`（新文件） | 断言 `teacher_main_menu_kb()` 按钮总数 == 3；签到 callback 在第一行；3 个 callback 全在 `teacher_self:*` 或 `teacher:status*` 命名空间 |
| 文档更新 | `docs/POLICY.md` 或 `docs/DESIGN.md` | 加一段「老师主菜单按钮上限契约：≤ 3 按钮，签到置顶」 |

### 6.3 不推荐：大改命名空间

不建议把 `teacher:list/delete/enable/view/similar` 等改为 `teacher_admin:*` / `teacher_view:*` 拆分命名空间：
- 改动量大（30+ callback + 所有历史 inline button 失效）
- 收益小（现状权限校验已足够，仅是"看起来更整洁"）
- 与 ROADMAP §2.4 "旧 callback 兼容" 原则冲突

### 6.4 不推荐：新增「我的评价 / 帮助」入口

当前项目没有：
- 老师视角"收到的评价列表"功能（仅有评价审核流程在 `rreview_admin.py`，是超管视角）
- `/help` 命令 handler

新增这两项属于**业务功能扩展**，不属于 §8 "面板精简" 范围；如有需求应另开 Sprint。

---

## 7. 下一步建议

1. **本 PR**（审查 PR）：仅落地本文档；零代码改动
2. **可选下一 PR**（防御性精简 PR）：按 §6.2 行动 —— 新增 `tests/test_teacher_main_menu.py` 锁定"主菜单按钮数 ≤ 3 + 签到置顶"契约；同步 POLICY 文档加一段「老师主菜单契约」段
3. **跳过其它工作**：§8 视为已收官，进入 Sprint 7

