"""管理员后台「📜 积分规则一览」只读规则快照（Sprint 4 §6.2.1）。

提供：
    - PointsRulesSnapshot：dataclass，承载所有当前生效的积分规则
    - get_points_rules_snapshot()：从代码常量 + config 表读取
    - render_points_rules()：纯渲染函数

设计原则：
    - 全程只读：不写任何表，不修改加扣分逻辑
    - 与 POLICY.md Part I §四 / §五 / §六 内容口径一致；
      service 是唯一聚合口径，避免漂移
    - 仅暴露规则与配置，**不**展示运营状态（持币 TOP / 累计加分），
      状态查询走既有 admin:points:overview

为什么这是「规则页」而不是「编辑页」：
    - 规则：加扣分的 reason 取值 / 套餐预设 / 自定义范围 / 余额一致性约束
    - 编辑：手动加扣分（既有 admin:points:grant FSM）
    - 编辑能力在 §6.2.2（下一个 Sprint）继续；本页严格只读
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pytz import timezone as pytz_timezone

from bot.config import config
from bot.database import (
    POINT_CUSTOM_MAX,
    POINT_CUSTOM_MIN,
    POINT_GRANT_REASON_OPTIONS,
    POINT_PACKAGE_OPTIONS,
    get_reimbursement_min_points,
)

logger = logging.getLogger(__name__)


# 手动加扣分自定义范围（spec §6.3 step 2）—— 集中常量以便规则页引用
MANUAL_GRANT_DELTA_MIN = -100
MANUAL_GRANT_DELTA_MAX = 100


@dataclass
class PointsRulesSnapshot:
    """当前生效的积分规则快照。

    所有列表字段都是代码常量的浅拷贝；不会因运行时修改而变化（运行时也
    没有对这些常量的写入路径）。
    """

    # 评价/报告审核通过加分（reason='review_approved'）
    review_packages: list[dict] = field(default_factory=list)
    review_custom_min: int = POINT_CUSTOM_MIN
    review_custom_max: int = POINT_CUSTOM_MAX

    # 手动加扣分（reason='admin_grant' / 'admin_revoke'）
    manual_reason_options: list[dict] = field(default_factory=list)
    manual_delta_min: int = MANUAL_GRANT_DELTA_MIN
    manual_delta_max: int = MANUAL_GRANT_DELTA_MAX

    # 已知 reason 取值映射（含含义与来源）
    reason_catalog: list[dict] = field(default_factory=list)

    # 报销最低积分门槛（与 Sprint 3 §6.2.1 一致；从 config 读）
    reimburse_min_points: Optional[int] = None

    # 元信息
    generated_at: Optional[datetime] = None


def _now_local() -> datetime:
    return datetime.now(pytz_timezone(config.timezone))


# 与 POLICY §3 "已知的 reason 取值"表保持同步；此处显式声明用于后台展示。
# 不读 DB，避免与可能的历史脏数据混淆 —— 规则页展示的是「代码层已声明的」reason。
REASON_CATALOG: list[dict] = [
    {
        "reason": "review_approved",
        "meaning": "评价 / 报告审核通过",
        "source": "超管在「报告审核」点通过时按所选套餐加分",
        "delta_sign": "+",
    },
    {
        "reason": "admin_grant",
        "meaning": "管理员加分",
        "source": "超管「积分管理」手动 + 分",
        "delta_sign": "+",
    },
    {
        "reason": "admin_revoke",
        "meaning": "管理员扣分",
        "source": "超管「积分管理」手动 - 分",
        "delta_sign": "-",
    },
    # Phase A0（2026-05-23）已下线：lottery_entry / lottery_refund 积分原因
    # （抽奖功能整体下线；历史 point_transactions 数据保留可查）
]


async def get_points_rules_snapshot() -> PointsRulesSnapshot:
    """读取当前生效的积分规则快照。"""
    snap = PointsRulesSnapshot(
        review_packages=list(POINT_PACKAGE_OPTIONS),
        manual_reason_options=list(POINT_GRANT_REASON_OPTIONS),
        reason_catalog=list(REASON_CATALOG),
        generated_at=_now_local(),
    )
    # 与 Sprint 3 §5.2.1 同口径引用报销门槛
    try:
        snap.reimburse_min_points = await get_reimbursement_min_points()
    except Exception as e:
        logger.warning("读取 reimburse_min_points 失败: %s", e)
        snap.reimburse_min_points = None
    return snap


# ============ 渲染 ============


def _fmt_int(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def _fmt_delta(delta: int) -> str:
    """加分用 +N 显式带号；0 / 负数原样。"""
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def _fmt_reimburse_min(snap: PointsRulesSnapshot) -> str:
    if snap.reimburse_min_points is None:
        return "N/A（与 admin:reimburse_rules 同源）"
    if snap.reimburse_min_points == 0:
        return "0 分（未启用门槛；详见报销规则一览）"
    return f"{snap.reimburse_min_points} 分（详见报销规则一览）"


def render_points_rules(snap: PointsRulesSnapshot) -> str:
    """渲染积分规则只读页文本。"""
    if snap.generated_at is not None:
        try:
            ts_str = snap.generated_at.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_str = "N/A"
    else:
        ts_str = "N/A"

    lines: list[str] = [
        "📜 积分规则一览",
        "（只读 · 加扣分操作请回上一页选择对应入口）",
        "",
        "积分流水 reason 取值",
    ]
    for entry in snap.reason_catalog:
        lines.append(
            f"• {entry['delta_sign']} {entry['reason']}：{entry['meaning']}"
        )
    lines.append("")
    lines.append("评价 / 报告审核加分套餐（reason=review_approved）")
    if not snap.review_packages:
        lines.append("• N/A（POINT_PACKAGE_OPTIONS 为空）")
    else:
        for pkg in snap.review_packages:
            lines.append(
                f"• {pkg.get('label', pkg.get('key'))}（key={pkg.get('key')}）："
                f"{_fmt_delta(int(pkg.get('delta') or 0))}"
            )
    lines.append(
        f"• 自定义范围：{_fmt_delta(snap.review_custom_min)} ~ "
        f"{_fmt_delta(snap.review_custom_max)}（仅加分，不在此处扣分）"
    )
    lines.append("")
    lines.append("管理员手动加扣分（admin:points:grant）")
    if not snap.manual_reason_options:
        lines.append("• N/A（POINT_GRANT_REASON_OPTIONS 为空）")
    else:
        for opt in snap.manual_reason_options:
            lines.append(
                f"• {opt.get('label', opt.get('key'))}（key={opt.get('key')}）："
                f"默认 reason={opt.get('reason')}"
            )
    lines.append(
        f"• 自定义 delta 范围：{_fmt_delta(snap.manual_delta_min)} ~ "
        f"{_fmt_delta(snap.manual_delta_max)}（含 0；可正可负）"
    )
    lines.append("• ⚠️ 手动扣分不校验余额，可能产生负余额（POLICY §6.4）")
    lines.append("")
    # Phase A0（2026-05-23）已下线：抽奖积分（lottery_entry / lottery_refund）章节
    lines.append("报销最低积分门槛")
    lines.append(f"• 当前：{_fmt_reimburse_min(snap)}")
    lines.append("")
    lines.append("余额一致性")
    lines.append("• users.total_points 应等于 SUM(point_transactions.delta)")
    lines.append("• 无自动对账工具（§6.2.3 待落地，POLICY §7.2）")
    lines.append("")
    lines.append(f"快照时间：{ts_str}")
    return "\n".join(lines)
