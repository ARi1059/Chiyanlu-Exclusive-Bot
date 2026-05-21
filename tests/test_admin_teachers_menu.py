"""管理员后台「👩‍🏫 老师管理」二级菜单分组单元测试。

测试范围：
    1. 主菜单含 admin:teachers 入口（保留「老师管理」文案，super/非 super 都可见）
    2. 主菜单不再直接含 menu:teacher / admin:hot_manage / admin:today_status /
       admin:user_tags（这四个原一级 callback 已下沉到 admin:teachers）
    3. admin_teachers_kb 含全部预期 callback + menu:main 返回
    4. 精确 5 行（4 个入口 + 返回），无多余项
    5. 不含其它二级菜单的 callback（防误纳）
    6. handler 源码含 admin:teachers 字面量与 cb_admin_teachers
    7. cb_admin_teachers 装饰器为 @admin_required
    8. 旧 4 个老师管理 callback 字面量仍存在于代码中
    9. 不新增数据库迁移；不修改老师管理 handler 业务逻辑

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:teachers 替代四个一级 callback ============


def test_main_menu_kb_contains_admin_teachers():
    """主菜单必须含 admin:teachers 入口（super/非 super 都可见，文案保留「老师管理」）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data == "admin:teachers":
                    found = True
                    assert "老师管理" in btn.text
        assert found, f"主菜单 (is_super={is_super}) 缺少 admin:teachers 入口"


def test_main_menu_kb_no_longer_contains_demoted_teacher_callbacks():
    """主菜单不应再直接含下沉到 admin:teachers 的四个 callback。"""
    from bot.keyboards.admin_kb import main_menu_kb
    forbidden = {
        "menu:teacher",           # 老师管理子菜单（callback 改为 admin:teachers）
        "admin:hot_manage",        # 热门推荐
        "admin:today_status",      # 今日发布状态
        "admin:user_tags",         # 用户画像
    }
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        leaked = forbidden & callbacks
        assert not leaked, (
            f"主菜单 (is_super={is_super}) 不应直接含 {leaked}，"
            f"它们已被收纳至 admin:teachers 二级页"
        )


# ============ admin_teachers_kb 结构 ============


def test_teachers_kb_contains_all_entries():
    """admin_teachers_kb 必须含 4 个老师管理入口。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    kb = admin_teachers_kb()
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "menu:teacher" in callbacks, "缺少 老师列表与启停 入口"
    assert "admin:hot_manage" in callbacks, "缺少 热门推荐 入口"
    assert "admin:today_status" in callbacks, "缺少 今日发布状态 入口"
    assert "admin:user_tags" in callbacks, "缺少 用户画像 入口"


def test_teachers_kb_back_button_is_menu_main():
    """返回按钮复用既有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    kb = admin_teachers_kb()
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "menu:main"
    assert "返回后台" in last_row[0].text


def test_teachers_kb_exactly_five_rows():
    """精确五行：4 个入口 + 返回，不能漏不能多。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    kb = admin_teachers_kb()
    assert len(kb.inline_keyboard) == 5


def test_teachers_kb_button_texts():
    from bot.keyboards.admin_kb import admin_teachers_kb
    kb = admin_teachers_kb()
    by_callback = {
        b.callback_data: b.text for row in kb.inline_keyboard for b in row
    }
    assert "老师列表" in by_callback["menu:teacher"] or \
           "启停" in by_callback["menu:teacher"]
    assert "热门推荐" in by_callback["admin:hot_manage"]
    assert "今日" in by_callback["admin:today_status"]
    assert "用户画像" in by_callback["admin:user_tags"]


# ============ 不含其它二级菜单的 callback（防误纳） ============


def test_teachers_kb_does_not_contain_other_submenu_callbacks():
    """admin_teachers_kb 不应误纳已被其它二级菜单收纳的 callback。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    kb = admin_teachers_kb()
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    forbidden = {
        # 属于 admin:dashboard
        "admin:overview",
        "admin:reimbursement_pool",
        "admin:lottery_status",
        # 属于 admin:review_tasks
        "review:enter",
        "rreview:enter",
        "reimburse:enter",
        "reimburse:queued:0",
        # 属于 admin:operations
        "admin:lottery",
        "admin:points",
        # 属于 admin:settings
        "admin:subreq",
        "admin:publish_templates",
        "menu:channel",
        "admin:report_settings",
        "menu:system",
        "system:reimburse_pool",
        "system:reimburse_toggle",
    }
    leaked = forbidden & callbacks
    assert not leaked, f"admin_teachers_kb 不应含其它二级菜单的 callback：{leaked}"


# ============ handler 字符串契约 + 权限装饰器 ============


def test_admin_teachers_handler_present_in_source():
    """admin_panel.py 必须含 admin:teachers 字面量与 cb_admin_teachers。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:teachers"' in src
    assert "cb_admin_teachers" in src


def test_admin_teachers_handler_uses_admin_required():
    """cb_admin_teachers 装饰器为 @admin_required（所有 admin 可访问）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    idx = src.find("async def cb_admin_teachers(")
    assert idx > 0, "找不到 cb_admin_teachers 定义"
    window = src[max(0, idx - 300):idx]
    assert "@admin_required" in window, (
        "cb_admin_teachers 应使用 @admin_required；当前窗口：\n" + window
    )
    # 防御：不应错配为 @super_admin_required（所有 admin 都可访问老师管理）
    assert "@super_admin_required" not in window, (
        "cb_admin_teachers 不应是 @super_admin_required（所有 admin 均需访问老师管理）"
    )


# ============ 旧 callback 字面量仍存在 ============


def test_legacy_teacher_callback_literals_still_exist():
    """旧 4 个老师管理 callback 字面量必须仍在代码中（handler 未删 / kb 仍引用）。

    分布：
        menu:teacher        → admin_panel.py + admin_teachers_kb
        admin:hot_manage    → hot_teachers.py + admin_teachers_kb
        admin:today_status  → teacher_daily_status.py + admin_teachers_kb
        admin:user_tags     → user_tags.py + admin_teachers_kb
    """
    import bot.handlers.admin_panel as ap
    import bot.handlers.hot_teachers as ht
    import bot.handlers.teacher_daily_status as tds
    import bot.handlers.user_tags as ut
    import bot.keyboards.admin_kb as akb
    import inspect

    assert '"menu:teacher"' in inspect.getsource(ap)
    assert '"admin:hot_manage"' in inspect.getsource(ht)
    assert '"admin:today_status"' in inspect.getsource(tds)
    assert '"admin:user_tags"' in inspect.getsource(ut)

    # admin_kb 中必须保留全部 4 个字面量
    kb_src = inspect.getsource(akb)
    for cb in (
        '"menu:teacher"',
        '"admin:hot_manage"',
        '"admin:today_status"',
        '"admin:user_tags"',
    ):
        assert cb in kb_src, f"admin_kb 缺少 {cb} 字面量"


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_in_MIGRATIONS_list():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states", "20260520_002_quick_entry_keywords", "20260521_001_teacher_reviews_gesture_nullable"}


# ============ 不修改业务 handler ============


def test_teacher_target_handlers_still_importable():
    """老师管理类 handler 模块仍可正常 import；router 仍存在。"""
    from bot.handlers.admin_panel import router as r1
    from bot.handlers.hot_teachers import router as r2
    from bot.handlers.teacher_daily_status import router as r3
    from bot.handlers.user_tags import router as r4
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None


def test_menu_teacher_handler_still_present():
    """menu:teacher 旧 handler（老师管理子菜单）仍在 admin_panel.py 中，
    callback 含义未变；旧消息中的 inline button 仍可工作。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert 'F.data == "menu:teacher"' in src
    # 确认 teacher_menu_kb 仍被使用（旧子菜单视图）
    assert "teacher_menu_kb" in src


# ============ 主菜单结构精简验证 ============


def test_main_menu_super_row_count_reduced():
    """超管主菜单行数应保持紧凑（4 行）：
        Row 1: [老师管理, 管理员管理]
        Row 2: [数据看板 dashboard:enter, 审核处理]
        Row 3: [活动运营] (super only)
        Row 4: [数据看板 admin:dashboard, 系统配置]
    """
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    assert len(kb.inline_keyboard) == 4


def test_main_menu_non_super_row_count_reduced():
    """非超管主菜单行数应保持紧凑（3 行）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=False)
    assert len(kb.inline_keyboard) == 3
