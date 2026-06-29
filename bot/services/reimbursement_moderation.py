"""报销审核共享 service（拒绝 / 激活 / 打款的业务核心）。

抽自 bot/handlers/admin_reimburse.py —— 把业务副作用（落库 + 审计 + 通知用户 + 打款）与
Telegram FSM/UI 解耦，bot handler 与 MiniApp web 端点共用，杜绝逻辑漂移。

「同意/打款」是真实打款（超管输支付宝口令 → bot DM 发用户 → 发送成功才 approve），口令是真钱：
    - 口令**不存库**；audit 只记 mask_token；本模块**绝不 log 明文 token**；
    - **先发后批**：safe_send_user_payout 成功才 approve_reimbursement（发失败不批，可重试）；
    - 月池 / 周配额 / voucher 服务端权威复核（compute_payout_precheck）。
打款仍由 bot 进程发（§十七 口令送达留 bot），core 只编排。MiniApp 端点调本模块；bot 的
cb_reimburse_payout_confirm 暂未委托（动钱路径，后续单列），两边共用底层原语保持一致。

幂等闸门：reject_reimbursement / activate_queued_reimbursement / approve_reimbursement 均
`WHERE status=...` 原子，返回值区分"本次生效" vs "已处理"。通知用 safe_* 函数（内部容错，不回滚）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from bot.database import (
    activate_queued_reimbursement,
    approve_reimbursement,
    consume_reimbursement_reset,
    count_approved_reimbursements_in_week,
    get_config,
    get_reimbursement,
    get_reimbursement_monthly_pool_usage,
    get_reimbursement_weekly_limit,
    get_unused_reimbursement_reset,
    grant_reimbursement_reset,
    log_admin_audit,
    mark_reimbursement_notified,
    reject_reimbursement,
)
from bot.utils.reimburse_notify import (
    mask_token,
    safe_notify_user_reimburse_activated,
    safe_notify_user_reimburse_reject,
    safe_send_user_payout,
)

logger = logging.getLogger(__name__)

# 支付宝口令长度边界（与 bot/handlers/admin_reimburse.py 的 _TOKEN_MIN/MAX_LEN 对齐）
_TOKEN_MIN_LEN = 4
_TOKEN_MAX_LEN = 200


@dataclass
class RejectResult:
    ok: bool
    error: Optional[str] = None
    reimb_id: int = 0
    user_id: int = 0
    amount: int = 0


@dataclass
class ActivateResult:
    ok: bool
    error: Optional[str] = None
    reimb_id: int = 0
    user_id: int = 0
    amount: int = 0


async def reject_reimbursement_core(
    bot, *, reimb_id: int, admin_id: int, reason: str,
) -> RejectResult:
    """驳回报销 + 通知用户（移自 on_reimburse_reject_reason 611–637）。"""
    reimb = await get_reimbursement(reimb_id)
    if not reimb or reimb["status"] != "pending":
        return RejectResult(ok=False, error="报销状态已变更", reimb_id=reimb_id)

    ok = await reject_reimbursement(reimb_id, admin_id, reason)
    if not ok:
        return RejectResult(ok=False, error="驳回失败", reimb_id=reimb_id)

    user_id = int(reimb["user_id"])
    amount = int(reimb["amount"])
    await log_admin_audit(
        admin_id=admin_id,
        action="reimburse_reject",
        target_type="reimbursement",
        target_id=str(reimb_id),
        detail={"user_id": user_id, "reason": reason},
    )
    # UX-4.1：驳回通知附 CTA（safe_ 内部容错）
    await safe_notify_user_reimburse_reject(
        bot, user_id=user_id, reimb_id=reimb_id, amount=amount, reason=reason,
    )
    return RejectResult(ok=True, reimb_id=reimb_id, user_id=user_id, amount=amount)


async def activate_reimbursement_core(
    bot, *, reimb_id: int, admin_id: int,
) -> ActivateResult:
    """激活 queued → pending + 通知用户（移自 cb_reimburse_activate 825–852）。"""
    reimb = await get_reimbursement(reimb_id)
    if not reimb:
        return ActivateResult(ok=False, error="报销不存在", reimb_id=reimb_id)
    if reimb["status"] != "queued":
        return ActivateResult(
            ok=False, error=f"当前状态 {reimb['status']}，无法激活", reimb_id=reimb_id,
        )

    ok = await activate_queued_reimbursement(reimb_id)
    if not ok:
        return ActivateResult(ok=False, error="激活失败", reimb_id=reimb_id)

    user_id = int(reimb["user_id"])
    amount = int(reimb["amount"])
    await log_admin_audit(
        admin_id=admin_id,
        action="reimburse_activate",
        target_type="reimbursement",
        target_id=str(reimb_id),
        detail={"user_id": user_id, "amount": amount},
    )
    # UX-4.4：激活后通知用户"已进入审核队列"（safe_ 内部容错）
    await safe_notify_user_reimburse_activated(
        bot, user_id=user_id, reimb_id=reimb_id, amount=amount,
    )
    return ActivateResult(ok=True, reimb_id=reimb_id, user_id=user_id, amount=amount)


# ============ 打款（§15.5）：配额预检 + 口令发放 ============


@dataclass
class PayoutPrecheck:
    """打款前的月池 / 周配额 / voucher 复核结果（纯读，无副作用）。

    state ∈ {ok, need_voucher, week_blocked, over_pool}，优先级与 bot 一致：
    over_pool > week_*（满）> ok。need_voucher 表示周配额满但有 reset voucher 可消耗。
    """
    state: str
    amount: int = 0
    week_used: int = 0
    weekly_limit: int = 0
    month_used: int = 0
    pool: int = 0
    pool_remaining: Optional[int] = None
    has_reset: bool = False
    reset_voucher_id: Optional[int] = None  # 仅 need_voucher 时非 None（将被消耗）


@dataclass
class PayoutResult:
    ok: bool
    error: Optional[str] = None
    reimb_id: int = 0
    user_id: int = 0
    amount: int = 0


@dataclass
class ResetResult:
    ok: bool
    error: Optional[str] = None
    reimb_id: int = 0
    voucher_id: Optional[int] = None


async def compute_payout_precheck(reimb: dict) -> PayoutPrecheck:
    """复核打款资格（移自 admin_reimburse 详情 badge 124–147 + approve 校验 270–302）。

    纯读：月池 effective_used 口径、周已批次数、未消耗 voucher。供 MiniApp 详情徽标
    与 payout_reimbursement_core 共用，杜绝校验漂移。
    """
    user_id = int(reimb["user_id"])
    amount = int(reimb["amount"])

    week_used = await count_approved_reimbursements_in_week(user_id, reimb["week_key"])
    weekly_limit = await get_reimbursement_weekly_limit()
    reset = await get_unused_reimbursement_reset(user_id)
    has_reset = reset is not None

    pool_usage = await get_reimbursement_monthly_pool_usage(reimb["month_key"])
    month_used = int(pool_usage["effective_used"])
    pool_raw = await get_config("reimbursement_monthly_pool")
    try:
        pool = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool = 0
    pool_remaining = (pool - month_used) if pool > 0 else None

    over_pool = pool > 0 and pool_remaining is not None and amount > pool_remaining
    week_full = week_used >= weekly_limit
    if over_pool:
        state = "over_pool"
    elif week_full and has_reset:
        state = "need_voucher"
    elif week_full and not has_reset:
        state = "week_blocked"
    else:
        state = "ok"

    return PayoutPrecheck(
        state=state,
        amount=amount,
        week_used=week_used,
        weekly_limit=weekly_limit,
        month_used=month_used,
        pool=pool,
        pool_remaining=pool_remaining,
        has_reset=has_reset,
        reset_voucher_id=(int(reset["id"]) if state == "need_voucher" else None),
    )


async def payout_reimbursement_core(
    bot, *, reimb_id: int, admin_id: int, token: str,
) -> PayoutResult:
    """打款核心：校验 → 发口令 → 成功才 approve（移自 cb_reimburse_approve 270–323 +
    cb_reimburse_payout_confirm 464–512）。

    关键顺序（动钱安全，1:1 复刻 bot）：token 长度校验 → 状态/配额复核 → safe_send_user_payout
    成功才 approve_reimbursement → 消耗 voucher → mark_notified → audit（仅 mask_token）。
    任何分支都不 log 明文 token。
    """
    token = (token or "").strip()
    if len(token) < _TOKEN_MIN_LEN:
        return PayoutResult(ok=False, error=f"口令过短（至少 {_TOKEN_MIN_LEN} 字符）", reimb_id=reimb_id)
    if len(token) > _TOKEN_MAX_LEN:
        return PayoutResult(ok=False, error=f"口令过长（最多 {_TOKEN_MAX_LEN} 字符）", reimb_id=reimb_id)

    reimb = await get_reimbursement(reimb_id)
    if not reimb:
        return PayoutResult(ok=False, error="报销不存在", reimb_id=reimb_id)
    if reimb["status"] != "pending":
        return PayoutResult(ok=False, error=f"该报销已是 {reimb['status']}", reimb_id=reimb_id)

    pre = await compute_payout_precheck(reimb)
    if pre.state == "over_pool":
        return PayoutResult(ok=False, error=f"超月池：本月仅剩 {pre.pool_remaining} 元", reimb_id=reimb_id)
    if pre.state == "week_blocked":
        return PayoutResult(ok=False, error="周配额已满，请先点「重置本周」", reimb_id=reimb_id)

    user_id = int(reimb["user_id"])
    amount = pre.amount

    # 1. 先尝试发送给用户；失败 → 不 approve（与 bot 一致，可重试）
    sent_ok, err = await safe_send_user_payout(
        bot, user_id=user_id, token=token, amount=amount,
    )
    if not sent_ok:
        return PayoutResult(
            ok=False, error=f"给用户发送口令失败：{err or '未知错误'}", reimb_id=reimb_id,
        )

    # 2. 发送成功 → 真正 approve
    approved = await approve_reimbursement(reimb_id, admin_id)
    if not approved:
        # 极端：消息已发出但 DB 状态被其它进程改了 —— 与 bot 同样仅 warning
        logger.warning("payout: 已发送但 approve_reimbursement 失败 reimb=%s", reimb_id)

    # 3. 消耗 voucher（如判定需要）
    reset_consumed: Optional[int] = None
    if pre.reset_voucher_id is not None:
        try:
            await consume_reimbursement_reset(pre.reset_voucher_id, reimb_id)
            reset_consumed = pre.reset_voucher_id
        except Exception as e:
            logger.warning(
                "consume_reset 失败 reset=%s reimb=%s: %s",
                pre.reset_voucher_id, reimb_id, e,
            )

    # 4. 标记 notified
    try:
        await mark_reimbursement_notified(reimb_id)
    except Exception as e:
        logger.warning("mark_reimbursement_notified 失败 reimb=%s: %s", reimb_id, e)

    # 5. audit —— 不保存完整口令，只 mask
    await log_admin_audit(
        admin_id=admin_id,
        action="reimburse_payout_sent",
        target_type="reimbursement",
        target_id=str(reimb_id),
        detail={
            "user_id": user_id,
            "amount": amount,
            "token_masked": mask_token(token),
            "reset_consumed": reset_consumed,
        },
    )
    return PayoutResult(ok=True, reimb_id=reimb_id, user_id=user_id, amount=amount)


async def grant_reset_core(
    *, reimb_id: int, user_id: int, admin_id: int,
) -> ResetResult:
    """发放本周 reset voucher + audit（移自 cb_reimburse_reset_ok 682–692）。"""
    voucher_id = await grant_reimbursement_reset(user_id, admin_id)
    if not voucher_id:
        return ResetResult(ok=False, error="重置失败", reimb_id=reimb_id)
    await log_admin_audit(
        admin_id=admin_id,
        action="reimburse_reset",
        target_type="reimbursement",
        target_id=str(reimb_id),
        detail={"user_id": user_id, "voucher_id": voucher_id},
    )
    return ResetResult(ok=True, reimb_id=reimb_id, voucher_id=voucher_id)
