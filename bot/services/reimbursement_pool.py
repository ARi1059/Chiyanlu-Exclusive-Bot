"""管理员后台「💰 报销池状态」只读聚合统计。

提供：
    - ReimbursementPoolStats：dataclass，承载所有指标
    - get_reimbursement_pool_stats()：从主数据库读取（aiosqlite，复用 get_db）
    - render_reimbursement_pool()：纯渲染函数，便于测试

设计原则：
    - 全程只读：不写任何表，不修改报销审核流程，不修改金额规则
    - 防御性查询：单点失败 → 该字段 None，渲染 "N/A"，不影响其它指标
    - 复用现有 helper：current_week_key / current_month_key（bot.database）
    - feature_enabled / monthly_pool 与 admin_panel 现有读取口径完全一致
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiosqlite
from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import (
    current_month_key,
    current_week_key,
    get_config,
    get_db,
)

logger = logging.getLogger(__name__)


@dataclass
class ReimbursementPoolStats:
    """报销池状态聚合数据。

    Optional 字段语义：
        - None  → 渲染层显示 "N/A"（查询失败 / 配置缺失 / 无法可靠统计）
        - 已知值 → 渲染层正常显示
    """

    feature_enabled: Optional[bool] = None
    monthly_pool: Optional[int] = None
    month_key: Optional[str] = None
    week_key: Optional[str] = None
    # approved_amount_this_month 现在表示 effective_used（口径与审批月池一致）
    # 2026-05：保留字段名供既有测试 / 渲染兼容，但语义已是 effective_used
    approved_amount_this_month: Optional[int] = None
    # 2026-05 新增：本月原始已批准总额 + 已设置的 reset baseline，用于渲染层
    # 展示"原始 / 基线 / 有效"三个口径
    raw_used_this_month: Optional[int] = None
    reset_baseline_this_month: Optional[int] = None
    remaining_pool: Optional[int] = None
    pending_count: Optional[int] = None
    queued_count: Optional[int] = None
    approved_count_this_month: Optional[int] = None
    rejected_count_this_month: Optional[int] = None
    approved_users_this_week: Optional[int] = None
    approved_amount_this_week: Optional[int] = None
    reset_vouchers_used_this_week: Optional[int] = None
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
        logger.warning("reimbursement_pool 标量查询失败: sql=%r err=%s", sql, e)
        return None


def _parse_monthly_pool(raw: Optional[str]) -> Optional[int]:
    """config.reimbursement_monthly_pool → int；空 / 解析失败返回 None。

    注：项目约定 "0" = 不限（不是 None）；此处保留 0，让渲染层决定怎么呈现。
    """
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("monthly_pool 配置值非整数: %r", raw)
        return None


async def get_reimbursement_pool_stats() -> ReimbursementPoolStats:
    """读取报销池状态全部指标并返回。

    每个指标独立 try / 容错；不会因某张表缺失或 schema 漂移而整体失败。
    """
    stats = ReimbursementPoolStats(generated_at=_now_local())

    # ---- month_key / week_key（依赖 datetime + config.timezone，理论不会失败） ----
    try:
        stats.month_key = current_month_key()
    except Exception as e:
        logger.warning("current_month_key 失败: %s", e)
    try:
        stats.week_key = current_week_key()
    except Exception as e:
        logger.warning("current_week_key 失败: %s", e)

    # ---- feature_enabled ----
    # 与 admin_panel 行为一致：值 "1" 视为开启，其余（"0" / None / 任意）视为关闭。
    # 这里把 None（key 不存在）单独标记为 None，让渲染显示 N/A，便于排查。
    try:
        raw_enabled = await get_config("reimbursement_feature_enabled")
        if raw_enabled is None:
            stats.feature_enabled = None
        else:
            stats.feature_enabled = (raw_enabled == "1")
    except Exception as e:
        logger.warning("读取 reimbursement_feature_enabled 失败: %s", e)
        stats.feature_enabled = None

    # ---- monthly_pool ----
    try:
        raw_pool = await get_config("reimbursement_monthly_pool")
        stats.monthly_pool = _parse_monthly_pool(raw_pool)
    except Exception as e:
        logger.warning("读取 reimbursement_monthly_pool 失败: %s", e)
        stats.monthly_pool = None

    # ---- 走主 db 连接做 SQL 聚合 ----
    db = await get_db()
    try:
        # 本月已批准金额：2026-05 改为 effective_used 口径（与审批月池校验一致）
        # raw_used = SUM(approved); effective_used = max(0, raw - reset_baseline)
        # 这里通过 get_reimbursement_monthly_pool_usage 拉取统一口径，避免漂移
        if stats.month_key is not None:
            try:
                from bot.database import get_reimbursement_monthly_pool_usage
                usage = await get_reimbursement_monthly_pool_usage(stats.month_key)
                stats.approved_amount_this_month = usage["effective_used"]
                stats.raw_used_this_month = usage["raw_used"]
                stats.reset_baseline_this_month = usage["reset_baseline"]
            except Exception as e:
                logger.warning(
                    "get_reimbursement_monthly_pool_usage 失败 month=%s: %s",
                    stats.month_key, e,
                )
            stats.approved_count_this_month = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM reimbursements "
                "WHERE month_key = ? AND status = 'approved'",
                (stats.month_key,),
            )
            stats.rejected_count_this_month = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM reimbursements "
                "WHERE month_key = ? AND status = 'rejected'",
                (stats.month_key,),
            )

        # pending / queued（无月份维度，全表统计）
        stats.pending_count = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM reimbursements WHERE status = 'pending'",
        )
        stats.queued_count = await _scalar_int(
            db,
            "SELECT COUNT(*) FROM reimbursements WHERE status = 'queued'",
        )

        # 本周通过情况
        if stats.week_key is not None:
            stats.approved_users_this_week = await _scalar_int(
                db,
                "SELECT COUNT(DISTINCT user_id) FROM reimbursements "
                "WHERE week_key = ? AND status = 'approved'",
                (stats.week_key,),
            )
            stats.approved_amount_this_week = await _scalar_int(
                db,
                "SELECT COALESCE(SUM(amount), 0) FROM reimbursements "
                "WHERE week_key = ? AND status = 'approved'",
                (stats.week_key,),
            )
            # 本周使用的 reset voucher：通过 consumed_reimb_id 关联到本周 reimbursements
            stats.reset_vouchers_used_this_week = await _scalar_int(
                db,
                "SELECT COUNT(*) FROM reimbursement_resets r "
                "JOIN reimbursements rb ON r.consumed_reimb_id = rb.id "
                "WHERE r.consumed = 1 AND rb.week_key = ?",
                (stats.week_key,),
            )
    finally:
        await db.close()

    # ---- 派生指标：剩余额度 ----
    # 规则：
    #   - monthly_pool == None → remaining None（N/A）
    #   - monthly_pool == 0    → 视为「不限」，remaining 也按 0 显示但渲染层会提示
    #   - approved_amount_this_month == None → remaining None
    #   - 其余 → monthly_pool - approved_amount_this_month（允许负值表示超额）
    if stats.monthly_pool is None or stats.approved_amount_this_month is None:
        stats.remaining_pool = None
    else:
        stats.remaining_pool = stats.monthly_pool - stats.approved_amount_this_month

    return stats


def _fmt(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_feature(enabled: Optional[bool]) -> str:
    if enabled is None:
        return "N/A"
    return "开启" if enabled else "关闭"


def _fmt_pool(monthly_pool: Optional[int]) -> str:
    """月度池渲染：None → N/A；0 → 不限；正数 → "X 元"。"""
    if monthly_pool is None:
        return "N/A"
    if monthly_pool == 0:
        return "不限（0）"
    return f"{monthly_pool} 元"


def _fmt_remaining(stats: ReimbursementPoolStats) -> str:
    """剩余额度渲染，含"已超额"提示与"不限"分支。"""
    if stats.monthly_pool is None or stats.approved_amount_this_month is None:
        return "N/A"
    if stats.monthly_pool == 0:
        # 不限池下不存在"剩余"概念
        return "不限"
    remaining = stats.remaining_pool
    if remaining is None:
        return "N/A"
    if remaining < 0:
        return f"{remaining} 元（⚠️ 已超额 {abs(remaining)} 元）"
    return f"{remaining} 元"


def render_reimbursement_pool(stats: ReimbursementPoolStats) -> str:
    """把 ReimbursementPoolStats 渲染为后台展示文本。

    纯函数：仅依赖入参，便于 pytest 直接断言。
    """
    if stats.generated_at is not None:
        try:
            ts_str = stats.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    # 已批准金额：N/A → N/A；其余正常显示数值 + 元
    approved_amount_str = (
        "N/A" if stats.approved_amount_this_month is None
        else f"{stats.approved_amount_this_month} 元"
    )
    approved_amount_week_str = (
        "N/A" if stats.approved_amount_this_week is None
        else f"{stats.approved_amount_this_week} 元"
    )

    lines = [
        "💰 报销池状态",
        "",
        "本月报销池",
        f"• 月度额度：{_fmt_pool(stats.monthly_pool)}",
        f"• 已批准：{approved_amount_str}",
        f"• 剩余额度：{_fmt_remaining(stats)}",
        "",
        "当前队列",
        f"• 待审核 pending：{_fmt(stats.pending_count)} 条",
        f"• queued 名单：{_fmt(stats.queued_count)} 条",
        f"• 本月已通过：{_fmt(stats.approved_count_this_month)} 条",
        f"• 本月已驳回：{_fmt(stats.rejected_count_this_month)} 条",
        "",
        "本周情况",
        f"• 本周已通过用户数：{_fmt(stats.approved_users_this_week)} 人",
        f"• 本周已通过金额：{approved_amount_week_str}",
        f"• 本周 reset voucher：{_fmt(stats.reset_vouchers_used_this_week)} 次",
        "",
        "系统状态",
        f"• 报销功能：{_fmt_feature(stats.feature_enabled)}",
        f"• 当前月份：{stats.month_key or 'N/A'}",
        f"• 当前周：{stats.week_key or 'N/A'}",
        "",
        f"更新时间：{ts_str}",
    ]
    return "\n".join(lines)
