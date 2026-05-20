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
ANOMALY_PAGE_SIZE = 20

# 异常类别优先级（高 → 低）；同 uid 跨类时归到优先级最高的那一类
ANOMALY_CATEGORY_PRIORITY = ("D", "B", "A")


@dataclass
class LotteryAnomalyUser:
    """异常用户单条记录（§4.2.2）。

    分类规则（D > B > A 优先级，同 uid 归最高优先级）：
        D 重复扣分：point_transactions 中 (uid, lottery_entry, lid) ≥ 2 条
        B 有扣分无 entry：lottery_entry 流水存在但 lottery_entries 无 entry
        A 有 entry 无扣分：lottery_entries 有 entry 但无 lottery_entry 流水
    """

    user_id: int
    category: str           # 'A' | 'B' | 'D'
    entry_id: Optional[int] = None        # A / D 类有；B 类 None
    tx_ids: list[int] = field(default_factory=list)  # B / D 类有；A 类空
    tx_total_delta: int = 0  # 涉及流水的总额（D / B 类为负）


@dataclass
class LotteryAnomalyList:
    """异常用户列表（含分页元信息）。"""

    lid: int
    items: list[LotteryAnomalyUser] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = ANOMALY_PAGE_SIZE
    total_pages: int = 1


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


# ============ 异常用户列表（§4.2.2） ============


async def _list_anomaly_d(
    db: aiosqlite.Connection, lid: int,
) -> list[LotteryAnomalyUser]:
    """D 类：同 (uid, lid) 在 lottery_entry 流水 ≥ 2 条。

    GROUP_CONCAT 拿到 tx_ids；同时关联 lottery_entries 取 entry_id（可能为
    None：D ∩ B，即重复扣分但无 entry）。
    """
    items: list[LotteryAnomalyUser] = []
    try:
        cur = await db.execute(
            "SELECT p.user_id, GROUP_CONCAT(p.id) AS tx_ids, "
            "       SUM(p.delta) AS total_delta "
            "FROM point_transactions p "
            "WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
            "GROUP BY p.user_id HAVING COUNT(*) >= 2 "
            "ORDER BY p.user_id",
            (lid,),
        )
        rows = await cur.fetchall()
    except Exception as e:
        logger.warning("list_anomaly_d 失败 lid=%s: %s", lid, e)
        return []

    for row in rows:
        uid = int(row["user_id"])
        tx_id_str = row["tx_ids"] or ""
        tx_ids = [int(s) for s in tx_id_str.split(",") if s.strip()]
        total_delta = int(row["total_delta"] or 0)
        # 关联 entry_id（容错：D∩B 时无 entry）
        try:
            cur = await db.execute(
                "SELECT id FROM lottery_entries WHERE lottery_id = ? AND user_id = ?",
                (lid, uid),
            )
            erow = await cur.fetchone()
            entry_id = int(erow["id"]) if erow else None
        except Exception:
            entry_id = None
        items.append(LotteryAnomalyUser(
            user_id=uid, category="D",
            entry_id=entry_id, tx_ids=tx_ids,
            tx_total_delta=total_delta,
        ))
    return items


async def _list_anomaly_b(
    db: aiosqlite.Connection, lid: int, exclude_uids: set[int],
) -> list[LotteryAnomalyUser]:
    """B 类：有 lottery_entry 流水但无 entry。

    exclude_uids：已经在 D 中归类的 uid，避免重复（D > B 优先级）。
    """
    items: list[LotteryAnomalyUser] = []
    try:
        cur = await db.execute(
            "SELECT p.user_id, p.id AS tx_id, p.delta "
            "FROM point_transactions p "
            "WHERE p.reason = 'lottery_entry' AND p.related_id = ? "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM lottery_entries e "
            "  WHERE e.lottery_id = p.related_id "
            "  AND e.user_id = p.user_id"
            ") "
            "ORDER BY p.user_id, p.id",
            (lid,),
        )
        rows = await cur.fetchall()
    except Exception as e:
        logger.warning("list_anomaly_b 失败 lid=%s: %s", lid, e)
        return []

    # B ∩ D 已被 D 吸收（exclude_uids）；本函数只取真 B（uid 唯一一条 tx）
    seen: set[int] = set()
    for row in rows:
        uid = int(row["user_id"])
        if uid in exclude_uids or uid in seen:
            continue
        seen.add(uid)
        items.append(LotteryAnomalyUser(
            user_id=uid, category="B",
            entry_id=None,
            tx_ids=[int(row["tx_id"])],
            tx_total_delta=int(row["delta"] or 0),
        ))
    return items


async def _list_anomaly_a(
    db: aiosqlite.Connection, lid: int,
) -> list[LotteryAnomalyUser]:
    """A 类：有 entry 但无 lottery_entry 流水。

    A 与 D/B 必然不相交（A 要求 0 条 tx），无需 exclude_uids。
    """
    items: list[LotteryAnomalyUser] = []
    try:
        cur = await db.execute(
            "SELECT e.id AS entry_id, e.user_id "
            "FROM lottery_entries e "
            "WHERE e.lottery_id = ? "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM point_transactions p "
            "  WHERE p.reason = 'lottery_entry' "
            "  AND p.related_id = e.lottery_id "
            "  AND p.user_id = e.user_id"
            ") "
            "ORDER BY e.user_id",
            (lid,),
        )
        rows = await cur.fetchall()
    except Exception as e:
        logger.warning("list_anomaly_a 失败 lid=%s: %s", lid, e)
        return []

    for row in rows:
        items.append(LotteryAnomalyUser(
            user_id=int(row["user_id"]),
            category="A",
            entry_id=int(row["entry_id"]),
            tx_ids=[],
            tx_total_delta=0,
        ))
    return items


async def list_lottery_anomalies(
    lid: int, *, page: int = 1, page_size: int = ANOMALY_PAGE_SIZE,
) -> LotteryAnomalyList:
    """单活动异常用户列表（分页）。

    分类与优先级（D > B > A）：每个 uid 只归一类。
    排序：先 D，后 B，最后 A；类内按 user_id ASC。
    """
    page = max(1, int(page))
    page_size = max(1, int(page_size))

    db = await get_db()
    try:
        d_items = await _list_anomaly_d(db, lid)
        d_uids = {it.user_id for it in d_items}
        b_items = await _list_anomaly_b(db, lid, d_uids)
        a_items = await _list_anomaly_a(db, lid)
    finally:
        await db.close()

    full = d_items + b_items + a_items
    total = len(full)
    if total == 0:
        return LotteryAnomalyList(
            lid=int(lid), items=[], total=0, page=1,
            page_size=page_size, total_pages=1,
        )

    total_pages = (total + page_size - 1) // page_size
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    items_page = full[start:start + page_size]

    return LotteryAnomalyList(
        lid=int(lid), items=items_page, total=total,
        page=page, page_size=page_size, total_pages=total_pages,
    )


def _format_anomaly_user_line(au: LotteryAnomalyUser) -> str:
    """单个异常用户的展示行（纯函数）。"""
    if au.category == "A":
        suffix = f"entry_id={au.entry_id}"
    elif au.category == "B":
        tx_id = au.tx_ids[0] if au.tx_ids else "?"
        suffix = f"tx_id={tx_id} 扣 {au.tx_total_delta}"
    else:  # D
        tx_str = ",".join(str(t) for t in au.tx_ids)
        entry_str = (
            f"entry_id={au.entry_id} "
            if au.entry_id is not None else "无 entry "
        )
        suffix = f"{entry_str}tx_ids=[{tx_str}] 共扣 {au.tx_total_delta}"
    return f"• uid={au.user_id}  {suffix}"


def render_lottery_anomaly_list(data: LotteryAnomalyList) -> str:
    """异常用户列表页文本。"""
    if data.total == 0:
        return "\n".join([
            f"📋 异常用户 · 抽奖 #{data.lid}",
            "",
            "暂无异常用户 ✅",
            "",
            "（与对账详情口径一致：A∪B∪D 去重后为 0 人）",
        ])

    # 按类别分组
    d_users = [it for it in data.items if it.category == "D"]
    b_users = [it for it in data.items if it.category == "B"]
    a_users = [it for it in data.items if it.category == "A"]

    lines: list[str] = [
        f"📋 异常用户 · 抽奖 #{data.lid}",
        "",
        f"共 {data.total} 人，第 {data.page}/{data.total_pages} 页"
        f"（每页 {data.page_size}）",
        "",
    ]

    if d_users:
        lines.append(f"D 重复扣分（{len(d_users)} 人）")
        for au in d_users:
            lines.append(_format_anomaly_user_line(au))
        lines.append("")
    if b_users:
        lines.append(f"B 有扣分无 entry（{len(b_users)} 人）")
        for au in b_users:
            lines.append(_format_anomaly_user_line(au))
        lines.append("")
    if a_users:
        lines.append(f"A 有 entry 无扣分（{len(a_users)} 人）")
        for au in a_users:
            lines.append(_format_anomaly_user_line(au))
        lines.append("")

    # 去掉最后一个空行
    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)
