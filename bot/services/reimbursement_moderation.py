"""报销审核共享 service（拒绝 / 激活的业务核心）。

抽自 bot/handlers/admin_reimburse.py 的 on_reimburse_reject_reason / cb_reimburse_activate —
把业务副作用（落库 + 审计 + 通知用户）与 Telegram FSM/UI 解耦，bot handler 与 MiniApp web
端点共用，杜绝逻辑漂移。

⚠️ 不含「同意/打款」：同意是真实打款（超管输支付宝口令 → bot 发用户 → 发送成功才 approve），
口令是真钱、不存库，必须留在 bot 私聊已加固的口令 FSM；web 端只深链回 bot，不在此实现。

幂等闸门：reject_reimbursement / activate_queued_reimbursement 均 `WHERE status=...` 原子，
返回值区分"本次生效" vs "已处理"。通知用 safe_* 函数（内部容错，不回滚）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from bot.database import (
    activate_queued_reimbursement,
    get_reimbursement,
    log_admin_audit,
    reject_reimbursement,
)
from bot.utils.reimburse_notify import (
    safe_notify_user_reimburse_activated,
    safe_notify_user_reimburse_reject,
)

logger = logging.getLogger(__name__)


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
