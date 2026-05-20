"""抽奖参与对账（admin:lottery_reconcile）service 单元测试。

测试范围：
    1. LotteryReconcileItem / LotteryReconcileStats dataclass 行为
    2. _compute_item 核心对账场景：
       - 正常平账
       - A 类（有 entry 无扣分）
       - B 类（有扣分无 entry）
       - D 类（重复扣分）
       - A + B + D 去重（同 uid 多类）
       - 退款抵消
       - cost=0 的 entry_count > 0 活动（边界）
    3. get_lottery_reconcile_overview SQL 过滤：
       - 排除 status='draft'
       - 排除 entry_cost_points=0
       - 列表口径与 detail 口径一致
    4. get_lottery_reconcile_detail：
       - cost=0 → None
       - 不存在 lid → None
    5. render_lottery_reconcile_overview / render_lottery_reconcile_detail

仅使用 :memory: SQLite，不连接真实生产库；不连接 Telegram。
为避免引入 pytest-asyncio，async 通过 asyncio.run 同步包裹。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import aiosqlite

from bot.services import lottery_reconcile as svc_mod
from bot.services.lottery_reconcile import (
    ANOMALY_PAGE_SIZE,
    LotteryAnomalyList,
    LotteryAnomalyUser,
    LotteryReconcileItem,
    LotteryReconcileStats,
    RECONCILE_LIST_LIMIT,
    _compute_item,
    list_lottery_anomalies,
    render_lottery_anomaly_list,
    render_lottery_reconcile_detail,
    render_lottery_reconcile_overview,
    get_lottery_reconcile_overview,
    get_lottery_reconcile_detail,
)


# ============ helpers ============


def _run(coro):
    return asyncio.run(coro)


async def _fresh_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await _setup_tables(db)
    return db


async def _setup_tables(db: aiosqlite.Connection) -> None:
    """与生产 schema 字段子集一致。"""
    await db.execute(
        """
        CREATE TABLE lotteries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            status TEXT,
            entry_cost_points INTEGER DEFAULT 0,
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
            won INTEGER DEFAULT 0,
            UNIQUE(lottery_id, user_id)
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


async def _create_lottery(
    db: aiosqlite.Connection,
    *,
    name: str = "测试活动",
    status: str = "active",
    cost: int = 10,
    draw_at: Optional[str] = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO lotteries(name, status, entry_cost_points, draw_at) "
        "VALUES (?, ?, ?, ?)",
        (name, status, cost, draw_at),
    )
    await db.commit()
    return int(cur.lastrowid)


async def _add_entry(
    db: aiosqlite.Connection, lid: int, uid: int, won: int = 0,
) -> None:
    await db.execute(
        "INSERT INTO lottery_entries(lottery_id, user_id, won) VALUES (?, ?, ?)",
        (lid, uid, won),
    )
    await db.commit()


async def _add_tx(
    db: aiosqlite.Connection, uid: int, delta: int, reason: str, lid: int,
) -> None:
    await db.execute(
        "INSERT INTO point_transactions(user_id, delta, reason, related_id) "
        "VALUES (?, ?, ?, ?)",
        (uid, delta, reason, lid),
    )
    await db.commit()


async def _fetch_lottery_row(db: aiosqlite.Connection, lid: int) -> aiosqlite.Row:
    cur = await db.execute(
        "SELECT id, name, status, entry_cost_points, draw_at FROM lotteries "
        "WHERE id = ?",
        (lid,),
    )
    row = await cur.fetchone()
    assert row is not None
    return row


# ============ dataclass 行为 ============


def test_item_construction_full_fields():
    item = LotteryReconcileItem(
        id=1,
        name="春节抽奖",
        status="drawn",
        entry_cost_points=10,
        entry_count=5,
        winner_count=1,
        expected_deduct=50,
        actual_deduct=50,
        refunded=0,
        net_deduct=50,
        diff=0,
        anomaly_count_a=0,
        anomaly_count_b=0,
        anomaly_count_d=0,
        anomaly_users=0,
        draw_at="2026-02-10 18:00:00",
    )
    assert item.id == 1
    assert item.diff == 0
    assert item.anomaly_users == 0


def test_stats_defaults_empty_items():
    stats = LotteryReconcileStats()
    assert stats.items == []
    assert stats.total_paid_lotteries is None
    assert stats.total_anomaly_lotteries is None
    assert stats.generated_at is None


def test_reconcile_list_limit_constant():
    """常量集中定义防止漂移。"""
    assert RECONCILE_LIST_LIMIT == 20


# ============ _compute_item：核心对账场景 ============


async def _scenario_normal_balanced():
    """5 entries × cost=10，5 条扣分流水 → 平账。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    for uid in range(101, 106):
        await _add_entry(db, lid, uid)
        await _add_tx(db, uid, -10, "lottery_entry", lid)
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_normal_balanced():
    item = _run(_scenario_normal_balanced())
    assert item.entry_count == 5
    assert item.expected_deduct == 50
    assert item.actual_deduct == 50
    assert item.refunded == 0
    assert item.net_deduct == 50
    assert item.diff == 0
    assert item.anomaly_count_a == 0
    assert item.anomaly_count_b == 0
    assert item.anomaly_count_d == 0
    assert item.anomaly_users == 0


async def _scenario_anomaly_a():
    """3 entries，只 2 条扣分流水 → A=1 / 差异 +10。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    # 三个用户 entry
    for uid in (201, 202, 203):
        await _add_entry(db, lid, uid)
    # 仅前两个扣分；uid=203 漏扣
    await _add_tx(db, 201, -10, "lottery_entry", lid)
    await _add_tx(db, 202, -10, "lottery_entry", lid)
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_anomaly_a_entry_without_deduction():
    item = _run(_scenario_anomaly_a())
    assert item.entry_count == 3
    assert item.expected_deduct == 30
    assert item.actual_deduct == 20
    assert item.diff == 10  # 期望 30 - 净扣 20
    assert item.anomaly_count_a == 1
    assert item.anomaly_count_b == 0
    assert item.anomaly_count_d == 0
    assert item.anomaly_users == 1


async def _scenario_anomaly_b():
    """1 entry，2 条扣分流水（多余 uid 不在 entries）→ B=1。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    await _add_entry(db, lid, 301)
    # 正确扣分
    await _add_tx(db, 301, -10, "lottery_entry", lid)
    # uid=302 有扣分但无 entry
    await _add_tx(db, 302, -10, "lottery_entry", lid)
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_anomaly_b_deduction_without_entry():
    item = _run(_scenario_anomaly_b())
    assert item.entry_count == 1
    assert item.expected_deduct == 10
    assert item.actual_deduct == 20  # 两条扣分
    assert item.diff == -10  # 期望 10 - 净扣 20 = -10（多扣）
    assert item.anomaly_count_a == 0
    assert item.anomaly_count_b == 1
    assert item.anomaly_count_d == 0
    assert item.anomaly_users == 1


async def _scenario_anomaly_d():
    """1 entry，同 uid 扣 2 次 → D=1。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    await _add_entry(db, lid, 401)
    await _add_tx(db, 401, -10, "lottery_entry", lid)
    await _add_tx(db, 401, -10, "lottery_entry", lid)  # 重复
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_anomaly_d_duplicate_deduction():
    item = _run(_scenario_anomaly_d())
    assert item.entry_count == 1
    assert item.expected_deduct == 10
    assert item.actual_deduct == 20
    assert item.diff == -10
    assert item.anomaly_count_a == 0
    assert item.anomaly_count_b == 0
    assert item.anomaly_count_d == 1
    assert item.anomaly_users == 1


async def _scenario_anomaly_a_b_d_union_dedup():
    """A + B + D 各 1 人 → anomaly_users = 3（不同 uid）。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    # A：uid=501 有 entry 无扣分
    await _add_entry(db, lid, 501)
    # B：uid=502 无 entry 有扣分
    await _add_tx(db, 502, -10, "lottery_entry", lid)
    # D：uid=503 有 entry + 2 条扣分
    await _add_entry(db, lid, 503)
    await _add_tx(db, 503, -10, "lottery_entry", lid)
    await _add_tx(db, 503, -10, "lottery_entry", lid)
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_anomaly_abd_union_three_distinct_users():
    item = _run(_scenario_anomaly_a_b_d_union_dedup())
    assert item.anomaly_count_a == 1
    assert item.anomaly_count_b == 1
    assert item.anomaly_count_d == 1
    assert item.anomaly_users == 3


async def _scenario_refund_offset():
    """5 entries × 10，1 条 lottery_refund +10 → 净扣 40，差异 = 50 - 40 = 10。"""
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)
    for uid in range(601, 606):
        await _add_entry(db, lid, uid)
        await _add_tx(db, uid, -10, "lottery_entry", lid)
    # 退款一个用户
    await _add_tx(db, 601, 10, "lottery_refund", lid)
    row = await _fetch_lottery_row(db, lid)
    item = await _compute_item(db, row)
    await db.close()
    return item


def test_compute_item_refund_reduces_net_deduct():
    item = _run(_scenario_refund_offset())
    assert item.expected_deduct == 50
    assert item.actual_deduct == 50
    assert item.refunded == 10
    assert item.net_deduct == 40
    assert item.diff == 10


# ============ get_lottery_reconcile_overview / detail：通过 monkeypatch 集成 ============


def _make_get_db_stub(db: aiosqlite.Connection):
    """返回一个 async 替身：调用时返回固定 db，并把 close 改为 no-op。"""
    original_close = db.close

    async def _noop_close():
        return None

    db.close = _noop_close  # type: ignore[assignment]

    async def _fake_get_db() -> aiosqlite.Connection:
        return db

    return _fake_get_db, original_close


async def _setup_overview_scenario():
    """构造 3 个活动：
        L1 cost=10 active   → 平账
        L2 cost=10 cancelled → A 类异常 1
        L3 cost=0  active   → 免费活动（应被列表过滤）
        L4 cost=10 draft    → 草稿（应被列表过滤）
    """
    db = await _fresh_db()
    l1 = await _create_lottery(db, name="L1 平账", status="active", cost=10)
    await _add_entry(db, l1, 1001)
    await _add_tx(db, 1001, -10, "lottery_entry", l1)

    l2 = await _create_lottery(db, name="L2 异常", status="cancelled", cost=10)
    await _add_entry(db, l2, 1002)
    await _add_entry(db, l2, 1003)
    # 仅 1002 扣分，1003 漏扣
    await _add_tx(db, 1002, -10, "lottery_entry", l2)

    l3 = await _create_lottery(db, name="L3 免费", status="active", cost=0)
    await _add_entry(db, l3, 1004)

    l4 = await _create_lottery(db, name="L4 草稿", status="draft", cost=10)

    return db, l1, l2, l3, l4


def test_get_overview_filters_draft_and_zero_cost(monkeypatch):
    db, l1, l2, l3, l4 = _run(_setup_overview_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)
    stats = _run(get_lottery_reconcile_overview())
    ids = [it.id for it in stats.items]
    assert l1 in ids
    assert l2 in ids
    assert l3 not in ids  # 免费过滤
    assert l4 not in ids  # 草稿过滤
    assert stats.total_paid_lotteries == 2  # L1 + L2
    assert stats.total_anomaly_lotteries == 1  # 仅 L2 有异常
    _run(_restore())


def test_get_overview_items_match_detail(monkeypatch):
    """同一活动在 overview 与 detail 两个入口对账口径必须一致。"""
    db, l1, l2, _l3, _l4 = _run(_setup_overview_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)
    stats = _run(get_lottery_reconcile_overview())
    for it in stats.items:
        detail = _run(get_lottery_reconcile_detail(it.id))
        assert detail is not None
        assert detail.id == it.id
        assert detail.expected_deduct == it.expected_deduct
        assert detail.actual_deduct == it.actual_deduct
        assert detail.diff == it.diff
        assert detail.anomaly_users == it.anomaly_users
    _run(_restore())


def test_get_detail_returns_none_for_free_lottery(monkeypatch):
    db, _l1, _l2, l3, _l4 = _run(_setup_overview_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)
    detail = _run(get_lottery_reconcile_detail(l3))  # cost=0
    assert detail is None
    _run(_restore())


def test_get_detail_returns_none_for_nonexistent(monkeypatch):
    db, *_ = _run(_setup_overview_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)
    detail = _run(get_lottery_reconcile_detail(99999))
    assert detail is None
    _run(_restore())


# ============ 渲染：纯函数 ============


def _balanced_item() -> LotteryReconcileItem:
    return LotteryReconcileItem(
        id=1,
        name="平账活动",
        status="drawn",
        entry_cost_points=10,
        entry_count=5,
        winner_count=1,
        expected_deduct=50,
        actual_deduct=50,
        refunded=0,
        net_deduct=50,
        diff=0,
        anomaly_count_a=0,
        anomaly_count_b=0,
        anomaly_count_d=0,
        anomaly_users=0,
        draw_at="2026-02-10 18:00:00",
    )


def _diverging_item() -> LotteryReconcileItem:
    return LotteryReconcileItem(
        id=2,
        name="差异活动",
        status="active",
        entry_cost_points=10,
        entry_count=3,
        winner_count=0,
        expected_deduct=30,
        actual_deduct=20,
        refunded=0,
        net_deduct=20,
        diff=10,
        anomaly_count_a=1,
        anomaly_count_b=0,
        anomaly_count_d=0,
        anomaly_users=1,
        draw_at=None,
    )


def test_render_overview_header_and_summary():
    stats = LotteryReconcileStats(
        items=[_balanced_item(), _diverging_item()],
        total_paid_lotteries=2,
        total_anomaly_lotteries=1,
        generated_at=datetime(2026, 5, 20, 12, 0, 0),
    )
    text = render_lottery_reconcile_overview(stats)
    assert "📊 抽奖对账" in text
    assert "积分门票活动数：2" in text
    assert "有差异 / 异常活动数：1" in text
    assert "更新时间：2026-05-20 12:00:00" in text


def test_render_overview_balanced_label():
    stats = LotteryReconcileStats(items=[_balanced_item()])
    text = render_lottery_reconcile_overview(stats)
    assert "✅ 平账" in text


def test_render_overview_divergence_label():
    stats = LotteryReconcileStats(items=[_diverging_item()])
    text = render_lottery_reconcile_overview(stats)
    assert "⚠️" in text
    assert "差异 +10" in text
    assert "异常 1 人" in text


def test_render_overview_empty_items():
    stats = LotteryReconcileStats(
        items=[], total_paid_lotteries=0, total_anomaly_lotteries=0,
    )
    text = render_lottery_reconcile_overview(stats)
    assert "暂无积分门票活动" in text


def test_render_detail_all_eight_metrics():
    """详情页 8 项指标必须全部出现。"""
    item = _diverging_item()
    text = render_lottery_reconcile_detail(item)
    assert "期望扣分：30" in text
    assert "实际扣分：20" in text
    assert "退款总额：0" in text
    assert "净扣分：20" in text
    assert "差异：+10" in text
    assert "A 有 entry 无扣分：1 人" in text
    assert "B 有扣分无 entry：0 人" in text
    assert "D 重复扣分：0 人" in text
    assert "异常用户总数（A∪B∪D 去重）：1" in text


def test_render_detail_balanced_shows_check_mark():
    text = render_lottery_reconcile_detail(_balanced_item())
    assert "✅ 平账" in text


def test_render_detail_includes_meta_fields():
    text = render_lottery_reconcile_detail(_balanced_item())
    assert "名称：平账活动" in text
    assert "状态：drawn" in text
    assert "开奖时间：2026-02-10 18:00" in text
    assert "积分门票：10 分" in text


def test_render_detail_handles_missing_draw_at():
    item = _diverging_item()  # draw_at=None
    text = render_lottery_reconcile_detail(item)
    assert "开奖时间：N/A" in text


# ============ 边界：负值差异显示带 - 号 ============


def test_diff_format_negative():
    item = LotteryReconcileItem(
        id=3, name="多扣", status="drawn", entry_cost_points=10,
        entry_count=1, winner_count=0,
        expected_deduct=10, actual_deduct=30, refunded=0, net_deduct=30,
        diff=-20,
        anomaly_count_a=0, anomaly_count_b=0, anomaly_count_d=0,
        anomaly_users=0,
    )
    text = render_lottery_reconcile_detail(item)
    assert "差异：-20" in text


# ============ §4.2.2 异常用户列表 ============


def test_anomaly_page_size_constant():
    assert ANOMALY_PAGE_SIZE == 20


def test_anomaly_user_dataclass_defaults():
    au = LotteryAnomalyUser(user_id=1, category="A")
    assert au.entry_id is None
    assert au.tx_ids == []
    assert au.tx_total_delta == 0


def test_anomaly_list_dataclass_defaults():
    al = LotteryAnomalyList(lid=42)
    assert al.items == []
    assert al.total == 0
    assert al.page == 1
    assert al.page_size == ANOMALY_PAGE_SIZE
    assert al.total_pages == 1


async def _setup_anomaly_scenario():
    """构造 1 个活动，含 A / B / D 三类异常 + 1 个正常用户。

    布局：
        uid=100 正常：有 entry + 1 条扣分 → 不在异常列表
        uid=201 A 类：有 entry，无扣分流水
        uid=202 A 类：有 entry，无扣分流水
        uid=301 B 类：1 条扣分流水，无 entry
        uid=401 D 类：有 entry + 2 条扣分流水
        uid=402 D∩B 类：2 条扣分流水，无 entry → 归 D（按 D > B 优先级）
    """
    db = await _fresh_db()
    lid = await _create_lottery(db, cost=10)

    # 正常
    await _add_entry(db, lid, 100)
    await _add_tx(db, 100, -10, "lottery_entry", lid)

    # A 类
    await _add_entry(db, lid, 201)
    await _add_entry(db, lid, 202)

    # B 类
    await _add_tx(db, 301, -10, "lottery_entry", lid)

    # D 类（有 entry）
    await _add_entry(db, lid, 401)
    await _add_tx(db, 401, -10, "lottery_entry", lid)
    await _add_tx(db, 401, -10, "lottery_entry", lid)

    # D∩B（无 entry，但流水 2 条）→ 归 D
    await _add_tx(db, 402, -10, "lottery_entry", lid)
    await _add_tx(db, 402, -10, "lottery_entry", lid)

    return db, lid


def test_list_anomalies_categorizes_a_b_d(monkeypatch):
    db, lid = _run(_setup_anomaly_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    assert al.lid == lid
    assert al.total == 5  # A×2 + B×1 + D×2（不含正常 uid=100）

    cats = {it.user_id: it.category for it in al.items}
    assert cats[201] == "A"
    assert cats[202] == "A"
    assert cats[301] == "B"
    assert cats[401] == "D"
    assert cats[402] == "D"  # D > B 优先级
    assert 100 not in cats

    _run(_restore())


def test_list_anomalies_order_d_before_b_before_a(monkeypatch):
    db, lid = _run(_setup_anomaly_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    cats_in_order = [it.category for it in al.items]
    # 应为：D D B A A
    assert cats_in_order == ["D", "D", "B", "A", "A"]

    _run(_restore())


def test_list_anomalies_d_includes_tx_ids_and_total_delta(monkeypatch):
    db, lid = _run(_setup_anomaly_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    d_401 = next(it for it in al.items if it.user_id == 401)
    assert d_401.category == "D"
    assert d_401.entry_id is not None  # 有 entry
    assert len(d_401.tx_ids) == 2
    assert d_401.tx_total_delta == -20

    d_402 = next(it for it in al.items if it.user_id == 402)
    assert d_402.category == "D"
    assert d_402.entry_id is None  # D∩B：无 entry
    assert len(d_402.tx_ids) == 2
    assert d_402.tx_total_delta == -20

    _run(_restore())


def test_list_anomalies_b_has_single_tx_no_entry(monkeypatch):
    db, lid = _run(_setup_anomaly_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    b_301 = next(it for it in al.items if it.user_id == 301)
    assert b_301.category == "B"
    assert b_301.entry_id is None
    assert len(b_301.tx_ids) == 1
    assert b_301.tx_total_delta == -10

    _run(_restore())


def test_list_anomalies_a_has_entry_id_no_tx(monkeypatch):
    db, lid = _run(_setup_anomaly_scenario())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    a_201 = next(it for it in al.items if it.user_id == 201)
    assert a_201.category == "A"
    assert a_201.entry_id is not None
    assert a_201.tx_ids == []
    assert a_201.tx_total_delta == 0

    _run(_restore())


def test_list_anomalies_empty_when_balanced(monkeypatch):
    """5 entries × 10 全部扣分，应为 0 异常用户。"""
    async def _setup():
        db = await _fresh_db()
        lid = await _create_lottery(db, cost=10)
        for uid in range(101, 106):
            await _add_entry(db, lid, uid)
            await _add_tx(db, uid, -10, "lottery_entry", lid)
        return db, lid
    db, lid = _run(_setup())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    al = _run(list_lottery_anomalies(lid))
    assert al.total == 0
    assert al.items == []
    assert al.total_pages == 1

    _run(_restore())


def test_list_anomalies_pagination(monkeypatch):
    """构造 25 个 A 类异常，验证 page=1/2 切分。"""
    async def _setup():
        db = await _fresh_db()
        lid = await _create_lottery(db, cost=10)
        for uid in range(1000, 1025):  # 25 个 A 类
            await _add_entry(db, lid, uid)
        return db, lid
    db, lid = _run(_setup())
    fake_get_db, _restore = _make_get_db_stub(db)
    monkeypatch.setattr(svc_mod, "get_db", fake_get_db)

    p1 = _run(list_lottery_anomalies(lid, page=1))
    assert p1.total == 25
    assert p1.total_pages == 2
    assert len(p1.items) == 20  # ANOMALY_PAGE_SIZE
    assert p1.page == 1

    p2 = _run(list_lottery_anomalies(lid, page=2))
    assert p2.total == 25
    assert p2.total_pages == 2
    assert len(p2.items) == 5
    assert p2.page == 2

    # 越界 page 自动夹紧
    p99 = _run(list_lottery_anomalies(lid, page=99))
    assert p99.page == 2
    assert len(p99.items) == 5

    _run(_restore())


# ============ 异常列表渲染 ============


def test_render_anomaly_list_empty():
    al = LotteryAnomalyList(lid=7)
    text = render_lottery_anomaly_list(al)
    assert "📋 异常用户 · 抽奖 #7" in text
    assert "暂无异常用户" in text


def test_render_anomaly_list_grouped_by_category():
    al = LotteryAnomalyList(
        lid=8, total=3, page=1, page_size=20, total_pages=1,
        items=[
            LotteryAnomalyUser(
                user_id=100, category="D", entry_id=10,
                tx_ids=[1, 2], tx_total_delta=-20,
            ),
            LotteryAnomalyUser(
                user_id=200, category="B", entry_id=None,
                tx_ids=[5], tx_total_delta=-10,
            ),
            LotteryAnomalyUser(
                user_id=300, category="A", entry_id=20,
            ),
        ],
    )
    text = render_lottery_anomaly_list(al)
    assert "D 重复扣分（1 人）" in text
    assert "B 有扣分无 entry（1 人）" in text
    assert "A 有 entry 无扣分（1 人）" in text
    # 三种格式
    assert "uid=100" in text
    assert "tx_ids=[1,2]" in text
    assert "uid=200" in text
    assert "tx_id=5" in text
    assert "uid=300" in text
    assert "entry_id=20" in text


def test_render_anomaly_list_page_header():
    al = LotteryAnomalyList(
        lid=9, total=42, page=2, page_size=20, total_pages=3,
        items=[
            LotteryAnomalyUser(user_id=i, category="A", entry_id=i)
            for i in range(100, 120)
        ],
    )
    text = render_lottery_anomaly_list(al)
    assert "共 42 人" in text
    assert "第 2/3 页" in text


def test_render_anomaly_d_no_entry_shows_marker():
    """D∩B（无 entry）应显式渲染「无 entry」标识，避免误读为 D∩A。"""
    al = LotteryAnomalyList(
        lid=10, total=1, page=1, total_pages=1,
        items=[
            LotteryAnomalyUser(
                user_id=999, category="D",
                entry_id=None, tx_ids=[7, 8],
                tx_total_delta=-20,
            ),
        ],
    )
    text = render_lottery_anomaly_list(al)
    assert "无 entry" in text
    assert "tx_ids=[7,8]" in text
