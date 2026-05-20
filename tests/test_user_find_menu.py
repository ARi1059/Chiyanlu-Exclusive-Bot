"""Sprint UX-3 第一批：用户侧「🔎 找老师」分组契约测试。

背景：
    用户主菜单 13 个一级按钮里 8 个与找老师强相关，认知密度偏高。本批新增
    一个聚合二级页 user:find，收纳 4 个找老师入口；旧 4 个 callback 在主
    菜单原位完全保留，进入双跑观察期。

设计：
    user_main_menu_kb 新增独占首行 [🔎 找老师 → "user:find"]，其它 13 个旧
    按钮位置完全保留。

    新增 user_find_kb()，含 4 个收纳按钮 + 1 个返回主菜单：
        🔥 热门推荐    → user:hot
        📚 今天能约谁  → user:today
        🔎 按条件找    → user:filter
        📜 搜索历史    → user:search_history
        ⬅️ 返回主菜单  → user:main

    刻意不收纳：⭐ 我的收藏 / 🕘 最近看过 / 🔍 直接搜索 / 🎯 帮我推荐 /
    💝 收藏开课 / 🔔 我的提醒（这些 callback 仍只在主菜单一级位置存在）。

    新增 user_panel.py 内 cb_user_find handler 渲染二级页；不动任何 service。

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect


# ============ helpers ============


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _texts(kb) -> list:
    return [b.text for row in kb.inline_keyboard for b in row]


# ============ 1. 主菜单含「🔎 找老师」入口 + 旧 callback 保留 ============


def test_user_main_menu_contains_find_entry():
    """主菜单必须含 user:find 入口，文案包含「找老师」。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    callbacks = _cbs(kb)
    assert "user:find" in callbacks, "主菜单缺少 user:find 入口"
    btn = next(b for row in kb.inline_keyboard for b in row
               if b.callback_data == "user:find")
    assert "找老师" in btn.text, f"按钮文案应含「找老师」，实际：{btn.text}"


def test_user_main_menu_still_contains_legacy_find_callbacks():
    """UX-3 第一批严格保留旧 4 个找老师 callback（双跑期）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    callbacks = set(_cbs(user_main_menu_kb()))
    for cb in ("user:hot", "user:today", "user:filter", "user:search_history"):
        assert cb in callbacks, (
            f"主菜单应保留旧找老师 callback {cb}（UX-3 第一批不撤旧入口）"
        )


def test_user_main_menu_still_contains_retention_callbacks():
    """主菜单仍含留存类 callback：我的收藏 / 最近看过（spec 明确不收纳）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    callbacks = set(_cbs(user_main_menu_kb()))
    assert "user:favorites" in callbacks, "主菜单不应隐藏我的收藏"
    assert "user:recent" in callbacks, "主菜单不应隐藏最近看过"


def test_user_main_menu_still_contains_direct_search():
    """主菜单仍含 user:search（直接搜索）—— 最直觉入口不应被藏起来。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    callbacks = set(_cbs(user_main_menu_kb()))
    assert "user:search" in callbacks, "主菜单不应隐藏直接搜索入口"


def test_user_main_menu_still_contains_other_legacy_callbacks():
    """主菜单仍含其它一级 callback（推荐 / 收藏开课 / 提醒 / 积分 / 报销 / 写评价）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    callbacks = set(_cbs(user_main_menu_kb()))
    for cb in (
        "user:recommend",
        "user:fav_today",
        "user:reminders",
        "user:points",
        "user:reimburse",
        "user:write_review",
    ):
        assert cb in callbacks, f"主菜单缺少旧一级 callback {cb}"


# ============ 2. user_find_kb 结构 ============


def test_user_find_kb_function_exists():
    """user_find_kb 函数必须存在且可调用。"""
    from bot.keyboards.user_kb import user_find_kb
    assert callable(user_find_kb)
    kb = user_find_kb()
    # 必须是 InlineKeyboardMarkup 实例
    from aiogram.types import InlineKeyboardMarkup
    assert isinstance(kb, InlineKeyboardMarkup)


def test_user_find_kb_contains_four_legacy_entries_plus_back():
    """user_find_kb 必须含 4 个旧 callback + 返回主菜单。"""
    from bot.keyboards.user_kb import user_find_kb
    callbacks = set(_cbs(user_find_kb()))
    # 严格 5 个 callback：4 个收纳 + 返回
    assert "user:hot" in callbacks
    assert "user:today" in callbacks
    assert "user:filter" in callbacks
    assert "user:search_history" in callbacks
    assert "user:main" in callbacks


def test_user_find_kb_does_not_contain_retention_or_other_entries():
    """user_find_kb 不应纳入主菜单留存类 / 其它入口。"""
    from bot.keyboards.user_kb import user_find_kb
    callbacks = set(_cbs(user_find_kb()))
    forbidden = {
        "user:favorites",     # 留存类，spec 明确不收纳
        "user:recent",        # 留存类，spec 明确不收纳
        "user:search",        # 最直觉入口，不应藏入二级
        "user:recommend",     # 与找老师互补，本批不动
        "user:fav_today",     # 与找老师互补，本批不动
        "user:reminders",     # 个人通知类
        "user:points",        # 个人资产
        "user:reimburse",     # 个人资产
        "user:write_review",  # 评价类
    }
    leaked = forbidden & callbacks
    assert not leaked, (
        f"user_find_kb 不应含以下 callback：{leaked}（本批刻意不收纳）"
    )


def test_user_find_kb_exactly_five_callbacks_no_more():
    """user_find_kb 严格 5 个 callback，无多余。"""
    from bot.keyboards.user_kb import user_find_kb
    callbacks = _cbs(user_find_kb())
    assert len(callbacks) == 5, (
        f"user_find_kb 应严格含 5 个 callback（4 收纳 + 返回），实际 {len(callbacks)}"
    )


def test_user_find_kb_back_button_text_and_callback():
    """user_find_kb 返回按钮文案与 callback 验证。"""
    from bot.keyboards.user_kb import user_find_kb
    kb = user_find_kb()
    back_btn = None
    for row in kb.inline_keyboard:
        for b in row:
            if b.callback_data == "user:main":
                back_btn = b
    assert back_btn is not None
    assert "主菜单" in back_btn.text or "返回" in back_btn.text


def test_user_find_kb_button_texts_match_entries():
    """user_find_kb 按钮文案匹配各自含义（防止 callback / 文案错配）。"""
    from bot.keyboards.user_kb import user_find_kb
    kb = user_find_kb()
    by_cb = {b.callback_data: b.text for row in kb.inline_keyboard for b in row}
    assert "热门" in by_cb["user:hot"]
    assert "今天" in by_cb["user:today"] or "今日" in by_cb["user:today"]
    assert "按条件" in by_cb["user:filter"] or "筛选" in by_cb["user:filter"]
    assert "搜索历史" in by_cb["user:search_history"] or "历史" in by_cb["user:search_history"]


# ============ 3. user:find handler 已注册 ============


def test_user_find_handler_present_in_user_panel():
    """user_panel.py 必须含 user:find handler 字面量与 cb_user_find 函数。"""
    import bot.handlers.user_panel as up
    src = inspect.getsource(up)
    assert '"user:find"' in src
    assert "cb_user_find" in src


def test_user_find_handler_uses_user_find_kb():
    """cb_user_find 函数体必须调用 user_find_kb()。"""
    import bot.handlers.user_panel as up
    src = inspect.getsource(up)
    idx = src.find("async def cb_user_find(")
    assert idx > 0, "找不到 cb_user_find 函数定义"
    body = src[idx:idx + 1500]
    assert "user_find_kb()" in body, "cb_user_find 应使用 user_find_kb()"


def test_user_find_handler_does_not_require_admin():
    """cb_user_find 不应使用 @admin_required / @super_admin_required（这是普通用户入口）。"""
    import bot.handlers.user_panel as up
    src = inspect.getsource(up)
    idx = src.find("async def cb_user_find(")
    assert idx > 0
    # 取函数定义前 300 字符（含装饰器组）
    window = src[max(0, idx - 300):idx]
    assert "@admin_required" not in window, (
        "cb_user_find 不应使用 @admin_required（这是普通用户入口）"
    )
    assert "@super_admin_required" not in window, (
        "cb_user_find 不应使用 @super_admin_required（这是普通用户入口）"
    )


# ============ 4. 旧 callback 仍在各自 handler 中 ============


def test_legacy_find_callbacks_still_in_their_handlers():
    """旧 4 个找老师 callback 字面量仍在对应 handler 源码中（含义未变）。

    user:hot               → hot_teachers.cb_user_hot
    user:today             → user_panel.cb_today
    user:filter            → user_filter.cb_filter_home
    user:search_history    → user_history.cb_search_history
    """
    import bot.handlers.hot_teachers as ht
    import bot.handlers.user_panel as up
    import bot.handlers.user_filter as uf
    import bot.handlers.user_history as uh

    assert '"user:hot"' in inspect.getsource(ht)
    assert '"user:today"' in inspect.getsource(up)
    assert '"user:filter"' in inspect.getsource(uf)
    assert '"user:search_history"' in inspect.getsource(uh)


# ============ 5. 不修改 schema / 业务 handler / service ============


def test_schema_migrations_baseline_unchanged():
    """UX-3 第一批不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert {m.version for m in MIGRATIONS} == {"20260520_001_teacher_draft_states"}


def test_user_services_still_importable():
    """三个用户侧 service 仍可正常 import + 关键函数 callable。"""
    from bot.services.recent_views import (
        get_recent_teacher_views,
        render_recent_views,
        EMPTY_TEXT as RECENT_EMPTY,
    )
    from bot.services.user_favorites import (
        get_user_favorites,
        render_user_favorites,
        EMPTY_TEXT as FAV_EMPTY,
    )
    from bot.services.search_history import (
        get_user_search_history_detailed,
        render_search_history,
        EMPTY_TEXT as HIST_EMPTY,
    )
    for fn in (
        get_recent_teacher_views, render_recent_views,
        get_user_favorites, render_user_favorites,
        get_user_search_history_detailed, render_search_history,
    ):
        assert callable(fn)
    # 空状态文案字符串存在（防止被本批意外删除）
    assert isinstance(RECENT_EMPTY, str)
    assert isinstance(FAV_EMPTY, str)
    assert isinstance(HIST_EMPTY, str)


def test_search_and_teacher_detail_handlers_still_importable():
    """搜索 / 老师详情 / keyword / start_router handler 仍可正常 import。

    UX-3 第一批严禁触动这些 handler 业务逻辑。
    """
    from bot.handlers.user_search import router as r1
    from bot.handlers.user_filter import router as r2
    from bot.handlers.user_history import router as r3
    from bot.handlers.teacher_detail import router as r4
    from bot.handlers.keyword import router as r5
    from bot.handlers.start_router import router as r6
    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert r4 is not None
    assert r5 is not None
    assert r6 is not None


def test_user_main_kb_still_has_write_review_at_end():
    """末行布局契约：「📝 写评价」与「🎁 抽奖中心」（UX-6.1 新增）同一行；
    write_review 仍排第一（左侧）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    last_row = kb.inline_keyboard[-1]
    cbs = [b.callback_data for b in last_row]
    assert "user:write_review" in cbs
    # UX-6.1：抽奖中心入口与写评价共享末行
    assert "user:lottery" in cbs
    # write_review 应排在 lottery 之前
    assert cbs.index("user:write_review") < cbs.index("user:lottery")
