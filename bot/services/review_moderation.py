"""评价审核共享 service（通过 / 拒绝的业务核心）。

抽自 bot/handlers/rreview_admin.py 的 _do_approve_inner / _do_reject —— 把「业务副作用」
与「Telegram UI 翻页」解耦：本模块只做业务（落库 + 加分 + 审计 + 锁 + 报销联动 + 重算 +
频道/讨论群/私聊通知），返回结果 dataclass；调用方（bot handler / MiniApp web 端点）各自
处理自己的 UI。两处共用同一实现，杜绝逻辑漂移。

幂等闸门：以 approve_teacher_review / reject_teacher_review 的原子 UPDATE 返回值为唯一防重
依据（WHERE status='pending'，并发只第一个赢）。除落库 + 加分外，其余副作用 best-effort
（失败仅 logger.warning，不回滚、不阻断），与原 handler 行为一致。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from bot.database import (
    add_point_transaction,
    approve_teacher_review,
    clear_review_discussion_msg,
    compute_reimbursement_amount,
    create_reimbursement,
    current_month_key,
    current_week_key,
    get_teacher,
    get_teacher_review,
    get_user,
    get_user_total_points,
    log_admin_audit,
    reject_teacher_review,
    set_review_hidden,
)
from bot.utils.rreview_notify import notify_review_approved, notify_review_rejected

logger = logging.getLogger(__name__)


@dataclass
class ApproveResult:
    ok: bool
    error: Optional[str] = None
    review_id: int = 0
    teacher_id: int = 0
    user_id: int = 0
    teacher_name: Optional[str] = None
    delta: int = 0
    new_total: Optional[int] = None
    reimb_amount: int = 0
    reimb_status: str = ""
    reimb_created_id: Optional[int] = None
    hidden: bool = False


@dataclass
class VisibilityResult:
    ok: bool
    error: Optional[str] = None
    review_id: int = 0
    hidden: bool = False


@dataclass
class RejectResult:
    ok: bool
    error: Optional[str] = None
    review_id: int = 0
    teacher_id: int = 0
    user_id: int = 0
    teacher_name: Optional[str] = None


async def approve_review(
    bot,
    *,
    review_id: int,
    reviewer_id: int,
    delta: int,
    package_label: Optional[str],
    hidden: bool = False,
) -> ApproveResult:
    """通过一条评价 + 加分 + 全部副作用（移自 _do_approve_inner 396–588）。

    hidden=True（超管「通过并隐藏」）：加分/重算数据/通知用户「已通过」/报销联动**全部照旧**，
    唯独**不发评论区**（跳过 publish_review_comment），并告知老师该评价已被隐藏。
    返回 ApproveResult；ok=False 时 error 为原因（不存在 / 非 pending / 落库失败）。
    """
    review = await get_teacher_review(review_id)
    if not review:
        return ApproveResult(ok=False, error="评价不存在", review_id=review_id)
    if review["status"] != "pending":
        return ApproveResult(ok=False, error=f"该评价已是 {review['status']}", review_id=review_id)

    # 1. approve（原子防重闸门）
    ok = await approve_teacher_review(review_id, reviewer_id=reviewer_id)
    if not ok:
        return ApproveResult(ok=False, error="通过失败", review_id=review_id)

    # 1b. 隐藏标记（超管「通过并隐藏」）—— 在后续展示/发布判定前落库
    if hidden:
        try:
            await set_review_hidden(review_id, True)
        except Exception as e:
            logger.warning("set_review_hidden 失败 review=%s: %s", review_id, e)

    teacher_id = review["teacher_id"]
    user_id = review["user_id"]

    # 2. 加分（P.1）
    new_total: Optional[int] = None
    try:
        tx_id = await add_point_transaction(
            user_id,
            delta=delta,
            reason="review_approved",
            related_id=review_id,
            operator_id=reviewer_id,
            note=package_label or None,
        )
        new_total = await get_user_total_points(user_id)
        if tx_id is None:
            logger.warning("add_point_transaction 返回 None review=%s delta=%s", review_id, delta)
    except Exception as e:
        logger.warning("add_point_transaction 失败 review=%s delta=%s: %s", review_id, delta, e)

    # audit
    await log_admin_audit(
        admin_id=reviewer_id,
        action="rreview_approve",
        target_type="teacher_review",
        target_id=str(review_id),
        detail={
            "teacher_id": teacher_id,
            "user_id": user_id,
            "delta": delta,
            "package": package_label,
            "new_total": new_total,
            "hidden": bool(hidden),
        },
    )
    # 释放 claim 锁
    try:
        from bot.utils.review_claim import release_claim
        release_claim("teacher_review", review_id, reviewer_id)
    except Exception:
        pass

    # 2.5 报销联动：
    #   request_reimbursement=1 (用户勾选) → status='pending'（admin 审批）
    #   request_reimbursement=2 (功能关闭时静默录入) → status='queued'（admin 名单）
    #   request_reimbursement=0 → 不创建；两种情况都需满足实时积分门槛 + 老师价位 > 0
    reimb_created_id: Optional[int] = None
    reimb_amount: int = 0
    reimb_status: str = ""
    try:
        teacher_id_for_reimb = teacher_id
        req_flag = int(review.get("request_reimbursement") or 0)
        if req_flag in (1, 2):
            teacher_obj = await get_teacher(teacher_id_for_reimb)
            reimb_amount = compute_reimbursement_amount(
                teacher_obj.get("price") if teacher_obj else None
            )
            from bot.database import get_reimbursement_min_points
            min_pts = await get_reimbursement_min_points()
            effective_pts = new_total if new_total is not None else 0
            if reimb_amount > 0 and (min_pts == 0 or effective_pts >= min_pts):
                reimb_status = "pending" if req_flag == 1 else "queued"
                reimb_created_id = await create_reimbursement(
                    user_id=user_id,
                    review_id=review_id,
                    teacher_id=teacher_id_for_reimb,
                    amount=reimb_amount,
                    week_key=current_week_key(),
                    month_key=current_month_key(),
                    status=reimb_status,
                )
                if reimb_created_id:
                    action_label = (
                        "reimburse_created" if reimb_status == "pending"
                        else "reimburse_queued"
                    )
                    await log_admin_audit(
                        admin_id=reviewer_id,
                        action=action_label,
                        target_type="reimbursement",
                        target_id=str(reimb_created_id),
                        detail={
                            "user_id": user_id,
                            "review_id": review_id,
                            "amount": reimb_amount,
                            "status": reimb_status,
                        },
                    )
                    # 通知所有超管去审核报销（pending / queued 都通知）；失败仅 warning
                    try:
                        from bot.utils.reimburse_notify import (
                            notify_supers_reimburse_pending,
                        )
                        teacher_obj = await get_teacher(teacher_id_for_reimb)
                        teacher_label = (
                            teacher_obj.get("display_name")
                            if teacher_obj else f"#{teacher_id_for_reimb}"
                        )
                        try:
                            user_obj = await get_user(int(user_id))
                        except Exception:
                            user_obj = None
                        if user_obj and user_obj.get("username"):
                            user_label = f"@{user_obj['username']}"
                        elif user_obj and user_obj.get("first_name"):
                            user_label = user_obj["first_name"]
                        else:
                            user_label = str(user_id)
                        await notify_supers_reimburse_pending(
                            bot,
                            reimb_id=reimb_created_id,
                            user_id=int(user_id),
                            user_label=user_label,
                            teacher_label=teacher_label,
                            review_id=review_id,
                            amount=reimb_amount,
                            status=reimb_status,
                        )
                    except Exception as e:
                        logger.warning(
                            "通知超管报销待审核失败 reimb=%s: %s",
                            reimb_created_id, e,
                        )
    except Exception as e:
        logger.warning("报销联动失败 review=%s: %s", review_id, e)

    # 3-4. 9.5 链：recalc + caption + 讨论群评论
    try:
        from bot.database import recalculate_teacher_review_stats
        await recalculate_teacher_review_stats(teacher_id)
    except Exception as e:
        logger.warning("recalculate_teacher_review_stats 失败 teacher=%s: %s", teacher_id, e)
    try:
        from bot.utils.teacher_channel_publish import update_teacher_post_caption
        await update_teacher_post_caption(bot, teacher_id, force=True)
    except Exception as e:
        logger.warning("update_teacher_post_caption 失败 teacher=%s: %s", teacher_id, e)
    # 隐藏的评价不发评论区（其余副作用照旧）
    if not hidden:
        try:
            from bot.utils.review_comment import publish_review_comment, CommentError
            await publish_review_comment(bot, review_id)
        except CommentError as e:
            logger.warning(
                "publish_review_comment failed review=%s reason=%s: %s",
                review_id, getattr(e, "reason", "?"), e,
            )
        except Exception as e:
            logger.warning("publish_review_comment 异常 review=%s: %s", review_id, e)

    # 4b. 推送评价到老师私聊；失败仅 warning。hidden 时附「已隐藏」提示。
    try:
        from bot.utils.rreview_notify import notify_teacher_review_approved
        await notify_teacher_review_approved(bot, review_id, hidden=hidden)
    except Exception as e:
        logger.warning(
            "notify_teacher_review_approved 异常 review=%s: %s", review_id, e,
        )

    # 5. 通知评价者（附积分）
    teacher = await get_teacher(teacher_id)
    teacher_name = teacher["display_name"] if teacher else None
    try:
        # 静默 queued 不向用户提示报销（用户也没勾选/没见到选项）
        notify_reimb_pending = (
            reimb_created_id is not None and reimb_status == "pending"
        )
        await notify_review_approved(
            bot, review_id,
            teacher_name=teacher_name,
            delta=delta,
            new_total=new_total,
            package_label=package_label,
            reimb_amount=reimb_amount,
            reimb_pending=notify_reimb_pending,
        )
    except Exception as e:
        logger.warning("notify_review_approved 失败 review=%s: %s", review_id, e)

    return ApproveResult(
        ok=True,
        review_id=review_id,
        teacher_id=teacher_id,
        user_id=user_id,
        teacher_name=teacher_name,
        delta=delta,
        new_total=new_total,
        reimb_amount=reimb_amount,
        reimb_status=reimb_status,
        reimb_created_id=reimb_created_id,
        hidden=bool(hidden),
    )


async def reject_review(
    bot,
    *,
    review_id: int,
    reviewer_id: int,
    reason: Optional[str],
) -> RejectResult:
    """驳回一条评价 + 通知提交者（移自 _do_reject 1156–1201）。

    返回 RejectResult；ok=False 时 error 为原因（不存在 / 非 pending / 落库失败）。
    """
    review = await get_teacher_review(review_id)
    if not review:
        return RejectResult(ok=False, error="评价不存在或已被处理", review_id=review_id)
    if review["status"] != "pending":
        return RejectResult(ok=False, error=f"该评价已是 {review['status']}", review_id=review_id)

    ok = await reject_teacher_review(review_id, reviewer_id=reviewer_id, reason=reason)
    if not ok:
        return RejectResult(ok=False, error="驳回失败", review_id=review_id)

    teacher_id = review["teacher_id"]
    user_id = review["user_id"]

    await log_admin_audit(
        admin_id=reviewer_id,
        action="rreview_reject",
        target_type="teacher_review",
        target_id=str(review_id),
        detail={
            "teacher_id": teacher_id,
            "user_id": user_id,
            "reason": reason or "",
        },
    )
    # 释放 claim 锁
    try:
        from bot.utils.review_claim import release_claim
        release_claim("teacher_review", review_id, reviewer_id)
    except Exception:
        pass

    teacher = await get_teacher(teacher_id)
    teacher_name = teacher["display_name"] if teacher else None
    try:
        await notify_review_rejected(
            bot, review_id, teacher_name=teacher_name, reason=reason,
        )
    except Exception as e:
        logger.warning("notify_review_rejected 失败 review=%s: %s", review_id, e)

    return RejectResult(
        ok=True,
        review_id=review_id,
        teacher_id=teacher_id,
        user_id=user_id,
        teacher_name=teacher_name,
    )


async def set_review_visibility_core(
    bot, *, review_id: int, reviewer_id: int, hidden: bool,
) -> VisibilityResult:
    """事后切换评价可见性（隐藏 / 取消隐藏），仅对已通过评价有意义。

    - hidden=True（事后隐藏）：标记隐藏 → 尽力删讨论群已发评论 + 清引用（容错）。
    - hidden=False（取消隐藏）：标记取消 → 若无讨论群消息则补发评论区。
    两路都写 audit + best-effort 通知老师。可见列表 list_approved_reviews 即时反映。
    """
    review = await get_teacher_review(review_id)
    if not review:
        return VisibilityResult(ok=False, error="评价不存在", review_id=review_id)
    if review["status"] != "approved":
        return VisibilityResult(
            ok=False, error="仅已通过的评价可切换可见性", review_id=review_id,
        )

    await set_review_hidden(review_id, hidden)
    await log_admin_audit(
        admin_id=reviewer_id,
        action="rreview_hide" if hidden else "rreview_unhide",
        target_type="teacher_review",
        target_id=str(review_id),
        detail={"teacher_id": review.get("teacher_id"), "user_id": review.get("user_id")},
    )

    if hidden:
        # 事后隐藏：删掉讨论群已发评论（若有），清引用以便日后取消隐藏可重发
        chat_id = review.get("discussion_chat_id")
        msg_id = review.get("discussion_msg_id")
        if chat_id and msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning("隐藏删评论失败 review=%s: %s", review_id, e)
            try:
                await clear_review_discussion_msg(review_id)
            except Exception as e:
                logger.warning("clear_review_discussion_msg 失败 review=%s: %s", review_id, e)
    else:
        # 取消隐藏：无讨论群消息则补发评论区
        if not review.get("discussion_msg_id"):
            try:
                from bot.utils.review_comment import publish_review_comment, CommentError
                await publish_review_comment(bot, review_id)
            except CommentError as e:
                logger.warning(
                    "取消隐藏补发评论 failed review=%s reason=%s: %s",
                    review_id, getattr(e, "reason", "?"), e,
                )
            except Exception as e:
                logger.warning("取消隐藏补发评论异常 review=%s: %s", review_id, e)

    # best-effort 通知老师可见性变更
    try:
        from bot.utils.rreview_notify import notify_teacher_review_visibility
        await notify_teacher_review_visibility(bot, review_id, hidden=hidden)
    except Exception as e:
        logger.warning("notify_teacher_review_visibility 失败 review=%s: %s", review_id, e)

    return VisibilityResult(ok=True, review_id=review_id, hidden=hidden)
