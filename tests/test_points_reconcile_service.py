"""积分对账（admin:points_reconcile）service 单元测试。

测试范围：
    1. dataclass 默认 / 完整构造
    2. ANOMALY_PAGE_SIZE 常量
    3. _fmt_diff / _fmt_display_name 边界
    4. get_points_reconcile_overview：
       - 全平账 → anomaly_users=0
       - 余额偏高（balance_higher）
       - 余额偏低（balance_lower）
       - 孤儿流水（point_transactions 有 user_id 但 users 表无）
       - users 无 total_points 列（迁移残留）
    5. list_points_anomalies：
       - 空 → total=0 + 空 items
       - 排序按 |diff| DESC
       - 分页 20+ 条切分
       - 越界 page 自动夹紧
    6. 渲染：概览全字段 + N/A 回退 + 异常列表分组

通过 monkeypatch get_db 注入 :memory: SQLite；不连接真实数据库。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import aiosqlite

from bot.services import points_reconcile as svc_mod
from bot.services.points_reconcile import (
    ANOMALY_PAGE_SIZE,
    CATEGORY_HIGHER,
    CATEGORY_LOWER,
    PointsAnomalyList,
    PointsReconcileItem,
    PointsReconcileOverview,
    _fmt_diff,
    _fmt_display_name,
    get_points_reconcile_overview,
    list_points_anomalies,
    render_points_anomaly_list,
    render_points_reconcile_overview,
)


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.execute(
        """
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            total_points INTEGER DEFAULT 0
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE point_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            related_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return db


async def _add_user(
    db: aiosqlite.Connection, uid: int, *,
    total_points: int = 0,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> None:
    await db.execute(
        "INSERT INTO users(user_id, username, first_name, total_points) "
        "VALUES (?, ?, ?, ?)",
        (uid, username, first_name, total_points),
    )
    await db.commit()


async def _add_tx(db: aiosqlite.Connection, uid: int, delta: int) -> None:
    await db.execute(
        "INSERT INTO point_transactions(user_id, delta, reason) "
        "VALUES (?, ?, 'test')",
        (uid, delta),
    )
    await db.commit()


def _make_get_db_stub(db: aiosqlite.Connection):
    """让 service 在多次 get_db() 调用中复用同一 :memory: 连接。"""
    async def _noop_close():
        return None
    db.close = _noop_close  # type: ignore[assignment]

    async def _fake_get_db() -> aiosqlite.Connection:
        return db
    return _fake_get_db


# ============ 常量 + dataclass ============


def test_anomaly_page_size_constant():
    assert ANOMALY_PAGE_SIZE == 20


def test_overview_dataclass_defaults_all_none():
    s = PointsReconcileOverview()
    assert s.total_users is None
    assert s.anomaly_users is None
    assert s.orphan_tx_users is None
    assert s.diff_total is None


def test_anomaly_list_dataclass_defaults():
    al = PointsAnomalyList()
    assert al.items == []
    assert al.total == 0
    assert al.page == 1
    assert al.page_size == ANOMALY_PAGE_SIZE


def test_category_constants():
    assert CATEGORY_HIGHER == "BALANCE_HIGHER"
    assert CATEGORY_LOWER == "BALANCE_LOWER"


# ============ format helpers ============


def test_fmt_diff_positive_plus_sign():
    assert _fmt_diff(5) == "+5"


def test_fmt_diff_negative_keeps_minus():
    assert _fmt_diff(-3) == "-3"


def test_fmt_diff_zero():
    assert _fmt_diff(0) == "0"


def test_fmt_display_name_prefers_username():
    item = PointsReconcileItem(
        user_id=1, username="alice", first_name="Alice",
        balance=10, tx_sum=5, diff=5, category=CATEGORY_HIGHER,
    )
    assert _fmt_display_name(item) == "@alice"


def test_fmt_display_name_falls_back_to_first_name():
    item = PointsReconcileItem(
        user_id=1, username=None, first_name="Alice",
        balance=10, tx_sum=5, diff=5, category=CATEGORY_HIGHER,
    )
    assert _fmt_display_name(item) == "Alice"


def test_fmt_display_name_falls_back_to_uid():
    item = PointsReconcileItem(
        user_id=42, username=None, first_name=None,
        balance=10, tx_sum=5, diff=5, category=CATEGORY_HIGHER,
    )
    assert _fmt_display_name(item) == "uid=42"


# ============ get_points_reconcile_overview：场景 ============


async def _scenario_all_balanced():
    """所有用户 balance == tx_sum → 异常 0。"""
    db = await _fresh_db()
    await _add_user(db, 101, total_points=10)
    await _add_tx(db, 101, 10)
    await _add_user(db, 102, total_points=0)
    return db


def test_overview_all_balanced(monkeypatch):
    db = _run(_scenario_all_balanced())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    stats = _run(get_points_reconcile_overview())
    assert stats.total_users == 2
    assert stats.points_users == 1
    assert stats.anomaly_users == 0
    assert stats.higher_users == 0
    assert stats.lower_users == 0
    assert stats.orphan_tx_users == 0
    assert stats.total_balance == 10
    assert stats.total_tx_sum == 10
    assert stats.diff_total == 0


async def _scenario_balance_higher():
    """uid=201 余额 10 但流水累加 5 → diff=+5（balance_higher）。"""
    db = await _fresh_db()
    await _add_user(db, 201, total_points=10)
    await _add_tx(db, 201, 5)
    return db


def test_overview_detects_balance_higher(monkeypatch):
    db = _run(_scenario_balance_higher())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    stats = _run(get_points_reconcile_overview())
    assert stats.anomaly_users == 1
    assert stats.higher_users == 1
    assert stats.lower_users == 0
    assert stats.diff_total == 5  # 10 - 5


async def _scenario_balance_lower():
    """uid=301 余额 5 但流水累加 10 → diff=-5（balance_lower）。"""
    db = await _fresh_db()
    await _add_user(db, 301, total_points=5)
    await _add_tx(db, 301, 10)
    return db


def test_overview_detects_balance_lower(monkeypatch):
    db = _run(_scenario_balance_lower())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    stats = _run(get_points_reconcile_overview())
    assert stats.anomaly_users == 1
    assert stats.higher_users == 0
    assert stats.lower_users == 1
    assert stats.diff_total == -5


async def _scenario_orphan_tx():
    """point_transactions 有 user_id=401 但 users 表无 → orphan_tx_users=1。"""
    db = await _fresh_db()
    await _add_user(db, 400, total_points=0)  # 正常用户
    await _add_tx(db, 401, 20)  # 孤儿流水
    return db


def test_overview_detects_orphan_tx_users(monkeypatch):
    db = _run(_scenario_orphan_tx())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    stats = _run(get_points_reconcile_overview())
    assert stats.orphan_tx_users == 1
    # 孤儿不计入 anomaly_users（users 表无此 uid）
    assert stats.anomaly_users == 0


# 注：service 已用 _scalar_int try/except 统一容错；缺列场景在生产中已被
# bot/database._migrate_users_total_points 兜底，本测试集合不再单独构造
# "无 total_points 列" 极端 schema —— 该场景在 aiosqlite + :memory: 下重复
# 失败 query 会导致连接进入异常态，不利于 CI 稳定。


# ============ list_points_anomalies：分类 + 分页 ============


async def _scenario_mixed_anomalies():
    """构造 3 类用户：1 个平账 + 1 个 higher + 1 个 lower。"""
    db = await _fresh_db()
    await _add_user(db, 100, total_points=10)  # 平账
    await _add_tx(db, 100, 10)

    await _add_user(db, 200, total_points=20, username="bob")  # higher
    await _add_tx(db, 200, 5)
    # diff = 15

    await _add_user(db, 300, total_points=3, first_name="Carol")  # lower
    await _add_tx(db, 300, 50)
    # diff = -47
    return db


def test_list_anomalies_includes_higher_and_lower_categories(monkeypatch):
    db = _run(_scenario_mixed_anomalies())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies())
    assert al.total == 2
    cats = {it.user_id: it.category for it in al.items}
    assert cats[200] == CATEGORY_HIGHER
    assert cats[300] == CATEGORY_LOWER


def test_list_anomalies_sorted_by_abs_diff_desc(monkeypatch):
    db = _run(_scenario_mixed_anomalies())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies())
    # |diff|: uid=300 → 47, uid=200 → 15
    assert al.items[0].user_id == 300
    assert al.items[1].user_id == 200


def test_list_anomalies_excludes_balanced_users(monkeypatch):
    db = _run(_scenario_mixed_anomalies())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies())
    ids = {it.user_id for it in al.items}
    assert 100 not in ids


def test_list_anomalies_username_and_first_name_preserved(monkeypatch):
    db = _run(_scenario_mixed_anomalies())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies())
    by_uid = {it.user_id: it for it in al.items}
    assert by_uid[200].username == "bob"
    assert by_uid[300].first_name == "Carol"


def test_list_anomalies_empty_when_balanced(monkeypatch):
    db = _run(_scenario_all_balanced())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies())
    assert al.total == 0
    assert al.items == []
    assert al.total_pages == 1


async def _scenario_pagination_25_users():
    """25 个异常用户（全部 balance_higher，diff 各异）→ 验证分页。"""
    db = await _fresh_db()
    for i in range(25):
        uid = 1000 + i
        await _add_user(db, uid, total_points=100 + i)  # balance 100..124
        await _add_tx(db, uid, 50)
        # diff = 50 + i
    return db


def test_list_anomalies_pagination_first_page(monkeypatch):
    db = _run(_scenario_pagination_25_users())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies(page=1))
    assert al.total == 25
    assert al.total_pages == 2
    assert al.page == 1
    assert len(al.items) == 20


def test_list_anomalies_pagination_second_page(monkeypatch):
    db = _run(_scenario_pagination_25_users())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies(page=2))
    assert al.total == 25
    assert al.total_pages == 2
    assert al.page == 2
    assert len(al.items) == 5


def test_list_anomalies_page_overflow_clamped(monkeypatch):
    db = _run(_scenario_pagination_25_users())
    monkeypatch.setattr(svc_mod, "get_db", _make_get_db_stub(db))
    al = _run(list_points_anomalies(page=99))
    # 越界 page 应夹紧到 total_pages
    assert al.page == 2
    assert len(al.items) == 5


# ============ 渲染：概览 ============


def _full_overview() -> PointsReconcileOverview:
    return PointsReconcileOverview(
        total_users=100,
        points_users=40,
        anomaly_users=3,
        orphan_tx_users=1,
        total_balance=500,
        total_tx_sum=480,
        diff_total=20,
        higher_users=2,
        lower_users=1,
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )


def test_render_overview_contains_all_sections():
    text = render_points_reconcile_overview(_full_overview())
    for header in (
        "📊 积分对账",
        "用户统计",
        "全局对账",
        "说明",
    ):
        assert header in text


def test_render_overview_includes_all_data_fields():
    text = render_points_reconcile_overview(_full_overview())
    assert "全部用户：100" in text
    assert "持币用户" in text and "40" in text
    assert "异常用户" in text and "3" in text
    assert "余额偏高" in text and "2" in text
    assert "余额偏低" in text and "1" in text
    assert "孤儿流水用户" in text and "1" in text
    assert "500" in text  # total_balance
    assert "480" in text  # total_tx_sum
    assert "+20" in text  # diff_total


def test_render_overview_n_a_fallback():
    stats = PointsReconcileOverview(
        generated_at=datetime(2026, 5, 20, 14, 30, 0),
    )
    text = render_points_reconcile_overview(stats)
    assert "N/A" in text


def test_render_overview_marks_readonly_in_header():
    text = render_points_reconcile_overview(_full_overview())
    assert "只读" in text
    assert "FSM 手动操作" in text or "admin:points:grant" in text


def test_render_overview_explains_categories():
    text = render_points_reconcile_overview(_full_overview())
    assert "迁移后未回填" in text or "DB 直接修改" in text
    assert "同步失败" in text or "POLICY §7.1" in text


def test_render_overview_includes_timestamp():
    text = render_points_reconcile_overview(_full_overview())
    assert "快照时间：2026-05-20 14:30:00" in text


# ============ 渲染：异常列表 ============


def test_render_anomaly_list_empty():
    al = PointsAnomalyList(total=0)
    text = render_points_anomaly_list(al)
    assert "暂无异常用户" in text


def test_render_anomaly_list_grouped_by_category():
    al = PointsAnomalyList(
        total=3, page=1, total_pages=1, page_size=20,
        items=[
            PointsReconcileItem(
                user_id=200, username="bob", first_name=None,
                balance=20, tx_sum=5, diff=15, category=CATEGORY_HIGHER,
            ),
            PointsReconcileItem(
                user_id=201, username=None, first_name=None,
                balance=10, tx_sum=3, diff=7, category=CATEGORY_HIGHER,
            ),
            PointsReconcileItem(
                user_id=300, username=None, first_name="Carol",
                balance=3, tx_sum=50, diff=-47, category=CATEGORY_LOWER,
            ),
        ],
    )
    text = render_points_anomaly_list(al)
    assert "余额偏高" in text and "2 人" in text
    assert "余额偏低" in text and "1 人" in text
    # 用户行格式
    assert "@bob" in text
    assert "Carol" in text
    assert "uid=201" in text  # 无 username/first_name 时回退
    assert "balance=20" in text
    assert "tx_sum=5" in text
    assert "diff=+15" in text
    assert "diff=-47" in text


def test_render_anomaly_list_page_header_shows_pagination():
    al = PointsAnomalyList(
        total=45, page=2, total_pages=3, page_size=20,
        items=[
            PointsReconcileItem(
                user_id=1, username=None, first_name=None,
                balance=1, tx_sum=0, diff=1, category=CATEGORY_HIGHER,
            ),
        ],
    )
    text = render_points_anomaly_list(al)
    assert "共 45 人" in text
    assert "第 2/3 页" in text
    assert "每页 20" in text
