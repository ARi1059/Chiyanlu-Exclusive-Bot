"""报告审核通知（Phase 9.4）

两类通知：
1. 私聊评价者：审核通过 / 驳回（含原因）
2. 推送超管：新评价提交后（媒体组 2 张证据图 + 概要 + 前往审核按钮）—— Phase 9.4.3

容错：用户屏蔽 bot / chat 不可达 → TelegramForbiddenError / BadRequest 时仅 warning，
不抛错（不阻塞超管审核流程）。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InputMediaPhoto

from bot.database import (
    REVIEW_RATINGS,
    get_teacher_review,
    get_teacher,
    list_super_admins,
)
from bot.keyboards.admin_kb import rreview_push_action_kb

logger = logging.getLogger(__name__)


def _rating_str(rating_key: Optional[str]) -> str:
    meta = {r["key"]: r for r in REVIEW_RATINGS}.get(
        rating_key, {"emoji": "❓", "label": rating_key or "?"},
    )
    return f"{meta['emoji']} {meta['label']}"


async def _safe_send_text(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    """发文字消息容错；用户屏蔽 / chat 不可达时返回 False"""
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except TelegramForbiddenError as e:
        logger.warning("send_message Forbidden chat=%s: %s", chat_id, e)
    except TelegramBadRequest as e:
        logger.warning("send_message BadRequest chat=%s: %s", chat_id, e)
    except Exception as e:
        logger.warning("send_message 失败 chat=%s: %s", chat_id, e)
    return False


async def notify_review_approved(
    bot: Bot,
    review_id: int,
    *,
    teacher_name: Optional[str] = None,
) -> None:
    """通知评价者：审核通过"""
    review = await get_teacher_review(review_id)
    if not review:
        return
    name = teacher_name
    if name is None:
        teacher = await get_teacher(review["teacher_id"])
        name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"
    text = (
        f"✅ 你的评价已通过审核。\n\n"
        f"老师：{name}\n"
        f"评级：{_rating_str(review.get('rating'))} · "
        f"🎯 综合 {review.get('overall_score', '?')}\n\n"
        "感谢你的反馈！"
    )
    await _safe_send_text(bot, review["user_id"], text)


async def notify_review_rejected(
    bot: Bot,
    review_id: int,
    *,
    teacher_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """通知评价者：审核驳回（含原因或"未填写"提示）"""
    review = await get_teacher_review(review_id)
    if not review:
        return
    name = teacher_name
    if name is None:
        teacher = await get_teacher(review["teacher_id"])
        name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"
    reason_line = f"驳回原因：{reason}" if reason else "驳回原因：未填写"
    text = (
        f"❌ 你的评价未通过审核。\n\n"
        f"老师：{name}\n"
        f"评级：{_rating_str(review.get('rating'))}\n\n"
        f"{reason_line}\n\n"
        "如有疑问可联系超管。"
    )
    await _safe_send_text(bot, review["user_id"], text)


def _anonymize_user_id(uid: int) -> str:
    s = str(uid)
    if len(s) <= 4:
        return "****"
    return "*" * (len(s) - 4) + s[-4:]


async def notify_super_admins_anchor_lost(
    bot: Bot,
    *,
    teacher_id: int,
    teacher_name: Optional[str] = None,
) -> None:
    """Phase 9.5.3：讨论群锚消息丢失告警（fallback 已发不 reply 消息）"""
    name = teacher_name or f"#{teacher_id}"
    text = (
        "⚠️ 讨论群锚消息丢失\n\n"
        f"老师：{name} (teacher_id={teacher_id})\n"
        "评价已用 fallback 发到讨论群（不挂在锚消息下）。\n"
        "建议：在频道重发档案帖（重发档案帖 → 让 Telegram 自动转发→ 监听器重写锚 id）。"
    )
    supers = await list_super_admins()
    for uid in supers:
        await _safe_send_text(bot, uid, text)


async def notify_super_admins_new_review(bot: Bot, review_id: int) -> None:
    """新评价提交后推送给所有超管（媒体组 + 概要 + 前往审核按钮）— Phase 9.4.3 用"""
    review = await get_teacher_review(review_id)
    if not review:
        return
    teacher = await get_teacher(review["teacher_id"])
    teacher_name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"
    summary = review.get("summary") or "（未填写）"
    text = (
        "🆕 有新报告待审核\n\n"
        f"老师：{teacher_name}\n"
        f"评价者：{_anonymize_user_id(review['user_id'])} "
        f"(uid: {_anonymize_user_id(review['user_id'])})\n"
        f"评级：{_rating_str(review.get('rating'))} · "
        f"🎯 {review.get('overall_score', '?')}/10\n"
        f"📝 过程：{summary}"
    )
    media = [
        InputMediaPhoto(media=review["booking_screenshot_file_id"], caption="📸 约课记录"),
        InputMediaPhoto(media=review["gesture_photo_file_id"], caption="✋ 现场手势"),
    ]
    supers = await list_super_admins()
    for uid in supers:
        # 媒体组
        try:
            await bot.send_media_group(chat_id=uid, media=media)
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.warning("notify_super_admins media_group skip uid=%s: %s", uid, e)
            continue
        except Exception as e:
            logger.warning("notify_super_admins media_group 失败 uid=%s: %s", uid, e)
            continue
        # 文字 + 前往审核按钮
        await _safe_send_text(
            bot, uid, text,
            reply_markup=rreview_push_action_kb(),
        )
