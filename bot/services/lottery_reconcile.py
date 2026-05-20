"""管理员后台「📊 抽奖对账」只读对账服务（Sprint 2 §4.2.1）。

提供：
    - LotteryReconcileItem / LotteryReconcileStats：dataclass 数据结构
    - get_lottery_reconcile_overview()：列表页（最近 N 条 cost>0 且非 draft 活动）
    - get_lottery_reconcile_detail(lid)：单活动详情
    - render_lottery_reconcile_overview / render_lottery_reconcile_detail：纯渲染

对账口径（仅对 entry_cost_points > 0 且 status != 'draft' 的活动）：
    期望扣分 = entry_count × entry_cost_points
              其中 entry_count = COUNT(lottery_entries WHERE lottery_id=L)

    实际扣分 = -SUM(delta) FROM point_transactions
              WHERE reason='lottery_entry' AND related_id=L
              （delta 为负，取负号变为正数）

    退款    = SUM(delta) FROM point_transactions
              WHERE reason='lottery_refund' AND related_id=L
              （delta 为正数）

    净扣分 = 实际扣分 - 退款
    差异   = 期望扣分 - 净扣分
            > 0 少扣（漏扣 / 退款过多）；< 0 多扣；= 0 平账

异常 4 类：
    A 有 entry 无扣分：lottery_entries 有 (uid, L) 但 point_transactions
                       无 (uid, 'lottery_entry', L)
    B 有扣分无 entry：point_transactions 有 (uid, 'lottery_entry', L) 但
                       lottery_entries 无 (uid, L)
    C 双向缺失：SQL 视角不可能出现，常量 0，不展示
    D 重复扣分：同 (uid, L) 在 point_transactions 'lottery_entry' ≥ 2 次

异常人数 = unique users in A ∪ B ∪ D

设计原则：
    - 全程只读：不写任何表、不修改抽奖创建 / 参与 / 扣分 / 开奖逻辑
    - 防御性查询：单点失败 → 该字段 None / 0，渲染时降级，不影响其它指标
    - 不导出文件、不提供修复按钮（§4.3 禁止事项）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

logger = logging.getLogger(__name__)


RECONCILE_LIST_LIMIT = 20


@dataclass
class LotteryReconcileItem:
    """单活动对账数据。"""

    id: int
    name: str
    status: str
    entry_cost_points: int
    entry_count: int
    winner_count: int
    expected_deduct: int
    actual_deduct: int
    refunded: int
    net_deduct: int
    diff: int
    anomaly_count_a: int
    anomaly_count_b: int
    anomaly_count_d: int
    anomaly_users: int
    draw_at: Optional[str] = None


@dataclass
class LotteryReconcileStats:
    """对账列表页聚合数据。"""

    items: list[LotteryReconcileItem] = field(default_factory=list)
    total_paid_lotteries: Optional[int] = None
    total_anomaly_lotteries: Optional[int] = None
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


async def _scalar_int(
    db: aiosqlite.Connection, sql: str, params: tuple = (),
) -> Optional[int]:
    """执行标量整数 SQL；空结果返 0；异常返 None。"""
    try:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            return 0
        value = row[0]
        return int(value) if value is not None else 0
    except Exception as e:
        logger.warning("lottery_reconcile 标量查询失败: sql=%r err=%s", sql, e)
        return None


async def _compute_item(
    db: aiosqlite.Connection,
    lottery_row: aiosqlite.Row,
) -> LotteryReconcileItem:
    """对单条 lottery row 计算完整对账字段。

    lottery_row 必须包含：id / name / status / entry_cost_points / draw_at。
    其它指标本函数内部独立查询，单点失败降级到 0（不抛异常）。
    """
    lid = int(lottery_row["id"])
    cost = int(lottery_row["entry_cost_points"] or 0)

    entry_count = await _scalar_int(
        db,
        "SELECT COUNT(*) FROM lottery_entries WHERE lottery_id = ?",
        (lid,),
    ) or 0

    winner_count = await _scalar_int(
        db,
        "SELECT COUNT(*) FROM lottery_entries WHERE lottery_id = ? AND won = 1",
        (lid,),
    ) or 0

    sum_entry_delta = await _scalar_int(
        db,
        "SELECT COALESCE(SUM(delta), 0) FROM point_transactions "
        "WHERE reason = 'lottery_entry' AND related_id = ?",
        (lid,),
    ) or 0
    actual_deduct = -int(sum_entry_delta)

    refunded = await _scalar_int(
        db,
        "SELECT COALESCE(SUM(delta), 0) FROM point_transactions "
        "WHERE reason = 'lottery_refund' AND related_id = ?",
        (lid,),
    ) or 0

    expected_deduct = entry_count * cost
    net_deduct = actual_deduct - int(refunded)
    diff = expected_deduct - net_deduct

    # A 类：有 entry 无 lottery_entry 扣分流水
    anomaly_a = await _scalar_int(
        db,
        "SELECT COUNT(DISTINCT e.user_id) FROM lottery_entries e "
        "WHERE e.lottery_id = ? "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM point_transactions p "
        "  WHERE p.reason = 'lottery_entry' "
        "  AND p.related_id = e.lottery_id "
        "  AND p.user_id = e.user_id"
        ")",
        (lid,),
    ) or 0

    # B 类：有 lottery_entry 扣分流水但无 entry
    anomaly_b = await _scalar_int(
        db,
        "SELECT COUNT(DISTINCT p.user_id) FROM point_transactions p "
        "WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM lottery_entries e "
        "  WHERE e.lottery_id = p.related_id "
        "  AND e.user_id = p.user_id"
        ")",
        (lid,),
    ) or 0

    # D 类：(uid, lid) 在 lottery_entry 流水中 ≥ 2 次
    anomaly_d = await _scalar_int(
        db,
        "SELECT COUNT(*) FROM ("
        "  SELECT p.user_id FROM point_transactions p "
        "  WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
        "  GROUP BY p.user_id HAVING COUNT(*) >= 2"
        ")",
        (lid,),
    ) or 0

    # 异常人数 = |A ∪ B ∪ D| distinct user_id
    anomaly_users = await _scalar_int(
        db,
        "SELECT COUNT(DISTINCT uid) FROM ("
        # A
        "  SELECT e.user_id AS uid FROM lottery_entries e "
        "  WHERE e.lottery_id = ? "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM point_transactions p "
        "    WHERE p.reason = 'lottery_entry' "
        "    AND p.related_id = e.lottery_id "
        "    AND p.user_id = e.user_id"
        "  ) "
        "  UNION "
        # B
        "  SELECT p.user_id AS uid FROM point_transactions p "
        "  WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM lottery_entries e "
        "    WHERE e.lottery_id = p.related_id "
        "    AND e.user_id = p.user_id"
        "  ) "
        "  UNION "
        # D
        "  SELECT p.user_id AS uid FROM point_transactions p "
        "  WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
        "  GROUP BY p.user_id HAVING COUNT(*) >= 2"
        ")",
        (lid, lid, lid),
    ) or 0

    return LotteryReconcileItem(
        id=lid,
        name=str(lottery_row["name"] or "(未命名)"),
        status=str(lottery_row["status"] or ""),
        entry_cost_points=cost,
        entry_count=int(entry_count),
        winner_count=int(winner_count),
        expected_deduct=int(expected_deduct),
        actual_deduct=int(actual_deduct),
        refunded=int(refunded),
        net_deduct=int(net_deduct),
        diff=int(diff),
        anomaly_count_a=int(anomaly_a),
        anomaly_count_b=int(anomaly_b),
        anomaly_count_d=int(anomaly_d),
        anomaly_users=int(anomaly_users),
        draw_at=lottery_row["draw_at"] if "draw_at" in lottery_row.keys() else None,
    )


async def get_lottery_reconcile_overview(
    limit: int = RECONCILE_LIST_LIMIT,
) -> LotteryReconcileStats:
    """列表页：最近 N 条 cost>0 且非 draft 的活动，每条带完整对账字段。"""
    stats = LotteryReconcileStats(generated_at=_now_local())

    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "SELECT id, name, status, entry_cost_points, draw_at "
                "FROM lotteries "
                "WHERE entry_cost_points > 0 AND status != 'draft' "
                "ORDER BY created_at DESC, id DESC "
                "LIMIT ?",
                (int(limit),),
            )
            rows = await cur.fetchall()
        except Exception as e:
            logger.warning("lottery_reconcile list 查询失败: %s", e)
            rows = []

        items: list[LotteryReconcileItem] = []
        for row in rows:
            try:
                items.append(await _compute_item(db, row))
            except Exception as e:
                logger.warning(
                    "lottery_reconcile _compute_item 失败 lid=%s: %s",
                    row["id"] if "id" in row.keys() else "?", e,
                )

        stats.items = items
        stats.total_paid_lotteries = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM lotteries "
            "WHERE entry_cost_points > 0 AND status != 'draft'",
        )
        stats.total_anomaly_lotteries = sum(
            1 for it in items if it.anomaly_users > 0 or it.diff != 0
        )
    finally:
        await db.close()

    return stats


async def get_lottery_reconcile_detail(lid: int) -> Optional[LotteryReconcileItem]:
    """单活动详情：重新精确计算，避免列表口径误差。

    若活动不存在或 cost=0，返回 None。
    """
    db = await get_db()
    try:
        try:
            cur = await db.execute(
                "SELECT id, name, status, entry_cost_points, draw_at "
                "FROM lotteries WHERE id = ?",
                (int(lid),),
            )
            row = await cur.fetchone()
        except Exception as e:
            logger.warning("lottery_reconcile detail 查询失败 lid=%s: %s", lid, e)
            return None
        if row is None:
            return None
        cost = int(row["entry_cost_points"] or 0)
        if cost <= 0:
            return None
        return await _compute_item(db, row)
    finally:
        await db.close()


# ============ 渲染 ============


def _fmt_int(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_diff(diff: int) -> str:
    """差异显示带正负号：+10 / -5 / 0。"""
    if diff > 0:
        return f"+{diff}"
    return str(diff)


def _fmt_dt(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    if len(value) >= 16:
        return value[:16]
    return value


def _item_status_label(item: LotteryReconcileItem) -> str:
    """单条活动的状态标识："""
    if item.diff == 0 and item.anomaly_users == 0:
        return "✅ 平账"
    parts: list[str] = []
    if item.diff != 0:
        parts.append(f"差异 {_fmt_diff(item.diff)}")
    if item.anomaly_users > 0:
        parts.append(f"异常 {item.anomaly_users} 人")
    return "⚠️ " + " / ".join(parts)


def render_lottery_reconcile_overview(stats: LotteryReconcileStats) -> str:
    """对账列表页文本。"""
    if stats.generated_at is not None:
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    lines: list[str] = [
        "📊 抽奖对账",
        "",
        f"积分门票活动数：{_fmt_int(stats.total_paid_lotteries)}",
        f"有差异 / 异常活动数：{_fmt_int(stats.total_anomaly_lotteries)}",
        "",
        "对账列表（最近活动）",
    ]

    if not stats.items:
        lines.append("暂无积分门票活动")
    else:
        for i, item in enumerate(stats.items):
            if i > 0:
                lines.append("")
            lines.append(f"#{item.id} {item.name}")
            lines.append(f"状态：{item.status or 'N/A'}")
            lines.append(
                f"参与 {item.entry_count} 人 × {item.entry_cost_points} 分 "
                f"= 期望 {item.expected_deduct}"
            )
            lines.append(
                f"实际扣 {item.actual_deduct}，退款 {item.refunded}，"
                f"净扣 {item.net_deduct}"
            )
            lines.append(_item_status_label(item))

    lines.append("")
    lines.append(f"更新时间：{ts_str}")
    return "\n".join(lines)


def render_lottery_reconcile_detail(item: LotteryReconcileItem) -> str:
    """单活动详情页文本。"""
    lines: list[str] = [
        f"📊 抽奖对账 · #{item.id}",
        "",
        f"名称：{item.name}",
        f"状态：{item.status or 'N/A'}",
        f"开奖时间：{_fmt_dt(item.draw_at)}",
        f"积分门票：{item.entry_cost_points} 分",
        "",
        "参与与扣分",
        f"• 参与人数：{item.entry_count}",
        f"• 中奖人数：{item.winner_count}",
        f"• 期望扣分：{item.expected_deduct} "
        f"({item.entry_count} × {item.entry_cost_points})",
        f"• 实际扣分：{item.actual_deduct}",
        f"• 退款总额：{item.refunded}",
        f"• 净扣分：{item.net_deduct}",
        f"• 差异：{_fmt_diff(item.diff)}",
        "",
        "异常分类",
        f"• A 有 entry 无扣分：{item.anomaly_count_a} 人",
        f"• B 有扣分无 entry：{item.anomaly_count_b} 人",
        f"• D 重复扣分：{item.anomaly_count_d} 人",
        f"• 异常用户总数（A∪B∪D 去重）：{item.anomaly_users}",
        "",
        _item_status_label(item),
    ]
    return "\n".join(lines)
