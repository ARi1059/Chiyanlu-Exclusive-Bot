"""Sprint UX-1 第一批：子页面返回路径优化（admin:dashboard 子页）契约测试。

范围：仅覆盖「📊 运营看板」(admin:dashboard) 下的三个子页：
    - 📊 运营总览       admin:overview         keyboard: admin_overview_kb
    - 💰 报销池状态     admin:reimbursement_pool   keyboard: admin_reimbursement_pool_kb
    - 🎲 抽奖状态       admin:lottery_status   keyboard: admin_lottery_status_kb

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §4.3.B / §7 Sprint UX-1）：
    这三个子页面看完后，管理员通常会想回到「📊 运营看板」继续看下一个看板，
    而不是被甩回主菜单。返回按钮 callback 从 menu:main 调整为 admin:dashboard。

本文件是 UX-1 第一批改动的「集中契约」：
    1. 三个子页 keyboard 的返回按钮 callback_data == "admin:dashboard"
    2. 三个子页 keyboard 仍含各自的 refresh callback
    3. admin_dashboard_kb 仍是入口聚合页（三个子页入口 + menu:main 兜底）
    4. 不修改统计 service（import / callable 静态断言）
    5. 不新增数据库迁移（baseline = 9，MIGRATIONS = []）

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 1. 三个子页返回按钮 callback_data == "admin:dashboard" ============


def _return_buttons(kb) -> list:
    """提取 keyboard 中所有"返回"类按钮（文案包含 ⬅️ 或 "返回"）。"""
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if "⬅️" in btn.text or "返回" in btn.text:
                out.append(btn)
    return out


def test_admin_overview_kb_return_button_goes_to_admin_dashboard():
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1, (
        f"admin_overview_kb 应有恰好 1 个返回按钮，实际：{[b.text for b in backs]}"
    )
    assert backs[0].callback_data == "admin:dashboard", (
        f"admin_overview_kb 返回按钮 callback 应为 admin:dashboard，"
        f"实际：{backs[0].callback_data}"
    )
    assert "运营看板" in backs[0].text, (
        f"返回按钮文案应含「运营看板」，实际：{backs[0].text}"
    )


def test_admin_reimbursement_pool_kb_return_button_goes_to_admin_dashboard():
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:dashboard"
    assert "运营看板" in backs[0].text


def test_admin_lottery_status_kb_return_button_goes_to_admin_dashboard():
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:dashboard"
    assert "运营看板" in backs[0].text


def test_three_subpages_no_longer_return_to_menu_main():
    """UX-1：三个子页不再直接返回 menu:main。"""
    from bot.keyboards.admin_kb import (
        admin_overview_kb,
        admin_reimbursement_pool_kb,
        admin_lottery_status_kb,
    )
    for kb_fn in (admin_overview_kb, admin_reimbursement_pool_kb, admin_lottery_status_kb):
        kb = kb_fn()
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:main" not in callbacks, (
            f"{kb_fn.__name__} 不应再含 menu:main 返回（UX-1 已下沉到 admin:dashboard）"
        )


# ============ 2. 三个子页 refresh callback 保持不变 ============


def test_admin_overview_kb_keeps_refresh_callback():
    from bot.keyboards.admin_kb import admin_overview_kb
    callbacks = [b.callback_data for row in admin_overview_kb().inline_keyboard for b in row]
    assert "admin:overview:refresh" in callbacks


def test_admin_reimbursement_pool_kb_keeps_refresh_callback():
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    callbacks = [b.callback_data for row in admin_reimbursement_pool_kb().inline_keyboard for b in row]
    assert "admin:reimbursement_pool:refresh" in callbacks


def test_admin_lottery_status_kb_keeps_refresh_callback():
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    callbacks = [b.callback_data for row in admin_lottery_status_kb().inline_keyboard for b in row]
    assert "admin:lottery_status:refresh" in callbacks


# ============ 3. admin_dashboard_kb 仍是聚合入口页 ============


def test_admin_dashboard_kb_still_lists_three_entries():
    """二级运营看板页仍含三个子页入口（UX-1 只动子页返回，不动入口）。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    callbacks = [b.callback_data for row in admin_dashboard_kb().inline_keyboard for b in row]
    assert "admin:overview" in callbacks
    assert "admin:reimbursement_pool" in callbacks
    assert "admin:lottery_status" in callbacks


def test_admin_dashboard_kb_keeps_menu_main_back_button():
    """二级页 admin:dashboard 自身仍有 menu:main 返回（兜底）。

    UX-1 改的是「三个子页 → admin:dashboard」，没有改「admin:dashboard → menu:main」。
    """
    from bot.keyboards.admin_kb import admin_dashboard_kb
    callbacks = [b.callback_data for row in admin_dashboard_kb().inline_keyboard for b in row]
    assert "menu:main" in callbacks


# ============ 4. 不修改统计 service（import + callable 静态断言） ============


def test_three_stat_services_still_importable():
    """UX-1 第一批严禁修改 service 层；保留 import + callable 静态断言。"""
    from bot.services.admin_overview import (
        get_admin_overview_stats,
        render_admin_overview,
    )
    from bot.services.reimbursement_pool import (
        get_reimbursement_pool_stats,
        render_reimbursement_pool,
    )
    from bot.services.lottery_status import (
        get_lottery_status_stats,
        render_lottery_status,
    )
    for fn in (
        get_admin_overview_stats, render_admin_overview,
        get_reimbursement_pool_stats, render_reimbursement_pool,
        get_lottery_status_stats, render_lottery_status,
    ):
        assert callable(fn)


# ============ 5. 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged():
    """UX-1 第一批不新增 schema 变更：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    """UX-1 第一批不新增 Migration：MIGRATIONS 仍为空 list。"""
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


# ============ 6. 旧 callback 含义未被破坏 ============


def test_legacy_subpage_callbacks_still_in_handler_source():
    """admin:overview / :reimbursement_pool / :lottery_status 字面量
    仍存在于 handler 源码中（UX-1 不改 callback 含义）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    for cb in (
        '"admin:overview"', '"admin:overview:refresh"',
        '"admin:reimbursement_pool"', '"admin:reimbursement_pool:refresh"',
        '"admin:lottery_status"', '"admin:lottery_status:refresh"',
    ):
        assert cb in src, f"admin_panel.py 缺少 {cb}（UX-1 不应改 callback 含义）"


def test_admin_dashboard_handler_still_present():
    """admin:dashboard handler 仍在 admin_panel.py 中。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:dashboard"' in src
    assert "cb_admin_dashboard" in src
