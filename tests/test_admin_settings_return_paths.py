"""Sprint UX-1 第三批：子页面返回路径优化（admin:settings 子页）契约测试。

范围：覆盖「⚙️ 系统配置」(admin:settings) 下的四个主面板：
    - 📢 频道 / 群组设置   menu:channel           keyboard: channel_menu_kb
    - ⚙️ 系统设置          menu:system            keyboard: system_menu_kb
    - 🧩 发布模板          admin:publish_templates  keyboard: publish_templates_menu_kb
    - 📅 报表设置          admin:report_settings  keyboard: report_settings._settings_kb

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §7 Sprint UX-1）：
    管理员在系统配置内逐个看完后，应回到二级页 admin:settings 继续做下一项，
    而不是被甩回主菜单。返回按钮 callback 从 menu:main 调整为 admin:settings。

本文件是 UX-1 第三批改动的「集中契约」：
    1. 四个主面板返回按钮 callback_data == "admin:settings"
    2. 四个主面板都不再含 menu:main
    3. 四个主面板仍保留各自核心管理入口
    4. admin_settings_kb 仍含 5 个基础入口 + 2 个 super-only 入口 + menu:main 兜底
    5. menu:channel / menu:system / admin:publish_templates / admin:report_settings /
       admin:settings 五个 callback 字面量未删
    6. 不新增数据库迁移
    7. 不修改配置业务 handler（router 仍 importable）
    8. promo_links / source_stats 仍未注册

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ helpers ============


def _return_buttons(kb) -> list:
    """提取 keyboard 中所有"返回"类按钮（文案含 ⬅️ / 🔙 / "返回"）。"""
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if "⬅️" in btn.text or "🔙" in btn.text or "返回" in btn.text:
                out.append(btn)
    return out


def _all_callbacks(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _report_main_kb():
    """加载 report_settings._settings_kb（handler 内私有，但 Python 可访问）。

    给两个固定 bool（false/false）让函数构造主面板；本批断言只关心返回按钮。
    """
    from bot.handlers.report_settings import _settings_kb
    return _settings_kb(daily_enabled=False, weekly_enabled=False)


# ============ 1. 四个主面板返回按钮 callback_data == "admin:settings" ============


def test_channel_menu_kb_return_button_goes_to_admin_settings():
    from bot.keyboards.admin_kb import channel_menu_kb
    kb = channel_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1, (
        f"channel_menu_kb 应有恰好 1 个返回按钮，实际：{[b.text for b in backs]}"
    )
    assert backs[0].callback_data == "admin:settings"
    assert "系统配置" in backs[0].text


def test_system_menu_kb_return_button_goes_to_admin_settings():
    from bot.keyboards.admin_kb import system_menu_kb
    kb = system_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:settings"
    assert "系统配置" in backs[0].text


def test_publish_templates_menu_kb_return_button_goes_to_admin_settings():
    from bot.keyboards.admin_kb import publish_templates_menu_kb
    kb = publish_templates_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:settings"
    assert "系统配置" in backs[0].text


def test_report_settings_main_kb_return_button_goes_to_admin_settings():
    kb = _report_main_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:settings"
    assert "系统配置" in backs[0].text


def test_four_main_panels_no_longer_return_to_menu_main():
    """UX-1 第三批：四个配置主面板都不再直接返回 menu:main。"""
    from bot.keyboards.admin_kb import (
        channel_menu_kb, system_menu_kb, publish_templates_menu_kb,
    )
    panels = [
        ("channel_menu_kb", channel_menu_kb()),
        ("system_menu_kb", system_menu_kb()),
        ("publish_templates_menu_kb", publish_templates_menu_kb()),
        ("report_settings._settings_kb", _report_main_kb()),
    ]
    for name, kb in panels:
        callbacks = _all_callbacks(kb)
        assert "menu:main" not in callbacks, (
            f"{name} 不应再含 menu:main 返回（UX-1 已下沉到 admin:settings）"
        )


# ============ 2. 四个主面板仍保留核心管理入口 ============


def test_channel_menu_kb_keeps_core_entries():
    from bot.keyboards.admin_kb import channel_menu_kb
    callbacks = _all_callbacks(channel_menu_kb())
    assert "channel:set_publish" in callbacks
    assert "channel:set_archive" in callbacks
    assert "channel:set_response" in callbacks
    assert "channel:view" in callbacks


def test_system_menu_kb_keeps_core_entries():
    from bot.keyboards.admin_kb import system_menu_kb
    callbacks = _all_callbacks(system_menu_kb())
    # 抽样确认主要入口仍在
    assert "system:status" in callbacks
    assert "publish:preview" in callbacks
    assert "publish:manual" in callbacks
    assert "system:reminder_time" in callbacks
    assert "system:reminder_toggle" in callbacks
    assert "system:publish_time" in callbacks
    assert "system:cooldown" in callbacks


def test_publish_templates_menu_kb_keeps_core_entries():
    from bot.keyboards.admin_kb import publish_templates_menu_kb
    callbacks = _all_callbacks(publish_templates_menu_kb())
    assert "admin:publish_templates:list" in callbacks
    assert "admin:publish_templates:create" in callbacks
    assert "admin:publish_templates:edit_default" in callbacks
    assert "admin:publish_templates:set_default" in callbacks


def test_report_settings_main_kb_keeps_core_entries():
    callbacks = _all_callbacks(_report_main_kb())
    assert "admin:report:daily_toggle" in callbacks
    assert "admin:report:daily_time" in callbacks
    assert "admin:report:weekly_toggle" in callbacks
    assert "admin:report:weekly_time" in callbacks
    assert "admin:report:weekly_day" in callbacks
    assert "admin:report:chat_id" in callbacks
    assert "admin:report:test_daily" in callbacks
    assert "admin:report:test_weekly" in callbacks


# ============ 3. admin_settings_kb 自身仍为聚合二级页 ============


def test_admin_settings_kb_keeps_all_base_entries_and_menu_main():
    """UX-1 第三批不改 admin_settings_kb 自身：仍含 5 基础入口 + menu:main 兜底。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    for is_super in (True, False):
        callbacks = set(_all_callbacks(admin_settings_kb(is_super=is_super)))
        assert "admin:subreq" in callbacks
        assert "admin:publish_templates" in callbacks
        assert "menu:channel" in callbacks
        assert "admin:report_settings" in callbacks
        assert "menu:system" in callbacks
        # admin:settings 自己回主菜单仍走 menu:main（兜底）
        assert "menu:main" in callbacks


def test_admin_settings_kb_super_only_entries_unchanged():
    """admin_settings_kb 超管专属入口：聚合报销配置入口。

    2026-05 修订：原 system:reimburse_pool / system:reimburse_toggle 两个
    并列入口已删除（与 admin:reimburse_config 聚合页重叠）。callback handler
    保留兼容历史 inline button。"""
    from bot.keyboards.admin_kb import admin_settings_kb
    super_cbs = set(_all_callbacks(admin_settings_kb(is_super=True)))
    normal_cbs = set(_all_callbacks(admin_settings_kb(is_super=False)))
    # 仅聚合入口可见
    assert "admin:reimburse_config" in super_cbs
    assert "admin:reimburse_config" not in normal_cbs
    # 旧并列入口已撤除，两种角色下都不应出现
    assert "system:reimburse_pool" not in super_cbs
    assert "system:reimburse_toggle" not in super_cbs
    assert "system:reimburse_pool" not in normal_cbs
    assert "system:reimburse_toggle" not in normal_cbs


# ============ 4. 旧 callback 字面量未删 ============


def test_legacy_callbacks_still_in_handlers_and_kb():
    """5 个配置入口 callback 字面量在对应 handler / kb 源码中仍存在。

    （UX-1 不改 callback 含义，旧 inline button 仍能命中各自 handler。）
    """
    import inspect
    import bot.handlers.publish_templates as pt
    import bot.handlers.report_settings as rs
    import bot.handlers.admin_panel as panel
    import bot.keyboards.admin_kb as akb

    assert '"admin:publish_templates"' in inspect.getsource(pt)
    assert '"admin:report_settings"' in inspect.getsource(rs)
    panel_src = inspect.getsource(panel)
    assert '"menu:channel"' in panel_src
    assert '"menu:system"' in panel_src
    assert '"admin:settings"' in panel_src
    # admin_kb 中的 5 个字面量
    kb_src = inspect.getsource(akb)
    for lit in (
        '"menu:channel"',
        '"menu:system"',
        '"admin:publish_templates"',
        '"admin:report_settings"',
        '"admin:settings"',
    ):
        assert lit in kb_src, f"admin_kb 缺少 {lit}（UX-1 不应改 callback 含义）"


# ============ 5. 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged():
    """UX-1 第三批不新增 schema 变更：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    """UX-1 第三批不新增 Migration：MIGRATIONS 仍为空 list。"""
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


# ============ 6. 不修改业务 handler ============


def test_config_handlers_still_importable():
    """四个配置入口的 handler / kb 都仍可正常 import；router 非空。"""
    from bot.handlers.publish_templates import router as r1
    from bot.handlers.report_settings import router as r2
    from bot.handlers.admin_panel import router as r3
    from bot.handlers.subreq_admin import router as r4
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None


def test_promo_links_source_stats_routers_still_not_registered():
    """UX-1 不重新启用 Phase 4 已下线的 promo_links / source_stats。"""
    import bot.routers as routers_mod
    import inspect
    src = inspect.getsource(routers_mod)
    assert "promo_links_router" not in src
    assert "source_stats_router" not in src
