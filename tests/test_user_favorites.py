"""用户「⭐ 我的收藏」增强版单元测试。

测试范围：
    1. FavoriteTeacherItem / FavoriteTeachersStats dataclass
    2. render_user_favorites：标题 / 三计数 / mode 文案 / 老师条目 / 空占位
    3. None 字段显示 N/A，不崩溃
    4. mode='today' 且无可约老师时的提示文案
    5. get_user_favorites 查询：
       - 总数 / 今日可约 / 今日未签 计数正确
       - mode='today' 只保留今日可约
       - limit 生效
       - 停用老师过滤
       - 同一老师 PRIMARY KEY 去重（行为继承 favorites 主键）
    6. 关键 callback_data 字符串契约
       user:favorites / user:favorites:today / user:favorites:refresh / user:favorites:rm:<id>

不连接真实 Telegram；仅使用 :memory: SQLite。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone as dt_timezone
import os

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.services.user_favorites import (
    EMPTY_TEXT,
    FavoriteTeacherItem,
    FavoriteTeachersStats,
    MODE_ALL,
    MODE_TODAY,
    render_user_favorites,
)


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


async def _setup_min_schema(db: aiosqlite.Connection) -> None:
    """最小可运行 schema（teachers / favorites / checkins）。"""
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
        CREATE TABLE favorites (
            user_id INTEGER,
            teacher_id INTEGER,
            created_at TEXT,
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


_LOCAL_TZ = pytz_timezone(os.environ.get("TIMEZONE", "Asia/Shanghai"))


# ============ dataclass ============


def test_item_defaults():
    item = FavoriteTeacherItem(
        teacher_id=1, display_name="x", favorited_at=None,
    )
    assert item.is_checked_in_today is None


def test_stats_defaults():
    s = FavoriteTeachersStats()
    assert s.total_count is None
    assert s.checked_in_today_count is None
    assert s.not_checked_in_today_count is None
    assert s.items == []
    assert s.mode == MODE_ALL
    assert s.generated_at is None


def test_stats_field_assignment():
    s = FavoriteTeachersStats(
        total_count=3,
        checked_in_today_count=1,
        not_checked_in_today_count=2,
        mode=MODE_TODAY,
        generated_at=datetime(2026, 5, 18, 12, 0, 0),
    )
    assert s.total_count == 3
    assert s.mode == "today"


# ============ render_user_favorites ============


def test_render_empty_when_total_none():
    """total_count=None（如查询失败）也应显示空占位。"""
    s = FavoriteTeachersStats(total_count=None, mode=MODE_ALL)
    assert render_user_favorites(s) == EMPTY_TEXT


def test_render_empty_when_total_zero():
    s = FavoriteTeachersStats(total_count=0)
    text = render_user_favorites(s)
    assert text == EMPTY_TEXT
    assert "你还没有收藏老师" in text


def test_render_contains_header_and_counts():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="老师A",
        favorited_at=None, is_checked_in_today=True,
    )]
    s = FavoriteTeachersStats(
        total_count=1,
        checked_in_today_count=1,
        not_checked_in_today_count=0,
        items=items, mode=MODE_ALL,
    )
    text = render_user_favorites(s)
    assert "⭐ 我的收藏" in text
    assert "今日可约：1 位" in text
    assert "今日未签到：0 位" in text
    assert "总收藏：1 位" in text


def test_render_item_with_status_and_time():
    fav_local = _LOCAL_TZ.localize(datetime(2026, 5, 18, 12, 30, 0))
    fav_utc = fav_local.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="老师A",
        favorited_at=fav_utc, is_checked_in_today=True,
    )]
    s = FavoriteTeachersStats(
        total_count=1,
        checked_in_today_count=1,
        not_checked_in_today_count=0,
        items=items,
        mode=MODE_ALL,
        generated_at=fav_local,
    )
    text = render_user_favorites(s)
    assert "1. 老师A" in text
    assert "状态：今日可约" in text
    assert "收藏时间：今天 12:30" in text
    assert "更新时间：" in text


def test_render_status_unsigned():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="x",
        favorited_at=None, is_checked_in_today=False,
    )]
    s = FavoriteTeachersStats(
        total_count=1,
        checked_in_today_count=0,
        not_checked_in_today_count=1,
        items=items, mode=MODE_ALL,
    )
    text = render_user_favorites(s)
    assert "状态：今日未签到" in text


def test_render_status_none_shows_na():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="x",
        favorited_at=None, is_checked_in_today=None,
    )]
    s = FavoriteTeachersStats(
        total_count=1,
        checked_in_today_count=0,
        not_checked_in_today_count=1,
        items=items, mode=MODE_ALL,
    )
    text = render_user_favorites(s)
    assert "状态：N/A" in text
    assert "收藏时间：N/A" in text


def test_render_count_none_shows_na():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="x",
        favorited_at=None, is_checked_in_today=True,
    )]
    s = FavoriteTeachersStats(
        total_count=1,  # 非 0 → 不进入 EMPTY_TEXT 分支
        checked_in_today_count=None,
        not_checked_in_today_count=None,
        items=items, mode=MODE_ALL,
    )
    text = render_user_favorites(s)
    assert "今日可约：N/A 位" in text
    assert "今日未签到：N/A 位" in text


def test_render_today_mode_shows_view_label():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="老师A",
        favorited_at=None, is_checked_in_today=True,
    )]
    s = FavoriteTeachersStats(
        total_count=2,
        checked_in_today_count=1,
        not_checked_in_today_count=1,
        items=items, mode=MODE_TODAY,
    )
    text = render_user_favorites(s)
    assert "视图：只看今日可约" in text
    assert "1. 老师A" in text


def test_render_today_mode_empty_items_shows_hint():
    """有收藏但今日无人签到时的特定提示。"""
    s = FavoriteTeachersStats(
        total_count=3,
        checked_in_today_count=0,
        not_checked_in_today_count=3,
        items=[], mode=MODE_TODAY,
    )
    text = render_user_favorites(s)
    assert "你的收藏老师今日均未签到" in text
    assert "查看全部" in text
    # 不应触发 EMPTY_TEXT
    assert "你还没有收藏老师" not in text


def test_render_multiple_numbered():
    items = [
        FavoriteTeacherItem(
            teacher_id=i, display_name=f"老师{i}",
            favorited_at=None, is_checked_in_today=(i % 2 == 0),
        )
        for i in range(1, 4)
    ]
    s = FavoriteTeachersStats(
        total_count=3,
        checked_in_today_count=1,
        not_checked_in_today_count=2,
        items=items, mode=MODE_ALL,
    )
    text = render_user_favorites(s)
    assert "1. 老师1" in text
    assert "2. 老师2" in text
    assert "3. 老师3" in text


def test_render_is_pure_function():
    items = [FavoriteTeacherItem(
        teacher_id=1, display_name="x",
        favorited_at=None, is_checked_in_today=True,
    )]
    fixed = _LOCAL_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
    s = FavoriteTeachersStats(
        total_count=1, checked_in_today_count=1, not_checked_in_today_count=0,
        items=items, mode=MODE_ALL, generated_at=fixed,
    )
    assert render_user_favorites(s) == render_user_favorites(s)


# ============ get_user_favorites 查询 ============


async def _seed_favorites(db: aiosqlite.Connection) -> None:
    """通用种子数据：
        teachers: 1=老师A active / 2=老师B active / 3=老师C inactive / 4=老师D active
        user 100 收藏: 1, 2, 3, 4
        今日签到: 老师 1, 老师 4
        预期 active 收藏 3 条（排除 3）；其中可约 2（1+4），未签 1（2）。
    """
    await db.executescript(
        """
        INSERT INTO teachers (user_id, display_name, is_active) VALUES
            (1, '老师A', 1),
            (2, '老师B', 1),
            (3, '老师C', 0),
            (4, '老师D', 1);
        INSERT INTO favorites (user_id, teacher_id, created_at) VALUES
            (100, 1, '2026-05-18 02:00:00'),
            (100, 2, '2026-05-18 03:00:00'),
            (100, 3, '2026-05-18 04:00:00'),
            (100, 4, '2026-05-18 05:00:00');
        """
    )
    today_local = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d")
    await db.execute(
        "INSERT INTO checkins (teacher_id, checkin_date) VALUES (?, ?)",
        (1, today_local),
    )
    await db.execute(
        "INSERT INTO checkins (teacher_id, checkin_date) VALUES (?, ?)",
        (4, today_local),
    )
    await db.commit()


def _patch_get_db(uf_module, db: aiosqlite.Connection):
    """劫持 uf.get_db → 返回不真关的 wrapper（让一次 get_db 拿到同一 db）"""
    async def _fake_get_db():
        class _W:
            def __init__(self, r):
                self._r = r
            def __getattr__(self, n):
                return getattr(self._r, n)
            async def close(self):
                pass
        return _W(db)
    uf_module.get_db = _fake_get_db


def test_query_counts_are_correct():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_favorites(db)
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="all", limit=10)
            # 老师 3 因停用过滤掉
            assert stats.total_count == 3
            assert stats.checked_in_today_count == 2   # 1 + 4
            assert stats.not_checked_in_today_count == 1  # 2
            tids = [it.teacher_id for it in stats.items]
            # 按 favorited_at DESC：4, 2, 1（3 已过滤）
            assert tids == [4, 2, 1]
        finally:
            await db.close()
    _run(go())


def test_query_today_mode_filter():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_favorites(db)
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="today", limit=10)
            # 计数仍是全量（today 不影响计数）
            assert stats.total_count == 3
            assert stats.checked_in_today_count == 2
            assert stats.not_checked_in_today_count == 1
            # items 只保留今日签到的老师 4 与 1
            tids = [it.teacher_id for it in stats.items]
            assert tids == [4, 1]
            assert stats.mode == "today"
        finally:
            await db.close()
    _run(go())


def test_query_invalid_mode_falls_back_to_all():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_favorites(db)
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="weird", limit=10)
            assert stats.mode == "all"
            assert len(stats.items) == 3
        finally:
            await db.close()
    _run(go())


def test_query_limit_respected():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await _seed_favorites(db)
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="all", limit=1)
            # 计数不变
            assert stats.total_count == 3
            # items 只剩 1 条（最新收藏老师 4）
            assert len(stats.items) == 1
            assert stats.items[0].teacher_id == 4
        finally:
            await db.close()
    _run(go())


def test_query_inactive_teachers_filtered():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            # 全部老师停用 + 一条收藏
            await db.execute(
                "INSERT INTO teachers (user_id, display_name, is_active) VALUES (1, 'x', 0)"
            )
            await db.execute(
                "INSERT INTO favorites (user_id, teacher_id, created_at) "
                "VALUES (100, 1, '2026-05-18 02:00:00')"
            )
            await db.commit()
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="all", limit=10)
            assert stats.total_count == 0
            assert stats.items == []
        finally:
            await db.close()
    _run(go())


def test_query_empty_when_no_favorites():
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await db.commit()
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=999, mode="all", limit=10)
            assert stats.total_count == 0
            assert stats.items == []
        finally:
            await db.close()
    _run(go())


def test_query_no_duplicate_favorite():
    """favorites PRIMARY KEY 保证 (user, teacher) 唯一。"""
    async def go():
        from bot.services import user_favorites as uf
        db = await _fresh_db()
        try:
            await _setup_min_schema(db)
            await db.execute(
                "INSERT INTO teachers (user_id, display_name, is_active) VALUES (1, 'x', 1)"
            )
            await db.execute(
                "INSERT INTO favorites (user_id, teacher_id, created_at) "
                "VALUES (100, 1, '2026-05-18 02:00:00')"
            )
            # 重复 INSERT 会因 PRIMARY KEY 失败 → 我们用 OR IGNORE 模拟现实重复点击
            await db.execute(
                "INSERT OR IGNORE INTO favorites (user_id, teacher_id, created_at) "
                "VALUES (100, 1, '2026-05-18 04:00:00')"
            )
            await db.commit()
            _patch_get_db(uf, db)

            stats = await uf.get_user_favorites(user_id=100, mode="all", limit=10)
            assert stats.total_count == 1
            assert len(stats.items) == 1
        finally:
            await db.close()
    _run(go())


# ============ keyboard / callback 字符串契约 ============


def test_user_favorites_callback_present_in_main_menu_kb():
    """主菜单已有 user:favorites 入口（不新增重复）。"""
    from bot.keyboards.user_kb import user_main_menu_kb
    kb = user_main_menu_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:favorites" in callbacks


def test_favorites_rich_kb_all_mode_callbacks():
    """all 模式 keyboard 含切换到 today / refresh / 主菜单 + 每条 view/rm。"""
    from bot.keyboards.user_kb import favorites_rich_kb
    items = [
        FavoriteTeacherItem(teacher_id=10, display_name="老师A",
                            favorited_at=None, is_checked_in_today=True),
        FavoriteTeacherItem(teacher_id=20, display_name="老师B",
                            favorited_at=None, is_checked_in_today=False),
    ]
    kb = favorites_rich_kb(items, mode="all")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    # UX-3 第二批：callback 现带 from:favorites
    assert "teacher:view:10:from:favorites" in callbacks
    assert "teacher:view:20:from:favorites" in callbacks
    assert "user:favorites:rm:10" in callbacks
    assert "user:favorites:rm:20" in callbacks
    # all 模式下应显示切换到 today 的按钮
    assert "user:favorites:today" in callbacks
    assert "user:favorites:refresh" in callbacks
    assert "user:main" in callbacks


def test_favorites_rich_kb_today_mode_shows_view_all():
    """today 模式 keyboard 应显示 [查看全部]（user:favorites）。"""
    from bot.keyboards.user_kb import favorites_rich_kb
    items = [FavoriteTeacherItem(
        teacher_id=10, display_name="x", favorited_at=None,
        is_checked_in_today=True,
    )]
    kb = favorites_rich_kb(items, mode="today")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    # today 模式下应能切回 all（user:favorites）
    assert "user:favorites" in callbacks
    assert "user:favorites:today" not in callbacks


def test_favorites_rich_kb_supports_dict_input():
    """兼容 dict 输入，与 favorites_rich_kb 解耦。"""
    from bot.keyboards.user_kb import favorites_rich_kb
    items = [{"teacher_id": 5, "display_name": "X"}]
    kb = favorites_rich_kb(items, mode="all")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    # UX-3 第二批：callback 现带 from:favorites
    assert "teacher:view:5:from:favorites" in callbacks
    assert "user:favorites:rm:5" in callbacks


def test_favorites_empty_kb_has_guide_callbacks():
    """空收藏引导 keyboard：热门 / 条件搜索 / 最近看过 / 主菜单。"""
    from bot.keyboards.user_kb import favorites_empty_kb
    kb = favorites_empty_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "user:hot" in callbacks
    assert "user:filter" in callbacks
    assert "user:recent" in callbacks
    assert "user:main" in callbacks


def test_favorites_handlers_present_in_source():
    """handler 源码必须含全部新 callback 字面量。"""
    import bot.handlers.user_panel as up
    import inspect
    src = inspect.getsource(up)
    assert '"user:favorites"' in src
    assert '"user:favorites:today"' in src
    assert '"user:favorites:refresh"' in src
    assert '"user:favorites:rm:"' in src
