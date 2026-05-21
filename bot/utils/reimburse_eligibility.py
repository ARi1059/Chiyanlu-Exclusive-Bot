"""评价前置报销资格预判（2026-05-21）。

把"该用户当前能否申请报销"这一判定从 review_card._enter_reimburse_or_submit
（submit 时刻）提到 start_card_review（选老师后、写评价前）的位置。

判定项（任意一项不满足均视为 ineligible，按以下优先级返回 reason）：
    1. feature_off       —— reimbursement_feature_enabled != '1'
    2. amount_zero       —— 老师 price 档不在报销范围（compute_reimbursement_amount=0）
    3. below_threshold   —— min_pts > 0 且 user 总积分 < min_pts
    4. pool_exhausted    —— 月池有上限且剩余 < amount（含 reset baseline 口径）

通过：返回 (True, info)，info 中 reason=None。

设计原则：
    - 仅 SELECT，不写 DB
    - 复用既有 helper，不内联 SQL（[get_reimbursement_min_points] /
      [get_user_total_points] / [compute_reimbursement_amount] /
      [get_reimbursement_monthly_pool_usage] / [current_month_key]）
    - reason 字符串与 [format_reimburse_ineligibility_hint] 的分支一一对应
    - 调用方拿 info 后，可直接传给 hint formatter 渲染提交成功页尾注；也可
      在 admin 审批阶段以同一口径 re-check

PS：本判定是「预判」性质——final 落库 / 审批仍以 admin 处那次为准
（admin_reimburse.py 内月池 / weekly_limit 校验保持不变）；本预判失败
也不会阻塞普通评价提交，仅决定是否在 UI 上提示报销选择。
"""
from __future__ import annotations

import logging
from typing import Optional

from bot.database import (
    compute_reimbursement_amount,
    current_month_key,
    get_config,
    get_reimbursement_min_points,
    get_reimbursement_monthly_pool_usage,
    get_user_total_points,
)

logger = logging.getLogger(__name__)


REASON_FEATURE_OFF = "feature_off"
REASON_AMOUNT_ZERO = "amount_zero"
REASON_BELOW_THRESHOLD = "below_threshold"
REASON_POOL_EXHAUSTED = "pool_exhausted"


async def is_user_reimburse_eligible_for_review(
    user_id: int,
    teacher_price: Optional[str],
) -> tuple[bool, dict]:
    """评价前置报销资格预判。

    Args:
        user_id: 评价者 TG id
        teacher_price: 老师 price 字段原始值（如 "1000P"）

    Returns:
        (eligible, info) where info dict 含：
            amount (int)             —— compute_reimbursement_amount(teacher_price)
            points (int)             —— 用户当前总积分
            min_pts (int)            —— 报销门槛（0 表示不启用）
            feature_enabled (bool)   —— 报销功能总开关
            pool_limit (int)         —— 月池上限（0 表示不限）
            pool_used (int)          —— 月池本月已用（effective_used 口径）
            pool_remaining (int)     —— 月池剩余；pool_limit=0 时为 -1（不限）
            reason (Optional[str])   —— None 表示 eligible；否则为上述常量之一

    所有 SQL 查询走 try/except 容错——任何单项查询失败不阻塞判定，按
    "保守路径"（视为 ineligible 或 0）继续；上层调用方仍能拿到 info 并渲染
    最有意义的 hint。
    """
    info: dict = {
        "amount": 0,
        "points": 0,
        "min_pts": 0,
        "feature_enabled": False,
        "pool_limit": 0,
        "pool_used": 0,
        "pool_remaining": -1,
        "reason": None,
    }

    # 1) feature toggle
    try:
        feature_enabled = (await get_config("reimbursement_feature_enabled")) == "1"
    except Exception as e:
        logger.warning("eligibility: get feature toggle 失败 user=%s: %s", user_id, e)
        feature_enabled = False
    info["feature_enabled"] = feature_enabled

    # 2) amount（老师价位档）—— 不依赖 DB，纯计算
    amount = compute_reimbursement_amount(teacher_price)
    info["amount"] = amount

    # 3) 积分 + 门槛
    try:
        points = await get_user_total_points(int(user_id))
    except Exception as e:
        logger.warning("eligibility: get_user_total_points 失败 user=%s: %s", user_id, e)
        points = 0
    info["points"] = points

    try:
        min_pts = await get_reimbursement_min_points()
    except Exception as e:
        logger.warning("eligibility: get_reimbursement_min_points 失败: %s", e)
        min_pts = 0
    info["min_pts"] = min_pts

    # 4) 月池
    try:
        pool_raw = await get_config("reimbursement_monthly_pool")
        pool_limit = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool_limit = 0
    except Exception as e:
        logger.warning("eligibility: get monthly_pool config 失败: %s", e)
        pool_limit = 0
    info["pool_limit"] = pool_limit

    pool_used = 0
    if pool_limit > 0:
        try:
            usage = await get_reimbursement_monthly_pool_usage(current_month_key())
            pool_used = int(usage.get("effective_used", 0))
        except Exception as e:
            logger.warning("eligibility: pool usage 查询失败: %s", e)
            pool_used = 0
    info["pool_used"] = pool_used
    info["pool_remaining"] = (pool_limit - pool_used) if pool_limit > 0 else -1

    # ---- 按优先级判定 ----
    if not feature_enabled:
        info["reason"] = REASON_FEATURE_OFF
        return False, info
    if amount <= 0:
        info["reason"] = REASON_AMOUNT_ZERO
        return False, info
    if min_pts > 0 and points < min_pts:
        info["reason"] = REASON_BELOW_THRESHOLD
        return False, info
    if pool_limit > 0 and info["pool_remaining"] < amount:
        info["reason"] = REASON_POOL_EXHAUSTED
        return False, info

    return True, info
