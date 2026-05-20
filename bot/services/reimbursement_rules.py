"""管理员后台「📜 报销规则一览」只读规则快照（Sprint 3 §5.2.1）。

提供：
    - ReimbursementRulesSnapshot：dataclass，承载所有当前生效的报销规则
    - get_reimbursement_rules_snapshot()：从主数据库 + config 表读取
    - render_reimbursement_rules()：纯渲染函数，便于测试

设计原则：
    - 全程只读：不写任何表，不修改报销审核 / queued / reset voucher 任何流程
    - 防御性查询：单点失败 → 该字段 None，渲染 "N/A"，不影响其它指标
    - 与 POLICY.md Part II 内容口径一致（每周限制 / reset voucher 规则等硬编码项
      在文档中已说明，本 service 把这些值显式暴露给后台）
    - 仅暴露规则与配置，**不**展示运营状态（如本月已批准金额）。状态见
      `services/reimbursement_pool.py`。

为什么这是「规则页」而不是「状态页」：
    - 规则：能/不能做、上限多少、阈值多少 —— 配置类
    - 状态：当前用了多少、queued 队列多长 —— 统计类
    - 二者天然分离：规则页用于审计与公告草稿；状态页用于运营决策。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import (
    REIMBURSE_MIN_POINTS_DEFAULT,
    REIMBURSE_MIN_POINTS_MAX,
    count_queued_reimbursements,
    current_month_key,
    current_week_key,
    get_config,
    get_reimburse_pool_reset_baselines,
    get_reimburse_required_chats,
    get_reimbursement_min_points,
)

logger = logging.getLogger(__name__)


# 硬编码规则常量（与 POLICY.md Part II 同步；当前未走 config）
WEEKLY_APPROVED_LIMIT = 1
"""POLICY §6.1：每用户每 ISO 周最多 1 次 approved 报销（硬编码）。"""


@dataclass
class ReimbursementRulesSnapshot:
    """当前生效的报销规则快照。

    Optional 字段语义：
        - None  → 渲染层显示 "N/A"（查询失败 / 配置缺失）
        - 已知值 → 正常显示

    `feature_enabled = None` 表示 config key 不存在（与"显式关闭"的"0"区分），
    便于后台排查配置漂移。
    """

    # 功能开关 + 队列模式触发条件
    feature_enabled: Optional[bool] = None
    queued_count: Optional[int] = None  # 当前 queued 名单条数

    # 月度池
    monthly_pool: Optional[int] = None  # None=N/A；0=不限；>0=正常
    current_month_key: Optional[str] = None
    current_month_reset_baseline: Optional[int] = None  # 本月是否有 reset baseline

    # 最低积分门槛
    min_points: Optional[int] = None
    min_points_default: int = REIMBURSE_MIN_POINTS_DEFAULT
    min_points_max: int = REIMBURSE_MIN_POINTS_MAX

    # 每周限制（硬编码）
    weekly_approved_limit: int = WEEKLY_APPROVED_LIMIT
    current_week_key: Optional[str] = None

    # 必关频道 / 群组数（reimbursement_required_chats）
    required_chats_total: Optional[int] = None
    required_chats_enabled: Optional[int] = None

    # 元信息
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


def _parse_monthly_pool(raw: Optional[str]) -> Optional[int]:
    """config.reimbursement_monthly_pool → int；空 / 解析失败返回 None。

    与 services/reimbursement_pool.py 口径一致：保留 0（=不限）。
    """
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("monthly_pool 配置值非整数: %r", raw)
        return None


async def get_reimbursement_rules_snapshot() -> ReimbursementRulesSnapshot:
    """读取当前生效的报销规则，全部容错。"""
    snap = ReimbursementRulesSnapshot(generated_at=_now_local())

    # ---- month / week key ----
    try:
        snap.current_month_key = current_month_key()
    except Exception as e:
        logger.warning("current_month_key 失败: %s", e)
    try:
        snap.current_week_key = current_week_key()
    except Exception as e:
        logger.warning("current_week_key 失败: %s", e)

    # ---- feature_enabled ----
    try:
        raw_enabled = await get_config("reimbursement_feature_enabled")
        if raw_enabled is None:
            snap.feature_enabled = None
        else:
            snap.feature_enabled = (raw_enabled == "1")
    except Exception as e:
        logger.warning("读取 reimbursement_feature_enabled 失败: %s", e)
        snap.feature_enabled = None

    # ---- monthly_pool ----
    try:
        raw_pool = await get_config("reimbursement_monthly_pool")
        snap.monthly_pool = _parse_monthly_pool(raw_pool)
    except Exception as e:
        logger.warning("读取 reimbursement_monthly_pool 失败: %s", e)
        snap.monthly_pool = None

    # ---- 本月 reset baseline（如有）----
    if snap.current_month_key:
        try:
            baselines = await get_reimburse_pool_reset_baselines()
            entry = baselines.get(snap.current_month_key)
            if isinstance(entry, dict):
                snap.current_month_reset_baseline = int(
                    entry.get("baseline_amount") or 0
                )
        except Exception as e:
            logger.warning("读取 reset baseline 失败: %s", e)

    # ---- 最低积分门槛 ----
    try:
        snap.min_points = await get_reimbursement_min_points()
    except Exception as e:
        logger.warning("读取 min_points 失败: %s", e)
        snap.min_points = None

    # ---- queued 名单条数 ----
    try:
        snap.queued_count = await count_queued_reimbursements()
    except Exception as e:
        logger.warning("count_queued_reimbursements 失败: %s", e)
        snap.queued_count = None

    # ---- 必关频道 / 群组 ----
    try:
        chats = await get_reimburse_required_chats()
        snap.required_chats_total = len(chats)
        snap.required_chats_enabled = sum(
            1 for c in chats if c.get("enabled")
        )
    except Exception as e:
        logger.warning("get_reimburse_required_chats 失败: %s", e)
        snap.required_chats_total = None
        snap.required_chats_enabled = None

    return snap


# ============ 渲染 ============


def _fmt(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_feature(enabled: Optional[bool]) -> str:
    if enabled is None:
        return "N/A（config 未设置）"
    return "✅ 开启" if enabled else "❌ 关闭"


def _fmt_pool(monthly_pool: Optional[int]) -> str:
    if monthly_pool is None:
        return "N/A"
    if monthly_pool == 0:
        return "不限（0 元）"
    return f"{monthly_pool} 元"


def _fmt_min_points(snap: ReimbursementRulesSnapshot) -> str:
    if snap.min_points is None:
        return "N/A"
    if snap.min_points == 0:
        return f"0 分（未启用门槛；上限 {snap.min_points_max} 分）"
    return (
        f"{snap.min_points} 分 "
        f"(默认 {snap.min_points_default} / 上限 {snap.min_points_max})"
    )


def _fmt_queued_mode(snap: ReimbursementRulesSnapshot) -> str:
    """queued 模式描述：仅当 feature_enabled=False 时触发新 queued 入队。"""
    if snap.feature_enabled is None:
        return "N/A（功能开关未设置）"
    if snap.feature_enabled:
        return (
            f"功能开启时不入队；当前 queued 名单 {_fmt(snap.queued_count)} 条"
            f"（来自历史 OFF 期遗留）"
        )
    return (
        f"功能关闭时合格用户进 queued；当前 queued 名单 "
        f"{_fmt(snap.queued_count)} 条"
    )


def _fmt_required_chats(snap: ReimbursementRulesSnapshot) -> str:
    if snap.required_chats_total is None:
        return "N/A"
    if snap.required_chats_total == 0:
        return "无（不拦截报销）"
    return (
        f"共 {snap.required_chats_total} 个 "
        f"(启用 {_fmt(snap.required_chats_enabled)})"
    )


def render_reimbursement_rules(snap: ReimbursementRulesSnapshot) -> str:
    """渲染只读规则页。

    内容来源：
        - config 表：feature_enabled / monthly_pool / min_points / required_chats
                     / reset baselines
        - 数据库：queued 名单条数
        - 硬编码：weekly limit / reset voucher 规则
    """
    if snap.generated_at is not None:
        try:
            ts_str = snap.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    # 月度池 + 重置基线说明
    pool_lines = [f"• 月度池上限：{_fmt_pool(snap.monthly_pool)}"]
    if snap.current_month_reset_baseline is not None:
        pool_lines.append(
            f"• 本月 ({snap.current_month_key}) 重置基线："
            f"{snap.current_month_reset_baseline} 元"
        )
    else:
        pool_lines.append(
            f"• 本月 ({snap.current_month_key or 'N/A'}) 未设置重置基线"
        )

    lines: list[str] = [
        "📜 报销规则一览",
        "（只读 · 编辑请回上一页选择对应配置项）",
        "",
        "功能开关",
        f"• 报销功能：{_fmt_feature(snap.feature_enabled)}",
        "",
        "月度报销池",
        *pool_lines,
        "",
        "积分门槛",
        f"• 最低积分：{_fmt_min_points(snap)}",
        "",
        "每周限制",
        f"• 每用户每周 approved 上限：{snap.weekly_approved_limit} 次（硬编码）",
        f"• 当前周 ({snap.current_week_key or 'N/A'})",
        f"• reset voucher 一次性跳过本周校验（不增加永久额度）",
        "",
        "queued 名单模式",
        f"• {_fmt_queued_mode(snap)}",
        "",
        "报销必关频道 / 群组",
        f"• {_fmt_required_chats(snap)}",
        "",
        f"快照时间：{ts_str}",
    ]
    return "\n".join(lines)
