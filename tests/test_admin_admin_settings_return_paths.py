"""Sprint UX-1 第五批：子页面返回路径优化（admin:admin_settings 子页）契约测试。

范围：覆盖「🛡 管理员设置」(admin:admin_settings) 下的管理员管理子菜单：
    - 👥 管理员管理 menu:admin  keyboard: admin_menu_kb

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §7 Sprint UX-1）：
    超管在管理员设置内查看 / 调整管理员后，应回到二级页 admin:admin_settings
    继续做下一项（如查看审计日志），而不是被甩回主菜单。
    返回按钮 callback 从 menu:main 调整为 admin:admin_settings。

刻意保留：
    dashboard:audit（审计日志）同时可从「📈 数据分析」(dashboard:enter) 进入，
    其返回路径本批暂不调整，单独评估，以避免影响旧数据分析路径体验。

本文件是 UX-1 第五批改动的「集中契约」：
    1. admin_menu_kb 返回按钮 callback_data == "admin:admin_settings"
    2. admin_menu_kb 仍含 3 个核心入口（admin:add / admin:remove / admin:list）
    3. admin_menu_kb 不再含 menu:main
    4. admin_admin_settings_kb 自身仍含 menu:admin / dashboard:audit / menu:main 兜底
    5. dashboard:audit 字面量未删（本批不动其返回路径）
    6. 5 个核心 callback 字面量在 handler / kb 源码中未删
    7. 不新增数据库迁移
    8. 不修改管理员业务 handler（router / 装饰器 / 字面量都未动）
    9. 权限装饰器保持：menu:admin handler 仍是 @super_admin_required

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


# ============ 1. admin_menu_kb 返回按钮指向 admin:admin_settings ============


def test_admin_menu_kb_return_button_goes_to_admin_admin_settings():
    from bot.keyboards.admin_kb import admin_menu_kb
    kb = admin_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1, (
        f"admin_menu_kb 应有恰好 1 个返回按钮，实际：{[b.text for b in backs]}"
    )
    assert backs[0].callback_data == "admin:admin_settings", (
        f"管理员管理主面板返回按钮 callback 应为 admin:admin_settings，"
        f"实际：{backs[0].callback_data}"
    )
    assert "管理员设置" in backs[0].text, (
        f"返回按钮文案应含「管理员设置」，实际：{backs[0].text}"
    )


def test_admin_menu_kb_no_longer_returns_to_menu_main():
    """UX-1 第五批：admin_menu_kb 不再直接含 menu:main 返回。"""
    from bot.keyboards.admin_kb import admin_menu_kb
    callbacks = _all_callbacks(admin_menu_kb())
    assert "menu:main" not in callbacks, (
        "admin_menu_kb 不应再含 menu:main 返回（UX-1 已下沉到 admin:admin_settings）"
    )


# ============ 2. admin_menu_kb 仍含三个核心入口 ============


def test_admin_menu_kb_keeps_core_entries():
    """管理员管理子菜单的核心入口（添加 / 移除 / 列表）保持。"""
    from bot.keyboards.admin_kb import admin_menu_kb
    callbacks = _all_callbacks(admin_menu_kb())
    assert "admin:add" in callbacks
    assert "admin:remove" in callbacks
    assert "admin:list" in callbacks


# ============ 3. admin_admin_settings_kb 自身仍是聚合二级页 ============


def test_admin_admin_settings_kb_keeps_all_entries():
    """UX-1 第五批不改 admin_admin_settings_kb 自身：仍含
    menu:admin + dashboard:audit + menu:main 兜底。"""
    from bot.keyboards.admin_kb import admin_admin_settings_kb
    callbacks = set(_all_callbacks(admin_admin_settings_kb()))
    assert "menu:admin" in callbacks
    assert "dashboard:audit" in callbacks
    # admin:admin_settings 自己回主菜单仍走 menu:main（兜底）
    assert "menu:main" in callbacks


# ============ 4. dashboard:audit 返回路径本批不动（仅断言字面量未删） ============


def test_dashboard_audit_callback_literal_still_in_kb():
    """dashboard:audit 字面量仍在 admin_kb 源码中。

    本批刻意不调整 dashboard:audit 返回路径——它同时可从 dashboard:enter
    （📈 数据分析）进入，返回 dashboard:enter 仍合理，单独评估。
    """
    import inspect
    import bot.keyboards.admin_kb as akb
    src = inspect.getsource(akb)
    assert '"dashboard:audit"' in src


def test_dashboard_audit_back_kb_unchanged():
    """dashboard_audit_back_kb 自身的返回路径本批不动。

    它含「返回看板 → dashboard:enter」+「主菜单 → menu:main」两个按钮，
    UX-1 第五批不修改。
    """
    from bot.keyboards.admin_kb import dashboard_audit_back_kb
    callbacks = _all_callbacks(dashboard_audit_back_kb())
    assert "dashboard:enter" in callbacks, (
        "dashboard_audit_back_kb 应保留「返回看板 → dashboard:enter」"
    )
    assert "menu:main" in callbacks, (
        "dashboard_audit_back_kb 应保留「主菜单 → menu:main」快捷出口"
    )


# ============ 5. 旧 callback 字面量未删 ============


def test_legacy_callbacks_still_in_handler_and_kb():
    """5 个核心 callback 字面量在 handler / kb 源码中仍存在。"""
    import inspect
    import bot.handlers.admin_panel as ap
    import bot.keyboards.admin_kb as akb

    ap_src = inspect.getsource(ap)
    for lit in (
        '"menu:admin"',
        '"admin:admin_settings"',
        '"admin:add"',
        '"admin:remove"',
        '"admin:list"',
    ):
        assert lit in ap_src, (
            f"admin_panel.py 缺少 {lit}（UX-1 不应改 callback 含义）"
        )

    kb_src = inspect.getsource(akb)
    for lit in (
        '"menu:admin"',
        '"admin:admin_settings"',
        '"admin:add"',
        '"admin:remove"',
        '"admin:list"',
    ):
        assert lit in kb_src, f"admin_kb.py 缺少 {lit}"


# ============ 6. 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged():
    """UX-1 第五批不新增 schema 变更：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    """UX-1 第五批不新增 Migration：MIGRATIONS 仍为空 list。"""
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []


# ============ 7. 不修改业务 handler / 装饰器 ============


def test_admin_panel_router_still_importable():
    """admin_panel.py router 仍可正常 import；UX-1 第五批不动 handler 业务逻辑。"""
    from bot.handlers.admin_panel import router
    assert router is not None


def test_menu_admin_handler_uses_super_admin_required():
    """menu:admin handler 仍使用 @super_admin_required（权限装饰器未变）。"""
    import bot.handlers.admin_panel as ap
    import inspect
    src = inspect.getsource(ap)
    # 寻找 F.data == "menu:admin" 周围窗口的装饰器
    idx = src.find('F.data == "menu:admin"')
    assert idx > 0, "找不到 menu:admin handler 声明"
    # 装饰器组通常紧邻 @router.callback_query 之前
    # 取该 callback_query 装饰器前 300 字符窗口
    window_start = max(0, idx - 600)
    window = src[window_start:idx + 200]
    assert "@super_admin_required" in window, (
        "menu:admin handler 应使用 @super_admin_required；"
        f"当前窗口未找到该装饰器：\n{window[-400:]}"
    )


def test_admin_add_remove_list_handlers_use_super_admin_required():
    """admin:add / admin:remove / admin:list 三个 handler 仍使用 @super_admin_required。

    本批不动权限边界——管理员管理仍是超管专属。
    """
    import bot.handlers.admin_panel as ap
    import inspect
    src = inspect.getsource(ap)
    # 每个 callback 字符串都应在 super_admin_required 上下文中出现
    for cb in ("admin:add", "admin:remove", "admin:list"):
        idx = src.find(f'F.data == "{cb}"')
        assert idx > 0, f"找不到 {cb} handler 声明"
        window_start = max(0, idx - 600)
        window = src[window_start:idx + 200]
        assert "@super_admin_required" in window, (
            f"{cb} handler 应使用 @super_admin_required；"
            f"window 末尾：\n{window[-400:]}"
        )


# ============ 8. 不影响旧消息 inline button ============


def test_menu_main_handler_still_present():
    """menu:main handler 仍在 admin_panel.py 中——旧 inline button 中的
    menu:main 仍能命中（admin_menu_kb 历史消息里残留的按钮可正常工作）。"""
    import bot.handlers.admin_panel as ap
    import inspect
    src = inspect.getsource(ap)
    assert 'F.data == "menu:main"' in src or 'F.data=="menu:main"' in src, (
        "admin_panel.py 应仍含 menu:main handler 注册"
    )


# ============ 9. 不破坏深层子页返回（admin_remove_kb） ============


def test_admin_remove_kb_still_returns_to_menu_admin():
    """admin_remove_kb（移除管理员选择列表）的返回按钮指向 menu:admin，本批不动。

    这是深层子页应有的"返回上一级（管理员管理主面板）"行为。
    """
    from bot.keyboards.admin_kb import admin_remove_kb
    # 构造空 admins 列表，仅含返回按钮的最小结构
    kb = admin_remove_kb([])
    callbacks = _all_callbacks(kb)
    assert "menu:admin" in callbacks, (
        "admin_remove_kb 应保留「返回 → menu:admin」（深层返回上一级，本批不动）"
    )
