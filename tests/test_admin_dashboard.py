"""管理员后台「📊 数据看板」二级菜单分组单元测试。

测试范围：
    1. 主菜单含 admin:dashboard 入口（替代原三个一级按钮）
    2. 主菜单不再直接含 admin:overview / admin:reimbursement_pool / admin:lottery_status
    3. admin_dashboard_kb 含三个看板入口 + menu:main 返回
    4. handler 源码含 admin:dashboard 字面量与 cb_admin_dashboard
    5. 三个旧 callback 字面量仍在 handler 源码中存在（未删除）
    6. 不新增数据库迁移（schema_migrations baseline 数量未变）
    7. 不修改统计 service（三个 service 仍可正常 import）

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:dashboard 替代原三个一级按钮 ============


def test_main_menu_kb_contains_admin_dashboard():
    """主菜单必须含 admin:dashboard 入口（文案『📊 运营看板』，区分于
    dashboard:enter 的『📈 数据分析』）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data == "admin:dashboard":
                    found = True
                    assert "运营看板" in btn.text, (
                        f"admin:dashboard 按钮文案应含「运营看板」，实际：{btn.text}"
                    )
                    # 防御：不应再叫「数据看板」（与 dashboard:enter 冲突）
                    assert "数据看板" not in btn.text, (
                        f"admin:dashboard 按钮文案不应再叫「数据看板」，与 dashboard:enter 冲突"
                    )
        assert found, f"主菜单 (is_super={is_super}) 缺少 admin:dashboard 入口"


def test_main_menu_kb_dashboard_enter_renamed_to_data_analysis():
    """dashboard:enter 按钮文案应为「📈 数据分析」（旧 Phase 1 user_events 看板）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data == "dashboard:enter":
                    found = True
                    assert "数据分析" in btn.text, (
                        f"dashboard:enter 按钮文案应含「数据分析」，实际：{btn.text}"
                    )
                    # 防御：不应再叫「数据看板」
                    assert "数据看板" not in btn.text
        assert found, f"主菜单 (is_super={is_super}) 缺少 dashboard:enter 入口"


def test_main_menu_kb_two_dashboards_have_distinct_labels():
    """主菜单中 dashboard:enter 与 admin:dashboard 必须文案不同（命名优化目标）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    label_by_callback: dict[str, str] = {}
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data in ("dashboard:enter", "admin:dashboard"):
                label_by_callback[btn.callback_data] = btn.text
    assert "dashboard:enter" in label_by_callback
    assert "admin:dashboard" in label_by_callback
    assert label_by_callback["dashboard:enter"] != label_by_callback["admin:dashboard"], (
        f"两个看板入口文案不应相同：{label_by_callback}"
    )


def test_admin_dashboard_handler_title_uses_new_label():
    """cb_admin_dashboard 渲染文本应使用「📊 运营看板」标题，不再是「📊 数据看板」。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    # 定位 cb_admin_dashboard 函数体（窗口约 500 字符）
    idx = src.find("async def cb_admin_dashboard(")
    assert idx > 0
    window = src[idx:idx + 700]
    assert "📊 运营看板" in window, "cb_admin_dashboard 应渲染「📊 运营看板」标题"
    # cb_admin_dashboard 函数体内不应再有「📊 数据看板」字面量
    assert "📊 数据看板" not in window, (
        "cb_admin_dashboard 函数体不应再含『📊 数据看板』字面量"
    )


def test_main_menu_kb_no_longer_contains_three_dashboards():
    """主菜单不应再直接含三个被收纳的看板 callback。"""
    from bot.keyboards.admin_kb import main_menu_kb
    forbidden = {"admin:overview", "admin:reimbursement_pool", "admin:lottery_status"}
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        leaked = forbidden & callbacks
        assert not leaked, (
            f"主菜单 (is_super={is_super}) 不应直接含 {leaked}，"
            f"它们已被收纳至 admin:dashboard 二级页"
        )


# ============ admin_dashboard_kb：聚合三个看板入口 ============


def test_admin_dashboard_kb_contains_three_callbacks():
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "admin:overview" in callbacks
    assert "admin:reimbursement_pool" in callbacks
    assert "admin:lottery_status" in callbacks


def test_admin_dashboard_kb_has_menu_main_back():
    """返回按钮复用现有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "menu:main" in callbacks


def test_admin_dashboard_kb_button_texts():
    """三个看板按钮文案应有标识性 emoji 和名称。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    by_callback = {
        btn.callback_data: btn.text
        for row in kb.inline_keyboard
        for btn in row
    }
    assert "运营总览" in by_callback["admin:overview"]
    assert "报销池状态" in by_callback["admin:reimbursement_pool"]
    assert "抽奖状态" in by_callback["admin:lottery_status"]


def test_admin_dashboard_kb_only_four_rows():
    """二级菜单仅四行：三个看板 + 返回按钮，不能漏不能多。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    assert len(kb.inline_keyboard) == 4


# ============ handler 字符串契约 ============


def test_admin_dashboard_handler_present_in_source():
    """admin_panel.py 必须含 admin:dashboard 的 handler 字面量。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:dashboard"' in src
    assert "cb_admin_dashboard" in src


def test_legacy_callback_literals_still_in_handler_source():
    """旧三个 callback 字面量仍必须在 admin_panel.py 源码中存在（handler 未删）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    for cb in ('"admin:overview"', '"admin:reimbursement_pool"', '"admin:lottery_status"'):
        assert cb in src, f"admin_panel.py 缺少旧 callback {cb} 字面量"


# ============ 不修改统计 service ============


def test_three_stat_services_still_importable_unchanged():
    """三个统计 service 仍可正常 import + 关键函数存在（未删除/重命名）。"""
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
    # 触发引用，确保没有被静态优化掉
    for fn in (
        get_admin_overview_stats, render_admin_overview,
        get_reimbursement_pool_stats, render_reimbursement_pool,
        get_lottery_status_stats, render_lottery_status,
    ):
        assert callable(fn)


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    # 9 条历史迁移；新增任何一条会改变这里。如果未来确实有迁移，需要单独修改此数字。
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_class_in_MIGRATIONS_list():
    """MIGRATIONS 注册器列表本阶段应保持为空。"""
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords"}
