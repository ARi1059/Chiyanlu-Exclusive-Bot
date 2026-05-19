"""运营总览（admin:overview）单元测试。

测试范围：
    1. AdminOverviewStats dataclass 默认构造行为
    2. render_admin_overview 渲染所有关键字段
    3. render_admin_overview 对 None 字段显示 N/A
    4. schema_migrations hard/soft failed 渲染正确
    5. 关键 callback_data 字符串在 keyboard / handler 中存在
    6. 仅使用 :memory: SQLite，绝不连接真实生产库；不连接 Telegram

为避免引入 pytest-asyncio，async 测试通过 asyncio.run 同步包裹。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import aiosqlite

from bot.services.admin_overview import (
    AdminOverviewStats,
    render_admin_overview,
    _scalar_int,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


# ============ AdminOverviewStats dataclass ============


def test_stats_defaults_all_none():
    """空构造时所有字段都是 None（→ 渲染会显示 N/A）。"""
    stats = AdminOverviewStats()
    assert stats.today_checkin_teachers is None
    assert stats.today_new_users is None
    assert stats.today_new_favorites is None
    assert stats.today_new_reviews is None
    assert stats.pending_teacher_edits is None  # UX-2 第三项第一批新增
    assert stats.pending_reviews is None
    assert stats.pending_reimbursements is None
    assert stats.queued_reimbursements is None
    assert stats.active_lotteries is None
    assert stats.scheduled_lotteries is None
    assert stats.active_lotteries_waiting_draw is None
    assert stats.failed_hard_migrations is None
    assert stats.failed_soft_migrations is None
    assert stats.generated_at is None


def test_stats_can_set_all_fields():
    stats = AdminOverviewStats(
        today_checkin_teachers=1,
        today_new_users=2,
        today_new_favorites=3,
        today_new_reviews=4,
        pending_reviews=5,
        pending_reimbursements=6,
        queued_reimbursements=7,
        active_lotteries=8,
        scheduled_lotteries=9,
        active_lotteries_waiting_draw=10,
        failed_hard_migrations=11,
        failed_soft_migrations=12,
        generated_at=datetime(2026, 5, 18, 12, 34, 56),
    )
    assert stats.today_checkin_teachers == 1
    assert stats.failed_soft_migrations == 12
    assert stats.generated_at.year == 2026


# ============ render_admin_overview ============


def test_render_contains_header_and_sections():
    """渲染输出包含主标题与所有分组标题"""
    text = render_admin_overview(AdminOverviewStats())
    assert "📊 运营总览" in text
    assert "今日数据" in text
    assert "待处理" in text
    assert "抽奖" in text
    assert "系统" in text


def test_render_contains_all_metric_labels():
    """每条关键指标的中文标签都应出现"""
    text = render_admin_overview(AdminOverviewStats())
    expected_labels = [
        "今日签到老师",
        "今日新增用户",
        "今日新增收藏",
        "今日新增评价",
        "待审核评价",
        "待审核报销",
        "queued 报销名单",
        "进行中抽奖",
        "待发布抽奖",
        "待开奖抽奖",
        "schema_migrations 失败迁移",
        "更新时间",
    ]
    for label in expected_labels:
        assert label in text, f"render 缺少标签：{label}"


def test_render_none_shows_na():
    """所有 None 字段都应渲染为 N/A，且每个分组各显示 N/A。"""
    text = render_admin_overview(AdminOverviewStats())
    # 12 个数值字段全 None
    assert text.count("N/A") >= 12
    assert "0 位" not in text  # 不应把 None 当 0


def test_render_numbers_appear_when_set():
    stats = AdminOverviewStats(
        today_checkin_teachers=3,
        today_new_users=10,
        today_new_favorites=2,
        today_new_reviews=1,
        pending_reviews=4,
        pending_reimbursements=5,
        queued_reimbursements=6,
        active_lotteries=7,
        scheduled_lotteries=8,
        active_lotteries_waiting_draw=9,
        failed_hard_migrations=0,
        failed_soft_migrations=0,
    )
    text = render_admin_overview(stats)
    assert "3 位" in text
    assert "10 人" in text
    assert "2 次" in text
    assert "1 条" in text
    assert "4 条" in text
    assert "5 条" in text
    assert "6 条" in text
    assert "7 个" in text
    assert "8 个" in text
    assert "9 个" in text
    # hard / soft 失败迁移在同一行
    assert "hard 0 / soft 0" in text


def test_render_hard_soft_failed_correct():
    """hard 和 soft 数值要分别正确出现，hard 必须出现在 soft 之前"""
    stats = AdminOverviewStats(
        failed_hard_migrations=2,
        failed_soft_migrations=5,
    )
    text = render_admin_overview(stats)
    assert "hard 2 / soft 5" in text
    # hard 在 soft 之前
    assert text.index("hard 2") < text.index("soft 5")


def test_render_generated_at_iso_formatting():
    stats = AdminOverviewStats(
        generated_at=datetime(2026, 5, 18, 9, 30, 45),
    )
    text = render_admin_overview(stats)
    assert "2026-05-18 09:30:45" in text


def test_render_generated_at_none_shows_na():
    text = render_admin_overview(AdminOverviewStats(generated_at=None))
    assert "更新时间：N/A" in text


def test_render_is_pure_function():
    """连续两次调用同一 stats，输出一致（纯函数）。"""
    stats = AdminOverviewStats(
        today_checkin_teachers=1,
        failed_hard_migrations=0,
        failed_soft_migrations=0,
        generated_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert render_admin_overview(stats) == render_admin_overview(stats)


# ============ _scalar_int 防御性查询 ============


def test_scalar_int_returns_int_on_success():
    async def go():
        db = await _fresh_db()
        try:
            await db.execute(
                "CREATE TABLE t (id INTEGER PRIMARY KEY)"
            )
            await db.execute("INSERT INTO t (id) VALUES (1)")
            await db.execute("INSERT INTO t (id) VALUES (2)")
            await db.commit()
            n = await _scalar_int(db, "SELECT COUNT(*) FROM t")
            assert n == 2
        finally:
            await db.close()
    _run(go())


def test_scalar_int_returns_none_on_missing_table():
    """表不存在 → None（让渲染显示 N/A，而非抛错）。"""
    async def go():
        db = await _fresh_db()
        try:
            n = await _scalar_int(db, "SELECT COUNT(*) FROM nonexistent_table")
            assert n is None
        finally:
            await db.close()
    _run(go())


def test_scalar_int_empty_table_returns_zero():
    async def go():
        db = await _fresh_db()
        try:
            await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            await db.commit()
            n = await _scalar_int(db, "SELECT COUNT(*) FROM t")
            assert n == 0
        finally:
            await db.close()
    _run(go())


def test_scalar_int_with_params():
    async def go():
        db = await _fresh_db()
        try:
            await db.execute(
                "CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT)"
            )
            await db.execute("INSERT INTO t VALUES (1, 'pending')")
            await db.execute("INSERT INTO t VALUES (2, 'pending')")
            await db.execute("INSERT INTO t VALUES (3, 'done')")
            await db.commit()
            n = await _scalar_int(
                db, "SELECT COUNT(*) FROM t WHERE status = ?", ("pending",),
            )
            assert n == 2
        finally:
            await db.close()
    _run(go())


# ============ schema_migrations 失败统计（仿真小库） ============


def test_failed_migrations_counts_against_real_schema_shape():
    """构造仿真 schema_migrations 表，验证 hard/soft 失败统计 SQL 正确。

    这是 _scalar_int 的功能验证，也间接证明 get_admin_overview_stats 用的 SQL
    口径与 schema_migrations 表实际字段（success / kind）兼容。
    """
    async def go():
        db = await _fresh_db()
        try:
            await db.execute(
                """
                CREATE TABLE schema_migrations (
                    version     TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    kind        TEXT NOT NULL DEFAULT 'soft',
                    applied_at  TEXT,
                    success     INTEGER NOT NULL DEFAULT 1,
                    error       TEXT,
                    checksum    TEXT,
                    duration_ms INTEGER,
                    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            rows = [
                ("v1", "ok hard",    "hard", 1, None),
                ("v2", "ok soft",    "soft", 1, None),
                ("v3", "fail hard1", "hard", 0, "boom"),
                ("v4", "fail hard2", "hard", 0, "boom2"),
                ("v5", "fail soft1", "soft", 0, "warn"),
            ]
            for v, n, k, s, e in rows:
                await db.execute(
                    "INSERT INTO schema_migrations "
                    "(version, name, kind, success, error) VALUES (?,?,?,?,?)",
                    (v, n, k, s, e),
                )
            await db.commit()

            hard_failed = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE success = 0 AND kind = 'hard'",
            )
            soft_failed = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE success = 0 AND kind = 'soft'",
            )
            assert hard_failed == 2
            assert soft_failed == 1
        finally:
            await db.close()
    _run(go())


# ============ callback_data 字符串契约 ============


def test_admin_overview_present_in_dashboard_kb():
    """admin:overview 已收纳到二级「📊 数据看板」(admin_dashboard_kb)。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:overview":
                found = True
                assert "运营总览" in btn.text
    assert found, "admin_dashboard_kb 缺少 admin:overview 入口按钮"


def test_admin_overview_no_longer_in_main_menu_kb():
    """主菜单不再直接含 admin:overview（已下沉到 admin:dashboard）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:overview" not in callbacks, (
            f"主菜单 (is_super={is_super}) 不应再直接含 admin:overview"
        )


def test_admin_overview_refresh_callback_present_in_overview_kb():
    """运营总览页面按钮：刷新 admin:overview:refresh + 返回 admin:dashboard。

    UX-1 第一批返回路径优化（2026-05）：返回按钮从 menu:main 调整为
    二级页 admin:dashboard（📊 运营看板），让管理员"看完即可回看板"。
    """
    from bot.keyboards.admin_kb import admin_overview_kb
    kb = admin_overview_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "admin:overview:refresh" in callbacks
    assert "admin:dashboard" in callbacks
    # UX-1：不再直接回 menu:main，走二级页 admin:dashboard
    assert "menu:main" not in callbacks


def test_admin_overview_callbacks_present_in_handler_source():
    """handler 源码中必须直接出现两个 callback 字符串字面量。

    （字符串契约，hardcoded 防止漂移）
    """
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:overview"' in src
    assert '"admin:overview:refresh"' in src
