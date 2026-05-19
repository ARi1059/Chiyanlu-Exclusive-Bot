"""Sprint UX-3 第二批：老师详情页「返回来源」契约测试。

背景：
    用户从搜索结果 / 收藏 / 最近看过 / 热门 / 今日 / 条件筛选 等入口进入老师
    详情后，旧实现只能"返回主菜单"，无法回到来源列表。UX-3 第二批引入
    teacher:view:<id>:from:<source> 新格式 callback，详情页根据 source 渲染
    对应"返回 X"按钮。

设计：
    helper（bot.keyboards.user_kb）：
        TEACHER_VIEW_SOURCES                  source 白名单（含 main / hot /
                                              today / filter / search / history /
                                              recent / favorites / similar）
        format_teacher_view_callback(id, src) 拼 callback；src="main" 与旧格式一致
        parse_teacher_view_callback(data)     兼容旧/新格式；非法 src 回退 "main"

    teacher_detail_kb 增加 source 参数（默认 "main"），按 source 渲染返回按钮：
        hot → user:hot；today → user:today；filter → user:filter；
        search → user:search；history → user:search_history；
        recent → user:recent；favorites → user:favorites；
        main / similar / 未知 → user:main

    接入的低风险生产点（仅这些列表会产生 from:<source> callback）：
        my_favorites_kb              → "favorites"
        recent_views_rich_kb         → "recent"
        favorites_rich_kb            → "favorites"
        teacher_detail_list_kb       → 按 caller 传入的 source 参数
        user_search._send_list       → "search"
        hot_teachers.cb_user_hot     → "hot"
        user_panel.cb_today          → "today"
        user_filter._filter_result_kb → "filter"

    不接入：similar 子页、start_router deep link 落地、群卡片 v2 兜底、
    review_cancelled_kb（返回详情自身）、review_list_pagination_kb（同上）、
    user_recommend / user_history reminders（不在 spec 白名单）。

不连接真实 Telegram；不访问生产 DB；纯静态 / keyboard 断言。
"""

from __future__ import annotations

import inspect

import pytest


# ============ helpers ============


def _cbs(kb) -> list:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def _back_button(kb):
    """从 teacher_detail_kb 输出中提取返回按钮（最后一行第一个按钮）。"""
    return kb.inline_keyboard[-1][0]


def _fake_teacher(teacher_id: int = 100) -> dict:
    """构造最小老师 dict，覆盖 teacher_detail_kb 所需字段。"""
    return {
        "user_id": teacher_id,
        "display_name": "测试老师",
        "region": "测试地区",
        "price": "100",
        "button_url": "",       # 无 URL → 不渲染联系按钮
        "button_text": "",
    }


# ============================================================
# 1. format_teacher_view_callback / parse_teacher_view_callback
# ============================================================


def test_format_default_source_main_matches_legacy_format():
    """source="main"（默认）→ 与旧格式 teacher:view:<id> 逐字一致。"""
    from bot.keyboards.user_kb import format_teacher_view_callback
    assert format_teacher_view_callback(100) == "teacher:view:100"
    assert format_teacher_view_callback(100, "main") == "teacher:view:100"


def test_format_known_sources_emit_from_suffix():
    """白名单非 main source → "teacher:view:<id>:from:<source>" 形式。"""
    from bot.keyboards.user_kb import format_teacher_view_callback
    assert format_teacher_view_callback(100, "hot") == "teacher:view:100:from:hot"
    assert format_teacher_view_callback(100, "today") == "teacher:view:100:from:today"
    assert format_teacher_view_callback(100, "filter") == "teacher:view:100:from:filter"
    assert format_teacher_view_callback(100, "search") == "teacher:view:100:from:search"
    assert format_teacher_view_callback(100, "history") == "teacher:view:100:from:history"
    assert format_teacher_view_callback(100, "recent") == "teacher:view:100:from:recent"
    assert format_teacher_view_callback(100, "favorites") == "teacher:view:100:from:favorites"
    assert format_teacher_view_callback(100, "similar") == "teacher:view:100:from:similar"


def test_format_unknown_source_falls_back_to_legacy():
    """source 不在白名单 → 退化为旧格式（不允许任意字符串注入 callback）。"""
    from bot.keyboards.user_kb import format_teacher_view_callback
    assert format_teacher_view_callback(100, "evil") == "teacher:view:100"
    assert format_teacher_view_callback(100, "") == "teacher:view:100"
    assert format_teacher_view_callback(100, "MAIN") == "teacher:view:100"  # 大小写敏感


def test_parse_legacy_callback_returns_main_source():
    """旧格式 teacher:view:<id> → (id, "main")。"""
    from bot.keyboards.user_kb import parse_teacher_view_callback
    tid, src = parse_teacher_view_callback("teacher:view:100")
    assert tid == 100
    assert src == "main"


def test_parse_new_callback_returns_source():
    """新格式 teacher:view:<id>:from:<source> → (id, source)。"""
    from bot.keyboards.user_kb import parse_teacher_view_callback
    for src in ("hot", "today", "filter", "search",
                "history", "recent", "favorites", "similar"):
        tid, parsed = parse_teacher_view_callback(f"teacher:view:200:from:{src}")
        assert tid == 200
        assert parsed == src


def test_parse_unknown_source_falls_back_to_main():
    """非法 source → 回退 "main"（不抛错，详情页正常渲染）。"""
    from bot.keyboards.user_kb import parse_teacher_view_callback
    tid, src = parse_teacher_view_callback("teacher:view:300:from:evil")
    assert tid == 300
    assert src == "main"


def test_parse_non_view_callback_raises_value_error():
    """非 teacher:view: 前缀 → ValueError（保留与旧 cb_teacher_view 的失败语义）。"""
    from bot.keyboards.user_kb import parse_teacher_view_callback
    with pytest.raises(ValueError):
        parse_teacher_view_callback("user:main")
    with pytest.raises(ValueError):
        parse_teacher_view_callback("teacher:reviews:100")


def test_parse_invalid_teacher_id_raises_value_error():
    """teacher_id 解析失败 → ValueError（cb_teacher_view 兜底回答"无效操作"）。"""
    from bot.keyboards.user_kb import parse_teacher_view_callback
    with pytest.raises(ValueError):
        parse_teacher_view_callback("teacher:view:abc")
    with pytest.raises(ValueError):
        parse_teacher_view_callback("teacher:view:abc:from:hot")


# ============================================================
# 2. teacher_detail_kb 按 source 渲染返回按钮
# ============================================================


@pytest.mark.parametrize("source,expected_cb,expected_text", [
    ("main",       "user:main",            "主菜单"),
    ("hot",        "user:hot",             "热门推荐"),
    ("today",      "user:today",           "今日可约"),
    ("filter",     "user:filter",          "条件筛选"),
    ("search",     "user:search",          "搜索"),
    ("history",    "user:search_history",  "搜索历史"),
    ("recent",     "user:recent",          "最近看过"),
    ("favorites",  "user:favorites",       "我的收藏"),
    ("similar",    "user:main",            "主菜单"),  # similar 回退到主菜单
])
def test_teacher_detail_kb_back_button_by_source(source, expected_cb, expected_text):
    from bot.keyboards.user_kb import teacher_detail_kb
    kb = teacher_detail_kb(
        _fake_teacher(),
        is_favorited=False,
        notify_enabled=True,
        review_count=0,
        source=source,
    )
    back = _back_button(kb)
    assert back.callback_data == expected_cb, (
        f"source={source} 返回按钮 callback 应为 {expected_cb}，实际 {back.callback_data}"
    )
    assert expected_text in back.text, (
        f"source={source} 返回按钮文案应含「{expected_text}」，实际 {back.text}"
    )


def test_teacher_detail_kb_unknown_source_falls_back_to_main():
    """未知 source 回退 user:main。"""
    from bot.keyboards.user_kb import teacher_detail_kb
    kb = teacher_detail_kb(
        _fake_teacher(), is_favorited=False, source="evil",
    )
    back = _back_button(kb)
    assert back.callback_data == "user:main"


def test_teacher_detail_kb_default_source_is_main():
    """teacher_detail_kb 不传 source 时默认 main（向后兼容）。"""
    from bot.keyboards.user_kb import teacher_detail_kb
    kb = teacher_detail_kb(_fake_teacher(), is_favorited=False)
    back = _back_button(kb)
    assert back.callback_data == "user:main"


def test_teacher_detail_kb_non_back_buttons_callbacks_unchanged():
    """收藏 / 写评价 / 相似推荐等非返回按钮 callback 与 source 无关。"""
    from bot.keyboards.user_kb import teacher_detail_kb
    for src in ("main", "hot", "favorites", "recent"):
        kb = teacher_detail_kb(
            _fake_teacher(teacher_id=42),
            is_favorited=False,
            notify_enabled=True,
            review_count=5,
            source=src,
        )
        cbs = _cbs(kb)
        assert "teacher:toggle_fav:42" in cbs
        assert "teacher:remind:42" in cbs
        assert "teacher:reviews:42" in cbs
        assert "teacher:similar:42" in cbs
        assert "review:start:42" in cbs


# ============================================================
# 3. teacher_detail_list_kb 按 source 拼 callback
# ============================================================


def test_teacher_detail_list_kb_default_source_emits_legacy_callback():
    """teacher_detail_list_kb 默认 source="main" → 旧格式 callback。"""
    from bot.keyboards.user_kb import teacher_detail_list_kb
    kb = teacher_detail_list_kb([_fake_teacher(11), _fake_teacher(22)])
    cbs = _cbs(kb)
    assert "teacher:view:11" in cbs
    assert "teacher:view:22" in cbs
    # 不应出现 :from:
    assert not any(":from:" in c for c in cbs)


def test_teacher_detail_list_kb_with_source_search():
    """teacher_detail_list_kb source="search" → 每个 callback 带 from:search。"""
    from bot.keyboards.user_kb import teacher_detail_list_kb
    kb = teacher_detail_list_kb(
        [_fake_teacher(11), _fake_teacher(22)],
        source="search",
    )
    cbs = _cbs(kb)
    assert "teacher:view:11:from:search" in cbs
    assert "teacher:view:22:from:search" in cbs


def test_teacher_detail_list_kb_with_source_hot():
    from bot.keyboards.user_kb import teacher_detail_list_kb
    kb = teacher_detail_list_kb([_fake_teacher(11)], source="hot")
    assert "teacher:view:11:from:hot" in _cbs(kb)


# ============================================================
# 4. 各 rich/list kb 产生的 callback 带正确 source
# ============================================================


def test_recent_views_rich_kb_emits_from_recent():
    """最近看过列表每个 teacher callback 带 from:recent。"""
    from bot.keyboards.user_kb import recent_views_rich_kb
    items = [{"teacher_id": 31, "display_name": "A"}, {"teacher_id": 32, "display_name": "B"}]
    kb = recent_views_rich_kb(items)
    cbs = _cbs(kb)
    assert "teacher:view:31:from:recent" in cbs
    assert "teacher:view:32:from:recent" in cbs


def test_favorites_rich_kb_emits_from_favorites():
    """我的收藏增强版列表 callback 带 from:favorites（两处：行标题 + 查看详情）。"""
    from bot.keyboards.user_kb import favorites_rich_kb
    items = [{"teacher_id": 41, "display_name": "T1"}]
    kb = favorites_rich_kb(items)
    cbs = _cbs(kb)
    # 行标题与 👀 查看详情 两处都应带 from:favorites
    assert cbs.count("teacher:view:41:from:favorites") == 2


def test_my_favorites_kb_emits_from_favorites():
    """旧版 my_favorites_kb 老师按钮也带 from:favorites。"""
    from bot.keyboards.user_kb import my_favorites_kb
    favs = [{"user_id": 51, "display_name": "X", "region": "R", "price": "100"}]
    kb = my_favorites_kb(favs)
    assert "teacher:view:51:from:favorites" in _cbs(kb)


# ============================================================
# 5. handler 接入点静态契约
# ============================================================


def test_user_search_send_list_uses_search_source():
    """user_search._send_list 应用 source="search" 调用 teacher_detail_list_kb。"""
    import bot.handlers.user_search as us
    src = inspect.getsource(us)
    idx = src.find("async def _send_list(")
    assert idx > 0
    body = src[idx:idx + 2000]
    assert 'source="search"' in body, (
        "user_search._send_list 应传 source=\"search\""
    )


def test_hot_teachers_uses_hot_source():
    """hot_teachers 的列表渲染应传 source="hot"。"""
    import bot.handlers.hot_teachers as ht
    src = inspect.getsource(ht)
    # 静态扫描：必须出现 source="hot"
    assert 'source="hot"' in src, "hot_teachers 应传 source=\"hot\""


def test_user_panel_cb_today_uses_today_source():
    """user_panel.cb_today 应用 format_teacher_view_callback(..., "today")。"""
    import bot.handlers.user_panel as up
    src = inspect.getsource(up)
    idx = src.find("async def cb_today(")
    assert idx > 0
    body = src[idx:idx + 3000]
    assert 'format_teacher_view_callback' in body
    assert '"today"' in body, "cb_today 列表应附带 source=\"today\""


def test_user_filter_result_kb_uses_filter_source():
    """user_filter._filter_result_kb 应用 source="filter"。"""
    import bot.handlers.user_filter as uf
    src = inspect.getsource(uf)
    idx = src.find("def _filter_result_kb(")
    assert idx > 0
    body = src[idx:idx + 1500]
    assert 'format_teacher_view_callback' in body
    assert '"filter"' in body


# ============================================================
# 6. cb_teacher_view 解析新格式
# ============================================================


def test_cb_teacher_view_uses_parse_teacher_view_callback():
    """cb_teacher_view handler 应调用 parse_teacher_view_callback 解析。"""
    import bot.handlers.teacher_detail as td
    src = inspect.getsource(td)
    assert "parse_teacher_view_callback" in src, (
        "cb_teacher_view 应使用 parse_teacher_view_callback 解析"
    )
    # source 透传给 _render_detail
    assert "source=source" in src or "source = source" in src


def test_teacher_detail_payload_accepts_source():
    """_build_detail_payload / _render_detail / send_teacher_detail_message
    都应支持 source 参数（向后兼容默认 main）。"""
    import bot.handlers.teacher_detail as td
    src = inspect.getsource(td)
    # 所有三个函数定义都应含 source = "main" 默认值
    for name in (
        "_build_detail_payload",
        "_render_detail",
        "send_teacher_detail_message",
    ):
        idx = src.find(f"async def {name}(")
        assert idx > 0, f"找不到 {name} 定义"
        body = src[idx:idx + 800]
        assert 'source: str = "main"' in body, (
            f"{name} 应有 source: str = \"main\" 参数"
        )


# ============================================================
# 7. 业务回退 / 兼容性 / 不该改的不被改
# ============================================================


def test_teacher_view_callbacks_fit_in_telegram_limit():
    """生成的 callback 字符串都应在 Telegram 64 字节限制内。

    teacher:view:<id> 最长 14 + len(id)；带 :from:<source> 时 +14 字符。
    用 9999999999（10 位）+ favorites（最长 source）测最坏情况。
    """
    from bot.keyboards.user_kb import format_teacher_view_callback, TEACHER_VIEW_SOURCES
    for src in TEACHER_VIEW_SOURCES:
        cb = format_teacher_view_callback(9_999_999_999, src)
        assert len(cb.encode("utf-8")) <= 64, (
            f"callback {cb!r} 超过 Telegram 64 字节限制（{len(cb.encode('utf-8'))} 字节）"
        )


def test_similar_path_keeps_legacy_callback_form():
    """teacher:similar 路径产生的"返回老师详情" callback 仍使用旧格式（spec 允许）。"""
    import bot.handlers.teacher_detail as td
    src = inspect.getsource(td)
    # _similar_back_kb 函数体仍用 f"teacher:view:{teacher_id}" 形式
    assert 'f"teacher:view:{teacher_id}"' in src, (
        "_similar_back_kb 应仍使用旧 teacher:view:<id> 格式"
    )


def test_start_router_deep_link_landing_unchanged():
    """start_router._teacher_detail_landing_kb 的 callback 仍是旧格式
    （spec 明确不动 deep link 路径）。"""
    import bot.handlers.start_router as sr
    src = inspect.getsource(sr)
    # _teacher_detail_landing_kb 内的 callback 拼接形式
    idx = src.find("def _teacher_detail_landing_kb(")
    assert idx > 0
    body = src[idx:idx + 600]
    assert 'f"teacher:view:{teacher_id}"' in body, (
        "deep link 落地按钮应仍为旧格式"
    )
    assert ":from:" not in body


def test_review_cancelled_kb_keeps_legacy_form():
    """review_cancelled_kb 的"返回老师详情页" callback 仍是旧格式
    （这是返回详情自身，不是来源列表）。"""
    from bot.keyboards.user_kb import review_cancelled_kb
    kb = review_cancelled_kb(teacher_id=123)
    cbs = _cbs(kb)
    assert "teacher:view:123" in cbs
    assert "teacher:view:123:from:" not in " ".join(cbs)


# ============================================================
# 8. schema / 业务保护
# ============================================================


def test_schema_migrations_baseline_unchanged():
    """UX-3 第二批不动 schema。"""
    from bot.database import SCHEMA_MIGRATIONS_BASELINE
    assert len(SCHEMA_MIGRATIONS_BASELINE) == 9


def test_migrations_list_still_empty():
    from bot.database import MIGRATIONS
    assert MIGRATIONS == []


def test_relevant_services_still_importable():
    """三个用户侧 service 仍可正常 import + 关键函数 callable。"""
    from bot.services.recent_views import (
        get_recent_teacher_views, render_recent_views,
    )
    from bot.services.user_favorites import (
        get_user_favorites, render_user_favorites,
    )
    from bot.services.search_history import (
        get_user_search_history_detailed, render_search_history,
    )
    for fn in (
        get_recent_teacher_views, render_recent_views,
        get_user_favorites, render_user_favorites,
        get_user_search_history_detailed, render_search_history,
    ):
        assert callable(fn)


def test_teacher_detail_router_still_importable():
    """teacher_detail / user_search / user_filter / user_panel / hot_teachers /
    start_router router 均仍可正常 import（业务 handler 未被破坏）。"""
    from bot.handlers.teacher_detail import router as r1
    from bot.handlers.user_search import router as r2
    from bot.handlers.user_filter import router as r3
    from bot.handlers.user_panel import router as r4
    from bot.handlers.hot_teachers import router as r5
    from bot.handlers.start_router import router as r6
    for r in (r1, r2, r3, r4, r5, r6):
        assert r is not None


def test_teacher_view_callback_handler_uses_startswith():
    """cb_teacher_view 仍用 startswith("teacher:view:") 注册，捕获两种格式。"""
    import bot.handlers.teacher_detail as td
    src = inspect.getsource(td)
    assert 'F.data.startswith("teacher:view:")' in src
