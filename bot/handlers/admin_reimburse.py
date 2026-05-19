"""报销审核子菜单（超管）

callback 命名空间：reimburse:*
  - reimburse:enter                    → 显示首条 pending
  - reimburse:item:<id>                → 报销详情
  - reimburse:approve:<id>             → 通过（含周配额 + 池校验）
  - reimburse:reject:<id>              → 驳回（进 FSM 收原因）
  - reimburse:reset:<user_id>:<rid>    → 重置该用户本周配额（二次确认）
  - reimburse:reset_ok:<user_id>:<rid> → 实际 reset voucher
"""
from __future__ import annotations

import functools
import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from bot.config import config
from bot.database import (
    activate_queued_reimbursement,
    approve_reimbursement,
    consume_reimbursement_reset,
    count_approved_reimbursements_in_week,
    count_pending_reimbursements,
    count_queued_reimbursements,
    get_config,
    get_reimbursement,
    get_reimbursement_monthly_pool_usage,
    get_teacher,
    get_teacher_review,
    get_unused_reimbursement_reset,
    get_user,
    grant_reimbursement_reset,
    is_super_admin,
    list_pending_reimbursements,
    list_queued_reimbursements_paged,
    log_admin_audit,
    reject_reimbursement,
)
from bot.keyboards.admin_kb import (
    admin_review_done_next_kb,
    main_menu_kb,
    reimburse_action_kb,
    reimburse_empty_kb,
    reimburse_payout_confirm_kb,
    reimburse_payout_done_kb,
    reimburse_payout_waiting_cancel_kb,
    reimburse_queued_item_kb,
    reimburse_queued_pagination_kb,
    reimburse_reject_cancel_kb,
    reimburse_reset_confirm_kb,
)
from bot.states.teacher_states import ReimbursePayoutStates, ReimburseRejectStates
from bot.utils.reimburse_notify import (
    POWERED_BY_FOOTER,
    format_payout_confirm_text,
    format_payout_done_text,
    format_payout_waiting_token_text,
    mask_token,
    safe_notify_user_reimburse_activated,
    safe_notify_user_reimburse_reject,
    safe_send_user_payout,
)

logger = logging.getLogger(__name__)

router = Router(name="admin_reimburse")


def _super_admin_required(func):
    """仅超管

    @functools.wraps 让 aiogram 看到内层 handler 真实签名，避免 dispatcher
    等 kwargs 误注入引发 TypeError。
    """
    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            uid = event.from_user.id if event.from_user else 0
        else:
            uid = event.from_user.id if event.from_user else 0
        if uid != config.super_admin_id and not await is_super_admin(uid):
            if isinstance(event, types.CallbackQuery):
                await event.answer("⚠️ 仅超管可用", show_alert=True)
            return
        return await func(event, *args, **kwargs)
    return wrapper


async def _render_reimbursement_detail(reimb: dict) -> str:
    """渲染报销详情文本（统一格式）"""
    review = await get_teacher_review(reimb["review_id"])
    teacher = await get_teacher(reimb["teacher_id"]) if reimb.get("teacher_id") else None
    user = await get_user(reimb["user_id"]) if reimb.get("user_id") else None

    teacher_name = teacher["display_name"] if teacher else f"#{reimb['teacher_id']}"
    teacher_price = teacher.get("price") if teacher else "?"
    user_display = (user.get("first_name") if user else None) or f"uid {reimb['user_id']}"
    user_uname = user.get("username") if user else None
    user_line = f"{user_display}" + (f" (@{user_uname})" if user_uname else "")

    # 周/月统计
    week_used = await count_approved_reimbursements_in_week(
        reimb["user_id"], reimb["week_key"],
    )
    reset = await get_unused_reimbursement_reset(reimb["user_id"])
    has_reset = reset is not None
    # 2026-05：使用 effective_used 口径（与 ReimbursementPoolStats 一致）
    pool_usage = await get_reimbursement_monthly_pool_usage(reimb["month_key"])
    month_used = pool_usage["effective_used"]
    pool_raw = await get_config("reimbursement_monthly_pool")
    try:
        pool = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool = 0
    pool_remaining = (pool - month_used) if pool > 0 else None

    status_label = {
        "pending":   "⏳ 待审核",
        "approved":  "✅ 已通过",
        "rejected":  "❌ 已驳回",
        "cancelled": "🚫 已取消",
    }.get(reimb["status"], reimb["status"])

    # UX-8.2：仅 pending 状态时计算决策色块（已审完的不需要提示）
    badge_line: Optional[str] = None
    if reimb["status"] == "pending":
        amount = int(reimb["amount"])
        over_pool = (
            pool > 0 and pool_remaining is not None and amount > pool_remaining
        )
        week_full = week_used >= 1
        if over_pool:
            badge_line = (
                f"🛑 超月池：本月仅剩 {pool_remaining} 元，"
                f"本次需 {amount} 元（驳回 / 等月池重置）"
            )
        elif week_full and has_reset:
            badge_line = (
                "⚠️ 需消耗 voucher：本周已批 1 次，"
                "通过将消耗预留 voucher"
            )
        elif week_full and not has_reset:
            badge_line = (
                "🛑 周配额已满：通过前需先点 [🔄 重置该用户本周]"
            )
        else:
            badge_line = "✅ 可批：周配额 + 月池均满足"

    lines = [
        f"💰 报销申请 #{reimb['id']}",
    ]
    if badge_line:
        lines.append(badge_line)
    lines += [
        "━━━━━━━━━━━━━━━",
        f"📌 状态：{status_label}",
        f"🙋 申请者：{user_line}",
        f"   uid: {reimb['user_id']}",
        f"👩‍🏫 老师：{teacher_name}（价格 {teacher_price}）",
        f"📝 评价 ID：#{reimb['review_id']}",
        f"💰 报销金额：{reimb['amount']} 元",
        "━━━━━━━━━━━━━━━",
        f"🗓 周 key：{reimb['week_key']}",
        f"   本周已批：{week_used}/1" + (
            "（有 1 张未消耗 reset voucher）" if has_reset else ""
        ),
        f"📅 月 key：{reimb['month_key']}",
        f"   本月已批总额：{month_used} 元",
    ]
    if pool > 0:
        lines.append(f"   本月池预算：{pool} 元（剩余 {pool_remaining}）")
    else:
        lines.append(f"   本月池预算：不限")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"创建时间：{reimb.get('created_at', '?')}")
    if reimb.get("decided_at"):
        lines.append(f"审核时间：{reimb['decided_at']} (by {reimb.get('decided_by')})")
    if reimb.get("reject_reason"):
        lines.append(f"驳回原因：{reimb['reject_reason']}")
    return "\n".join(lines)


# ============ 入口 + 详情 ============


@router.callback_query(F.data == "reimburse:enter")
@_super_admin_required
async def cb_reimburse_enter(callback: types.CallbackQuery, state: FSMContext):
    """[💰 报销审核] 入口：显示首条 pending；无则 empty"""
    await state.clear()
    pending = await list_pending_reimbursements(limit=1)
    if not pending:
        text = "✅ 当前没有待审核的报销申请。"
        try:
            await callback.message.edit_text(text, reply_markup=reimburse_empty_kb())
        except Exception:
            await callback.message.answer(text, reply_markup=reimburse_empty_kb())
        await callback.answer()
        return
    reimb = pending[0]
    text = await _render_reimbursement_detail(reimb)
    kb = reimburse_action_kb(reimb["id"], reimb["user_id"])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("reimburse:item:"))
@_super_admin_required
async def cb_reimburse_item(callback: types.CallbackQuery, state: FSMContext):
    """详情页（用于驳回取消 / 重置取消的回退）"""
    await state.clear()
    try:
        rid = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    reimb = await get_reimbursement(rid)
    if not reimb:
        await callback.answer("报销不存在", show_alert=True)
        return
    text = await _render_reimbursement_detail(reimb)
    kb = reimburse_action_kb(reimb["id"], reimb["user_id"])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


# ============ 通过 ============


async def _user_label_for_reimb(reimb: dict) -> str:
    """从 reimbursements 行查出 user 信息，组装 @username 或姓名兜底。"""
    user_id = reimb.get("user_id")
    try:
        u = await get_user(int(user_id)) if user_id is not None else None
    except Exception:
        u = None
    if not u:
        return str(user_id)
    name = u.get("username") or u.get("first_name") or ""
    return f"@{name}" if u.get("username") else (name or str(user_id))


@router.callback_query(F.data.startswith("reimburse:approve:"))
@_super_admin_required
async def cb_reimburse_approve(callback: types.CallbackQuery, state: FSMContext):
    """点击「✅ 同意报销」——本批不再直接 approve，而是先做月池 / 周配额校验，
    通过后进入 ReimbursePayoutStates.waiting_token，等待超管输入支付宝口令红包口令。

    口令成功发给用户后才调 approve_reimbursement（保留与旧实现一致的 audit）。
    """
    try:
        rid = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    reimb = await get_reimbursement(rid)
    if not reimb:
        await callback.answer("报销不存在", show_alert=True)
        return
    if reimb["status"] != "pending":
        await callback.answer(f"已是 {reimb['status']}", show_alert=True)
        return

    # 月池校验（2026-05：使用 effective_used = max(0, raw_used - reset_baseline)）
    pool_raw = await get_config("reimbursement_monthly_pool")
    try:
        pool = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool = 0
    if pool > 0:
        pool_usage = await get_reimbursement_monthly_pool_usage(reimb["month_key"])
        month_used = pool_usage["effective_used"]
        if month_used + int(reimb["amount"]) > pool:
            remaining = pool - month_used
            await callback.answer(
                f"⚠️ 本月池余额 {remaining} 元，不足以批准本次 {reimb['amount']} 元",
                show_alert=True,
            )
            return

    # 周配额校验
    week_used = await count_approved_reimbursements_in_week(
        reimb["user_id"], reimb["week_key"],
    )
    reset_voucher_id = None
    if week_used >= 1:
        reset_voucher = await get_unused_reimbursement_reset(reimb["user_id"])
        if reset_voucher is None:
            await callback.answer(
                "⚠️ 该用户本周已批过 1 次；如要继续，请点 [🔄 重置该用户本周]",
                show_alert=True,
            )
            return
        reset_voucher_id = reset_voucher["id"]

    # 进入 waiting_token FSM；保留所有校验通过的上下文供后续 confirm 使用
    await state.set_state(ReimbursePayoutStates.waiting_token)
    await state.update_data(
        reimbursement_id=rid,
        user_id=reimb["user_id"],
        amount=int(reimb["amount"]),
        week_key=reimb["week_key"],
        month_key=reimb["month_key"],
        reset_voucher_id=reset_voucher_id,
    )
    text = format_payout_waiting_token_text()
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_payout_waiting_cancel_kb(rid),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_payout_waiting_cancel_kb(rid),
        )
    await callback.answer()


# ============ 支付宝口令红包发放 FSM ============

_TOKEN_MIN_LEN = 4
_TOKEN_MAX_LEN = 200


@router.message(ReimbursePayoutStates.waiting_token)
@_super_admin_required
async def step_reimburse_payout_token(
    message: types.Message, state: FSMContext,
):
    """收到超管输入的口令 → 校验 → 展示确认页。"""
    # 群组中粘贴的支付口令会被其他成员看到，必须在任何业务校验、日志、
    # FSM 写入之前拒绝；本守卫块刻意不读取消息正文以免下游路径意外回显口令。
    if message.chat.type != "private":
        try:
            await message.reply(
                "⚠️ 报销支付口令必须在私聊里发送，请在私聊里重新粘贴口令。",
            )
        except Exception as e:
            logger.warning(
                "[reimburse] payout token guard reply failed (chat_id=%s): %s",
                message.chat.id, e,
            )
        return
    token = (message.text or "").strip()
    data = await state.get_data()
    rid = data.get("reimbursement_id")
    if not token:
        await message.reply(
            "❌ 口令不能为空，请重新输入。",
            reply_markup=reimburse_payout_waiting_cancel_kb(int(rid or 0)),
        )
        return
    if len(token) < _TOKEN_MIN_LEN:
        await message.reply(
            f"❌ 口令过短（至少 {_TOKEN_MIN_LEN} 个字符），请重新输入。",
            reply_markup=reimburse_payout_waiting_cancel_kb(int(rid or 0)),
        )
        return
    if len(token) > _TOKEN_MAX_LEN:
        await message.reply(
            f"❌ 口令过长（最多 {_TOKEN_MAX_LEN} 个字符），请重新输入。",
            reply_markup=reimburse_payout_waiting_cancel_kb(int(rid or 0)),
        )
        return
    # 保存到 FSM data，进入 confirming
    await state.update_data(token=token)
    await state.set_state(ReimbursePayoutStates.confirming)

    user_id = data.get("user_id")
    amount = data.get("amount")
    reimb = await get_reimbursement(int(rid)) if rid else None
    user_label = await _user_label_for_reimb(reimb) if reimb else str(user_id)
    text = format_payout_confirm_text(
        user_id=int(user_id),
        user_label=user_label,
        amount=int(amount),
        token=token,
    )
    await message.answer(text, reply_markup=reimburse_payout_confirm_kb(int(rid)))


@router.callback_query(
    F.data.startswith("reimburse:payout:retry:"),
    ReimbursePayoutStates.confirming,
)
@_super_admin_required
async def cb_reimburse_payout_retry(
    callback: types.CallbackQuery, state: FSMContext,
):
    """超管点「🔁 重新输入」→ 清掉 token，回到 waiting_token。"""
    data = await state.get_data()
    rid = data.get("reimbursement_id")
    if rid is None:
        await callback.answer("会话已过期，请重新进入审核", show_alert=True)
        await state.clear()
        return
    # 清掉 token，但保留校验过的上下文
    await state.update_data(token=None)
    await state.set_state(ReimbursePayoutStates.waiting_token)
    text = format_payout_waiting_token_text()
    try:
        await callback.message.edit_text(
            text, reply_markup=reimburse_payout_waiting_cancel_kb(int(rid)),
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=reimburse_payout_waiting_cancel_kb(int(rid)),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("reimburse:payout:cancel:"))
@_super_admin_required
async def cb_reimburse_payout_cancel(
    callback: types.CallbackQuery, state: FSMContext,
):
    """取消 payout FSM：清状态、不改报销 status；回到报销列表入口。

    支持 waiting_token / confirming 两种状态下点击。
    """
    await state.clear()
    await callback.answer("已取消，报销保持待审核")
    # 回到入口（推下一条）
    await cb_reimburse_enter(
        callback.model_copy(update={"data": "reimburse:enter"}),
        state,
    )


@router.callback_query(
    F.data.startswith("reimburse:payout:confirm:"),
    ReimbursePayoutStates.confirming,
)
@_super_admin_required
async def cb_reimburse_payout_confirm(
    callback: types.CallbackQuery, state: FSMContext,
):
    """超管点「✅ 确认发送并完成」→ 给用户发口令 → 成功才 approve 报销 + audit log。

    关键顺序：
        1. 给用户 send_message；失败 → 不 approve，保留 FSM 让超管重试或取消
        2. 用户发送成功 → approve_reimbursement → consume reset voucher（如有）→
           mark_reimbursement_notified → write audit log（含 masked token）
        3. 成功提示 + 清 FSM + 推下一条
    """
    data = await state.get_data()
    rid = data.get("reimbursement_id")
    token = data.get("token")
    user_id = data.get("user_id")
    amount = data.get("amount")
    reset_voucher_id = data.get("reset_voucher_id")
    if not rid or not token or not user_id or amount is None:
        await callback.answer("会话已过期，请重新进入审核", show_alert=True)
        await state.clear()
        return

    # 1. 先尝试发送给用户
    ok, err = await safe_send_user_payout(
        callback.bot, user_id=int(user_id), token=str(token), amount=int(amount),
    )
    if not ok:
        # 发送失败 → 保留 FSM 让超管选择重试或取消
        await callback.answer(
            f"❌ 给用户发送口令失败：{err or '未知错误'}\n请重试或取消。",
            show_alert=True,
        )
        return

    # 2. 用户消息发送成功 → 真正 approve 报销
    approved = await approve_reimbursement(int(rid), callback.from_user.id)
    if not approved:
        # 极端：刚才用户消息发出去了，但 DB 状态已被其它进程改了；只记录 warning
        logger.warning(
            "payout: 用户消息发送成功但 approve_reimbursement 失败 rid=%s",
            rid,
        )
    # 消耗 reset voucher（如果之前判定要用）
    if reset_voucher_id is not None:
        try:
            await consume_reimbursement_reset(int(reset_voucher_id), int(rid))
        except Exception as e:
            logger.warning(
                "consume_reset 失败 reset=%s reimb=%s: %s",
                reset_voucher_id, rid, e,
            )
    # 标记 notified（用 notified_at 字段表示口令已发送）
    try:
        from bot.database import mark_reimbursement_notified
        await mark_reimbursement_notified(int(rid))
    except Exception as e:
        logger.warning("mark_reimbursement_notified 失败 rid=%s: %s", rid, e)

    # 3. 写 audit log —— 不保存完整口令，只 mask token
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_payout_sent",
        target_type="reimbursement",
        target_id=str(rid),
        detail={
            "user_id": int(user_id),
            "amount": int(amount),
            "token_masked": mask_token(str(token)),
            "reset_consumed": reset_voucher_id,
        },
    )

    # 4. 给超管展示完成提示 + 清 FSM
    reimb = await get_reimbursement(int(rid))
    user_label = await _user_label_for_reimb(reimb) if reimb else str(user_id)
    done_text = format_payout_done_text(
        user_label=user_label,
        user_id=int(user_id),
        amount=int(amount),
    )
    await state.clear()
    try:
        await callback.message.edit_text(
            done_text, reply_markup=reimburse_payout_done_kb(),
        )
    except Exception:
        await callback.message.answer(
            done_text, reply_markup=reimburse_payout_done_kb(),
        )
    await callback.answer(f"✅ 口令已发送给用户（{amount} 元）")


# ============ 驳回 ============


@router.callback_query(F.data.startswith("reimburse:reject:"))
@_super_admin_required
async def cb_reimburse_reject(callback: types.CallbackQuery, state: FSMContext):
    """[❌ 驳回] → 进 FSM 等原因"""
    try:
        rid = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    reimb = await get_reimbursement(rid)
    if not reimb:
        await callback.answer("报销不存在", show_alert=True)
        return
    if reimb["status"] != "pending":
        await callback.answer(f"已是 {reimb['status']}", show_alert=True)
        return
    await state.set_state(ReimburseRejectStates.waiting_reason)
    await state.set_data({"reimb_id": rid})
    try:
        await callback.message.edit_text(
            f"❌ 驳回报销 #{rid}\n\n"
            "请输入驳回原因（一句话）：\n"
            "例如：证据不足 / 不符合规则\n\n"
            "/cancel 退出",
            reply_markup=reimburse_reject_cancel_kb(rid),
        )
    except Exception:
        await callback.message.answer(
            f"❌ 驳回报销 #{rid}\n请输入驳回原因：",
            reply_markup=reimburse_reject_cancel_kb(rid),
        )
    await callback.answer()


@router.message(F.text == "/cancel", ReimburseRejectStates.waiting_reason)
@_super_admin_required
async def cmd_cancel_reimburse_reject(message: types.Message, state: FSMContext):
    data = await state.get_data()
    rid = data.get("reimb_id")
    await state.clear()
    if rid:
        reimb = await get_reimbursement(int(rid))
        if reimb:
            text = await _render_reimbursement_detail(reimb)
            await message.answer(
                text,
                reply_markup=reimburse_action_kb(reimb["id"], reimb["user_id"]),
            )
            return
    await message.answer("❌ 已取消。")


@router.message(ReimburseRejectStates.waiting_reason, F.text)
@_super_admin_required
async def on_reimburse_reject_reason(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        return await cmd_cancel_reimburse_reject(message, state)
    if not text:
        await message.reply("请输入有效原因，或 /cancel 退出。")
        return
    if len(text) > 200:
        await message.reply("原因过长（>200 字），请精简一下。")
        return
    data = await state.get_data()
    rid = data.get("reimb_id")
    if not rid:
        await state.clear()
        await message.reply("⚠️ 会话失效。")
        return
    reimb = await get_reimbursement(int(rid))
    if not reimb or reimb["status"] != "pending":
        await state.clear()
        await message.reply("⚠️ 报销状态已变更。")
        return

    ok = await reject_reimbursement(int(rid), message.from_user.id, text)
    if not ok:
        await state.clear()
        await message.reply("⚠️ 驳回失败。")
        return

    await log_admin_audit(
        admin_id=message.from_user.id,
        action="reimburse_reject",
        target_type="reimbursement",
        target_id=str(rid),
        detail={"user_id": reimb["user_id"], "reason": text},
    )
    # UX-4.1：驳回通知附 CTA 按钮（联系客服申诉 / 我的报销）
    await safe_notify_user_reimburse_reject(
        message.bot,
        user_id=int(reimb["user_id"]),
        reimb_id=int(rid),
        amount=int(reimb["amount"]),
        reason=text,
    )

    await state.clear()
    # UX-5.3：非空队列只发简短 ack；空队列时显示 done_next_kb 给出口
    pending = await list_pending_reimbursements(limit=1)
    if pending:
        await message.answer(f"✅ 已驳回 #{rid}")
        reimb_next = pending[0]
        text_next = await _render_reimbursement_detail(reimb_next)
        await message.answer(
            text_next,
            reply_markup=reimburse_action_kb(reimb_next["id"], reimb_next["user_id"]),
        )
    else:
        await message.answer(
            f"✅ 已驳回 #{rid}\n\n当前没有待审核的报销申请。",
            reply_markup=admin_review_done_next_kb("reimburse"),
        )


# ============ 重置周配额 ============


@router.callback_query(F.data.startswith("reimburse:reset:"))
@_super_admin_required
async def cb_reimburse_reset(callback: types.CallbackQuery, state: FSMContext):
    """二次确认：[🔄 重置某用户本周配额]"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        user_id = int(parts[2])
        rid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"🔄 重置用户 uid {user_id} 本周报销配额？\n\n"
            "重置后该用户当周可再被批准 1 次报销（消耗一次 voucher）。\n"
            "你可以多次重置，每次给一张 voucher。",
            reply_markup=reimburse_reset_confirm_kb(user_id, rid),
        )
    except Exception:
        await callback.message.answer(
            "🔄 重置确认",
            reply_markup=reimburse_reset_confirm_kb(user_id, rid),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("reimburse:reset_ok:"))
@_super_admin_required
async def cb_reimburse_reset_ok(callback: types.CallbackQuery, state: FSMContext):
    """实际发放 reset voucher"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        user_id = int(parts[2])
        rid = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    voucher_id = await grant_reimbursement_reset(user_id, callback.from_user.id)
    if not voucher_id:
        await callback.answer("⚠️ 重置失败", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_reset",
        target_type="reimbursement",
        target_id=str(rid),
        detail={"user_id": user_id, "voucher_id": voucher_id},
    )
    await callback.answer(f"✅ 已发放 voucher #{voucher_id}", show_alert=True)
    # 回到 reimb 详情
    await cb_reimburse_item(
        callback.model_copy(update={"data": f"reimburse:item:{rid}"}),
        state,
    )


# ============ 报销名单（功能关闭期间静默录入） ============

_QUEUED_PAGE_SIZE = 10


@router.callback_query(F.data.startswith("reimburse:queued:"))
@_super_admin_required
async def cb_reimburse_queued(callback: types.CallbackQuery, state: FSMContext):
    """[📋 报销名单] 列表分页

    每条显示：reimb #id / user / teacher / amount / 提交时间 + [✅ 激活] 按钮
    激活后状态 queued → pending，admin 可在 [💰 报销审核] 队列处理。
    """
    await state.clear()
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        page = max(0, int(parts[2]))
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return

    total = await count_queued_reimbursements()
    if total == 0:
        text = "📋 报销名单（功能关闭期间录入）\n\n（暂无）"
        try:
            await callback.message.edit_text(
                text,
                reply_markup=reimburse_queued_pagination_kb(0, 1),
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=reimburse_queued_pagination_kb(0, 1),
            )
        await callback.answer()
        return

    total_pages = max(1, (total + _QUEUED_PAGE_SIZE - 1) // _QUEUED_PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
    offset = page * _QUEUED_PAGE_SIZE
    rows = await list_queued_reimbursements_paged(_QUEUED_PAGE_SIZE, offset)

    lines = [
        f"📋 报销名单（功能关闭期间录入）",
        f"共 {total} 笔 · 第 {page + 1}/{total_pages} 页",
        "━━━━━━━━━━━━━━━",
    ]
    # 每条用文字展示 + 一个激活按钮在 inline_keyboard 里
    extra_buttons: list[list] = []
    from aiogram.types import InlineKeyboardButton
    for idx, r in enumerate(rows, start=offset + 1):
        teacher_name = "?"
        if r.get("teacher_id"):
            t = await get_teacher(r["teacher_id"])
            teacher_name = t["display_name"] if t else f"#{r['teacher_id']}"
        user = await get_user(r["user_id"]) if r.get("user_id") else None
        user_label = (user.get("first_name") if user else None) or f"uid {r['user_id']}"
        uname = user.get("username") if user else None
        user_disp = user_label + (f" (@{uname})" if uname else "")
        lines.append(
            f"{idx}. #{r['id']} {user_disp}"
        )
        lines.append(
            f"    👩‍🏫 {teacher_name}  💰 {r['amount']} 元  {r.get('created_at', '')}"
        )
        extra_buttons.append([
            InlineKeyboardButton(
                text=f"✅ 激活 #{r['id']}",
                callback_data=f"reimburse:activate:{r['id']}",
            ),
        ])
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(
        "激活后状态 queued → pending，进入 [💰 报销审核] 队列。"
    )
    text = "\n".join(lines)

    # 组合：每条激活按钮在前，分页 nav 在后
    base_kb = reimburse_queued_pagination_kb(page, total_pages)
    kb_rows = extra_buttons + list(base_kb.inline_keyboard)
    from aiogram.types import InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("reimburse:activate:"))
@_super_admin_required
async def cb_reimburse_activate(callback: types.CallbackQuery, state: FSMContext):
    """激活 queued → pending"""
    try:
        rid = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    reimb = await get_reimbursement(rid)
    if not reimb:
        await callback.answer("报销不存在", show_alert=True)
        return
    if reimb["status"] != "queued":
        await callback.answer(f"当前状态 {reimb['status']}，无法激活", show_alert=True)
        return
    ok = await activate_queued_reimbursement(rid)
    if not ok:
        await callback.answer("⚠️ 激活失败", show_alert=True)
        return
    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_activate",
        target_type="reimbursement",
        target_id=str(rid),
        detail={
            "user_id": reimb["user_id"],
            "amount": reimb["amount"],
        },
    )
    # UX-4.4：激活后通知用户"已进入审核队列"（POLICY §9.6 标注的缺失通知）
    await safe_notify_user_reimburse_activated(
        callback.bot,
        user_id=int(reimb["user_id"]),
        reimb_id=int(rid),
        amount=int(reimb["amount"]),
    )
    await callback.answer(f"✅ 已激活 #{rid}（status → pending）", show_alert=True)
    # 刷新名单
    await cb_reimburse_queued(
        callback.model_copy(update={"data": "reimburse:queued:0"}),
        state,
    )
