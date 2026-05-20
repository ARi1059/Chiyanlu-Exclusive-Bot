"""管理员后台「⚙️ 系统配置」二级菜单分组单元测试。

测试范围：
    1. 主菜单含 admin:settings 入口（super / 非 super 双场景）
    2. 主菜单不再直接含 menu:channel / admin:publish_templates / admin:report_settings
       （这三个原一级 callback 已下沉到 admin:settings 二级页）
    3. 主菜单不再直接展示 ⚙️ 系统设置 (menu:system) 一级按钮 —— menu:system 已
       下沉到 admin:settings；callback 字面量仍保留在 admin_settings_kb 中
    4. admin_settings_kb 含全部预期 callback（含 / 不含 super 专属项）
    5. 不含已下线 / 不存在的入口（promo_links / source_stats / 关键词独立 callback）
    6. 不含其它二级菜单的 callback（防误纳）
    7. handler 源码含 admin:settings 字面量与 cb_admin_settings
    8. cb_admin_settings 装饰器为 @admin_required（基础入口对所有 admin 开放）
    9. 旧 7 个配置 callback 字面量仍存在于代码中
    10. 不新增数据库迁移；不修改配置 handler 业务逻辑

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:settings 替代多个一级配置按钮 ============


def test_main_menu_kb_contains_admin_settings():
    """主菜单必须新增 admin:settings 入口（含『系统配置』文案，super/非 super 都可见）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data == "admin:settings":
                    found = True
                    assert "系统配置" in btn.text
        assert found, f"主菜单 (is_super={is_super}) 缺少 admin:settings 入口"


def test_main_menu_kb_no_longer_contains_demoted_config_callbacks():
    """主菜单不应再直接含下沉到 admin:settings 的四个配置 callback。

    这四个原本作为一级菜单按钮存在，现在统一进入 admin:settings 二级页。
    """
    from bot.keyboards.admin_kb import main_menu_kb
    forbidden = {
        "menu:channel",              # 频道 / 群组设置
        "menu:system",               # 系统设置（子菜单入口）
        "admin:publish_templates",   # 发布模板
        "admin:report_settings",     # 日报 / 周报设置
    }
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        leaked = forbidden & callbacks
        assert not leaked, (
            f"主菜单 (is_super={is_super}) 不应直接含 {leaked}，"
            f"它们已被收纳至 admin:settings 二级页"
        )


# ============ admin_settings_kb 基础结构 ============


def test_settings_kb_contains_base_entries():
    """所有 admin 可见的 5 个基础入口。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    for is_super in (True, False):
        kb = admin_settings_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        assert "admin:subreq" in callbacks, "缺少 必关订阅 入口"
        assert "admin:publish_templates" in callbacks, "缺少 发布模板 入口"
        assert "menu:channel" in callbacks, "缺少 频道 / 群组设置 入口"
        assert "admin:report_settings" in callbacks, "缺少 日报 / 周报设置 入口"
        assert "menu:system" in callbacks, "缺少 系统设置 入口"


def test_settings_kb_contains_super_only_entries():
    """超管专属：报销池设置 + 报销功能开关。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "system:reimburse_pool" in callbacks
    assert "system:reimburse_toggle" in callbacks


def test_settings_kb_hides_super_only_entries_for_non_super():
    """非超管不应看到报销池设置 / 报销功能开关。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=False)
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "system:reimburse_pool" not in callbacks
    assert "system:reimburse_toggle" not in callbacks


def test_settings_kb_back_button_is_menu_main():
    """返回按钮复用既有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    for is_super in (True, False):
        kb = admin_settings_kb(is_super=is_super)
        last_row = kb.inline_keyboard[-1]
        assert len(last_row) == 1
        assert last_row[0].callback_data == "menu:main"
        assert "返回后台" in last_row[0].text


def test_settings_kb_row_counts():
    """超管：5 base + 2 super + 1 back = 8 行；非超管：5 base + 1 back = 6 行。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    assert len(admin_settings_kb(is_super=True).inline_keyboard) == 8
    assert len(admin_settings_kb(is_super=False).inline_keyboard) == 6


def test_settings_kb_button_texts_match_labels():
    """按钮文案应有清晰的中文标识。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    by_callback = {
        b.callback_data: b.text for row in kb.inline_keyboard for b in row
    }
    assert "必关订阅" in by_callback["admin:subreq"]
    assert "发布模板" in by_callback["admin:publish_templates"]
    assert "频道" in by_callback["menu:channel"]
    assert "日报" in by_callback["admin:report_settings"] or \
           "周报" in by_callback["admin:report_settings"]
    assert "系统设置" in by_callback["menu:system"]
    assert "报销池" in by_callback["system:reimburse_pool"]
    assert "报销功能开关" in by_callback["system:reimburse_toggle"]


# ============ 不含已下线 / 不存在 / 错误归属的入口 ============


def test_settings_kb_does_not_contain_downed_callbacks():
    """spec：promo_links / source_stats 在 Phase 4 已下线，不重新启用。
    关键词管理无独立 callback，不构造伪入口。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    callbacks = [b.callback_data or "" for row in kb.inline_keyboard for b in row]
    for cb in callbacks:
        assert "admin:promo" not in cb, f"不应启用已下线的 promo_links：{cb}"
        assert "admin:source_stats" not in cb, f"不应启用已下线的 source_stats：{cb}"
        assert "admin:keyword" not in cb, f"关键词无独立 callback，不应构造伪入口：{cb}"


def test_settings_kb_does_not_contain_other_submenu_callbacks():
    """admin_settings_kb 不应误纳其它二级菜单已收纳的 callback。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    kb = admin_settings_kb(is_super=True)
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    forbidden = {
        # 属于 admin:dashboard 二级页
        "admin:overview",
        "admin:reimbursement_pool",
        "admin:lottery_status",
        # 属于 admin:review_tasks 二级页
        "review:enter",
        "rreview:enter",
        "reimburse:enter",
        "reimburse:queued:0",
        # 属于 admin:operations 二级页
        "admin:lottery",
        "admin:points",
    }
    leaked = forbidden & callbacks
    assert not leaked, f"admin_settings_kb 不应含其它二级菜单的 callback：{leaked}"


# ============ handler 字符串契约 + 权限装饰器 ============


def test_admin_settings_handler_present_in_source():
    """admin_panel.py 必须含 admin:settings 字面量与 cb_admin_settings。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:settings"' in src
    assert "cb_admin_settings" in src


def test_admin_settings_handler_uses_admin_required():
    """cb_admin_settings 装饰器为 @admin_required（基础入口面向所有 admin）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    idx = src.find("async def cb_admin_settings(")
    assert idx > 0, "找不到 cb_admin_settings 定义"
    window = src[max(0, idx - 300):idx]
    assert "@admin_required" in window, (
        "cb_admin_settings 应使用 @admin_required；当前窗口：\n" + window
    )
    # 防御：不应错配为 @super_admin_required
    assert "@super_admin_required" not in window, (
        "cb_admin_settings 不应是 @super_admin_required（普通管理员也需访问基础配置）"
    )


# ============ 旧 callback 字面量仍存在 ============


def test_legacy_settings_callback_literals_still_exist():
    """旧 7 个配置 callback 字面量必须仍在代码中（handler 未删 / kb 仍引用）。

    分布：
        admin:subreq             → subreq_admin.py + admin_settings_kb
        admin:publish_templates  → publish_templates.py + admin_settings_kb
        menu:channel             → admin_panel.py + admin_settings_kb
        admin:report_settings    → report_settings.py + admin_settings_kb
        menu:system              → admin_panel.py + admin_settings_kb
        system:reimburse_pool    → admin_panel.py + admin_settings_kb
        system:reimburse_toggle  → admin_panel.py + admin_settings_kb
    """
    import bot.handlers.subreq_admin as sa
    import bot.handlers.publish_templates as pt
    import bot.handlers.report_settings as rs
    import bot.handlers.admin_panel as ap
    import bot.keyboards.admin_kb as akb
    import inspect

    assert '"admin:subreq"' in inspect.getsource(sa)
    assert '"admin:publish_templates"' in inspect.getsource(pt)
    assert '"admin:report_settings"' in inspect.getsource(rs)
    ap_src = inspect.getsource(ap)
    assert '"menu:channel"' in ap_src
    assert '"menu:system"' in ap_src
    assert '"system:reimburse_pool"' in ap_src
    assert '"system:reimburse_toggle"' in ap_src

    # admin_kb 中必须保留全部 7 个字面量
    kb_src = inspect.getsource(akb)
    for cb in (
        '"admin:subreq"',
        '"admin:publish_templates"',
        '"menu:channel"',
        '"admin:report_settings"',
        '"menu:system"',
        '"system:reimburse_pool"',
        '"system:reimburse_toggle"',
    ):
        assert cb in kb_src, f"admin_kb 缺少 {cb} 字面量"


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_in_MIGRATIONS_list():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}


# ============ 不修改业务 handler ============


def test_settings_target_handlers_still_importable():
    """配置类 handler 模块仍可正常 import；router 仍存在。"""
    from bot.handlers.subreq_admin import router as r1
    from bot.handlers.publish_templates import router as r2
    from bot.handlers.report_settings import router as r3
    from bot.handlers.admin_panel import router as r4
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None


def test_promo_links_source_stats_routers_still_not_registered():
    """spec：promo_links / source_stats 已下线，本任务不重新启用其 router 注册。"""
    import bot.routers as routers_mod
    import inspect
    src = inspect.getsource(routers_mod)
    assert "promo_links_router" not in src
    assert "source_stats_router" not in src
