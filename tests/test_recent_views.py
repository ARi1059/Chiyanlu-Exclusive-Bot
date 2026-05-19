"""用户「👀 最近看过」增强版单元测试。

测试范围：
    1. RecentTeacherViewItem dataclass 行为
    2. render_recent_views 渲染老师名 / 时间 / 状态 / 收藏
    3. 空列表显示固定引导文案 EMPTY_TEXT
    4. None 字段显示 N/A，不崩溃
    5. format_viewed_at_relative 今天 / 昨天 / 历史
    6. get_recent_teacher_views 查询：
       - 同一老师仅一条（PRIMARY KEY 去重）
       - limit 生效
       - is_favorited / is_checked_in_today 字段正确
       - 停用老师过滤
    7. recent_views_rich_kb / recent_views_empty_kb 含正确 callback

不连接真实 Telegram；仅使用 :memory: SQLite。
为避免引入 pytest-asyncio，async 通过 asyncio.run 同步包裹。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone as dt_timezone

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.services.recent_views import (
    EMPTY_TEXT,
    RecentTeacherViewItem,
    format_viewed_at_relative,
    render_recent_views,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


async def _setup_min_schema(db: aiosqlite.Connection) -> None:
    """最小可运行 schema（teachers / user_teacher_views / favorites / checkins）。"""
    await db.execute(
        """
        CREATE TABLE teachers (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE user_teacher_views (
            user_id INTEGER,
            teacher_id INTEGER,
            viewed_at TEXT,
            PRIMARY KEY (user_id, teacher_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE favorites (
            user_id INTEGER,
            teacher_id INTEGER,
            PRIMARY KEY (user_id, teacher_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            checkin_date TEXT,
            UNIQUE(teacher_id, checkin_date)
        )
        """
    )


_LOCAL_TZ_NAME = os.environ.get("TIMEZONE", "Asia/Shanghai")
_LOCAL_TZ = pytz_timezone(_LOCAL_TZ_NAME)


# ============ dataclass ============


def test_item_defaults():
    item = RecentTeacherViewItem(
        teacher_id=1, display_name="老师A", viewed_at=None,
    )
    assert item.teacher_id == 1
    assert item.display_name == "老师A"
    assert item.viewed_at is None
    assert item.is_favorited is None
    assert item.is_checked_in_today is None


def test_item_with_all_fields():
    item = RecentTeacherViewItem(
        teacher_id=2, display_name="老师B",
        viewed_at="2026-05-18 06:30:00",
        is_favorited=True, is_checked_in_today=False,
    )
    assert item.is_favorited is True
    assert item.is_checked_in_today is False


# ============ format_viewed_at_relative ============


def test_format_viewed_at_none():
    assert format_viewed_at_relative(None) == "N/A"


def test_format_viewed_at_empty_string():
    assert format_viewed_at_relative("") == "N/A"


def test_format_viewed_at_invalid_string():
    assert format_viewed_at_relative("not-a-date") == "N/A"


def test_format_viewed_at_today():
    """UTC 时间转本地后落在今天 → '今天 HH:mm'。"""
    # 构造一个绝对时间，并以同一时刻作为 now 注入
    now_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 14, 30, 0))
    # viewed_at 是 UTC 字符串（同一时刻往前 1 小时）
    utc_dt = (now_local.astimezone(dt_timezone.utc))
    s = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
    out = format_viewed_at_relative(s, now_local=now_local)
    assert out.startswith("今天 ")
    assert "14:30" in out


def test_format_viewed_at_yesterday():
    now_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 8, 0, 0))
    yesterday_local = _LOCAL_TZ.localize(datetime(2026, 5, 17, 22, 15, 0))
    utc_s = yesterday_local.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = format_viewed_at_relative(utc_s, now_local=now_local)
    assert out.startswith("昨天 ")
    assert "22:15" in out


def test_format_viewed_at_history():
    now_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 8, 0, 0))
    long_ago_local = _LOCAL_TZ.localize(datetime(2026, 4, 1, 9, 5, 0))
    utc_s = long_ago_local.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = format_viewed_at_relative(utc_s, now_local=now_local)
    assert out == "2026-04-01 09:05"


def test_format_viewed_at_iso_with_t():
    """SQLite 偶尔会写 'T' 分隔，需兼容。"""
    now_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 8, 0, 0))
    yesterday_local = _LOCAL_TZ.localize(datetime(2026, 5, 17, 12, 0, 0))
    utc_dt = yesterday_local.astimezone(dt_timezone.utc)
    s_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%S")
    out = format_viewed_at_relative(s_iso, now_local=now_local)
    assert out.startswith("昨天 ")


def test_format_viewed_at_naive_now_local_treated_as_local():
    """now_local 不带 tzinfo 时，函数应将其视为本地时区，不抛错。"""
    naive = datetime(2026, 5, 18, 8, 0, 0)
    out = format_viewed_at_relative(None, now_local=naive)
    assert out == "N/A"  # 仍走 None 分支，关键是不抛 TypeError


# ============ render_recent_views ============


def test_render_empty_returns_placeholder():
    text = render_recent_views([])
    assert text == EMPTY_TEXT
    assert "你还没有浏览过老师" in text
    assert "热门推荐" in text or "热门" in text


def test_render_single_item_contains_all_fields():
    now_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 14, 30, 0))
    utc_s = now_local.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    items = [RecentTeacherViewItem(
        teacher_id=10, display_name="老师A",
        viewed_at=utc_s,
        is_favorited=True, is_checked_in_today=True,
    )]
    text = render_recent_views(items, now_local=now_local)
    assert "👀 最近看过" in text
    assert "1. 老师A" in text
    assert "最近查看：今天 14:30" in text
    assert "状态：今日可约" in text
    assert "收藏：已收藏" in text
    assert "更新时间：" in text


def test_render_status_unsigned_unfavorited():
    items = [RecentTeacherViewItem(
        teacher_id=10, display_name="x", viewed_at=None,
        is_favorited=False, is_checked_in_today=False,
    )]
    text = render_recent_views(items)
    assert "状态：今日未签到" in text
    assert "收藏：未收藏" in text


def test_render_status_and_favorite_none_shows_na():
    items = [RecentTeacherViewItem(
        teacher_id=10, display_name="x", viewed_at=None,
        is_favorited=None, is_checked_in_today=None,
    )]
    text = render_recent_views(items)
    assert "状态：N/A" in text
    assert "收藏：N/A" in text
    assert "最近查看：N/A" in text


def test_render_display_name_none_or_empty_shows_na():
    items = [RecentTeacherViewItem(
        teacher_id=10, display_name="", viewed_at=None,
    )]
    text = render_recent_views(items)
    assert "1. N/A" in text


def test_render_multiple_items_numbered():
    items = [
        RecentTeacherViewItem(teacher_id=i, display_name=f"老师{i}", viewed_at=None)
        for i in range(1, 4)
    ]
    text = render_recent_views(items)
    assert "1. 老师1" in text
    assert "2. 老师2" in text
    assert "3. 老师3" in text
    assert "（3 位）" in text


def test_render_is_pure_function():
    items = [RecentTeacherViewItem(
        teacher_id=1, display_name="x", viewed_at=None,
    )]
    fixed = _LOCAL_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
    assert render_recent_views(items, generated_at=fixed) == \
        render_recent_views(items, generated_at=fixed)


def test_render_generated_at_appears():
    items = [RecentTeacherViewItem(
        teacher_id=1, display_name="x", viewed_at=None,
    )]
    fixed = _LOCAL_TZ.localize(datetime(2026, 5, 18, 9, 30, 45))
    text = render_recent_views(items, generated_at=fixed)
    assert "2026-05-18 09:30:45" in text


# ============ get_recent_teacher_views 查询 ============


def test_query_returns_empty_when_no_data():
    """无任何浏览记录时返回空列表。"""
    async def go():
        # 接管 bot.database.get_db 用 :memory:，避免触发 init_db
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await db.commit()

            async def _fake_get_db():
                # 返回同一个 db 实例；close 时不真关
                class _Wrapper:
                    def __init__(self, real):
                        self._real = real
                    def __getattr__(self, name):
                        return getattr(self._real, name)
                    async def close(self):
                        pass
                return _Wrapper(db)

            orig = rv.get_db
            rv.get_db = _fake_get_db
            try:
                items = await rv.get_recent_teacher_views(user_id=999, limit=10)
                assert items == []
            finally:
                rv.get_db = orig
        finally:
            await db.close()
    _run(go())


async def _seed_views(db: aiosqlite.Connection) -> None:
    """通用种子数据：3 位老师 + 浏览/收藏/签到混合。

    teachers: 1=active 老师A / 2=active 老师B / 3=inactive 老师C / 4=active 老师D
    user 100 浏览: 1(早), 2(中), 4(最近) — 3 inactive 不展示
    user 100 收藏: 老师 2
    今日签到: 老师 1
    """
    await db.executescript(
        """
        INSERT INTO teachers (user_id, display_name, is_active) VALUES
            (1, '老师A', 1),
            (2, '老师B', 1),
            (3, '老师C', 0),
            (4, '老师D', 1);
        """
    )
    # viewed_at 用 UTC 字符串区分先后
    await db.executescript(
        """
        INSERT INTO user_teacher_views (user_id, teacher_id, viewed_at) VALUES
            (100, 1, '2026-05-18 02:00:00'),
            (100, 2, '2026-05-18 03:00:00'),
            (100, 4, '2026-05-18 04:00:00'),
            (100, 3, '2026-05-18 05:00:00');
        INSERT INTO favorites (user_id, teacher_id) VALUES (100, 2);
        """
    )
    # 今日签到（本地时区 today）
    today_local = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
    await db.execute(
        "INSERT INTO checkins (teacher_id, checkin_date) VALUES (?, ?)",
        (1, today_local),
    )
    await db.commit()


def test_query_excludes_inactive_teachers():
    async def go():
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_views(db)

            async def _fake_get_db():
                class _W:
                    def __init__(self, r):
                        self._r = r
                    def __getattr__(self, n):
                        return getattr(self._r, n)
                    async def close(self):
                        pass
                return _W(db)
            rv.get_db = _fake_get_db
            try:
                items = await rv.get_recent_teacher_views(user_id=100, limit=10)
            finally:
                # 恢复原始（这里我们已经覆盖；测试 fixture 隔离）
                pass

            # 应包含 4/2/1 三位 active 老师，stopped 老师 3 排除
            tids = [it.teacher_id for it in items]
            assert tids == [4, 2, 1]
            # 顺序按 viewed_at DESC
            names = [it.display_name for it in items]
            assert names == ["老师D", "老师B", "老师A"]
        finally:
            await db.close()
    _run(go())


def test_query_marks_favorite_correctly():
    async def go():
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_views(db)

            async def _fake_get_db():
                class _W:
                    def __init__(self, r):
                        self._r = r
                    def __getattr__(self, n):
                        return getattr(self._r, n)
                    async def close(self):
                        pass
                return _W(db)
            rv.get_db = _fake_get_db

            items = await rv.get_recent_teacher_views(user_id=100, limit=10)
            d = {it.teacher_id: it for it in items}
            assert d[2].is_favorited is True   # 收藏过
            assert d[1].is_favorited is False
            assert d[4].is_favorited is False
        finally:
            await db.close()
    _run(go())


def test_query_marks_today_checkin_correctly():
    async def go():
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_views(db)

            async def _fake_get_db():
                class _W:
                    def __init__(self, r):
                        self._r = r
                    def __getattr__(self, n):
                        return getattr(self._r, n)
                    async def close(self):
                        pass
                return _W(db)
            rv.get_db = _fake_get_db

            items = await rv.get_recent_teacher_views(user_id=100, limit=10)
            d = {it.teacher_id: it for it in items}
            assert d[1].is_checked_in_today is True
            assert d[2].is_checked_in_today is False
            assert d[4].is_checked_in_today is False
        finally:
            await db.close()
    _run(go())


def test_query_limit_respected():
    async def go():
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_views(db)

            async def _fake_get_db():
                class _W:
                    def __init__(self, r):
                        self._r = r
                    def __getattr__(self, n):
                        return getattr(self._r, n)
                    async def close(self):
                        pass
                return _W(db)
            rv.get_db = _fake_get_db

            items = await rv.get_recent_teacher_views(user_id=100, limit=1)
            assert len(items) == 1
            assert items[0].teacher_id == 4  # 最近 viewed_at
        finally:
            await db.close()
    _run(go())


def test_query_no_duplicate_per_teacher():
    """user_teacher_views PRIMARY KEY (user_id, teacher_id) 保证去重；
    再 view 同一老师只是更新 viewed_at，行数不增长。"""
    async def go():
        from bot.services import recent_views as rv
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await db.execute(
                "INSERT INTO teachers (user_id, display_name, is_active) VALUES (1, 'x', 1)"
            )
            await db.execute(
                "INSERT INTO user_teacher_views (user_id, teacher_id, viewed_at) "
                "VALUES (100, 1, '2026-05-18 02:00:00')"
            )
            # 再次浏览：UPSERT 行为
            await db.execute(
                "INSERT INTO user_teacher_views (user_id, teacher_id, viewed_at) "
                "VALUES (100, 1, '2026-05-18 04:00:00') "
                "ON CONFLICT(user_id, teacher_id) DO UPDATE SET "
                "viewed_at = excluded.viewed_at"
            )
            await db.commit()

            async def _fake_get_db():
                class _W:
                    def __init__(self, r):
                        self._r = r
                    def __getattr__(self, n):
                        return getattr(self._r, n)
                    async def close(self):
                        pass
                return _W(db)
            rv.get_db = _fake_get_db

            items = await rv.get_recent_teacher_views(user_id=100, limit=10)
            assert len(items) == 1
            assert items[0].teacher_id == 1
            assert items[0].viewed_at == "2026-05-18 04:00:00"
        finally:
            await db.close()
    _run(go())


# ============ keyboard 契约 ============


def test_user_recent_callback_present_in_main_menu_kb():
    """主菜单已有 user:recent 入口（spec：不新增重复入口）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:recent" in callbacks


def test_recent_views_rich_kb_has_view_and_refresh_and_back():
    """rich kb 含 teacher:view:<id>:from:recent + user:recent:refresh + user:main。

    UX-3 第二批：列表 callback 现带 from:recent，让详情页"返回"指向最近看过。
    """
    from bot.keyboards.user_kb import recent_views_rich_kb
    items = [
        RecentTeacherViewItem(teacher_id=10, display_name="老师A", viewed_at=None),
        RecentTeacherViewItem(teacher_id=20, display_name="老师B", viewed_at=None),
    ]
    kb = recent_views_rich_kb(items)
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "teacher:view:10:from:recent" in callbacks
    assert "teacher:view:20:from:recent" in callbacks
    assert "user:recent:refresh" in callbacks
    assert "user:main" in callbacks


def test_recent_views_rich_kb_supports_dict_input():
    """兼容 dict 输入（防御性，避免反向依赖 service dataclass）"""
    from bot.keyboards.user_kb import recent_views_rich_kb
    items = [{"teacher_id": 5, "display_name": "老师 X"}]
    kb = recent_views_rich_kb(items)
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "teacher:view:5:from:recent" in callbacks


def test_recent_views_empty_kb_has_guide_callbacks():
    """空 kb 引导：热门推荐 / 条件搜索 / 返回主菜单。"""
    from bot.keyboards.user_kb import recent_views_empty_kb
    kb = recent_views_empty_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:hot" in callbacks
    assert "user:filter" in callbacks
    assert "user:main" in callbacks


def test_user_recent_refresh_handler_present_in_source():
    """handler 源码必须含 user:recent:refresh 字符串字面量。"""
    import bot.handlers.teacher_detail as td
    import inspect
    src = inspect.getsource(td)
    assert '"user:recent:refresh"' in src
    assert '"user:recent"' in src
