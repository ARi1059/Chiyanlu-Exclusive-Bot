"""管理员审核中心 handler（v2 §2.3.4 + §2.3.5）

Callbacks:
    review:enter                进入审核中心，展示第一条 pending
    review:show:<id>            展示指定 id 的请求（用于驳回-取消的回退）
    review:nav:prev:<id>        上一条
    review:nav:next:<id>        下一条
    review:approve:<id>         通过（含 photo_file_id 例外，DB 层已处理）
    review:reject:<id>          点驳回 → 询问是否填原因
    review:reject_reason:<id>   选"填写原因" → 进 FSM
    review:reject_skip:<id>     选"跳过原因" → 直接驳回（reason=None）

FSM:
    ReviewStates.waiting_reject_reason 等待管理员输入驳回原因
        state.data: {"request_id": int}
"""

import logging

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.database import (
    approve_edit_request,
    count_pending_edits,
    get_edit_request,
    get_teacher,
    list_pending_edits,
    log_admin_audit,
    reject_edit_request,
)
from bot.keyboards.admin_kb import (
    admin_review_done_next_kb,
    main_menu_kb,
    review_action_kb,
    review_empty_kb,
    review_reject_choice_kb,
)
from bot.keyboards.teacher_self_kb import FIELD_LABELS
# 老师通知文案已抽到共享 service（bot/web 同源）；此处 re-export 保持
# `from bot.handlers.admin_review import _notify_teacher_*` 与 cb_review_approve 调用不变。
from bot.services.teacher_edit_moderation import (  # noqa: F401
    _notify_teacher_approved,
    _notify_teacher_rejected,
)
from bot.states.teacher_self_states import ReviewStates
from bot.utils.permissions import admin_required

logger = logging.getLogger(__name__)

router = Router(name="admin_review")


# ========================================================
# 渲染辅助
# ========================================================

def _format_request_detail(
    req: dict, idx: int, total: int,
    *, viewers_hint: str | None = None,
) -> str:
    """构造单条待审核请求的展示文本（UX-7.4：可选附"近期查看者"提示行）。"""
    field_name = req["field_name"]
    label = FIELD_LABELS.get(field_name, field_name)
    teacher_name = req.get("teacher_display_name") or f"ID {req['teacher_id']}"

    # 图片字段不展示 file_id 原文（无意义且长）
    if field_name == "photo_file_id":
        old_repr = "已上传" if req["old_value"] else "（空）"
        new_repr = "新图（待审核生效）"
        extra = (
            "\n\n⚠️ 图片字段例外（v2 §2.3.3a）:\n"
            "  · 通过 → 切换为新图\n"
            "  · 驳回 → 保持旧图（线上从未变过）"
        )
    else:
        old_repr = req["old_value"] if req["old_value"] else "（空）"
        new_repr = req["new_value"] if req["new_value"] else "（空）"
        extra = (
            "\n\n💡 文字字段:\n"
            "  · 通过 → 保持当前展示（即新值）\n"
            "  · 驳回 → 回滚到原值"
        )

    # UX-7.4：在顶部加"近期查看者"提示（如果有）
    header = f"📝 待审核 [{idx}/{total}]\n"
    if viewers_hint:
        header += f"{viewers_hint}\n"

    return (
        f"{header}"
        f"━━━━━━━━━━━━━━━\n"
        f"老师: {teacher_name} (ID: {req['teacher_id']})\n"
        f"字段: {label}\n"
        f"原值: {old_repr}\n"
        f"新值: {new_repr}\n"
        f"提交: {req['created_at']}\n"
        f"━━━━━━━━━━━━━━━{extra}"
    )


async def _show_request_at_index(
    callback: types.CallbackQuery,
    pending: list[dict],
    index: int,
):
    """在管理员后台编辑当前消息，展示 pending[index]

    pending 已按 created_at DESC 排序（最新在前）。
    UX-7.4：渲染前查近期查看者 + 写入 review_view audit（真实 admin_id）。
    """
    if not pending or index < 0 or index >= len(pending):
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        return

    req = pending[index]
    admin_id = callback.from_user.id

    # UX-7.1：尝试 claim 锁；冲突时渲染冲突页而非详情
    try:
        from bot.utils.review_claim import try_claim
        ok, existing = try_claim("edit_request", req["id"], admin_id)
        if not ok and existing is not None:
            await _render_claim_conflict(
                callback, kind="edit_request",
                target_id=req["id"], existing=existing,
            )
            return
    except Exception as e:
        logger.warning("[UX-7.1] try_claim 失败（放行）req=%s: %s", req["id"], e)

    # UX-7.4：查近 5 分钟内其他管理员对该请求的 view 记录（排除自己）
    viewers_hint: str | None = None
    try:
        from bot.database import list_recent_target_viewers
        from bot.utils.review_viewers_hint import format_recent_viewers_hint
        viewers = await list_recent_target_viewers(
            target_type="edit_request",
            target_id=req["id"],
            action="review_view",
            exclude_admin_id=admin_id,
        )
        viewers_hint = format_recent_viewers_hint(viewers)
    except Exception as e:
        logger.warning("[UX-7.4] viewer hint 查询失败 req=%s: %s", req["id"], e)

    # UX-7.4：写入查看 audit（用真实 admin_id，便于其它管理员的并发提示）
    try:
        await log_admin_audit(
            admin_id=admin_id,
            action="review_view",
            target_type="edit_request",
            target_id=req["id"],
            detail={"idx": index, "total": len(pending)},
        )
    except Exception:
        pass

    text = _format_request_detail(
        req, index + 1, len(pending), viewers_hint=viewers_hint,
    )
    kb = review_action_kb(
        req["id"],
        has_prev=index > 0,
        has_next=index < len(pending) - 1,
    )
    await callback.message.edit_text(text, reply_markup=kb)


async def _find_index_of_request(
    pending: list[dict],
    request_id: int,
) -> int:
    """在 pending 列表里找 request_id 的索引，找不到返回 0"""
    for i, r in enumerate(pending):
        if r["id"] == request_id:
            return i
    return 0


async def _render_claim_conflict(
    callback: types.CallbackQuery, *, kind: str, target_id: int, existing,
) -> None:
    """UX-7.1：渲染"审核冲突"页（另一管理员持有锁）。

    `existing` 是 bot.utils.review_claim.ClaimInfo dataclass；本函数仅渲染，
    不修改锁状态——access 决策（强制接管 / 放弃）由用户在按钮上做出。
    """
    import time
    from bot.utils.review_viewers_hint import _relative_zh
    from bot.keyboards.admin_kb import review_claim_conflict_kb

    elapsed = max(0, int(time.time() - float(existing.acquired_at)))
    rel = _relative_zh(elapsed)
    text = (
        "⚠️ 审核冲突\n"
        "━━━━━━━━━━━━━━━\n"
        f"管理员 #{existing.admin_id} {rel} 进入了此条审核\n"
        "（锁将在 5 分钟无操作后自动释放）\n"
        "━━━━━━━━━━━━━━━\n\n"
        "如需协同处理，请先与对方沟通；\n"
        "或点击下方按钮强制接管（会写入审计日志）。"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=review_claim_conflict_kb(kind, target_id),
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=review_claim_conflict_kb(kind, target_id),
        )
    await callback.answer()


# 注：老师通知 _notify_teacher_approved / _notify_teacher_rejected 已抽到
# bot/services/teacher_edit_moderation.py（bot/web 同源），本文件顶部 re-export。


# ========================================================
# 进入审核中心 / 导航
# ========================================================

@router.callback_query(F.data == "review:enter")
@admin_required
async def cb_review_enter(callback: types.CallbackQuery, state: FSMContext):
    """从主菜单点击 [📝 待审核] 进入审核中心"""
    await state.clear()
    pending = await list_pending_edits()
    if not pending:
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        await callback.answer()
        return
    await _show_request_at_index(callback, pending, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("review:show:"))
@admin_required
async def cb_review_show(callback: types.CallbackQuery, state: FSMContext):
    """展示指定 id 的请求（驳回-取消的回退路径）"""
    await state.clear()
    try:
        request_id = int(callback.data[len("review:show:"):])
    except ValueError:
        await callback.answer("⚠️ 无效请求", show_alert=False)
        return

    pending = await list_pending_edits()
    if not pending:
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        await callback.answer()
        return

    idx = await _find_index_of_request(pending, request_id)
    await _show_request_at_index(callback, pending, idx)
    await callback.answer()


@router.callback_query(F.data.startswith("review:nav:"))
@admin_required
async def cb_review_nav(callback: types.CallbackQuery):
    """上一条 / 下一条"""
    # callback.data 格式：review:nav:prev:<id> 或 review:nav:next:<id>
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("⚠️ 无效操作")
        return
    direction = parts[2]
    try:
        current_id = int(parts[3])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    pending = await list_pending_edits()
    if not pending:
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        await callback.answer()
        return

    current_idx = await _find_index_of_request(pending, current_id)
    if direction == "prev":
        target_idx = max(0, current_idx - 1)
    elif direction == "next":
        target_idx = min(len(pending) - 1, current_idx + 1)
    else:
        target_idx = current_idx
    await _show_request_at_index(callback, pending, target_idx)
    await callback.answer()


# ========================================================
# 强制接管（UX-7.1）
# ========================================================

@router.callback_query(F.data.startswith("review:force_claim:"))
@admin_required
async def cb_review_force_claim(callback: types.CallbackQuery):
    """强制接管老师资料审核锁（UX-7.1）。

    流程：
        1. 取 request_id
        2. 读取现有锁（用于 audit detail）
        3. force_claim 覆盖锁
        4. 写 audit "review_force_claim"（含 previous_holder）
        5. 重新进入 _show_request_at_index 渲染详情
    """
    try:
        request_id = int(callback.data[len("review:force_claim:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作", show_alert=True)
        return
    admin_id = callback.from_user.id
    try:
        from bot.utils.review_claim import force_claim, get_claim
        existing = get_claim("edit_request", request_id)
        force_claim("edit_request", request_id, admin_id)
        prev_holder = existing.admin_id if existing else None
    except Exception as e:
        logger.warning("[UX-7.1] force_claim 异常 req=%s: %s", request_id, e)
        prev_holder = None
    try:
        await log_admin_audit(
            admin_id=admin_id,
            action="review_force_claim",
            target_type="edit_request",
            target_id=request_id,
            detail={"previous_holder": prev_holder},
        )
    except Exception:
        pass
    # 重新进入详情：找到该条在 pending 中的位置
    pending = await list_pending_edits()
    if not pending:
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        await callback.answer("已接管，但队列已空")
        return
    idx = await _find_index_of_request(pending, request_id)
    await _show_request_at_index(callback, pending, idx)
    await callback.answer("✅ 已强制接管")


# ========================================================
# 通过 / 驳回
# ========================================================

@router.callback_query(F.data.startswith("review:approve:"))
@admin_required
async def cb_review_approve(callback: types.CallbackQuery):
    """通过修改请求（含 photo_file_id 例外，DB 层已处理）"""
    try:
        request_id = int(callback.data[len("review:approve:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    ok = await approve_edit_request(request_id, callback.from_user.id)
    if not ok:
        await callback.answer(
            "⚠️ 该请求已处理或不存在",
            show_alert=True,
        )
    else:
        approved = await get_edit_request(request_id)
        await log_admin_audit(
            admin_id=callback.from_user.id,
            action="review_approve",
            target_type="edit_request",
            target_id=request_id,
            detail={
                "teacher_id": approved["teacher_id"] if approved else None,
                "field": approved["field_name"] if approved else None,
            },
        )
        # UX-7.1：处理完成后释放 claim 锁，避免占用 5 分钟超时
        try:
            from bot.utils.review_claim import release_claim
            release_claim("edit_request", request_id, callback.from_user.id)
        except Exception:
            pass
        # UX-5.2：通过审核后通知老师（与既有 _notify_teacher_rejected 对称）
        if approved:
            await _notify_teacher_approved(
                callback.bot,
                int(approved["teacher_id"]),
                str(approved["field_name"]),
                approved.get("new_value"),
            )
        await callback.answer("✅ 已通过")

    # 刷新列表，跳到下一条（保持索引同一位置，因为当前条已离开 pending 队列）
    pending = await list_pending_edits()
    if not pending:
        # UX-5.3：清完队列时显示 done_next_kb 给明确出口（切换审核类型 / 处理下一条）
        await callback.message.edit_text(
            "✅ 全部已处理完毕\n\n当前没有待审核的修改。",
            reply_markup=admin_review_done_next_kb("edit"),
        )
        return
    await _show_request_at_index(callback, pending, 0)


@router.callback_query(F.data.startswith("review:reject:"))
@admin_required
async def cb_review_reject(callback: types.CallbackQuery):
    """点击「驳回」→ 询问是否填写原因"""
    try:
        request_id = int(callback.data[len("review:reject:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    req = await get_edit_request(request_id)
    if not req or req["status"] != "pending":
        await callback.answer("⚠️ 该请求已处理或不存在", show_alert=True)
        return

    label = FIELD_LABELS.get(req["field_name"], req["field_name"])
    teacher = await get_teacher(req["teacher_id"])
    teacher_name = teacher["display_name"] if teacher else f"ID {req['teacher_id']}"

    await callback.message.edit_text(
        f"❌ 驳回 - {teacher_name} 的{label}修改\n\n"
        "是否填写驳回原因?\n"
        "（原因会通过私聊推送给老师；不填则给老师提示「未填写」）",
        reply_markup=review_reject_choice_kb(request_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review:reject_skip:"))
@admin_required
async def cb_review_reject_skip(callback: types.CallbackQuery):
    """选择「跳过原因」→ 直接驳回 reason=None"""
    try:
        request_id = int(callback.data[len("review:reject_skip:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return
    await _perform_reject(callback, request_id, reason=None)


@router.callback_query(F.data.startswith("review:reject_reason:"))
@admin_required
async def cb_review_reject_reason(callback: types.CallbackQuery, state: FSMContext):
    """选择「填写原因」→ 进入 FSM 等待管理员输入"""
    try:
        request_id = int(callback.data[len("review:reject_reason:"):])
    except ValueError:
        await callback.answer("⚠️ 无效操作")
        return

    await state.set_state(ReviewStates.waiting_reject_reason)
    await state.set_data({"request_id": request_id})
    await callback.message.edit_text(
        "📝 请输入驳回原因（一段文字）：\n\n"
        "原因会通过私聊推送给老师。\n"
        "发送 /cancel 取消（回到该请求的查看页）。",
    )
    await callback.answer()


@router.message(ReviewStates.waiting_reject_reason, Command("cancel"))
@admin_required
async def cmd_cancel_reject(message: types.Message, state: FSMContext):
    """驳回原因 FSM 状态下 /cancel 退出"""
    data = await state.get_data()
    request_id = data.get("request_id")
    await state.clear()
    await message.answer(
        "已取消填写原因。请回到主菜单或重新点击驳回。",
    )
    if request_id:
        # 给个返回主菜单的 keyboard，方便用户继续
        await message.answer(
            "🔧 痴颜录管理面板",
            reply_markup=await _build_user_aware_menu(message.from_user.id),
        )


@router.message(ReviewStates.waiting_reject_reason, F.text)
@admin_required
async def on_reject_reason(message: types.Message, state: FSMContext):
    """接收管理员输入的驳回原因 → 执行 reject"""
    data = await state.get_data()
    request_id: int | None = data.get("request_id")
    if request_id is None:
        await state.clear()
        await message.reply("⚠️ 状态异常，请重新进入审核")
        return

    reason = message.text.strip()
    if not reason:
        await message.reply("原因不能为空，请重新输入，或 /cancel 取消")
        return

    await state.clear()
    await _perform_reject_from_message(message, request_id, reason)


# ========================================================
# 实际执行驳回 + 通知 + 刷新
# ========================================================

async def _perform_reject(
    callback: types.CallbackQuery,
    request_id: int,
    reason: str | None,
):
    """实际执行驳回，从 callback 触发"""
    req = await get_edit_request(request_id)
    if not req or req["status"] != "pending":
        await callback.answer("⚠️ 该请求已处理", show_alert=True)
        # 跳到列表
        pending = await list_pending_edits()
        if pending:
            await _show_request_at_index(callback, pending, 0)
        else:
            await callback.message.edit_text(
                "✅ 没有待审核的修改",
                reply_markup=review_empty_kb(),
            )
        return

    ok = await reject_edit_request(request_id, callback.from_user.id, reason)
    if not ok:
        await callback.answer("⚠️ 驳回失败", show_alert=True)
        return

    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="review_reject",
        target_type="edit_request",
        target_id=request_id,
        detail={
            "teacher_id": req["teacher_id"],
            "field": req["field_name"],
            "reason": reason,
        },
    )

    # 通知老师
    await _notify_teacher_rejected(
        callback.bot,
        req["teacher_id"],
        req["field_name"],
        req["new_value"],
        reason,
    )

    await callback.answer("❌ 已驳回")

    # 刷新列表
    pending = await list_pending_edits()
    if not pending:
        await callback.message.edit_text(
            "✅ 没有待审核的修改",
            reply_markup=review_empty_kb(),
        )
        return
    await _show_request_at_index(callback, pending, 0)


async def _perform_reject_from_message(
    message: types.Message,
    request_id: int,
    reason: str | None,
):
    """实际执行驳回，从 FSM 文字消息触发（管理员输入了原因）"""
    req = await get_edit_request(request_id)
    if not req or req["status"] != "pending":
        await message.answer("⚠️ 该请求已处理，跳过")
    else:
        ok = await reject_edit_request(request_id, message.from_user.id, reason)
        if ok:
            await log_admin_audit(
                admin_id=message.from_user.id,
                action="review_reject",
                target_type="edit_request",
                target_id=request_id,
                detail={
                    "teacher_id": req["teacher_id"],
                    "field": req["field_name"],
                    "reason": reason,
                },
            )
            # UX-7.1：处理完成后释放 claim 锁
            try:
                from bot.utils.review_claim import release_claim
                release_claim("edit_request", request_id, message.from_user.id)
            except Exception:
                pass
            await _notify_teacher_rejected(
                message.bot,
                req["teacher_id"],
                req["field_name"],
                req["new_value"],
                reason,
            )
            await message.answer(
                f"❌ 已驳回（原因已推送给老师）\n请求 ID: {request_id}",
                reply_markup=admin_review_done_next_kb("edit"),
            )
        else:
            await message.answer("⚠️ 驳回操作失败")

    # 返回管理面板（带最新角标）
    await message.answer(
        "🔧 痴颜录管理面板",
        reply_markup=await _build_user_aware_menu(message.from_user.id),
    )


async def _count_pending() -> int:
    """内部辅助：取待审核数，用于刷新主菜单角标"""
    return await count_pending_edits()


async def _build_user_aware_menu(user_id: int):
    """根据 user_id 是否超管返回带 [📝 报告审核] 的主菜单（Phase 9.4）"""
    from bot.database import is_super_admin, count_pending_reviews
    from bot.config import config as _cfg
    n = await count_pending_edits()
    rcount = 0
    is_super = False
    if user_id == _cfg.super_admin_id or await is_super_admin(user_id):
        is_super = True
        rcount = await count_pending_reviews()
    return main_menu_kb(
        pending_count=n,
        pending_review_count=rcount,
        is_super=is_super,
    )
