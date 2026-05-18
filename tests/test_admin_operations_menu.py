"""管理员后台「🎲 活动运营」二级菜单分组单元测试。

测试范围：
    1. 主菜单超管可见 admin:operations 入口
    2. 主菜单非超管不可见 admin:operations 入口（保持原有权限边界）
    3. 主菜单不再直接含 admin:points / admin:lottery（已下沉）
    4. admin_operations_kb 含两个运营入口（admin:lottery / admin:points）+ menu:main
    5. admin_operations_kb 不含已下线的 promo_links / source_stats 入口
    6. admin_operations_kb 不含 reimbursement_pool / lottery_status（属于数据看板）
       与 reimburse:enter / reimburse:queued（属于审核处理）
    7. handler 源码含 admin:operations 字面量与 cb_admin_operations
    8. cb_admin_operations 装饰器为 @super_admin_required（与子入口权限一致）
    9. 旧 admin:lottery / admin:points 字面量仍存在于代码中（handler 未删）
    10. 不新增数据库迁移
    11. 不修改抽奖 / 积分 service 或 handler 业务逻辑

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:operations 替代两个一级 super-only 按钮 ============


def test_main_menu_kb_super_sees_admin_operations():
    """超管主菜单必须含 admin:operations 入口（含「活动运营」文案）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:operations":
                found = True
                assert "活动运营" in btn.text
    assert found, "超管主菜单缺少 admin:operations 入口"


def test_main_menu_kb_non_super_does_not_see_admin_operations():
    """非超管主菜单不应含 admin:operations（两个子入口都仅超管可用）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=False)
    callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "admin:operations" not in callbacks, (
        "非超管不应看到 admin:operations 入口（保持原有权限边界）"
    )


def test_main_menu_kb_no_longer_contains_points_or_lottery():
    """主菜单不应再直接含 admin:points / admin:lottery（已下沉到 admin:operations）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    forbidden = {"admin:points", "admin:lottery"}
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
        leaked = forbidden & callbacks
        assert not leaked, (
            f"主菜单 (is_super={is_super}) 不应直接含 {leaked}，"
            f"它们已被收纳至 admin:operations 二级页"
        )


# ============ admin_operations_kb 结构 ============


def test_operations_kb_contains_lottery_and_points():
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "admin:lottery" in callbacks
    assert "admin:points" in callbacks


def test_operations_kb_back_button_is_menu_main():
    """返回按钮复用既有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "menu:main"
    assert "返回后台" in last_row[0].text


def test_operations_kb_button_texts():
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    by_callback = {
        b.callback_data: b.text for row in kb.inline_keyboard for b in row
    }
    assert "抽奖管理" in by_callback["admin:lottery"]
    assert "积分管理" in by_callback["admin:points"]


def test_operations_kb_exactly_three_rows():
    """精确三行：抽奖 / 积分 / 返回，不应有多余项。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    assert len(kb.inline_keyboard) == 3


def test_operations_kb_does_not_contain_downed_promo_or_source():
    """admin_operations_kb 不应含已下线的 promo_links / source_stats 入口。

    promo_links / source_stats 在 Phase 4 已下线，router 未注册；本菜单不重新启用。
    """
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
    callbacks = [b.callback_data or "" for row in kb.inline_keyboard for b in row]
    for cb in callbacks:
        assert "admin:promo" not in cb, f"不应启用已下线的 promo_links：{cb}"
        assert "admin:source_stats" not in cb, f"不应启用已下线的 source_stats：{cb}"


def test_operations_kb_does_not_contain_dashboard_or_review_tasks_callbacks():
    """admin_operations_kb 不应误纳数据看板 / 审核处理类 callback。"""
    from bot.keyboards.admin_kb import admin_operations_kb
    kb = admin_operations_kb()
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
    }
    leaked = forbidden & callbacks
    assert not leaked, f"admin_operations_kb 不应含其它二级菜单的 callback：{leaked}"


# ============ handler 字符串契约 + 权限装饰器 ============


def test_admin_operations_handler_present_in_source():
    """admin_panel.py 必须含 admin:operations 字面量与 cb_admin_operations。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:operations"' in src
    assert "cb_admin_operations" in src


def test_admin_operations_handler_uses_super_admin_required():
    """cb_admin_operations 必须用 @super_admin_required 装饰（与子入口权限一致）。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    # 定位 cb_admin_operations 函数定义前的装饰器块
    idx = src.find("async def cb_admin_operations(")
    assert idx > 0, "找不到 cb_admin_operations 定义"
    # 装饰器在函数定义前一段窗口内
    window = src[max(0, idx - 300):idx]
    assert "@super_admin_required" in window, (
        "cb_admin_operations 应使用 @super_admin_required；当前窗口：\n" + window
    )


def test_legacy_operations_callback_literals_still_exist():
    """旧的活动运营 callback 字面量仍在代码中（handler 未删除）。

    admin:lottery → admin_lottery.py 处理；admin:points → admin_points.py 处理。
    admin_operations_kb 也必须保留这两个字面量。
    """
    import bot.handlers.admin_lottery as al
    import bot.handlers.admin_points as ap
    import bot.keyboards.admin_kb as akb
    import inspect

    lottery_src = inspect.getsource(al)
    points_src = inspect.getsource(ap)
    kb_src = inspect.getsource(akb)

    assert '"admin:lottery"' in lottery_src
    assert '"admin:points"' in points_src
    assert '"admin:lottery"' in kb_src
    assert '"admin:points"' in kb_src


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_in_MIGRATIONS_list():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []


# ============ 不修改业务 handler ============


def test_operations_target_handlers_still_importable():
    """admin_lottery / admin_points handler 模块仍可正常 import；router 仍存在。"""
    from bot.handlers.admin_lottery import router as r1
    from bot.handlers.admin_points import router as r2
    assert r1 is not None
    assert r2 is not None


def test_promo_links_source_stats_routers_not_registered():
    """spec：promo_links / source_stats 已下线，本任务不重新启用其 router 注册。"""
    import bot.routers as routers_mod
    import inspect
    src = inspect.getsource(routers_mod)
    assert "promo_links_router" not in src, (
        "promo_links router 已下线，spec 要求不重新启用"
    )
    assert "source_stats_router" not in src, (
        "source_stats router 已下线，spec 要求不重新启用"
    )
