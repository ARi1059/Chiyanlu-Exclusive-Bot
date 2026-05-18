"""抽奖状态总览（admin:lottery_status）单元测试。

测试范围：
    1. LotteryStatusStats / LotteryStatusItem dataclass 行为
    2. render_lottery_status 渲染所有状态计数
    3. None 显示 N/A
    4. recent_lotteries 为空时显示 "暂无抽奖活动"
    5. recent_lotteries 多条时只显示前 5 条
    6. paid_lottery_count / active_without_entries / winner_count 渲染正确
    7. _fmt_dt / _fmt_cost 边界
    8. _scalar_int / _fetch_recent_lotteries 防御性
    9. callback_data 字符串在 keyboard / handler 中存在

仅使用 :memory: SQLite，不连接真实生产库；不连接 Telegram。
为避免引入 pytest-asyncio，async 通过 asyncio.run 同步包裹。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import aiosqlite

from bot.services.lottery_status import (
    LotteryStatusItem,
    LotteryStatusStats,
    RECENT_LOTTERY_LIMIT,
    render_lottery_status,
    _fetch_recent_lotteries,
    _fmt_cost,
    _fmt_dt,
    _scalar_int,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


async def _setup_lottery_tables(db: aiosqlite.Connection) -> None:
    """创建最小 lotteries / lottery_entries 表（与生产 schema 字段子集一致）"""
    await db.execute(
        """
        CREATE TABLE lotteries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            status TEXT,
            entry_cost_points INTEGER DEFAULT 0,
            publish_at TEXT,
            draw_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE lottery_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_id INTEGER,
            user_id INTEGER,
            won INTEGER DEFAULT 0
        )
        """
    )


# ============ dataclass 行为 ============


def test_status_stats_defaults_all_none_and_empty_list():
    stats = LotteryStatusStats()
    assert stats.draft_count is None
    assert stats.scheduled_count is None
    assert stats.active_count is None
    assert stats.drawn_count is None
    assert stats.no_entries_count is None
    assert stats.cancelled_count is None
    assert stats.waiting_publish_count is None
    assert stats.waiting_draw_count is None
    assert stats.active_without_entries_count is None
    assert stats.paid_lottery_count is None
    assert stats.recent_lotteries == []  # default_factory(list)
    assert stats.generated_at is None


def test_status_item_construction():
    item = LotteryStatusItem(
        id=1, name="Test",
        status="active",
        entry_count=5,
        winner_count=2,
        draw_at="2026-05-20 18:00:00",
        publish_at="2026-05-19 12:00:00",
        entry_cost_points=3,
    )
    assert item.id == 1
    assert item.status == "active"
    assert item.entry_count == 5
    assert item.winner_count == 2
    assert item.entry_cost_points == 3


def test_recent_lottery_limit_is_5():
    """spec 要求最近 5 条；常量集中定义防止漂移。"""
    assert RECENT_LOTTERY_LIMIT == 5


# ============ render：基本结构 ============


def test_render_contains_header_and_sections():
    text = render_lottery_status(LotteryStatusStats())
    assert "🎲 抽奖状态" in text
    assert "状态总览" in text
    assert "待办提醒" in text
    assert "最近活动" in text


def test_render_contains_status_labels():
    text = render_lottery_status(LotteryStatusStats())
    expected = [
        "草稿 draft",
        "待发布 scheduled",
        "进行中 active",
        "已开奖 drawn",
        "无人参与 no_entries",
        "已取消 cancelled",
        "待发布：",
        "待开奖：",
        "active 但无人参与",
        "积分门票活动",
        "更新时间",
    ]
    for label in expected:
        assert label in text, f"render 缺少标签：{label}"


def test_render_all_none_shows_na():
    """全 None 时应大量出现 N/A，且不抛错。"""
    text = render_lottery_status(LotteryStatusStats())
    # 10 个计数字段 + generated_at
    assert text.count("N/A") >= 10


def test_render_status_counts_appear():
    stats = LotteryStatusStats(
        draft_count=1,
        scheduled_count=2,
        active_count=3,
        drawn_count=4,
        no_entries_count=5,
        cancelled_count=6,
        waiting_publish_count=2,
        waiting_draw_count=3,
        active_without_entries_count=1,
        paid_lottery_count=2,
    )
    text = render_lottery_status(stats)
    assert "草稿 draft：1 个" in text
    assert "待发布 scheduled：2 个" in text
    assert "进行中 active：3 个" in text
    assert "已开奖 drawn：4 个" in text
    assert "无人参与 no_entries：5 个" in text
    assert "已取消 cancelled：6 个" in text
    assert "active 但无人参与：1 个" in text
    assert "积分门票活动：2 个" in text


def test_render_paid_lottery_count_renders_correctly():
    text = render_lottery_status(LotteryStatusStats(paid_lottery_count=7))
    assert "积分门票活动：7 个" in text


def test_render_active_without_entries_renders_correctly():
    text = render_lottery_status(
        LotteryStatusStats(active_without_entries_count=4)
    )
    assert "active 但无人参与：4 个" in text


# ============ render：最近活动 ============


def test_render_empty_recent_shows_placeholder():
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[])
    )
    assert "暂无抽奖活动" in text
    # 不应再有 "#" 抽奖编号
    assert "\n#" not in text


def test_render_single_recent_lottery():
    item = LotteryStatusItem(
        id=12, name="新人福利",
        status="active",
        entry_count=80,
        winner_count=3,
        draw_at="2026-05-20 18:00:00",
        publish_at="2026-05-19 12:00:00",
        entry_cost_points=5,
    )
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[item])
    )
    assert "#12 新人福利" in text
    assert "状态：active" in text
    assert "参与人数：80" in text
    assert "中奖人数：3" in text
    # 分钟级截断
    assert "开奖时间：2026-05-20 18:00" in text
    assert "积分门票：5 分" in text


def test_render_winner_count_zero_displayed_explicitly():
    item = LotteryStatusItem(
        id=1, name="x", status="active",
        entry_count=10, winner_count=0,
    )
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[item])
    )
    assert "中奖人数：0" in text


def test_render_winner_count_none_displays_na():
    item = LotteryStatusItem(
        id=1, name="x", status="active",
        entry_count=None, winner_count=None,
    )
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[item])
    )
    assert "中奖人数：N/A" in text
    assert "参与人数：N/A" in text


def test_render_recent_caps_at_five():
    """超过 5 条时仅显示前 5 条。"""
    items = [
        LotteryStatusItem(
            id=i, name=f"Lottery #{i}",
            status="drawn",
            entry_count=i, winner_count=1,
            draw_at="2026-05-19 18:00:00",
            entry_cost_points=0,
        )
        for i in range(1, 9)  # 8 条
    ]
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=items)
    )
    for i in range(1, 6):
        assert f"#{i} Lottery #{i}" in text
    # 第 6/7/8 条不应出现
    for i in range(6, 9):
        assert f"#{i} Lottery #{i}" not in text


def test_render_recent_free_lottery():
    """entry_cost_points = 0 渲染"免费"。"""
    item = LotteryStatusItem(
        id=1, name="x", status="active",
        entry_count=10, winner_count=2,
        draw_at="2026-05-20 18:00:00",
        entry_cost_points=0,
    )
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[item])
    )
    assert "积分门票：免费" in text


def test_render_recent_unknown_status():
    """status 为空字符串时渲染 N/A，不抛错。"""
    item = LotteryStatusItem(id=1, name="x", status="")
    text = render_lottery_status(
        LotteryStatusStats(recent_lotteries=[item])
    )
    assert "状态：N/A" in text


def test_render_generated_at_formatting():
    text = render_lottery_status(
        LotteryStatusStats(generated_at=datetime(2026, 5, 18, 9, 30, 45))
    )
    assert "2026-05-18 09:30:45" in text


def test_render_is_pure_function():
    stats = LotteryStatusStats(
        draft_count=1,
        recent_lotteries=[LotteryStatusItem(id=1, name="x", status="active")],
        generated_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert render_lottery_status(stats) == render_lottery_status(stats)


# ============ 渲染 helper ============


def test_fmt_dt_none():
    assert _fmt_dt(None) == "N/A"


def test_fmt_dt_empty_string():
    assert _fmt_dt("") == "N/A"


def test_fmt_dt_full_iso():
    assert _fmt_dt("2026-05-20 18:00:00") == "2026-05-20 18:00"


def test_fmt_dt_short_string_returned_as_is():
    """异常短串容错：原样返回，不切片越界。"""
    assert _fmt_dt("bad") == "bad"


def test_fmt_cost_none():
    assert _fmt_cost(None) == "N/A"


def test_fmt_cost_zero_is_free():
    assert _fmt_cost(0) == "免费"


def test_fmt_cost_positive():
    assert _fmt_cost(5) == "5 分"


def test_fmt_cost_negative_treated_as_free():
    """理论不会出现负数（CHECK constraint）；防御渲染。"""
    assert _fmt_cost(-1) == "免费"


# ============ _scalar_int / DB 仿真 ============


def test_scalar_int_returns_none_on_missing_table():
    async def go():
        db = await _fresh_db()
        try:
            n = await _scalar_int(db, "SELECT COUNT(*) FROM not_exists")
            assert n is None
        finally:
            await db.close()
    _run(go())


def test_scalar_int_counts_status():
    async def go():
        db = await _fresh_db()
        try:
            await _setup_lottery_tables(db)
            await db.executescript(
                """
                INSERT INTO lotteries (name, status) VALUES
                    ('a', 'draft'),
                    ('b', 'active'),
                    ('c', 'active'),
                    ('d', 'cancelled');
                """
            )
            await db.commit()
            assert await _scalar_int(
                db, "SELECT COUNT(*) FROM lotteries WHERE status='active'",
            ) == 2
            assert await _scalar_int(
                db, "SELECT COUNT(*) FROM lotteries WHERE status='draft'",
            ) == 1
        finally:
            await db.close()
    _run(go())


def test_active_without_entries_sql_correct():
    """active 但无 entries 的 NOT EXISTS 口径正确性。"""
    async def go():
        db = await _fresh_db()
        try:
            await _setup_lottery_tables(db)
            # 三条 active：A 无 entries / B 有 entries / C 无 entries
            await db.executescript(
                """
                INSERT INTO lotteries (id, name, status) VALUES
                    (1, 'A', 'active'),
                    (2, 'B', 'active'),
                    (3, 'C', 'active');
                INSERT INTO lottery_entries (lottery_id, user_id) VALUES
                    (2, 1001);
                """
            )
            await db.commit()
            n = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM lotteries l "
                "WHERE l.status = 'active' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM lottery_entries e WHERE e.lottery_id = l.id"
                ")",
            )
            assert n == 2
        finally:
            await db.close()
    _run(go())


def test_paid_lottery_count_sql_correct():
    """scheduled + active 且 entry_cost_points > 0。"""
    async def go():
        db = await _fresh_db()
        try:
            await _setup_lottery_tables(db)
            await db.executescript(
                """
                INSERT INTO lotteries (name, status, entry_cost_points) VALUES
                    ('a', 'active',   0),
                    ('b', 'active',   3),
                    ('c', 'scheduled', 5),
                    ('d', 'scheduled', 0),
                    ('e', 'drawn',     3),
                    ('f', 'cancelled', 5);
                """
            )
            await db.commit()
            n = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM lotteries "
                "WHERE status IN ('scheduled','active') AND entry_cost_points > 0",
            )
            assert n == 2  # b + c
        finally:
            await db.close()
    _run(go())


def test_fetch_recent_lotteries_joins_entries_correctly():
    """_fetch_recent_lotteries 应正确聚合 entry_count / winner_count。"""
    async def go():
        db = await _fresh_db()
        try:
            await _setup_lottery_tables(db)
            await db.executescript(
                """
                INSERT INTO lotteries (id, name, status, entry_cost_points,
                                       draw_at, publish_at, created_at)
                VALUES
                    (1, 'Lot1', 'active', 0,
                       '2026-05-20 18:00:00', '2026-05-19 12:00:00',
                       '2026-05-18 10:00:00'),
                    (2, 'Lot2', 'drawn',  5,
                       '2026-05-15 18:00:00', '2026-05-14 12:00:00',
                       '2026-05-13 10:00:00');
                INSERT INTO lottery_entries (lottery_id, user_id, won) VALUES
                    (1, 11, 0),
                    (1, 12, 0),
                    (1, 13, 1),
                    (2, 21, 1),
                    (2, 22, 1);
                """
            )
            await db.commit()
            items = await _fetch_recent_lotteries(db, limit=5)
            assert len(items) == 2
            # created_at DESC → Lot1 在前
            first, second = items
            assert first.id == 1
            assert first.name == "Lot1"
            assert first.entry_count == 3
            assert first.winner_count == 1
            assert first.entry_cost_points == 0
            assert second.id == 2
            assert second.entry_count == 2
            assert second.winner_count == 2
            assert second.entry_cost_points == 5
        finally:
            await db.close()
    _run(go())


def test_fetch_recent_lotteries_respects_limit():
    async def go():
        db = await _fresh_db()
        try:
            await _setup_lottery_tables(db)
            for i in range(1, 9):
                await db.execute(
                    "INSERT INTO lotteries (id, name, status, created_at) "
                    "VALUES (?, ?, 'active', ?)",
                    (i, f"L{i}", f"2026-05-{i:02d} 10:00:00"),
                )
            await db.commit()
            items = await _fetch_recent_lotteries(db, limit=5)
            assert len(items) == 5
        finally:
            await db.close()
    _run(go())


def test_fetch_recent_lotteries_missing_table_returns_empty():
    """表不存在时返回空 list，不抛错。"""
    async def go():
        db = await _fresh_db()
        try:
            items = await _fetch_recent_lotteries(db, limit=5)
            assert items == []
        finally:
            await db.close()
    _run(go())


# ============ callback_data 字符串契约 ============


def test_lottery_status_present_in_dashboard_kb():
    """admin:lottery_status 已收纳到二级「📊 数据看板」(admin_dashboard_kb)。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:lottery_status":
                found = True
                assert "抽奖状态" in btn.text
    assert found, "admin_dashboard_kb 缺少 admin:lottery_status 入口按钮"


def test_lottery_status_no_longer_in_main_menu_kb():
    """主菜单不再直接含 admin:lottery_status（已下沉到 admin:dashboard）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:lottery_status" not in callbacks, (
            f"主菜单 (is_super={is_super}) 不应再直接含 admin:lottery_status"
        )


def test_lottery_status_refresh_callback_present_in_kb():
    """详情面板 keyboard 必须含 refresh + 返回主菜单。"""
    from bot.keyboards.admin_kb import admin_lottery_status_kb
    kb = admin_lottery_status_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "admin:lottery_status:refresh" in callbacks
    assert "menu:main" in callbacks


def test_lottery_status_callbacks_present_in_handler_source():
    """handler 源码必须直接出现两个 callback 字符串字面量。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:lottery_status"' in src
    assert '"admin:lottery_status:refresh"' in src
