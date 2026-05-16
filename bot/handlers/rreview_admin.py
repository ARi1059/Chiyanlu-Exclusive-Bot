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
    REVIEW_RATINGS,
)
from bot.keyboards.admin_kb import (
    main_menu_kb,
    rreview_action_kb,
    rreview_empty_kb,
)

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
