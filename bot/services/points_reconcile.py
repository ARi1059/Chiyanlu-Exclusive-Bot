"""管理员后台「📊 积分对账」只读对账服务（Sprint 4 §6.2.3）。

提供：
    - PointsReconcileOverview / PointsReconcileItem / PointsAnomalyList：dataclass
    - get_points_reconcile_overview()：全局聚合（用户数 / 异常数 / 差额合计）
    - list_points_anomalies(page)：异常用户分页列表
    - render_points_reconcile_overview / render_points_anomaly_list：纯渲染

对账口径（POLICY §7.2 / §9）：
    对每个 user，期望恒等式：
        users.total_points == COALESCE(SUM(delta), 0)   -- from point_transactions
        WHERE user_id = u.user_id

    任何打破等式的用户即为「积分异常」。

差异分类（每个 uid 只归一类）：
    BALANCE_HIGHER：余额 > 流水累加（可能是历史 INSERT 未同步 / 迁移未回填）
    BALANCE_LOWER ：余额 < 流水累加（可能是手动改余额 / 流水后 commit 失败）

不在异常域：
    - 余额与流水相等（平账）
    - point_transactions 有 user_id 但 users 表无（孤儿流水）：仅统计总数，
      不出现在异常用户列表中（POLICY §7.4 已知问题：迁移后不回填）

设计原则：
    - 全程只读：不写任何表，不修改 add_point_transaction / FSM
    - 防御性查询：单点失败 → 该字段 None，渲染 N/A
    - 不导出文件、不提供"一键修正"按钮（§6.3 禁止）
    - 与 §4.2.2 抽奖异常用户列表同分页模式（每页 20）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

logger = logging.getLogger(__name__)


ANOMALY_PAGE_SIZE = 20
# 列表按 |diff| DESC 排序，但要避免单次查询返回过大；通过分页约束
MAX_ANOMALY_LIST_ROWS = 1000

CATEGORY_HIGHER = "BALANCE_HIGHER"
CATEGORY_LOWER = "BALANCE_LOWER"


@dataclass
class PointsReconcileOverview:
    """全局聚合数据。

    Optional 字段语义：None → 渲染 N/A；查询失败时降级。
    """

    total_users: Optional[int] = None  # 全部用户数
    points_users: Optional[int] = None  # total_points > 0 用户
    anomaly_users: Optional[int] = None  # diff != 0 用户
    orphan_tx_users: Optional[int] = None  # point_transactions 有 user_id 但 users 表无
    total_balance: Optional[int] = None  # SUM(users.total_points)
    total_tx_sum: Optional[int] = None  # SUM(all point_transactions.delta)
    diff_total: Optional[int] = None  # total_balance - total_tx_sum
    higher_users: Optional[int] = None  # BALANCE_HIGHER 计数
    lower_users: Optional[int] = None  # BALANCE_LOWER 计数
    generated_at: Optional[datetime] = None


@dataclass
class PointsReconcileItem:
    """单条异常用户记录。"""

    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    balance: int
    tx_sum: int
    diff: int  # balance - tx_sum
    category: str  # CATEGORY_HIGHER / CATEGORY_LOWER


@dataclass
class PointsAnomalyList:
    """异常用户列表（含分页元信息）。"""

    items: list[PointsReconcileItem] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = ANOMALY_PAGE_SIZE
    total_pages: int = 1
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


async def _scalar_int(db, sql: str, params: tuple = ()) -> Optional[int]:
    """执行标量整数 SQL；空结果返 0；异常返 None。"""
    try:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            return 0
        value = row[0]
        return int(value) if value is not None else 0
    except Exception as e:
        logger.warning("points_reconcile 标量查询失败: sql=%r err=%s", sql, e)
        return None


async def get_points_reconcile_overview() -> PointsReconcileOverview:
    """全局聚合：用户数 / 异常数 / 余额与流水合计 / 差额。"""
    stats = PointsReconcileOverview(generated_at=_now_local())

    db = await get_db()
    try:
        stats.total_users = await _scalar_int(
            db, "SELECT COUNT(*) FROM users",
        )
        stats.points_users = await _scalar_int(
            db, "SELECT COUNT(*) FROM users WHERE COALESCE(total_points, 0) > 0",
        )
        stats.total_balance = await _scalar_int(
            db, "SELECT COALESCE(SUM(total_points), 0) FROM users",
        )
        stats.total_tx_sum = await _scalar_int(
            db, "SELECT COALESCE(SUM(delta), 0) FROM point_transactions",
        )

        # 异常用户：以 users 为主，LEFT JOIN 流水聚合，diff != 0
        anomaly_count = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM users u "
            "LEFT JOIN ("
            "  SELECT user_id, SUM(delta) AS tx_sum "
            "  FROM point_transactions GROUP BY user_id"
            ") tx ON tx.user_id = u.user_id "
            "WHERE COALESCE(u.total_points, 0) != COALESCE(tx.tx_sum, 0)",
        )
        stats.anomaly_users = anomaly_count

        higher = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM users u "
            "LEFT JOIN ("
            "  SELECT user_id, SUM(delta) AS tx_sum "
            "  FROM point_transactions GROUP BY user_id"
            ") tx ON tx.user_id = u.user_id "
            "WHERE COALESCE(u.total_points, 0) > COALESCE(tx.tx_sum, 0)",
        )
        stats.higher_users = higher

        lower = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM users u "
            "LEFT JOIN ("
            "  SELECT user_id, SUM(delta) AS tx_sum "
            "  FROM point_transactions GROUP BY user_id"
            ") tx ON tx.user_id = u.user_id "
            "WHERE COALESCE(u.total_points, 0) < COALESCE(tx.tx_sum, 0)",
        )
        stats.lower_users = lower

        # 孤儿流水：point_transactions 有 user_id 但 users 表无
        orphans = await _scalar_int(
            db,
            "SELECT COUNT(DISTINCT pt.user_id) FROM point_transactions pt "
            "LEFT JOIN users u ON u.user_id = pt.user_id "
            "WHERE u.user_id IS NULL",
        )
        stats.orphan_tx_users = orphans
    finally:
        await db.close()

    # diff_total 派生
    if stats.total_balance is not None and stats.total_tx_sum is not None:
        stats.diff_total = stats.total_balance - stats.total_tx_sum

    return stats


async def list_points_anomalies(
    *, page: int = 1, page_size: int = ANOMALY_PAGE_SIZE,
) -> PointsAnomalyList:
    """异常用户分页列表，按 |diff| DESC 排序。

    第一版只列 users 表中存在且 diff != 0 的用户；孤儿流水（point_transactions
    有 user_id 但 users 表无）仅在 overview 中显示总数，不在本列表。
    """
    page = max(1, int(page))
    page_size = max(1, int(page_size))

    db = await get_db()
    try:
        # 先取总数（用于 total_pages）
        total = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM users u "
            "LEFT JOIN ("
            "  SELECT user_id, SUM(delta) AS tx_sum "
            "  FROM point_transactions GROUP BY user_id"
            ") tx ON tx.user_id = u.user_id "
            "WHERE COALESCE(u.total_points, 0) != COALESCE(tx.tx_sum, 0)",
        ) or 0

        if total == 0:
            return PointsAnomalyList(
                items=[], total=0, page=1,
                page_size=page_size, total_pages=1,
                generated_at=_now_local(),
            )

        total_pages = (total + page_size - 1) // page_size
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size

        items: list[PointsReconcileItem] = []
        try:
            cur = await db.execute(
                "SELECT u.user_id, u.username, u.first_name, "
                "       COALESCE(u.total_points, 0) AS balance, "
                "       COALESCE(tx.tx_sum, 0) AS tx_sum, "
                "       COALESCE(u.total_points, 0) - COALESCE(tx.tx_sum, 0) AS diff "
                "FROM users u "
                "LEFT JOIN ("
                "  SELECT user_id, SUM(delta) AS tx_sum "
                "  FROM point_transactions GROUP BY user_id"
                ") tx ON tx.user_id = u.user_id "
                "WHERE COALESCE(u.total_points, 0) != COALESCE(tx.tx_sum, 0) "
                "ORDER BY ABS(COALESCE(u.total_points, 0) - "
                "             COALESCE(tx.tx_sum, 0)) DESC, u.user_id ASC "
                "LIMIT ? OFFSET ?",
                (page_size, offset),
            )
            rows = await cur.fetchall()
        except Exception as e:
            logger.warning("list_points_anomalies 查询失败: %s", e)
            rows = []

        for row in rows:
            diff = int(row["diff"])
            category = CATEGORY_HIGHER if diff > 0 else CATEGORY_LOWER
            items.append(PointsReconcileItem(
                user_id=int(row["user_id"]),
                username=row["username"] if "username" in row.keys() else None,
                first_name=row["first_name"] if "first_name" in row.keys() else None,
                balance=int(row["balance"]),
                tx_sum=int(row["tx_sum"]),
                diff=diff,
                category=category,
            ))

        return PointsAnomalyList(
            items=items, total=int(total), page=page,
            page_size=page_size, total_pages=total_pages,
            generated_at=_now_local(),
        )
    finally:
        await db.close()


# ============ 渲染 ============


def _fmt_int(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_diff(diff: int) -> str:
    if diff > 0:
        return f"+{diff}"
    return str(diff)


def _fmt_display_name(item: PointsReconcileItem) -> str:
    """用户显示名：username > first_name > uid。

    所有字段防御性容错（数据库脏数据或迁移残留）。
    """
    if item.username:
        return f"@{item.username}"
    if item.first_name:
        return str(item.first_name)
    return f"uid={item.user_id}"


def render_points_reconcile_overview(stats: PointsReconcileOverview) -> str:
    """对账概览页文本。"""
    if stats.generated_at is not None:
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    diff_total_str = "N/A"
    if stats.diff_total is not None:
        diff_total_str = _fmt_diff(stats.diff_total)

    lines = [
        "📊 积分对账",
        "（只读 · 修正动作不在本页，需走 admin:points:grant FSM 手动操作）",
        "",
        "用户统计",
        f"• 全部用户：{_fmt_int(stats.total_users)}",
        f"• 持币用户（balance>0）：{_fmt_int(stats.points_users)}",
        f"• 异常用户（balance ≠ tx_sum）：{_fmt_int(stats.anomaly_users)}",
        f"  ├ 余额偏高（balance > tx_sum）：{_fmt_int(stats.higher_users)}",
        f"  └ 余额偏低（balance < tx_sum）：{_fmt_int(stats.lower_users)}",
        f"• 孤儿流水用户（user_id 无 users 记录）：{_fmt_int(stats.orphan_tx_users)}",
        "",
        "全局对账",
        f"• 余额合计 SUM(total_points)：{_fmt_int(stats.total_balance)}",
        f"• 流水合计 SUM(delta)：{_fmt_int(stats.total_tx_sum)}",
        f"• 差额合计：{diff_total_str}",
        "",
        "说明",
        "• 余额偏高常见于：历史迁移后未回填 / DB 直接修改 users.total_points",
        "• 余额偏低常见于：流水写入后 total_points 同步失败（POLICY §7.1）",
        "• 孤儿流水多见于：用户已注销但流水保留（不在异常列表，仅供观察）",
        "",
        f"快照时间：{ts_str}",
    ]
    return "\n".join(lines)


def render_points_anomaly_list(data: PointsAnomalyList) -> str:
    """异常用户列表页文本。"""
    if data.total == 0:
        return "\n".join([
            "📋 积分异常用户",
            "",
            "暂无异常用户 ✅",
            "",
            "（与对账概览口径一致：balance ≠ tx_sum 为 0 人）",
        ])

    higher_items = [it for it in data.items if it.category == CATEGORY_HIGHER]
    lower_items = [it for it in data.items if it.category == CATEGORY_LOWER]

    lines: list[str] = [
        "📋 积分异常用户",
        "",
        f"共 {data.total} 人，第 {data.page}/{data.total_pages} 页"
        f"（每页 {data.page_size}，按 |diff| 降序）",
        "",
    ]

    if higher_items:
        lines.append(f"余额偏高（balance > tx_sum）：{len(higher_items)} 人")
        for it in higher_items:
            lines.append(
                f"• {_fmt_display_name(it)} (uid={it.user_id})  "
                f"balance={it.balance}  tx_sum={it.tx_sum}  "
                f"diff={_fmt_diff(it.diff)}"
            )
        lines.append("")

    if lower_items:
        lines.append(f"余额偏低（balance < tx_sum）：{len(lower_items)} 人")
        for it in lower_items:
            lines.append(
                f"• {_fmt_display_name(it)} (uid={it.user_id})  "
                f"balance={it.balance}  tx_sum={it.tx_sum}  "
                f"diff={_fmt_diff(it.diff)}"
            )
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
