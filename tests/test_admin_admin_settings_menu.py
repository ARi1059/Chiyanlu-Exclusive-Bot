"""管理员后台「🛡 管理员设置」二级菜单分组单元测试。

测试范围（仅超管可见）：
    1. 超管主菜单包含 admin:admin_settings 入口
    2. 普通管理员主菜单不包含 admin:admin_settings 入口
    3. 主菜单不再直接含 menu:admin（已下沉至 admin:admin_settings）
    4. admin_admin_settings_kb 含管理员管理 + 审计日志 + 返回
    5. admin_admin_settings_kb 不含其它二级菜单的 callback（防误纳）
    6. handler 源码含 admin:admin_settings 字面量与 cb_admin_admin_settings
    7. cb_admin_admin_settings 装饰器必须为 @super_admin_required
    8. 旧 4 个管理员 callback 字面量仍存在于代码中
    9. 不新增数据库迁移；不修改管理员权限业务逻辑

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:admin_settings 仅超管可见 ============


def test_super_main_menu_contains_admin_admin_settings():
    """超管主菜单必须含 admin:admin_settings 入口（含「管理员设置」文案）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:admin_settings":
                found = True
                assert "管理员设置" in btn.text
    assert found, "超管主菜单缺少 admin:admin_settings 入口"


def test_non_super_main_menu_does_not_contain_admin_admin_settings():
    """普通管理员主菜单不应含 admin:admin_settings（仅超管可见）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=False)
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "admin:admin_settings" not in callbacks, (
        "普通管理员不应看到 admin:admin_settings 入口（保持原有权限边界）"
    )


def test_main_menu_no_longer_contains_menu_admin_directly():
    """主菜单不应再直接含 menu:admin（已下沉到 admin:admin_settings）。

    super / 非 super 都不再展示 menu:admin —— 普通管理员原本就不该看到（pre-existing
    UX bug fix），现在被显式从一级菜单移除。
    """
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        assert "menu:admin" not in callbacks, (
            f"主菜单 (is_super={is_super}) 不应再直接含 menu:admin，"
            f"已被收纳至 admin:admin_settings 二级页"
        )


# ============ admin_admin_settings_kb 结构 ============


def test_settings_kb_contains_admin_management_and_audit():
    """2026-06：审计日志已并入「📊 数据看板」作唯一入口，管理员设置只剩 管理员管理(menu:admin)。"""
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    kb = admin_admin_settings_kb()
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "menu:admin" in callbacks, "缺少 管理员管理 入口"
    assert "dashboard:audit" not in callbacks, "审计日志应已移至数据看板，本面板不再含"


def test_settings_kb_back_button_is_menu_main():
    """返回按钮复用既有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    kb = admin_admin_settings_kb()
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "menu:main"
    assert "返回后台" in last_row[0].text


def test_settings_kb_exactly_three_rows():
    """2026-06：精确 2 行：管理员管理 / 返回（审计日志已并入数据看板）。"""
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    kb = admin_admin_settings_kb()
    assert len(kb.inline_keyboard) == 2


def test_settings_kb_button_texts():
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    kb = admin_admin_settings_kb()
    by_callback = {
        b.callback_data: b.text for row in kb.inline_keyboard for b in row
    }
    assert "管理员管理" in by_callback["menu:admin"]


# ============ 不含其它二级菜单的 callback（防误纳） ============


def test_settings_kb_does_not_contain_other_submenu_callbacks():
    """admin_admin_settings_kb 不应误纳其它二级菜单已收纳的 callback。"""
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    kb = admin_admin_settings_kb()
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
        # 属于 admin:teachers
        "menu:teacher",
        "admin:hot_manage",
        "admin:today_status",
        "admin:user_tags",
    }
    leaked = forbidden & callbacks
    assert not leaked, f"admin_admin_settings_kb 不应含其它二级菜单 callback：{leaked}"


# ============ handler 字符串契约 + 权限装饰器 ============


def test_admin_admin_settings_handler_present_in_source():
    """admin_panel.py 必须含 admin:admin_settings 字面量与 cb_admin_admin_settings。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:admin_settings"' in src
    assert "cb_admin_admin_settings" in src


def test_admin_admin_settings_handler_uses_super_admin_required():
    """cb_admin_admin_settings 必须用 @super_admin_required 装饰（spec 硬性要求）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    idx = src.find("async def cb_admin_admin_settings(")
    assert idx > 0, "找不到 cb_admin_admin_settings 定义"
    window = src[max(0, idx - 300):idx]
    assert "@super_admin_required" in window, (
        "cb_admin_admin_settings 必须使用 @super_admin_required；当前窗口：\n" + window
    )


# ============ 旧 callback 字面量仍存在 ============


def test_legacy_admin_callback_literals_still_exist():
    """旧 4 个管理员管理 callback 字面量必须仍在代码中（handler 未删 / kb 仍引用）。

    分布：
        menu:admin              → admin_panel.py
        admin:add               → admin_panel.py
        admin:remove            → admin_panel.py
        admin:list              → admin_panel.py
        admin:confirm_remove:   → admin_panel.py (prefix used in admin_remove_kb)
        dashboard:audit         → admin_panel.py + admin_admin_settings_kb
    """
    import bot.handlers.admin_panel as ap
    import bot.keyboards.admin_kb as akb
    import inspect

    ap_src = inspect.getsource(ap)
    for cb in (
        '"menu:admin"',
        '"admin:add"',
        '"admin:remove"',
        '"admin:list"',
        '"dashboard:audit"',
    ):
        assert cb in ap_src, f"admin_panel.py 缺少 {cb} 字面量"
    # admin:confirm_remove 在 .startswith() 中使用
    assert "admin:confirm_remove:" in ap_src

    # admin_kb 中必须保留 menu:admin / dashboard:audit / admin_menu_kb 行内的字面量
    kb_src = inspect.getsource(akb)
    assert '"menu:admin"' in kb_src
    assert '"dashboard:audit"' in kb_src
    # admin_menu_kb 中的 admin:add / admin:remove / admin:list 仍在
    assert '"admin:add"' in kb_src
    assert '"admin:remove"' in kb_src
    assert '"admin:list"' in kb_src


def test_admin_menu_kb_still_present_in_keyboards():
    """admin_menu_kb 函数仍存在（被 menu:admin handler 使用）。"""
    from bot.keyboards.admin_kb import admin_menu_kb
    kb = admin_menu_kb()
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    # 旧 admin_menu_kb 三个核心入口仍可用
    assert "admin:add" in callbacks
    assert "admin:remove" in callbacks
    assert "admin:list" in callbacks


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_in_MIGRATIONS_list():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


# ============ 不修改业务 handler ============


def test_admin_management_handlers_still_present_in_source():
    """4 个原管理员管理 handler 仍在 admin_panel.py 中，callback 含义未变。

    UX-9.6（2026-05-20）：dashboard:audit handler 从精确匹配 `F.data == ...`
    升级为 `F.data.startswith("dashboard:audit")` 支持分页 + 筛选子路径
    （dashboard:audit:p:N / dashboard:audit:f:<action>:N / dashboard:audit:filter
    / dashboard:audit:all）。callback 字面量 "dashboard:audit" 含义未变，
    仍是主入口（page=0，无过滤）。
    """
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert 'F.data == "menu:admin"' in src
    assert 'F.data == "admin:add"' in src
    assert 'F.data == "admin:remove"' in src
    assert 'F.data == "admin:list"' in src
    # UX-9.6：dashboard:audit 可能是 startswith 也可能是 ==；都视为存在
    assert (
        'F.data == "dashboard:audit"' in src
        or 'F.data.startswith("dashboard:audit")' in src
    )


def test_admin_management_handlers_use_super_admin_required():
    """menu:admin / admin:add / admin:remove / admin:list 都必须保持
    @super_admin_required（不降级权限）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    for name in ("cb_admin_menu", "cb_admin_add", "cb_admin_remove", "cb_admin_list"):
        idx = src.find(f"async def {name}(")
        assert idx > 0, f"找不到 {name} 定义"
        window = src[max(0, idx - 300):idx]
        assert "@super_admin_required" in window, (
            f"{name} 应保持 @super_admin_required；当前窗口：\n" + window
        )


# ============ 主菜单结构验证 ============


def test_main_menu_super_layout_after_admin_settings_grouping():
    """2026-06 重排后超管主菜单：
    Row0 🚀小程序 / Row1 ✅审核处理 / Row2 老师管理+数据看板 / Row3 系统配置+财务运营 / Row4 管理员设置。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    assert kb.inline_keyboard[0][0].web_app is not None  # §16.3 小程序入口
    assert [b.callback_data for b in kb.inline_keyboard[1]] == ["admin:review_tasks"]
    assert [b.callback_data for b in kb.inline_keyboard[2]] == ["admin:teachers", "admin:dashboard"]
    assert [b.callback_data for b in kb.inline_keyboard[3]] == ["admin:settings", "admin:operations"]
    assert [b.callback_data for b in kb.inline_keyboard[4]] == ["admin:admin_settings"]


def test_main_menu_non_super_layout_after_admin_settings_grouping():
    """2026-06 重排后非超管主菜单：无 财务运营/管理员设置；系统配置单独成行。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=False)
    assert kb.inline_keyboard[0][0].web_app is not None
    assert [b.callback_data for b in kb.inline_keyboard[1]] == ["admin:review_tasks"]
    assert [b.callback_data for b in kb.inline_keyboard[2]] == ["admin:teachers", "admin:dashboard"]
    assert [b.callback_data for b in kb.inline_keyboard[3]] == ["admin:settings"]
    all_cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "admin:operations" not in all_cbs
    assert "admin:admin_settings" not in all_cbs
