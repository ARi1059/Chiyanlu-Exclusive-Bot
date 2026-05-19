"""报销池状态（admin:reimbursement_pool）单元测试。

测试范围：
    1. ReimbursementPoolStats dataclass 默认构造与字段赋值
    2. render_reimbursement_pool 渲染所有关键字段
    3. render_reimbursement_pool 对 None 显示 N/A
    4. 剩余额度 = 月度池 - 本月已批准
    5. 超额时显示负数 + ⚠️ 已超额，不报错
    6. monthly_pool == 0（不限）特殊渲染
    7. feature_enabled True / False / None 显示正确
    8. _scalar_int / _parse_monthly_pool 防御性
    9. callback_data 字符串 admin:reimbursement_pool / :refresh 在 keyboard / handler 中存在

为避免引入 pytest-asyncio，async 测试通过 asyncio.run 同步包裹。
仅使用 :memory: SQLite，绝不连接真实生产库；不连接 Telegram。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import aiosqlite

from bot.services.reimbursement_pool import (
    ReimbursementPoolStats,
    render_reimbursement_pool,
    _scalar_int,
    _parse_monthly_pool,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    return db


# ============ ReimbursementPoolStats dataclass ============


def test_stats_defaults_all_none():
    """空构造时所有字段都是 None（→ 渲染会显示 N/A）。"""
    stats = ReimbursementPoolStats()
    assert stats.feature_enabled is None
    assert stats.monthly_pool is None
    assert stats.month_key is None
    assert stats.week_key is None
    assert stats.approved_amount_this_month is None
    assert stats.remaining_pool is None
    assert stats.pending_count is None
    assert stats.queued_count is None
    assert stats.approved_count_this_month is None
    assert stats.rejected_count_this_month is None
    assert stats.approved_users_this_week is None
    assert stats.approved_amount_this_week is None
    assert stats.reset_vouchers_used_this_week is None
    assert stats.generated_at is None


def test_stats_can_set_all_fields():
    stats = ReimbursementPoolStats(
        feature_enabled=True,
        monthly_pool=10000,
        month_key="2026-05",
        week_key="2026-W20",
        approved_amount_this_month=3000,
        remaining_pool=7000,
        pending_count=5,
        queued_count=2,
        approved_count_this_month=20,
        rejected_count_this_month=3,
        approved_users_this_week=4,
        approved_amount_this_week=600,
        reset_vouchers_used_this_week=1,
        generated_at=datetime(2026, 5, 18, 12, 34, 56),
    )
    assert stats.feature_enabled is True
    assert stats.monthly_pool == 10000
    assert stats.remaining_pool == 7000
    assert stats.month_key == "2026-05"
    assert stats.week_key == "2026-W20"


# ============ render_reimbursement_pool ============


def test_render_contains_header_and_sections():
    text = render_reimbursement_pool(ReimbursementPoolStats())
    assert "💰 报销池状态" in text
    assert "本月报销池" in text
    assert "当前队列" in text
    assert "本周情况" in text
    assert "系统状态" in text


def test_render_contains_all_labels():
    text = render_reimbursement_pool(ReimbursementPoolStats())
    expected = [
        "月度额度",
        "已批准",
        "剩余额度",
        "待审核 pending",
        "queued 名单",
        "本月已通过",
        "本月已驳回",
        "本周已通过用户数",
        "本周已通过金额",
        "本周 reset voucher",
        "报销功能",
        "当前月份",
        "当前周",
        "更新时间",
    ]
    for label in expected:
        assert label in text, f"render 缺少标签：{label}"


def test_render_all_none_shows_na():
    """所有字段为 None 时应大量出现 N/A，且不抛错。"""
    text = render_reimbursement_pool(ReimbursementPoolStats())
    # 至少 12 个数值字段 + feature + month_key + week_key + generated_at
    assert text.count("N/A") >= 12


def test_render_remaining_pool_normal_case():
    """剩余 = 月度池 - 已批准（正数场景）。"""
    stats = ReimbursementPoolStats(
        monthly_pool=10000,
        approved_amount_this_month=3000,
        remaining_pool=7000,
    )
    text = render_reimbursement_pool(stats)
    assert "10000 元" in text
    assert "3000 元" in text
    assert "7000 元" in text
    assert "超额" not in text


def test_render_remaining_pool_overdrawn():
    """已批准超过月度池时渲染负数 + ⚠️ 提示，不报错。"""
    stats = ReimbursementPoolStats(
        monthly_pool=1000,
        approved_amount_this_month=1500,
        remaining_pool=-500,
    )
    text = render_reimbursement_pool(stats)
    assert "-500 元" in text
    assert "已超额" in text
    assert "500" in text  # abs(-500) 也要显示
    # 不应该是 N/A
    assert "剩余额度：N/A" not in text


def test_render_remaining_pool_unlimited():
    """monthly_pool == 0 表示不限，应渲染特殊文案。"""
    stats = ReimbursementPoolStats(
        monthly_pool=0,
        approved_amount_this_month=999,
        remaining_pool=-999,  # 不限模式下也允许；渲染层会忽略并显示"不限"
    )
    text = render_reimbursement_pool(stats)
    # 月度额度行显示"不限"或"不限（0）"
    assert "不限" in text
    # 剩余额度行也显示"不限"，不显示负数
    # 找到剩余额度那一行验证
    remaining_line = next(
        line for line in text.splitlines() if "剩余额度" in line
    )
    assert "不限" in remaining_line
    assert "-999" not in remaining_line


def test_render_remaining_na_when_pool_none():
    """monthly_pool=None → 剩余 N/A。"""
    stats = ReimbursementPoolStats(
        monthly_pool=None,
        approved_amount_this_month=300,
    )
    text = render_reimbursement_pool(stats)
    remaining_line = next(
        line for line in text.splitlines() if "剩余额度" in line
    )
    assert "N/A" in remaining_line


def test_render_remaining_na_when_approved_none():
    """approved_amount=None → 剩余也 N/A。"""
    stats = ReimbursementPoolStats(
        monthly_pool=5000,
        approved_amount_this_month=None,
    )
    text = render_reimbursement_pool(stats)
    remaining_line = next(
        line for line in text.splitlines() if "剩余额度" in line
    )
    assert "N/A" in remaining_line


def test_render_feature_enabled_true():
    text = render_reimbursement_pool(
        ReimbursementPoolStats(feature_enabled=True)
    )
    feature_line = next(
        line for line in text.splitlines() if "报销功能" in line
    )
    assert "开启" in feature_line
    assert "关闭" not in feature_line


def test_render_feature_enabled_false():
    text = render_reimbursement_pool(
        ReimbursementPoolStats(feature_enabled=False)
    )
    feature_line = next(
        line for line in text.splitlines() if "报销功能" in line
    )
    assert "关闭" in feature_line
    assert "开启" not in feature_line


def test_render_feature_enabled_none():
    """配置 key 不存在时应显示 N/A，而非默认到 开启 / 关闭。"""
    text = render_reimbursement_pool(
        ReimbursementPoolStats(feature_enabled=None)
    )
    feature_line = next(
        line for line in text.splitlines() if "报销功能" in line
    )
    assert "N/A" in feature_line


def test_render_month_week_key_displayed():
    stats = ReimbursementPoolStats(
        month_key="2026-05",
        week_key="2026-W20",
    )
    text = render_reimbursement_pool(stats)
    assert "2026-05" in text
    assert "2026-W20" in text


def test_render_generated_at_formatting():
    stats = ReimbursementPoolStats(
        generated_at=datetime(2026, 5, 18, 9, 30, 45),
    )
    text = render_reimbursement_pool(stats)
    assert "2026-05-18 09:30:45" in text


def test_render_is_pure_function():
    """连续两次调用同一 stats，输出一致（纯函数）。"""
    stats = ReimbursementPoolStats(
        monthly_pool=1000,
        approved_amount_this_month=100,
        remaining_pool=900,
        generated_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert render_reimbursement_pool(stats) == render_reimbursement_pool(stats)


def test_render_numbers_with_units():
    stats = ReimbursementPoolStats(
        pending_count=3,
        queued_count=4,
        approved_count_this_month=10,
        rejected_count_this_month=2,
        approved_users_this_week=5,
        approved_amount_this_week=750,
        reset_vouchers_used_this_week=1,
    )
    text = render_reimbursement_pool(stats)
    assert "3 条" in text
    assert "4 条" in text
    assert "10 条" in text
    assert "2 条" in text
    assert "5 人" in text
    assert "750 元" in text
    assert "1 次" in text


# ============ _parse_monthly_pool ============


def test_parse_monthly_pool_none():
    assert _parse_monthly_pool(None) is None


def test_parse_monthly_pool_empty_string():
    assert _parse_monthly_pool("") is None


def test_parse_monthly_pool_normal_int():
    assert _parse_monthly_pool("1000") == 1000


def test_parse_monthly_pool_zero():
    """0 应保留为 0（不限），不能变成 None。"""
    assert _parse_monthly_pool("0") == 0


def test_parse_monthly_pool_invalid_string():
    """非整数字符串 → None，不抛错。"""
    assert _parse_monthly_pool("abc") is None


# ============ _scalar_int 防御性查询 ============


def test_scalar_int_returns_int_on_success():
    async def go():
        db = await _fresh_db()
        try:
            await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            await db.execute("INSERT INTO t (id) VALUES (1)")
            await db.execute("INSERT INTO t (id) VALUES (2)")
            await db.commit()
            n = await _scalar_int(db, "SELECT COUNT(*) FROM t")
            assert n == 2
        finally:
            await db.close()
    _run(go())


def test_scalar_int_returns_none_on_missing_table():
    async def go():
        db = await _fresh_db()
        try:
            n = await _scalar_int(db, "SELECT COUNT(*) FROM nonexistent_table")
            assert n is None
        finally:
            await db.close()
    _run(go())


def test_scalar_int_empty_table_zero():
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
            await db.execute("INSERT INTO t VALUES (1, 'approved')")
            await db.execute("INSERT INTO t VALUES (2, 'approved')")
            await db.execute("INSERT INTO t VALUES (3, 'rejected')")
            await db.commit()
            n = await _scalar_int(
                db, "SELECT COUNT(*) FROM t WHERE status = ?", ("approved",),
            )
            assert n == 2
        finally:
            await db.close()
    _run(go())


# ============ 仿真 schema 验证 SQL 口径正确性 ============


def test_approved_amount_sum_in_month():
    """模拟 reimbursements 表，验证本月已批准 SUM 口径。"""
    async def go():
        db = await _fresh_db()
        try:
            await db.execute(
                """
                CREATE TABLE reimbursements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    status TEXT,
                    week_key TEXT,
                    month_key TEXT
                )
                """
            )
            await db.executescript(
                """
                INSERT INTO reimbursements (user_id, amount, status, week_key, month_key)
                VALUES
                    (1, 100, 'approved', '2026-W20', '2026-05'),
                    (2, 150, 'approved', '2026-W20', '2026-05'),
                    (3, 200, 'pending',  '2026-W20', '2026-05'),
                    (4, 100, 'approved', '2026-W19', '2026-04');
                """
            )
            await db.commit()

            sum_amount = await _scalar_int(
                db,
                "SELECT COALESCE(SUM(amount), 0) FROM reimbursements "
                "WHERE month_key = ? AND status = 'approved'",
                ("2026-05",),
            )
            assert sum_amount == 250

            count = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM reimbursements "
                "WHERE month_key = ? AND status = 'approved'",
                ("2026-05",),
            )
            assert count == 2

            users = await _scalar_int(
                db,
                "SELECT COUNT(DISTINCT user_id) FROM reimbursements "
                "WHERE week_key = ? AND status = 'approved'",
                ("2026-W20",),
            )
            assert users == 2
        finally:
            await db.close()
    _run(go())


def test_reset_voucher_join_query_against_real_schema():
    """模拟 reimbursement_resets + reimbursements，验证 reset voucher JOIN 口径。"""
    async def go():
        db = await _fresh_db()
        try:
            await db.execute(
                """
                CREATE TABLE reimbursements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER, amount INTEGER, status TEXT,
                    week_key TEXT, month_key TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE reimbursement_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER, granted_by INTEGER,
                    consumed INTEGER DEFAULT 0,
                    consumed_at TEXT, consumed_reimb_id INTEGER
                )
                """
            )
            # 本周报销 #1（被一张 reset 消耗）
            await db.execute(
                "INSERT INTO reimbursements (id, user_id, amount, status, week_key, month_key) "
                "VALUES (1, 100, 100, 'approved', '2026-W20', '2026-05')"
            )
            # 上周报销 #2（被一张 reset 消耗）
            await db.execute(
                "INSERT INTO reimbursements (id, user_id, amount, status, week_key, month_key) "
                "VALUES (2, 100, 100, 'approved', '2026-W19', '2026-04')"
            )
            # 三张 reset：
            #   r1 consumed → 本周 reimb
            #   r2 consumed → 上周 reimb
            #   r3 未消耗
            await db.execute(
                "INSERT INTO reimbursement_resets "
                "(user_id, granted_by, consumed, consumed_reimb_id) VALUES "
                "(100, 1, 1, 1), (100, 1, 1, 2), (100, 1, 0, NULL)"
            )
            await db.commit()

            n = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM reimbursement_resets r "
                "JOIN reimbursements rb ON r.consumed_reimb_id = rb.id "
                "WHERE r.consumed = 1 AND rb.week_key = ?",
                ("2026-W20",),
            )
            assert n == 1
        finally:
            await db.close()
    _run(go())


# ============ callback_data 字符串契约 ============


def test_admin_reimbursement_pool_present_in_dashboard_kb():
    """admin:reimbursement_pool 已收纳到二级「📊 数据看板」(admin_dashboard_kb)。"""
    from bot.keyboards.admin_kb import admin_dashboard_kb
    kb = admin_dashboard_kb()
    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data == "admin:reimbursement_pool":
                found = True
                assert "报销池状态" in btn.text
    assert found, "admin_dashboard_kb 缺少 admin:reimbursement_pool 入口按钮"


def test_admin_reimbursement_pool_no_longer_in_main_menu_kb():
    """主菜单不再直接含 admin:reimbursement_pool（已下沉到 admin:dashboard）。"""
    from bot.keyboards.admin_kb import main_menu_kb
    for is_super in (True, False):
        kb = main_menu_kb(is_super=is_super)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "admin:reimbursement_pool" not in callbacks, (
            f"主菜单 (is_super={is_super}) 不应再直接含 admin:reimbursement_pool"
        )


def test_admin_reimbursement_pool_refresh_callback_present_in_kb():
    """详情面板 keyboard：刷新 + 返回 admin:dashboard。

    UX-1 第一批返回路径优化（2026-05）：返回按钮从 menu:main 调整为
    二级页 admin:dashboard（📊 运营看板）。
    """
    from bot.keyboards.admin_kb import admin_reimbursement_pool_kb
    kb = admin_reimbursement_pool_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "admin:reimbursement_pool:refresh" in callbacks
    assert "admin:dashboard" in callbacks
    # UX-1：不再直接回 menu:main，走二级页 admin:dashboard
    assert "menu:main" not in callbacks


def test_admin_reimbursement_pool_callbacks_present_in_handler_source():
    """handler 源码必须直接出现两个 callback 字符串字面量。"""
    import bot.handlers.admin_panel as admin_panel_module
    import inspect
    src = inspect.getsource(admin_panel_module)
    assert '"admin:reimbursement_pool"' in src
    assert '"admin:reimbursement_pool:refresh"' in src
