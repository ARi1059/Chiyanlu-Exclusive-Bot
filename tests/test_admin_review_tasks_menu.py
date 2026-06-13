"""管理员后台「✅ 审核处理」二级菜单分组单元测试。

测试范围：
    1. 主菜单含 admin:review_tasks 入口（替代原四个审核 callback 一级按钮）
    2. 主菜单不再直接含 review:enter / rreview:enter / reimburse:enter /
       reimburse:queued:0
    3. admin:review_tasks 在普通管理员和超管都可见
    4. admin_review_tasks_kb 含老师资料审核 + 仅超管含评价审核 / 报销审核 /
       报销名单（条件）+ menu:main 返回
    5. badge count 显示正确（pending 显示 / 零不显示）
    6. handler 源码含 admin:review_tasks 字面量与 cb_admin_review_tasks
    7. 旧四个 callback 字面量仍存在于代码中（旧 handler 未删除）
    8. 不新增数据库迁移（baseline 数量 + MIGRATIONS 空保持不变）

不连接真实 Telegram；不访问生产 data/bot.db；纯静态 / keyboard 断言。
"""

from __future__ import annotations


# ============ 主菜单：admin:review_tasks 替代四个审核一级按钮 ============


def test_main_menu_kb_contains_admin_review_tasks():
    """主菜单必须新增 admin:review_tasks 入口（含『审核处理』文案）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data == "admin:review_tasks":
                    found = True
                    assert "审核处理" in btn.text
        assert found, f"主菜单 (is_super={is_super}) 缺少 admin:review_tasks 入口"


def test_main_menu_kb_no_longer_contains_four_review_callbacks():
    """主菜单不应再直接含原四个审核 callback。"""
    from bot.keyboards.admin_kb import main_menu_kb
    forbidden = {
        "review:enter",
        "rreview:enter",
        "reimburse:enter",
        "reimburse:queued:0",
    }
    for is_super in (True, False):
        for queued in (0, 5):  # 含 / 不含 queued
            kb = main_menu_kb(
                is_super=is_super,
                pending_count=0,
                pending_review_count=0,
                pending_reimburse_count=0,
                queued_reimburse_count=queued,
            )
            callbacks = {b.callback_data for row in kb.inline_keyboard for b in row}
            leaked = forbidden & callbacks
            assert not leaked, (
                f"主菜单 (is_super={is_super}, queued={queued}) 不应直接含 {leaked}，"
                f"它们已被收纳至 admin:review_tasks 二级页"
            )


# ============ 主菜单 badge 计数 ============


def test_main_menu_review_badge_no_count_when_zero():
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(is_super=True)
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:review_tasks":
                assert "(" not in btn.text, f"无 pending 时不应显示括号：{btn.text}"


def test_main_menu_review_badge_aggregates_for_super():
    """超管：badge = pending_edit + pending_review + pending_reimburse。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(
        is_super=True,
        pending_count=3,
        pending_review_count=2,
        pending_reimburse_count=1,
        queued_reimburse_count=99,  # queued 不应进入主菜单 badge
    )
    btn = next(
        b for row in kb.inline_keyboard for b in row
        if b.callback_data == "admin:review_tasks"
    )
    # 3 + 2 + 1 = 6，queued 99 不计入
    assert "(6)" in btn.text


def test_main_menu_review_badge_only_pending_count_for_non_super():
    """非超管：badge 只看老师资料 pending_count。"""
    from bot.keyboards.admin_kb import main_menu_kb
    kb = main_menu_kb(
        is_super=False,
        pending_count=3,
        pending_review_count=99,
        pending_reimburse_count=99,
        queued_reimburse_count=99,
    )
    btn = next(
        b for row in kb.inline_keyboard for b in row
        if b.callback_data == "admin:review_tasks"
    )
    assert "(3)" in btn.text


# ============ admin_review_tasks_kb 结构 ============


def test_review_tasks_kb_non_super_only_edits_and_back():
    """非超管只能看到老师资料审核 + 返回（评价/报销审核 是超管权限）。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(is_super=False)
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callbacks == ["review:enter", "menu:main"]


def test_review_tasks_kb_super_no_queued_when_zero():
    """超管 + queued=0：含三个审核入口 + 返回，不含报销名单。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        is_super=True,
        queued_reimburse_count=0,
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callbacks == [
        "review:enter",
        "rreview:enter",
        "reimburse:enter",
        "menu:main",
    ]


def test_review_tasks_kb_super_with_queued():
    """超管 + queued>0：含四个审核入口 + 返回。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        is_super=True,
        queued_reimburse_count=5,
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert callbacks == [
        "review:enter",
        "rreview:enter",
        "reimburse:enter",
        "reimburse:queued:0",
        "menu:main",
    ]


def test_review_tasks_kb_badges():
    """各入口 badge 显示正确：>0 显示，=0 不显示。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(
        is_super=True,
        pending_edit_count=3,
        pending_review_count=0,
        pending_reimburse_count=2,
        queued_reimburse_count=4,
    )
    texts_by_callback = {
        b.callback_data: b.text for row in kb.inline_keyboard for b in row
    }
    assert "(3)" in texts_by_callback["review:enter"]
    assert "老师资料审核" in texts_by_callback["review:enter"]
    # 评价审核 count=0：不应有 (0)
    assert "(" not in texts_by_callback["rreview:enter"]
    assert "评价审核" in texts_by_callback["rreview:enter"]
    assert "(2)" in texts_by_callback["reimburse:enter"]
    assert "报销审核" in texts_by_callback["reimburse:enter"]
    assert "(4)" in texts_by_callback["reimburse:queued:0"]
    assert "报销名单" in texts_by_callback["reimburse:queued:0"]


def test_review_tasks_kb_back_button_is_menu_main():
    """返回按钮复用既有 menu:main，不引入新返回 callback。"""
    from bot.keyboards.admin_kb import admin_review_tasks_kb
    kb = admin_review_tasks_kb(is_super=True)
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == "menu:main"
    assert "返回后台" in last_row[0].text


# ============ handler 字符串契约 ============


def test_admin_review_tasks_handler_present_in_source():
    """admin_panel.py 必须含 admin:review_tasks 的 handler 字面量。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:review_tasks"' in src
    assert "cb_admin_review_tasks" in src


def test_legacy_review_callback_literals_still_exist():
    """旧四个 callback 字面量必须仍在代码中（handler 未删除 / kb 仍引用）。

    review:enter      → admin_review.py + admin_review_tasks_kb
    rreview:enter     → rreview_admin.py + admin_review_tasks_kb
    reimburse:enter   → admin_reimburse.py + admin_review_tasks_kb
    reimburse:queued: → admin_reimburse.py + admin_review_tasks_kb
    """
    import bot.handlers.admin_review as ar
    import bot.handlers.rreview_admin as rra
    import bot.handlers.admin_reimburse as ari
    import bot.keyboards.admin_kb as akb
    import inspect

    review_src = inspect.getsource(ar)
    rreview_src = inspect.getsource(rra)
    reimb_src = inspect.getsource(ari)
    kb_src = inspect.getsource(akb)

    assert '"review:enter"' in review_src
    assert '"rreview:enter"' in rreview_src
    assert '"reimburse:enter"' in reimb_src
    # reimburse:queued 在 admin_reimburse 中以 startswith 形式注册
    assert "reimburse:queued" in reimb_src

    # admin_review_tasks_kb 也必须包含这四个字面量
    for cb in (
        '"review:enter"', '"rreview:enter"',
        '"reimburse:enter"', '"reimburse:queued:0"',
    ):
        assert cb in kb_src, f"admin_kb 缺少 {cb} 字面量"


# ============ 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged_count():
    """spec：本阶段不新增数据库迁移。baseline 数量应保持 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_no_new_migration_in_MIGRATIONS_list():
    from bot.database import MIGRATIONS
    from _migration_baseline import EXPECTED_MIGRATION_VERSIONS
    assert {m.version for m in MIGRATIONS} == EXPECTED_MIGRATION_VERSIONS


# ============ 不修改审核业务 handler ============


def test_review_handlers_still_importable():
    """三个审核 handler 模块仍可正常 import；router 仍存在。"""
    from bot.handlers.admin_review import router as r1
    from bot.handlers.rreview_admin import router as r2
    from bot.handlers.admin_reimburse import router as r3
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
