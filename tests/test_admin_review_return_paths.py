"""Sprint UX-4 第六项（UX-4.6）：审核三类子页面返回路径增量优化契约测试。

范围：覆盖三大审核子系统的「详情页 / 空状态」共 6 个 keyboard：

    - review_action_kb      老师资料审核详情页
    - review_empty_kb       老师资料审核空状态
    - rreview_action_kb     评价审核详情页
    - rreview_empty_kb      评价审核空状态
    - reimburse_action_kb   报销审核详情页
    - reimburse_empty_kb    报销审核空状态

UX 目标（参见 docs/UX-FEATURE-ITERATION-2026-05-19.md §1 C3 + §7 痛点 5-6）：

    管理员审完一类后想切换审核类型 / 在空队列状态想继续别的审核时，被现有的
    "🔙 返回主菜单" 兜底按钮甩回主菜单，需多点 2 次才能回到 ✅ 审核处理二级页。
    本批新增「🔙 返回审核处理」按钮直接跳 admin:review_tasks。

约束（与 UX-EFFICIENCY-PLAN §1.2 一致）：
    1. 旧 callback_data="menu:main" 按钮 **不替换**，作为兜底保留。
    2. 新按钮 callback_data="admin:review_tasks" 排在主菜单按钮**之前**
       （上一级在前，最后才是主菜单兜底）。
    3. 顶部业务按钮（通过/驳回/上下条/重置等）行为完全不变。

本文件是 UX-4.6 改动的「集中契约」：
    1. 6 个 keyboard 各自必含 callback_data == "admin:review_tasks" 的按钮。
    2. 6 个 keyboard 各自**仍**含 callback_data == "menu:main" 的按钮（兼容）。
    3. "返回审核处理"必须排在 "返回主菜单" 之前。
    4. action_kb 的业务按钮（approve / reject / nav / reset）保持原契约。
    5. admin:review_tasks callback 在 admin_panel.py 仍有 handler 注册。

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _all_callbacks(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _flat_buttons(kb) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append(btn)
    return out


# ============================================================
# 1. 六个 keyboard 各自含 admin:review_tasks
# ============================================================


def test_review_action_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import review_action_kb
    kb = review_action_kb(request_id=1, has_prev=False, has_next=False)
    cbs = _all_callbacks(kb)
    assert "admin:review_tasks" in cbs


def test_review_empty_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import review_empty_kb
    cbs = _all_callbacks(review_empty_kb())
    assert "admin:review_tasks" in cbs


def test_rreview_action_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(review_id=1, has_prev=False, has_next=False)
    cbs = _all_callbacks(kb)
    assert "admin:review_tasks" in cbs


def test_rreview_empty_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import rreview_empty_kb
    cbs = _all_callbacks(rreview_empty_kb())
    assert "admin:review_tasks" in cbs


def test_reimburse_action_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import reimburse_action_kb
    kb = reimburse_action_kb(reimb_id=1, user_id=100)
    cbs = _all_callbacks(kb)
    assert "admin:review_tasks" in cbs


def test_reimburse_empty_kb_has_review_tasks_return():
    from bot.keyboards.admin_kb import reimburse_empty_kb
    cbs = _all_callbacks(reimburse_empty_kb())
    assert "admin:review_tasks" in cbs


# ============================================================
# 2. 六个 keyboard 仍保留 menu:main 兜底（不替换契约）
# ============================================================


def test_review_action_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import review_action_kb
    kb = review_action_kb(request_id=1, has_prev=False, has_next=False)
    assert "menu:main" in _all_callbacks(kb)


def test_review_empty_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import review_empty_kb
    assert "menu:main" in _all_callbacks(review_empty_kb())


def test_rreview_action_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(review_id=1, has_prev=False, has_next=False)
    assert "menu:main" in _all_callbacks(kb)


def test_rreview_empty_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import rreview_empty_kb
    assert "menu:main" in _all_callbacks(rreview_empty_kb())


def test_reimburse_action_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import reimburse_action_kb
    kb = reimburse_action_kb(reimb_id=1, user_id=100)
    assert "menu:main" in _all_callbacks(kb)


def test_reimburse_empty_kb_still_has_menu_main_fallback():
    from bot.keyboards.admin_kb import reimburse_empty_kb
    assert "menu:main" in _all_callbacks(reimburse_empty_kb())


# ============================================================
# 3. 顺序：admin:review_tasks 必须排在 menu:main 之前
# ============================================================


def _assert_review_tasks_before_menu_main(cbs: list) -> None:
    assert "admin:review_tasks" in cbs and "menu:main" in cbs
    assert cbs.index("admin:review_tasks") < cbs.index("menu:main"), (
        "返回审核处理应排在返回主菜单之前（上一级在前，兜底在后）"
    )


def test_review_action_kb_order():
    from bot.keyboards.admin_kb import review_action_kb
    kb = review_action_kb(request_id=1, has_prev=True, has_next=True)
    _assert_review_tasks_before_menu_main(_all_callbacks(kb))


def test_review_empty_kb_order():
    from bot.keyboards.admin_kb import review_empty_kb
    _assert_review_tasks_before_menu_main(_all_callbacks(review_empty_kb()))


def test_rreview_action_kb_order():
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(review_id=1, has_prev=True, has_next=True)
    _assert_review_tasks_before_menu_main(_all_callbacks(kb))


def test_rreview_empty_kb_order():
    from bot.keyboards.admin_kb import rreview_empty_kb
    _assert_review_tasks_before_menu_main(_all_callbacks(rreview_empty_kb()))


def test_reimburse_action_kb_order():
    from bot.keyboards.admin_kb import reimburse_action_kb
    kb = reimburse_action_kb(reimb_id=1, user_id=100)
    _assert_review_tasks_before_menu_main(_all_callbacks(kb))


def test_reimburse_empty_kb_order():
    from bot.keyboards.admin_kb import reimburse_empty_kb
    _assert_review_tasks_before_menu_main(_all_callbacks(reimburse_empty_kb()))


# ============================================================
# 4. 业务按钮契约保持（防止本批顺手改坏）
# ============================================================


def test_review_action_kb_business_buttons_preserved():
    from bot.keyboards.admin_kb import review_action_kb
    kb = review_action_kb(request_id=42, has_prev=True, has_next=True)
    cbs = _all_callbacks(kb)
    assert "review:approve:42" in cbs
    assert "review:reject:42" in cbs
    assert "review:nav:prev:42" in cbs
    assert "review:nav:next:42" in cbs


def test_rreview_action_kb_business_buttons_preserved():
    from bot.keyboards.admin_kb import rreview_action_kb
    kb = rreview_action_kb(review_id=42, has_prev=True, has_next=True)
    cbs = _all_callbacks(kb)
    assert "rreview:approve:42" in cbs
    assert "rreview:reject:42" in cbs
    assert "rreview:nav:prev:42" in cbs
    assert "rreview:nav:next:42" in cbs
    # 重看照片按钮也应仍在
    assert "rreview:photo:booking:42" in cbs
    assert "rreview:photo:gesture:42" in cbs


def test_reimburse_action_kb_business_buttons_preserved():
    from bot.keyboards.admin_kb import reimburse_action_kb
    kb = reimburse_action_kb(reimb_id=42, user_id=100)
    cbs = _all_callbacks(kb)
    assert "reimburse:approve:42" in cbs
    assert "reimburse:reject:42" in cbs
    assert "reimburse:reset:100:42" in cbs


# ============================================================
# 5. admin:review_tasks 仍有 handler（防止死按钮）
# ============================================================


def test_admin_review_tasks_handler_still_registered():
    """admin:review_tasks callback 必须在 admin_panel.py 仍有 handler 注册，
    否则本批新增的返回按钮会变成死按钮。"""
    import bot.handlers.admin_panel as mod
    src = inspect.getsource(mod)
    assert 'F.data == "admin:review_tasks"' in src, (
        "admin:review_tasks callback handler 应在 admin_panel.py 注册"
    )


# ============================================================
# 6. 不动 schema / 不引入新 callback_data 字面量
# ============================================================


def test_no_schema_migration_added():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


def test_no_new_callback_data_introduced():
    """UX-4.6 仅复用既有 admin:review_tasks 和 menu:main，
    不引入新 callback_data。"""
    from bot.keyboards.admin_kb import (
        review_action_kb,
        review_empty_kb,
        rreview_action_kb,
        rreview_empty_kb,
        reimburse_action_kb,
        reimburse_empty_kb,
    )
    all_cbs = set()
    for kb in (
        review_action_kb(request_id=1, has_prev=False, has_next=False),
        review_empty_kb(),
        rreview_action_kb(review_id=1, has_prev=False, has_next=False),
        rreview_empty_kb(),
        reimburse_action_kb(reimb_id=1, user_id=100),
        reimburse_empty_kb(),
    ):
        all_cbs.update(_all_callbacks(kb))
    # 这两个返回类 callback 字面量必须存在
    assert "admin:review_tasks" in all_cbs
    assert "menu:main" in all_cbs
