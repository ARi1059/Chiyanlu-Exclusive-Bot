"""管理员后台「📊 运营总览」只读聚合统计。

提供：
    - AdminOverviewStats：dataclass，承载所有指标
    - get_admin_overview_stats()：从主数据库读取（aiosqlite，复用 get_db）
    - render_admin_overview()：纯渲染函数，便于测试

设计原则：
    - 全程只读：不写任何表，不修改任何业务流程
    - 防御性查询：任何单项查询失败都只让对应字段为 None（渲染为 N/A），
      不影响其它指标
    - 时区：日期口径与现有 admin_panel._today_str 一致 → 按 config.timezone
      取本地"今日 YYYY-MM-DD"；DB 中 created_at 是 CURRENT_TIMESTAMP（UTC），
      与现有 get_dashboard_metrics 处理一致（用 DATE(created_at) 比较）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import get_db

logger = logging.getLogger(__name__)


@dataclass
class AdminOverviewStats:
    """运营总览全部统计指标。

    任意指标缺失（表/字段不存在、查询异常）→ 该字段为 None，
    渲染层会显示 "N/A"，不影响其它字段。
    """

    today_checkin_teachers: Optional[int] = None
    today_new_users: Optional[int] = None
    today_new_favorites: Optional[int] = None
    today_new_reviews: Optional[int] = None
    pending_teacher_edits: Optional[int] = None  # UX-2 第三项第一批新增（只读，不改原口径）
    pending_reviews: Optional[int] = None
    pending_reimbursements: Optional[int] = None
    queued_reimbursements: Optional[int] = None
    active_lotteries: Optional[int] = None
    scheduled_lotteries: Optional[int] = None
    active_lotteries_waiting_draw: Optional[int] = None
    failed_hard_migrations: Optional[int] = None
    failed_soft_migrations: Optional[int] = None
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


def _today_str() -> str:
    return _now_local().strftime("%Y-%m-%d")


async def _scalar_int(
    db: aiosqlite.Connection, sql: str, params: tuple = (),
) -> Optional[int]:
    """执行 COUNT 类 SQL，返回标量整数；任意异常返回 None。

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
        logger.warning("admin_overview scalar 查询失败: sql=%r err=%s", sql, e)
        return None


async def get_admin_overview_stats() -> AdminOverviewStats:
    """读取所有运营总览指标并返回。

    每个指标独立 try / 容错；不会因为某张表缺失或 schema 漂移而整体失败。
    """
    stats = AdminOverviewStats(generated_at=_now_local())
    today = _today_str()

    db = await get_db()
    try:
        # ---- 今日数据 ----
        # checkins.checkin_date 是本地日期字符串（参见 admin_panel._today_str）
        stats.today_checkin_teachers = await _scalar_int(
            db,
            "SELECT COUNT(DISTINCT teacher_id) FROM checkins "
            "WHERE checkin_date = ?",
            (today,),
        )
        stats.today_new_users = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?",
            (today,),
        )
        stats.today_new_favorites = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM favorites WHERE DATE(created_at) = ?",
            (today,),
        )
        stats.today_new_reviews = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM teacher_reviews WHERE DATE(created_at) = ?",
            (today,),
        )

        # ---- 待处理 ----
        # UX-2 第三项第一批：老师资料审核 pending（用于运营总览快捷跳转判断；
        # 渲染层未输出该字段以避免改动正文）
        stats.pending_teacher_edits = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM teacher_edit_requests WHERE status = 'pending'",
        )
        stats.pending_reviews = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM teacher_reviews WHERE status = 'pending'",
        )
        stats.pending_reimbursements = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM reimbursements WHERE status = 'pending'",
        )
        stats.queued_reimbursements = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM reimbursements WHERE status = 'queued'",
        )

        # Phase A0（2026-05-23）已下线：抽奖统计（active_lotteries / scheduled_lotteries /
        # active_lotteries_waiting_draw）。AdminOverviewStats 字段保留为 None 兼容旧 caller。

        # ---- 系统：schema_migrations 失败迁移 ----
        # 表不存在 / 字段差异都会被 _scalar_int 吞成 None；
        # 这里我们额外把 None 兜底为 0，符合 spec「不要报错、显示 0」
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
        stats.failed_hard_migrations = hard_failed if hard_failed is not None else 0
        stats.failed_soft_migrations = soft_failed if soft_failed is not None else 0
    finally:
        await db.close()

    return stats


def _fmt(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def render_admin_overview(stats: AdminOverviewStats) -> str:
    """把 AdminOverviewStats 渲染为 Markdown 友好的纯文本。

    纯函数：仅依赖入参，便于 pytest 直接断言。
    """
    if stats.generated_at is not None:
        # 已带 tz 时直接 strftime；测试里构造 naive datetime 时也安全
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    # Phase A0（2026-05-23）：移除「抽奖」section（功能整体下线）
    lines = [
        "📊 运营总览",
        "",
        "今日数据",
        f"• 今日签到老师：{_fmt(stats.today_checkin_teachers)} 位",
        f"• 今日新增用户：{_fmt(stats.today_new_users)} 人",
        f"• 今日新增收藏：{_fmt(stats.today_new_favorites)} 次",
        f"• 今日新增评价：{_fmt(stats.today_new_reviews)} 条",
        "",
        "待处理",
        f"• 待审核评价：{_fmt(stats.pending_reviews)} 条",
        f"• 待审核报销：{_fmt(stats.pending_reimbursements)} 条",
        f"• queued 报销名单：{_fmt(stats.queued_reimbursements)} 条",
        "",
        "系统",
        f"• schema_migrations 失败迁移："
        f"hard {_fmt(stats.failed_hard_migrations)} / "
        f"soft {_fmt(stats.failed_soft_migrations)}",
        "",
        f"更新时间：{ts_str}",
    ]
    return "\n".join(lines)
