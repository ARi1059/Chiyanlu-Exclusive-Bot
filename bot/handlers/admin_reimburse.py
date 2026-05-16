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
    sum_approved_reimbursements_in_month,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    reimburse_action_kb,
    reimburse_empty_kb,
    reimburse_queued_item_kb,
    reimburse_queued_pagination_kb,
    reimburse_reject_cancel_kb,
    reimburse_reset_confirm_kb,
)
from bot.states.teacher_states import ReimburseRejectStates

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
    month_used = await sum_approved_reimbursements_in_month(reimb["month_key"])
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

    lines = [
        f"💰 报销申请 #{reimb['id']}",
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


@router.callback_query(F.data.startswith("reimburse:approve:"))
@_super_admin_required
async def cb_reimburse_approve(callback: types.CallbackQuery, state: FSMContext):
    """通过报销：先校验周配额 + 月池，失败 alert 并提示用 [🔄 重置]"""
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

    # 月池校验
    pool_raw = await get_config("reimbursement_monthly_pool")
    try:
        pool = int(pool_raw or 0)
    except (TypeError, ValueError):
        pool = 0
    if pool > 0:
        month_used = await sum_approved_reimbursements_in_month(reimb["month_key"])
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
    reset_voucher = None
    if week_used >= 1:
        # 看是否有 reset voucher
        reset_voucher = await get_unused_reimbursement_reset(reimb["user_id"])
        if reset_voucher is None:
            await callback.answer(
                "⚠️ 该用户本周已批过 1 次；如要继续，请点 [🔄 重置该用户本周]",
                show_alert=True,
            )
            return

    # 执行通过
    ok = await approve_reimbursement(rid, callback.from_user.id)
    if not ok:
        await callback.answer("⚠️ 通过失败（可能已是终态）", show_alert=True)
        return

    # 消耗 reset voucher（如果用到）
    if reset_voucher is not None:
        try:
            await consume_reimbursement_reset(reset_voucher["id"], rid)
        except Exception as e:
            logger.warning("consume_reset 失败 reset=%s reimb=%s: %s",
                           reset_voucher["id"], rid, e)

    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="reimburse_approve",
        target_type="reimbursement",
        target_id=str(rid),
        detail={
            "user_id": reimb["user_id"],
            "amount": reimb["amount"],
            "week_key": reimb["week_key"],
            "month_key": reimb["month_key"],
            "reset_consumed": (reset_voucher["id"] if reset_voucher else None),
        },
    )

    # 通知用户
    try:
        await callback.bot.send_message(
            chat_id=reimb["user_id"],
            text=(
                f"✅ 你的报销申请 #{rid} 已通过\n\n"
                f"金额：{reimb['amount']} 元\n"
                "请联系客服领取（如已设置抽奖客服链接，可一致联系方式）。"
            ),
        )
    except Exception as e:
        logger.info("通知报销用户失败 uid=%s: %s", reimb["user_id"], e)

    await callback.answer(f"✅ 已通过（{reimb['amount']} 元）")
    # 推下一条（CallbackQuery 是 pydantic v2 frozen，不能直接赋值 data）
    await cb_reimburse_enter(
        callback.model_copy(update={"data": "reimburse:enter"}),
        state,
    )


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
    try:
        await message.bot.send_message(
            chat_id=reimb["user_id"],
            text=(
                f"❌ 你的报销申请 #{rid} 未通过\n\n"
                f"金额：{reimb['amount']} 元\n"
                f"原因：{text}"
            ),
        )
    except Exception as e:
        logger.info("通知报销驳回失败 uid=%s: %s", reimb["user_id"], e)

    await state.clear()
    await message.answer(f"✅ 已驳回 #{rid}")
    # 推下一条
    pending = await list_pending_reimbursements(limit=1)
    if pending:
        reimb_next = pending[0]
        text_next = await _render_reimbursement_detail(reimb_next)
        await message.answer(
            text_next,
            reply_markup=reimburse_action_kb(reimb_next["id"], reimb_next["user_id"]),
        )
    else:
        await message.answer(
            "✅ 当前没有待审核的报销申请。", reply_markup=reimburse_empty_kb(),
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
    await callback.answer(f"✅ 已激活 #{rid}（status → pending）", show_alert=True)
    # 刷新名单
    await cb_reimburse_queued(
        callback.model_copy(update={"data": "reimburse:queued:0"}),
        state,
    )
