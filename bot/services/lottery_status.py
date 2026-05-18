"""管理员后台「🎲 抽奖状态」只读聚合统计。

提供：
    - LotteryStatusItem / LotteryStatusStats：dataclass 数据结构
    - get_lottery_status_stats()：从主数据库读取（aiosqlite，复用 get_db）
    - render_lottery_status()：纯渲染函数，便于测试

设计原则：
    - 全程只读：不写任何表，不修改抽奖创建 / 参与 / 扣分 / 开奖逻辑
    - 防御性查询：单点失败 → 该字段 None，渲染 "N/A"，不影响其它指标
    - 时间口径：publish_at / draw_at 在 admin_lottery 处统一存
      'YYYY-MM-DD HH:MM:SS' 字符串（参见 admin_lottery._format_datetime_store），
      与同格式的 now() 字典序比较即可，无需 parse
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


# 最近活动展示上限
RECENT_LOTTERY_LIMIT = 5


@dataclass
class LotteryStatusItem:
    """最近活动列表中单条抽奖摘要。"""

    id: int
    name: str
    status: str
    entry_count: Optional[int] = None
    winner_count: Optional[int] = None
    draw_at: Optional[str] = None
    publish_at: Optional[str] = None
    entry_cost_points: Optional[int] = None


@dataclass
class LotteryStatusStats:
    """抽奖状态聚合数据。

    Optional 字段语义：
        - None → 渲染显示 "N/A"
        - 已知值 → 正常显示
    """

    draft_count: Optional[int] = None
    scheduled_count: Optional[int] = None
    active_count: Optional[int] = None
    drawn_count: Optional[int] = None
    no_entries_count: Optional[int] = None
    cancelled_count: Optional[int] = None
    waiting_publish_count: Optional[int] = None
    waiting_draw_count: Optional[int] = None
    active_without_entries_count: Optional[int] = None
    paid_lottery_count: Optional[int] = None
    recent_lotteries: list[LotteryStatusItem] = field(default_factory=list)
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


async def _scalar_int(
    db: aiosqlite.Connection, sql: str, params: tuple = (),
) -> Optional[int]:
    """执行标量整数 SQL，异常返回 None；空结果返回 0。

    防御层：调用方不应再 try / except，单点失败已被吞没。
    """
    try:
        cur = await db.execute(sql, params)
        row = await cur.fetchone()
        if row is None:
            return 0
        value = row[0]
        return int(value) if value is not None else 0
    except Exception as e:
        logger.warning("lottery_status 标量查询失败: sql=%r err=%s", sql, e)
        return None


async def _fetch_recent_lotteries(
    db: aiosqlite.Connection,
    limit: int = RECENT_LOTTERY_LIMIT,
) -> list[LotteryStatusItem]:
    """取最近 N 条抽奖（含参与人数 + 中奖人数）。失败时返回 []。"""
    sql = (
        "SELECT l.id, l.name, l.status, l.draw_at, l.publish_at, "
        "       l.entry_cost_points, "
        "       (SELECT COUNT(*) FROM lottery_entries e "
        "        WHERE e.lottery_id = l.id) AS entry_count, "
        "       (SELECT COUNT(*) FROM lottery_entries e "
        "        WHERE e.lottery_id = l.id AND e.won = 1) AS winner_count "
        "FROM lotteries l "
        "ORDER BY l.created_at DESC, l.id DESC LIMIT ?"
    )
    items: list[LotteryStatusItem] = []
    try:
        cur = await db.execute(sql, (int(limit),))
        rows = await cur.fetchall()
        for row in rows:
            items.append(LotteryStatusItem(
                id=int(row["id"]),
                name=row["name"] or "(未命名)",
                status=row["status"] or "",
                entry_count=int(row["entry_count"]) if row["entry_count"] is not None else None,
                winner_count=int(row["winner_count"]) if row["winner_count"] is not None else None,
                draw_at=row["draw_at"],
                publish_at=row["publish_at"],
                entry_cost_points=(
                    int(row["entry_cost_points"])
                    if row["entry_cost_points"] is not None else None
                ),
            ))
    except Exception as e:
        logger.warning("recent_lotteries 查询失败: %s", e)
    return items


async def get_lottery_status_stats() -> LotteryStatusStats:
    """读取抽奖状态全部指标并返回。

    每个指标独立 try / 容错；不会因某张表缺失或 schema 漂移而整体失败。
    """
    stats = LotteryStatusStats(generated_at=_now_local())

    db = await get_db()
    try:
        # ---- 状态总览 ----
        stats.draft_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'draft'",
        )
        stats.scheduled_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'scheduled'",
        )
        stats.active_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'active'",
        )
        stats.drawn_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'drawn'",
        )
        stats.no_entries_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'no_entries'",
        )
        stats.cancelled_count = await _scalar_int(
            db, "SELECT COUNT(*) FROM lotteries WHERE status = 'cancelled'",
        )

        # ---- 待办提醒 ----
        # 待发布 = scheduled（spec: 不改变状态；逾期未发布的统计仍归属 scheduled）
        stats.waiting_publish_count = stats.scheduled_count
        # 待开奖 = active 且 draw_at > now
        # draw_at 是 'YYYY-MM-DD HH:MM:SS' 字符串，与同格式 now 字典序比较
        now_iso = _now_local().strftime("%Y-%m-%d %H:%M:%S")
        waiting_draw = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM lotteries "
            "WHERE status = 'active' AND draw_at > ?",
            (now_iso,),
        )
        if waiting_draw is None:
            waiting_draw = stats.active_count  # 回退口径
        stats.waiting_draw_count = waiting_draw

        # active 但无人参与
        stats.active_without_entries_count = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM lotteries l "
            "WHERE l.status = 'active' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM lottery_entries e WHERE e.lottery_id = l.id"
            ")",
        )

        # 积分门票活动：scheduled / active 且 entry_cost_points > 0
        stats.paid_lottery_count = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM lotteries "
            "WHERE status IN ('scheduled','active') AND entry_cost_points > 0",
        )

        # ---- 最近活动 ----
        stats.recent_lotteries = await _fetch_recent_lotteries(
            db, limit=RECENT_LOTTERY_LIMIT,
        )
    finally:
        await db.close()

    return stats


def _fmt(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_dt(value: Optional[str]) -> str:
    """draw_at / publish_at 默认就是 'YYYY-MM-DD HH:MM:SS'；
    截到分钟级（spec UI 用 HH:mm）。None / 空串 → N/A。
    """
    if not value:
        return "N/A"
    # 容错：意外短串直接原样返回，避免切片越界
    if len(value) >= 16:
        return value[:16]
    return value


def _fmt_cost(points: Optional[int]) -> str:
    if points is None:
        return "N/A"
    if points <= 0:
        return "免费"
    return f"{points} 分"


def render_lottery_status(stats: LotteryStatusStats) -> str:
    """把 LotteryStatusStats 渲染为后台展示文本。

    纯函数：仅依赖入参，便于 pytest 直接断言。
    """
    if stats.generated_at is not None:
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    lines: list[str] = [
        "🎲 抽奖状态",
        "",
        "状态总览",
        f"• 草稿 draft：{_fmt(stats.draft_count)} 个",
        f"• 待发布 scheduled：{_fmt(stats.scheduled_count)} 个",
        f"• 进行中 active：{_fmt(stats.active_count)} 个",
        f"• 已开奖 drawn：{_fmt(stats.drawn_count)} 个",
        f"• 无人参与 no_entries：{_fmt(stats.no_entries_count)} 个",
        f"• 已取消 cancelled：{_fmt(stats.cancelled_count)} 个",
        "",
        "待办提醒",
        f"• 待发布：{_fmt(stats.waiting_publish_count)} 个",
        f"• 待开奖：{_fmt(stats.waiting_draw_count)} 个",
        f"• active 但无人参与：{_fmt(stats.active_without_entries_count)} 个",
        f"• 积分门票活动：{_fmt(stats.paid_lottery_count)} 个",
        "",
        "最近活动",
    ]

    if not stats.recent_lotteries:
        lines.append("暂无抽奖活动")
    else:
        for i, item in enumerate(stats.recent_lotteries[:RECENT_LOTTERY_LIMIT]):
            if i > 0:
                lines.append("")
            lines.append(f"#{item.id} {item.name}")
            lines.append(f"状态：{item.status or 'N/A'}")
            lines.append(f"参与人数：{_fmt(item.entry_count)}")
            lines.append(f"中奖人数：{_fmt(item.winner_count)}")
            lines.append(f"开奖时间：{_fmt_dt(item.draw_at)}")
            lines.append(f"积分门票：{_fmt_cost(item.entry_cost_points)}")

    lines.append("")
    lines.append(f"更新时间：{ts_str}")
    return "\n".join(lines)
