"""Sprint UX-1 第四批：子页面返回路径优化（admin:teachers 子页）契约测试。

范围：覆盖「👩‍🏫 老师管理」(admin:teachers) 下的四个主面板：
    - 👥 老师列表与启停 menu:teacher        keyboard: teacher_menu_kb
    - 🔥 热门推荐       admin:hot_manage    keyboard: hot_manage_menu_kb
    - 📅 今日发布状态   admin:today_status  keyboard: admin_today_status_kb
    - 🏷 用户画像       admin:user_tags     keyboard: user_tags_menu_kb

UX 目标（参见 docs/UX-EFFICIENCY-PLAN.md §7 Sprint UX-1）：
    管理员在老师管理内逐项处理后，应回到二级页 admin:teachers 继续做下一项，
    而不是被甩回主菜单。返回按钮 callback 从 menu:main 调整为 admin:teachers。

本文件是 UX-1 第四批改动的「集中契约」：
    1. 四个主面板返回按钮 callback_data == "admin:teachers"
    2. 四个主面板都不再含 menu:main
    3. 四个主面板仍保留各自核心管理入口
    4. admin_teachers_kb 仍含 4 个入口 + menu:main 兜底
    5. menu:teacher / admin:hot_manage / admin:today_status / admin:user_tags /
       admin:teachers 五个 callback 字面量未删
    6. 不新增数据库迁移
    7. 不修改老师管理业务 handler（router 仍可 import）
    8. 不把 review:enter 纳入 admin_teachers_kb（防止误把审核功能混入老师管理）
    9. 不新增不存在的「老师标签」伪入口（admin:teacher_tags / teacher:tags 等）

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


# ============ 1. 四个主面板返回按钮 callback_data == "admin:teachers" ============


def test_teacher_menu_kb_return_button_goes_to_admin_teachers():
    from bot.keyboards.admin_kb import teacher_menu_kb
    kb = teacher_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1, (
        f"teacher_menu_kb 应有恰好 1 个返回按钮，实际：{[b.text for b in backs]}"
    )
    assert backs[0].callback_data == "admin:teachers"
    assert "老师管理" in backs[0].text


def test_hot_manage_menu_kb_return_button_goes_to_admin_teachers():
    from bot.keyboards.admin_kb import hot_manage_menu_kb
    kb = hot_manage_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:teachers"
    assert "老师管理" in backs[0].text


def test_admin_today_status_kb_return_button_goes_to_admin_teachers():
    from bot.keyboards.admin_kb import admin_today_status_kb
    kb = admin_today_status_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:teachers"
    assert "老师管理" in backs[0].text


def test_user_tags_menu_kb_return_button_goes_to_admin_teachers():
    from bot.keyboards.admin_kb import user_tags_menu_kb
    kb = user_tags_menu_kb()
    backs = _return_buttons(kb)
    assert len(backs) == 1
    assert backs[0].callback_data == "admin:teachers"
    assert "老师管理" in backs[0].text


def test_four_main_panels_no_longer_return_to_menu_main():
    """UX-1 第四批：四个老师管理主面板都不再直接返回 menu:main。"""
    from bot.keyboards.admin_kb import (
        teacher_menu_kb,
        hot_manage_menu_kb,
        admin_today_status_kb,
        user_tags_menu_kb,
    )
    for kb_fn in (
        teacher_menu_kb, hot_manage_menu_kb,
        admin_today_status_kb, user_tags_menu_kb,
    ):
        callbacks = _all_callbacks(kb_fn())
        assert "menu:main" not in callbacks, (
            f"{kb_fn.__name__} 不应再含 menu:main 返回"
            f"（UX-1 已下沉到 admin:teachers）"
        )


# ============ 2. 四个主面板仍保留核心管理入口 ============


def test_teacher_menu_kb_keeps_core_entries():
    """老师管理子菜单的核心入口（档案管理 / 停用 / 启用 / 列表）保持。"""
    from bot.keyboards.admin_kb import teacher_menu_kb
    callbacks = _all_callbacks(teacher_menu_kb())
    assert "tprofile:menu" in callbacks
    assert "teacher:delete" in callbacks
    assert "teacher:enable" in callbacks
    assert "teacher:list" in callbacks


def test_hot_manage_menu_kb_keeps_core_entries():
    """热门推荐管理的核心入口（添加 / 权重 / 取消 / 重算）保持。"""
    from bot.keyboards.admin_kb import hot_manage_menu_kb
    callbacks = _all_callbacks(hot_manage_menu_kb())
    assert "admin:hot:add" in callbacks
    assert "admin:hot:weight" in callbacks
    assert "admin:hot:remove" in callbacks
    assert "admin:hot:recalc" in callbacks


def test_admin_today_status_kb_keeps_refresh_entry():
    """今日发布状态页保留 admin:today_status 刷新入口。"""
    from bot.keyboards.admin_kb import admin_today_status_kb
    callbacks = _all_callbacks(admin_today_status_kb())
    assert "admin:today_status" in callbacks


def test_user_tags_menu_kb_keeps_core_entries():
    """用户画像看板的核心入口（查询 / 刷新）保持。"""
    from bot.keyboards.admin_kb import user_tags_menu_kb
    callbacks = _all_callbacks(user_tags_menu_kb())
    assert "admin:user_tags:query" in callbacks
    assert "admin:user_tags" in callbacks  # 刷新按钮


# ============ 3. admin_teachers_kb 仍是聚合二级页 ============


def test_admin_teachers_kb_keeps_all_entries_and_menu_main():
    """UX-1 第四批不改 admin_teachers_kb 自身：仍含 4 个入口 + menu:main 兜底。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    callbacks = set(_all_callbacks(admin_teachers_kb()))
    assert "menu:teacher" in callbacks
    assert "admin:hot_manage" in callbacks
    assert "admin:today_status" in callbacks
    assert "admin:user_tags" in callbacks
    # admin:teachers 自己回主菜单仍走 menu:main（兜底）
    assert "menu:main" in callbacks


def test_admin_teachers_kb_does_not_contain_review_enter():
    """admin_teachers_kb 不应纳入 review:enter（老师资料审核属于 admin:review_tasks 二级页）。"""
    from bot.keyboards.admin_kb import admin_teachers_kb
    callbacks = set(_all_callbacks(admin_teachers_kb()))
    assert "review:enter" not in callbacks, (
        "review:enter 属于审核处理二级页，不应误入老师管理"
    )


def test_admin_teachers_kb_does_not_contain_fake_teacher_tags_entries():
    """admin_teachers_kb 不应构造不存在的「老师标签」伪入口。

    项目仅有 admin:user_tags（用户画像），没有独立的「老师标签」callback。
    """
    from bot.keyboards.admin_kb import admin_teachers_kb
    callbacks = set(_all_callbacks(admin_teachers_kb()))
    for fake in ("admin:teacher_tags", "teacher:tags", "admin:tag_teachers"):
        assert fake not in callbacks, (
            f"不应新增不存在的伪入口：{fake}"
        )


# ============ 4. 旧 callback 字面量未删 ============


def test_legacy_callbacks_still_in_handlers_and_kb():
    """5 个老师管理 callback 字面量在对应 handler / kb 源码中仍存在。

    （UX-1 不改 callback 含义，旧 inline button 仍能命中各自 handler。）
    """
    import inspect
    import bot.handlers.admin_panel as ap
    import bot.handlers.hot_teachers as ht
    import bot.handlers.teacher_daily_status as tds
    import bot.handlers.user_tags as ut
    import bot.keyboards.admin_kb as akb

    ap_src = inspect.getsource(ap)
    assert '"menu:teacher"' in ap_src
    assert '"admin:teachers"' in ap_src
    assert '"admin:hot_manage"' in inspect.getsource(ht)
    assert '"admin:today_status"' in inspect.getsource(tds)
    assert '"admin:user_tags"' in inspect.getsource(ut)

    # admin_kb 中的 5 个字面量
    kb_src = inspect.getsource(akb)
    for lit in (
        '"menu:teacher"',
        '"admin:hot_manage"',
        '"admin:today_status"',
        '"admin:user_tags"',
        '"admin:teachers"',
    ):
        assert lit in kb_src, f"admin_kb 缺少 {lit}（UX-1 不应改 callback 含义）"


# ============ 5. 不新增数据库迁移 ============


def test_schema_migrations_baseline_unchanged():
    """UX-1 第四批不新增 schema 变更：baseline 仍 9 条。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    """UX-1 第四批不新增 Migration：MIGRATIONS 仍为空 list。"""
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []


# ============ 6. 不修改业务 handler ============


def test_teachers_handlers_still_importable():
    """四个老师管理入口的 handler 都仍可正常 import；router 非空。"""
    from bot.handlers.admin_panel import router as r1
    from bot.handlers.hot_teachers import router as r2
    from bot.handlers.teacher_daily_status import router as r3
    from bot.handlers.user_tags import router as r4
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None


def test_user_tags_query_result_shortcut_to_main_menu_preserved():
    """深层快捷出口未受影响：user_tags_query_result_kb 仍含「🏠 主菜单」快捷键。

    UX-1 第四批只动主面板「返回」按钮，深层子页快捷出口保持不变。
    """
    from bot.keyboards.admin_kb import user_tags_query_result_kb
    callbacks = _all_callbacks(user_tags_query_result_kb())
    assert "menu:main" in callbacks, (
        "user_tags_query_result_kb 应保留「🏠 主菜单」快捷出口"
    )
