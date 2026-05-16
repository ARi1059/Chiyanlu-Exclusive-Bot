"""报告审核中心（Phase 9.4 — 超管对用户评价的审核）

callback 命名空间：rreview:*（区分老 admin_review.py 的 review:* 和 9.3
review_submit.py 的 review:* / review:start:*）。

入口：主菜单 [📝 报告审核] → rreview:enter → 展示第 0 条 pending。
本文件 Commit 9.4.1 范围：
  - 入口 + 展示详情（送媒体组 + 文字 + 操作按钮）
  - 通过 happy path（不含驳回 / 翻页 / 重看 / 私聊通知 / 推送超管）

Commit 9.4.2/9.4.3 在本文件追加：翻页 / 重看 / 驳回 / 通知。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InputMediaPhoto

from bot.config import config
from bot.database import (
    approve_teacher_review,
    count_pending_reviews,
    get_teacher,
    get_teacher_review,
    is_super_admin,
    list_pending_reviews,
    log_admin_audit,
    reject_teacher_review,
    REVIEW_RATINGS,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    rreview_action_kb,
    rreview_empty_kb,
    rreview_reject_choice_kb,
)
from bot.states.teacher_states import RReviewRejectStates
from bot.utils.rreview_notify import (
    notify_review_approved,
    notify_review_rejected,
)


# 4 条驳回预设原因（与 rreview_reject_choice_kb 顺序一致）
REJECT_PRESETS: list[str] = [
    "证据不充分",
    "内容违规",
    "重复提交",
    "评分明显不合理",
]

logger = logging.getLogger(__name__)

router = Router(name="rreview_admin")


# ============ 权限装饰器（仅超管）============

def _super_admin_required(func):
    """仅 super_admin 可访问；普通 admin / 用户 alert 拒绝"""
    async def wrapper(event, *args, **kwargs):
        if isinstance(event, types.CallbackQuery):
            uid = event.from_user.id
            denied_send = lambda: event.answer("此操作需超级管理员权限", show_alert=True)
        elif isinstance(event, types.Message):
            uid = event.from_user.id
            denied_send = lambda: event.reply("此操作需超级管理员权限")
        else:
            return
        if uid != config.super_admin_id and not await is_super_admin(uid):
            await denied_send()
            return
        return await func(event, *args, **kwargs)
    return wrapper


# ============ 入口 ============

@router.callback_query(F.data == "rreview:enter")
@_super_admin_required
async def cb_rreview_enter(callback: types.CallbackQuery, state: FSMContext):
    """[📝 报告审核] 入口：展示第 0 条 pending"""
    await state.clear()
    pending = await list_pending_reviews(limit=50)
    if not pending:
        await _show_empty(callback)
        return
    await _show_review_at_index(callback, state, pending, 0)


@router.callback_query(F.data.startswith("rreview:show:"))
@_super_admin_required
async def cb_rreview_show(callback: types.CallbackQuery, state: FSMContext):
    """rreview:show:<id> 用于驳回-取消时的回退展示"""
    try:
        review_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    pending = await list_pending_reviews(limit=50)
    idx = next((i for i, r in enumerate(pending) if r["id"] == review_id), -1)
    if idx == -1:
        await _show_empty(callback)
        return
    await _show_review_at_index(callback, state, pending, idx)


# ============ 通过 ============

@router.callback_query(F.data.startswith("rreview:approve:"))
@_super_admin_required
async def cb_rreview_approve(callback: types.CallbackQuery, state: FSMContext):
    """[✅ 通过]：DB UPDATE + audit + 提示 + 返回下一条 / 空列表"""
    try:
        review_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return

    review = await get_teacher_review(review_id)
    if not review:
        await callback.answer("该评价不存在", show_alert=True)
        return
    if review["status"] != "pending":
        await callback.answer(f"该评价已是 {review['status']}", show_alert=True)
        return

    ok = await approve_teacher_review(review_id, callback.from_user.id)
    if not ok:
        await callback.answer("⚠️ 通过失败", show_alert=True)
        return

    await log_admin_audit(
        admin_id=callback.from_user.id,
        action="rreview_approve",
        target_type="teacher_review",
        target_id=str(review_id),
        detail={"teacher_id": review["teacher_id"], "user_id": review["user_id"]},
    )

    # Phase 9.5：通过审核时一次性触发（任一步失败仅 warning，不阻塞通知）
    teacher_id = review["teacher_id"]
    # 1. 重算聚合统计
    try:
        from bot.database import recalculate_teacher_review_stats
        await recalculate_teacher_review_stats(teacher_id)
    except Exception as e:
        logger.warning("recalculate_teacher_review_stats 失败 teacher=%s: %s", teacher_id, e)
    # 2. 同步频道档案帖 caption（force=True 绕过 60s debounce）
    try:
        from bot.utils.teacher_channel_publish import update_teacher_post_caption
        await update_teacher_post_caption(callback.bot, teacher_id, force=True)
    except Exception as e:
        logger.warning("update_teacher_post_caption 失败 teacher=%s: %s", teacher_id, e)
    # 3. 在讨论群发评论（reply 到锚消息；锚丢失时 fallback + 告警超管）
    try:
        from bot.utils.review_comment import publish_review_comment, CommentError
        await publish_review_comment(callback.bot, review_id)
    except CommentError as e:
        logger.warning(
            "publish_review_comment failed review=%s reason=%s: %s",
            review_id, getattr(e, "reason", "?"), e,
        )
    except Exception as e:
        logger.warning("publish_review_comment 异常 review=%s: %s", review_id, e)

    # 私聊通知评价者（容错，不阻塞）
    teacher = await get_teacher(review["teacher_id"])
    teacher_name = teacher["display_name"] if teacher else None
    try:
        await notify_review_approved(
            callback.bot, review_id, teacher_name=teacher_name,
        )
    except Exception as e:
        logger.warning("notify_review_approved 失败 review=%s: %s", review_id, e)

    # 删除当前审核的 2 条消息 + 推下一条 / 空列表
    await _cleanup_messages(callback.bot, callback.message.chat.id, state)
    await callback.answer(f"✅ 已通过评价 #{review_id}")

    # 推下一条 pending（如果有）
    pending = await list_pending_reviews(limit=50)
    if not pending:
        # 队列空 → 回主面板
        rcount = 0
        try:
            await callback.bot.send_message(
                chat_id=callback.message.chat.id,
                text="🔧 痴颜录管理面板（队列已清空）",
                reply_markup=main_menu_kb(
                    pending_count=0,
                    pending_review_count=rcount,
                    is_super=True,
                ),
            )
        except Exception as e:
            logger.warning("发送空队列回主面板失败: %s", e)
        return
    await _send_review_at_index(callback.bot, callback.message.chat.id, state, pending, 0)


# ============ 内部辅助 ============

async def _show_empty(callback: types.CallbackQuery):
    text = "✅ 当前没有待审核的报告。"
    try:
        await callback.message.edit_text(text, reply_markup=rreview_empty_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=rreview_empty_kb())
    await callback.answer()


async def _show_review_at_index(
    callback: types.CallbackQuery,
    state: FSMContext,
    pending: list[dict],
    idx: int,
):
    """从某条 callback（如点击 rreview:enter）渲染索引为 idx 的 pending review"""
    if idx < 0 or idx >= len(pending):
        await _show_empty(callback)
        return
    chat_id = callback.message.chat.id
    # 清理触发本次的消息（菜单按钮所在消息）+ 之前发的审核消息
    await _cleanup_messages(callback.bot, chat_id, state)
    try:
        await callback.bot.delete_message(chat_id=chat_id, message_id=callback.message.message_id)
    except Exception:
        pass
    await _send_review_at_index(callback.bot, chat_id, state, pending, idx)
    await callback.answer()


async def _send_review_at_index(
    bot,
    chat_id: int,
    state: FSMContext,
    pending: list[dict],
    idx: int,
):
    """发送媒体组 + 文字消息 + 操作按钮，并把 msg_ids 暂存 state 供下次清理"""
    if idx < 0 or idx >= len(pending):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="✅ 当前没有待审核的报告。",
                reply_markup=rreview_empty_kb(),
            )
        except Exception:
            pass
        return

    review = pending[idx]
    teacher = await get_teacher(review["teacher_id"])
    total = len(pending)

    # 媒体组：2 张证据图
    media = [
        InputMediaPhoto(
            media=review["booking_screenshot_file_id"],
            caption="📸 约课记录",
        ),
        InputMediaPhoto(
            media=review["gesture_photo_file_id"],
            caption="✋ 现场手势",
        ),
    ]
    mg_msg_ids: list[int] = []
    try:
        sent = await bot.send_media_group(chat_id=chat_id, media=media)
        mg_msg_ids = [m.message_id for m in sent]
    except Exception as e:
        logger.warning("发送媒体组失败 review=%s: %s", review["id"], e)
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ 证据图发送失败：{e}\n请联系开发者排查。",
        )
        return

    # 文字 + 操作按钮
    text = _render_review_text(review, teacher, idx, total)
    text_msg_id: Optional[int] = None
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=rreview_action_kb(
                review_id=review["id"],
                has_prev=(idx > 0),
                has_next=(idx + 1 < total),
            ),
        )
        text_msg_id = msg.message_id
    except Exception as e:
        logger.warning("发送审核文字消息失败 review=%s: %s", review["id"], e)
        return

    await state.update_data(
        rreview_media_msg_ids=mg_msg_ids,
        rreview_text_msg_id=text_msg_id,
        rreview_current_id=review["id"],
        rreview_current_idx=idx,
    )

    # 记录"查看"行为（首次进入此条）
    try:
        await log_admin_audit(
            admin_id=0,  # placeholder：本辅助没有 admin_id；具体由 cb_rreview_enter 已记录
            action="rreview_view",
            target_type="teacher_review",
            target_id=str(review["id"]),
            detail={"idx": idx, "total": total},
        )
    except Exception:
        pass


async def _cleanup_messages(bot, chat_id: int, state: FSMContext):
    """删除上一次展示的媒体组 + 文字消息（best-effort）"""
    data = await state.get_data()
    mg_ids = data.get("rreview_media_msg_ids") or []
    text_mid = data.get("rreview_text_msg_id")
    for mid in list(mg_ids):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception as e:
            logger.debug("cleanup 删旧媒体消息失败 mid=%s: %s", mid, e)
    if text_mid:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=text_mid)
        except Exception as e:
            logger.debug("cleanup 删旧文字消息失败 mid=%s: %s", text_mid, e)
    await state.update_data(
        rreview_media_msg_ids=[],
        rreview_text_msg_id=None,
    )


def _anonymize_user_id(uid: int) -> str:
    """半匿名展示：****6204 类似格式"""
    s = str(uid)
    if len(s) <= 4:
        return "****"
    return "*" * (len(s) - 4) + s[-4:]


def _render_review_text(review: dict, teacher: Optional[dict], idx: int, total: int) -> str:
    """按 spec §4.2 渲染审核详情文字"""
    teacher_name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"
    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}.get(
        review.get("rating"), {"emoji": "❓", "label": review.get("rating", "?")},
    )
    rating_str = f"{rating_meta['emoji']} {rating_meta['label']}"
    summary = review.get("summary") or "（未填写）"
    lines = [
        f"[报告审核 {idx + 1}/{total}]",
        f"老师：{teacher_name}",
        f"评价者：{_anonymize_user_id(review['user_id'])} (uid: {_anonymize_user_id(review['user_id'])})",
        f"提交：{review.get('created_at', '?')}",
        "",
        "📸 审核材料：已在上方 2 张图",
        "────────────────────",
        f"评级：{rating_str} · 🎯 综合 {review.get('overall_score', '?')}",
        f"🎨 人照 {review.get('score_humanphoto', '?')} | "
        f"颜值 {review.get('score_appearance', '?')} | "
        f"身材 {review.get('score_body', '?')}",
        f"   服务 {review.get('score_service', '?')} | "
        f"态度 {review.get('score_attitude', '?')} | "
        f"环境 {review.get('score_environment', '?')}",
        f"📝 过程：{summary}",
        "────────────────────",
    ]
    return "\n".join(lines)


# ============ 翻页 ============

@router.callback_query(F.data.startswith("rreview:nav:"))
@_super_admin_required
async def cb_rreview_nav(callback: types.CallbackQuery, state: FSMContext):
    """上一条 / 下一条：rreview:nav:prev:<id> / rreview:nav:next:<id>"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    direction = parts[2]
    try:
        cur_id = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    pending = await list_pending_reviews(limit=50)
    cur_idx = next((i for i, r in enumerate(pending) if r["id"] == cur_id), -1)
    if cur_idx == -1:
        # 当前 review 已被其他超管处理掉了 → 退回展示当前队列第 0 条
        if not pending:
            await _show_empty(callback)
            return
        await _show_review_at_index(callback, state, pending, 0)
        return
    new_idx = cur_idx - 1 if direction == "prev" else cur_idx + 1
    if new_idx < 0 or new_idx >= len(pending):
        await callback.answer("已到边界", show_alert=True)
        return
    await _show_review_at_index(callback, state, pending, new_idx)


# ============ 重看截图 / 手势照片 ============

@router.callback_query(F.data.startswith("rreview:photo:"))
@_super_admin_required
async def cb_rreview_photo(callback: types.CallbackQuery):
    """[🖼 重看约课截图] / [✋ 重看手势照片]：单独 send_photo 不破坏当前视图"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    kind = parts[2]
    try:
        review_id = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    review = await get_teacher_review(review_id)
    if not review:
        await callback.answer("评价不存在", show_alert=True)
        return
    if kind == "booking":
        fid = review["booking_screenshot_file_id"]
        caption = "📸 约课记录"
    elif kind == "gesture":
        fid = review["gesture_photo_file_id"]
        caption = "✋ 现场手势"
    else:
        await callback.answer("未知类型", show_alert=True)
        return
    try:
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id, photo=fid, caption=caption,
        )
    except Exception as e:
        logger.warning("rreview:photo send_photo 失败 review=%s kind=%s: %s",
                       review_id, kind, e)
        await callback.answer(f"⚠️ 重看失败：{e}", show_alert=True)
        return
    await callback.answer()


# ============ 驳回流程 ============

@router.callback_query(F.data.startswith("rreview:reject:"))
@_super_admin_required
async def cb_rreview_reject_ask(callback: types.CallbackQuery, state: FSMContext):
    """[❌ 驳回] → 显示 4 预设 / 自定义 / 跳过 / 取消"""
    try:
        review_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    review = await get_teacher_review(review_id)
    if not review:
        await callback.answer("评价不存在", show_alert=True)
        return
    if review["status"] != "pending":
        await callback.answer(f"该评价已是 {review['status']}", show_alert=True)
        return
    teacher = await get_teacher(review["teacher_id"])
    name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"
    text = (
        f"❌ 驳回评价 #{review_id} - {name}\n\n"
        "请选择驳回原因：\n"
        "- 4 个预设原因（点击即驳回）\n"
        "- 📝 自定义原因（手输一段文字）\n"
        '- ⏭ 跳过原因（私聊提示评价者 "未填写"）'
    )
    try:
        await callback.message.edit_text(text, reply_markup=rreview_reject_choice_kb(review_id))
    except Exception:
        await callback.message.answer(text, reply_markup=rreview_reject_choice_kb(review_id))
    await callback.answer()


@router.callback_query(F.data.startswith("rreview:reject_preset:"))
@_super_admin_required
async def cb_rreview_reject_preset(callback: types.CallbackQuery, state: FSMContext):
    """选某条预设原因 → 直接驳回"""
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("参数错误", show_alert=True)
        return
    try:
        review_id = int(parts[2])
        preset_idx = int(parts[3])
    except ValueError:
        await callback.answer("参数错误", show_alert=True)
        return
    if not (0 <= preset_idx < len(REJECT_PRESETS)):
        await callback.answer("未知预设原因", show_alert=True)
        return
    reason = REJECT_PRESETS[preset_idx]
    await _perform_reject(callback, state, review_id, reason)


@router.callback_query(F.data.startswith("rreview:reject_skip:"))
@_super_admin_required
async def cb_rreview_reject_skip(callback: types.CallbackQuery, state: FSMContext):
    """[⏭ 跳过原因] → reason=None 驳回"""
    try:
        review_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    await _perform_reject(callback, state, review_id, None)


@router.callback_query(F.data.startswith("rreview:reject_custom:"))
@_super_admin_required
async def cb_rreview_reject_custom(callback: types.CallbackQuery, state: FSMContext):
    """[📝 自定义原因] → 进 FSM 等输入"""
    try:
        review_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("参数错误", show_alert=True)
        return
    await state.set_state(RReviewRejectStates.waiting_custom_reason)
    await state.update_data(reject_review_id=review_id)
    await callback.message.edit_text(
        "📝 请回复驳回原因（一段文字）。\n\n"
        "/cancel 取消（回到该报告的查看页）。",
    )
    await callback.answer()


@router.message(F.text == "/cancel", RReviewRejectStates.waiting_custom_reason)
@_super_admin_required
async def cmd_cancel_custom_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    review_id = data.get("reject_review_id")
    await state.clear()
    if not review_id:
        await message.answer("已取消。")
        return
    # 回到该 review 的展示页（通过 list 拿索引）
    pending = await list_pending_reviews(limit=50)
    idx = next((i for i, r in enumerate(pending) if r["id"] == review_id), -1)
    if idx == -1:
        await message.answer("✅ 当前没有待审核的报告。", reply_markup=rreview_empty_kb())
        return
    await _cleanup_messages(message.bot, message.chat.id, state)
    await _send_review_at_index(message.bot, message.chat.id, state, pending, idx)


@router.message(RReviewRejectStates.waiting_custom_reason, F.text)
@_super_admin_required
async def on_custom_reason(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.reply("❌ 请回复非空原因，或 /cancel 取消。")
        return
    if len(text) > 200:
        await message.reply("❌ 原因过长（≤ 200 字），请精简。")
        return
    data = await state.get_data()
    review_id = data.get("reject_review_id")
    if not review_id:
        await state.clear()
        await message.reply("⚠️ 状态丢失，请重新进入审核。")
        return
    # _perform_reject 不能用 callback；构造一个简单封装
    await _do_reject(
        bot=message.bot,
        chat_id=message.chat.id,
        reviewer_id=message.from_user.id,
        review_id=int(review_id),
        reason=text,
        state=state,
        ack_text=f"✅ 已驳回评价 #{review_id}（原因已私聊评价者）",
    )


async def _perform_reject(
    callback: types.CallbackQuery,
    state: FSMContext,
    review_id: int,
    reason: Optional[str],
):
    """callback 驱动的驳回入口（预设 / 跳过）"""
    await _do_reject(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        reviewer_id=callback.from_user.id,
        review_id=review_id,
        reason=reason,
        state=state,
        ack_text=(
            f"✅ 已驳回评价 #{review_id}"
            + (f"（原因：{reason}）" if reason else "（未填写原因）")
        ),
        trigger_message=callback.message,
    )
    await callback.answer()


async def _do_reject(
    *,
    bot,
    chat_id: int,
    reviewer_id: int,
    review_id: int,
    reason: Optional[str],
    state: FSMContext,
    ack_text: str,
    trigger_message: Optional[types.Message] = None,
):
    """实际驳回执行 + 通知 + 推下一条"""
    review = await get_teacher_review(review_id)
    if not review:
        if trigger_message:
            try:
                await trigger_message.edit_text("⚠️ 该评价不存在或已被处理")
            except Exception:
                pass
        return
    if review["status"] != "pending":
        if trigger_message:
            try:
                await trigger_message.edit_text(f"⚠️ 该评价已是 {review['status']}")
            except Exception:
                pass
        return

    ok = await reject_teacher_review(review_id, reviewer_id=reviewer_id, reason=reason)
    if not ok:
        return

    await log_admin_audit(
        admin_id=reviewer_id,
        action="rreview_reject",
        target_type="teacher_review",
        target_id=str(review_id),
        detail={
            "teacher_id": review["teacher_id"],
            "user_id": review["user_id"],
            "reason": reason or "",
        },
    )

    teacher = await get_teacher(review["teacher_id"])
    teacher_name = teacher["display_name"] if teacher else None
    try:
        await notify_review_rejected(
            bot, review_id, teacher_name=teacher_name, reason=reason,
        )
    except Exception as e:
        logger.warning("notify_review_rejected 失败 review=%s: %s", review_id, e)

    # 清旧消息 + 推下一条 / 队列空
    await _cleanup_messages(bot, chat_id, state)
    pending = await list_pending_reviews(limit=50)
    if not pending:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"{ack_text}\n\n✅ 当前已无待审核的报告。",
                reply_markup=main_menu_kb(
                    pending_count=0,
                    pending_review_count=0,
                    is_super=True,
                ),
            )
        except Exception as e:
            logger.warning("driver_reject empty msg 失败: %s", e)
        return
    try:
        await bot.send_message(chat_id=chat_id, text=ack_text)
    except Exception:
        pass
    await _send_review_at_index(bot, chat_id, state, pending, 0)
