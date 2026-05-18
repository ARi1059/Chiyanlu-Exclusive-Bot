"""用户「📜 搜索历史」增强版单元测试。

测试范围：
    1. SearchHistoryItem dataclass
    2. render_search_history：标题 / 序号 / 关键词 / 结果数 / 时间 / 引导文案
    3. None 字段显示 N/A，不崩溃
    4. 空列表显示固定空状态文案 EMPTY_TEXT
    5. get_user_search_history_detailed：
       - 只读 event_type='search'，不返回 'group_search'
       - 重复关键词大小写不敏感去重，保留最新一条
       - payload.raw 优先；缺时回退 tokens 拼接
       - result_count 缺失 / 非整数 → None
       - 表缺失 → 返回空 list 不抛错
       - limit 生效
    6. 关键 callback_data 契约：
       user:search_history / user:search_history:refresh / 现有 pick / 不含 :clear

不连接真实 Telegram；仅使用 :memory: SQLite。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone as dt_timezone

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.services.search_history import (
    EMPTY_TEXT,
    SearchHistoryItem,
    get_user_search_history_detailed,
    render_search_history,
)


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


async def _setup_user_events_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT,
            payload TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


_LOCAL_TZ = pytz_timezone(os.environ.get("TIMEZONE", "Asia/Shanghai"))


def _patch_get_db(mod, db: aiosqlite.Connection) -> None:
    async def _fake():
        class _W:
            def __init__(self, r):
                self._r = r
            def __getattr__(self, n):
                return getattr(self._r, n)
            async def close(self):
                pass
        return _W(db)
    mod.get_db = _fake


# ============ dataclass ============


def test_item_defaults_source_private():
    item = SearchHistoryItem(query="x", result_count=None, searched_at=None)
    assert item.source == "private"


def test_item_full_construction():
    item = SearchHistoryItem(
        query="高颜值", result_count=12,
        searched_at="2026-05-18 06:30:00",
        source="private",
    )
    assert item.query == "高颜值"
    assert item.result_count == 12


# ============ render_search_history ============


def test_render_empty_returns_placeholder():
    text = render_search_history([])
    assert text == EMPTY_TEXT
    assert "你还没有搜索记录" in text


def test_render_contains_header_and_guide_lines():
    items = [SearchHistoryItem(
        query="高颜值", result_count=12, searched_at=None,
    )]
    text = render_search_history(items)
    assert "📜 搜索历史" in text
    assert "（1 条）" in text
    assert "最近搜索：" in text
    assert "点击下方关键词可再次搜索" in text


def test_render_single_item_full_fields():
    fav_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 14, 20, 0))
    fav_utc = fav_local.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    items = [SearchHistoryItem(
        query="高颜值", result_count=12, searched_at=fav_utc,
    )]
    text = render_search_history(items, generated_at=fav_local, now_local=fav_local)
    assert "1. 高颜值" in text
    assert "结果：12 个" in text
    assert "时间：今天 14:20" in text
    assert "更新时间：" in text


def test_render_result_count_none_shows_na():
    items = [SearchHistoryItem(
        query="x", result_count=None, searched_at=None,
    )]
    text = render_search_history(items)
    assert "结果：N/A 个" in text


def test_render_searched_at_none_shows_na():
    items = [SearchHistoryItem(
        query="x", result_count=0, searched_at=None,
    )]
    text = render_search_history(items)
    assert "时间：N/A" in text


def test_render_multiple_items_numbered():
    items = [
        SearchHistoryItem(query=f"关键词{i}", result_count=i, searched_at=None)
        for i in range(1, 4)
    ]
    text = render_search_history(items)
    assert "1. 关键词1" in text
    assert "2. 关键词2" in text
    assert "3. 关键词3" in text
    assert "（3 条）" in text


def test_render_is_pure_function():
    items = [SearchHistoryItem(
        query="x", result_count=0, searched_at=None,
    )]
    fixed = _LOCAL_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
    assert render_search_history(items, generated_at=fixed) == \
        render_search_history(items, generated_at=fixed)


# ============ get_user_search_history_detailed ============


def test_query_returns_empty_for_no_data():
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(999, limit=10)
            assert items == []
        finally:
            await db.close()
    _run(go())


def test_query_missing_table_returns_empty():
    """user_events 表不存在 → 返回空 list，不抛错。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert items == []
        finally:
            await db.close()
    _run(go())


def test_query_excludes_group_search():
    """event_type='group_search' 不应被纳入（spec 本阶段不纳入）。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.executescript(
                """
                INSERT INTO user_events (user_id, event_type, payload, created_at) VALUES
                    (100, 'search',       '{"raw":"a","result_count":2}', '2026-05-18 01:00:00'),
                    (100, 'group_search', '{"query":"b","result_count":3}', '2026-05-18 02:00:00'),
                    (100, 'search',       '{"raw":"c","result_count":1}', '2026-05-18 03:00:00');
                """
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(100, limit=10)
            queries = [it.query for it in items]
            assert "a" in queries
            assert "c" in queries
            assert "b" not in queries  # group_search 排除
        finally:
            await db.close()
    _run(go())


def test_query_dedup_case_insensitive_keeps_latest():
    """同一关键词（大小写不敏感）应只保留 id DESC 顺序最新一条。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.executescript(
                """
                INSERT INTO user_events (user_id, event_type, payload, created_at) VALUES
                    (1, 'search', '{"raw":"AbC","result_count":7}', '2026-05-18 01:00:00'),
                    (1, 'search', '{"raw":"abc","result_count":99}', '2026-05-18 02:00:00');
                """
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert len(items) == 1
            # 最新一条是后插入的 id 大者（"abc"），result_count=99
            assert items[0].query == "abc"
            assert items[0].result_count == 99
        finally:
            await db.close()
    _run(go())


def test_query_payload_raw_preferred_over_tokens():
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.execute(
                "INSERT INTO user_events (user_id, event_type, payload) VALUES "
                "(1, 'search', '{\"raw\":\"high level\",\"tokens\":[\"foo\",\"bar\"]}')"
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert len(items) == 1
            assert items[0].query == "high level"
        finally:
            await db.close()
    _run(go())


def test_query_tokens_fallback_when_raw_missing():
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.execute(
                "INSERT INTO user_events (user_id, event_type, payload) VALUES "
                "(1, 'search', '{\"tokens\":[\"foo\",\"bar\"]}')"
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert len(items) == 1
            assert items[0].query == "foo bar"
        finally:
            await db.close()
    _run(go())


def test_query_skips_payload_without_query():
    """payload 既无 raw 也无 tokens → 跳过。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.executescript(
                """
                INSERT INTO user_events (user_id, event_type, payload) VALUES
                    (1, 'search', '{"result_count":5}'),
                    (1, 'search', '{"raw":"abc","result_count":2}');
                """
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert len(items) == 1
            assert items[0].query == "abc"
        finally:
            await db.close()
    _run(go())


def test_query_result_count_missing_is_none():
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.execute(
                "INSERT INTO user_events (user_id, event_type, payload) VALUES "
                "(1, 'search', '{\"raw\":\"x\"}')"
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert items[0].result_count is None
        finally:
            await db.close()
    _run(go())


def test_query_result_count_non_int_is_none():
    """payload.result_count 不是整数 → 解析为 None。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.execute(
                "INSERT INTO user_events (user_id, event_type, payload) VALUES "
                "(1, 'search', '{\"raw\":\"x\",\"result_count\":\"oops\"}')"
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert items[0].result_count is None
        finally:
            await db.close()
    _run(go())


def test_query_invalid_json_payload_skipped():
    """payload 非合法 JSON → 跳过该条。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.executescript(
                """
                INSERT INTO user_events (user_id, event_type, payload) VALUES
                    (1, 'search', 'not-a-json'),
                    (1, 'search', '{"raw":"x"}');
                """
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            assert len(items) == 1
            assert items[0].query == "x"
        finally:
            await db.close()
    _run(go())


def test_query_limit_respected_and_zero_returns_empty():
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            for i in range(15):
                await db.execute(
                    "INSERT INTO user_events (user_id, event_type, payload) "
                    f"VALUES (1, 'search', '{{\"raw\":\"q{i}\"}}')"
                )
            await db.commit()
            _patch_get_db(sh, db)
            items5 = await sh.get_user_search_history_detailed(1, limit=5)
            assert len(items5) == 5
            items0 = await sh.get_user_search_history_detailed(1, limit=0)
            assert items0 == []
            items_neg = await sh.get_user_search_history_detailed(1, limit=-1)
            assert items_neg == []
        finally:
            await db.close()
    _run(go())


def test_query_orders_by_id_desc():
    """最新的搜索（id 更大）排在前。"""
    async def go():
        from bot.services import search_history as sh
        db = await _fresh_db()
        try:
            await _setup_user_events_table(db)
            await db.executescript(
                """
                INSERT INTO user_events (user_id, event_type, payload) VALUES
                    (1, 'search', '{"raw":"first"}'),
                    (1, 'search', '{"raw":"second"}'),
                    (1, 'search', '{"raw":"third"}');
                """
            )
            await db.commit()
            _patch_get_db(sh, db)
            items = await sh.get_user_search_history_detailed(1, limit=10)
            queries = [it.query for it in items]
            assert queries == ["third", "second", "first"]
        finally:
            await db.close()
    _run(go())


# ============ callback / keyboard 契约 ============


def test_user_search_history_callback_present_in_main_menu_kb():
    """主菜单已有 user:search_history 入口（不新增重复入口）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:search_history" in callbacks


def test_search_history_rich_kb_has_pick_refresh_and_back():
    """rich kb：N 条历史按钮 + 刷新 + 主菜单。"""
    from bot.keyboards.user_kb import search_history_rich_kb
    kb = search_history_rich_kb(["高颜值", "1000P", "南门"])
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:search_history:pick:0" in callbacks
    assert "user:search_history:pick:1" in callbacks
    assert "user:search_history:pick:2" in callbacks
    assert "user:search_history:refresh" in callbacks
    assert "user:main" in callbacks


def test_search_history_rich_kb_button_text_uses_raw_query():
    """前 30 字符内的关键词不截断；长关键词应安全截断。"""
    from bot.keyboards.user_kb import search_history_rich_kb
    kb = search_history_rich_kb(["短词", "x" * 50])
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "短词" in texts
    long_btn = next(t for t in texts if t.startswith("x"))
    assert long_btn.endswith("…")


def test_search_history_empty_kb_has_guide_callbacks():
    """空状态引导：条件筛选 / 热门推荐 / 主菜单。"""
    from bot.keyboards.user_kb import search_history_empty_kb
    kb = search_history_empty_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:filter" in callbacks
    assert "user:hot" in callbacks
    assert "user:main" in callbacks


def test_no_clear_callback_anywhere():
    """spec：本阶段绝不引入清空 callback。"""
    import bot.handlers.user_history as uh
    import bot.keyboards.user_kb as ukb
    import bot.services.search_history as sh
    import inspect
    for mod in (uh, ukb, sh):
        src = inspect.getsource(mod)
        assert "user:search_history:clear" not in src, f"{mod.__name__} 出现禁止的 clear callback"


def test_existing_pick_handler_still_present():
    """点选回放 callback 必须仍然存在（cb_search_history_pick 未被破坏）。"""
    import bot.handlers.user_history as uh
    import inspect
    src = inspect.getsource(uh)
    assert '"user:search_history:pick:"' in src
    assert "cb_search_history_pick" in src


def test_search_history_refresh_callback_present_in_handler_source():
    import bot.handlers.user_history as uh
    import inspect
    src = inspect.getsource(uh)
    assert '"user:search_history:refresh"' in src
    assert "cb_search_history_refresh" in src


def test_main_menu_button_visible_for_non_super_admin_unchanged():
    """user:search_history 按钮主菜单中存在（与 admin 权限无关）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "user:search_history":
                found = True
                assert "搜索历史" in btn.text
    assert found
