"""申请验证共享 service（用户向老师自证「真实约课用户」）。

用户在某老师详情页一键「申请验证」→ bot 把该用户**最近一条已通过评价 + 约课截图**发到
该老师私聊，并**亮明 @username**（非半匿名），让老师即时核对约课记录，省去回头索要截图。

资格（服务端权威）：
    - 用户须有 Telegram 用户名（无 → 拒绝）；
    - 用户须有 ≥1 条 status='approved' 的评价（评价过任意老师即可）；
    - 同一用户对同一老师 1 小时内只能发一次（冷却）。

隐私边界：评论区评价展示仍半匿名（render_review_comment ****<last4>）；**仅本验证 DM 露名**。
发送失败（老师未开通 bot 私聊 / 屏蔽）→ 不记录，让用户可重试。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InputMediaPhoto

from bot.database import (
    REVIEW_RATINGS,
    add_verification_request,
    count_recent_verifications,
    get_teacher,
    get_user,
    list_user_reviews_paged,
)

logger = logging.getLogger(__name__)

# 同一用户对同一老师的冷却窗口（秒）
VERIFY_COOLDOWN_SECONDS = 3600


@dataclass
class VerifyResult:
    ok: bool
    error: Optional[str] = None


def _rating_label(key: Optional[str]) -> str:
    meta = {r["key"]: r for r in REVIEW_RATINGS}.get(
        key or "", {"emoji": "❓", "label": key or "?"},
    )
    return f"{meta['emoji']} {meta['label']}"


def _build_text(username: str, review: dict) -> str:
    """验证 DM 文本：实名 @username + 评级 + 综合分 + 6 维分 + 摘要。"""
    summary = review.get("summary") or "（未填写）"
    return (
        f"🔰 用户 @{username} 申请向你验证（真实约课用户）\n\n"
        f"评级：{_rating_label(review.get('rating'))} · "
        f"🎯 综合 {review.get('overall_score', '?')}/10\n"
        f"🎨 人照 {review.get('score_humanphoto', '?')} | "
        f"颜值 {review.get('score_appearance', '?')} | "
        f"身材 {review.get('score_body', '?')}\n"
        f"   服务 {review.get('score_service', '?')} | "
        f"态度 {review.get('score_attitude', '?')} | "
        f"环境 {review.get('score_environment', '?')}\n"
        f"📝 过程：{summary}\n\n"
        "上方为该用户的约课记录，可据此核对。"
    )


async def send_verification_to_teacher(
    bot: Bot, *, user_id: int, teacher_id: int,
) -> VerifyResult:
    """把用户最近一条已通过评价 + 约课截图发给老师私聊。

    资格 / 冷却全在服务端校验；发送成功才记录（用于冷却）。失败仅 warning，不抛。
    """
    teacher = await get_teacher(teacher_id)
    if not teacher or teacher.get("is_deleted"):
        return VerifyResult(ok=False, error="老师不存在")

    user = await get_user(user_id)
    username = (user or {}).get("username")
    if not username:
        return VerifyResult(
            ok=False, error="需先设置 Telegram 用户名才能申请验证",
        )

    if await count_recent_verifications(user_id, teacher_id, VERIFY_COOLDOWN_SECONDS) > 0:
        return VerifyResult(
            ok=False, error="1 小时内已向该老师发起过验证，请稍后再试",
        )

    rows = await list_user_reviews_paged(user_id, status_filter="approved", limit=1)
    if not rows:
        return VerifyResult(ok=False, error="需先有一条已通过审核的评价才能申请验证")
    review = rows[0]
    booking_fid = review.get("booking_screenshot_file_id")
    if not booking_fid:
        return VerifyResult(ok=False, error="该评价缺少约课记录，无法验证")

    media = [InputMediaPhoto(media=booking_fid, caption="📸 约课记录")]
    text = _build_text(username, review)

    try:
        await bot.send_media_group(chat_id=teacher_id, media=media)
        await bot.send_message(chat_id=teacher_id, text=text)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.warning(
            "send_verification 不可达 teacher=%s user=%s: %s", teacher_id, user_id, e,
        )
        return VerifyResult(ok=False, error="老师暂时无法接收（可能未开通 bot 私聊）")
    except Exception as e:
        logger.warning(
            "send_verification 失败 teacher=%s user=%s: %s", teacher_id, user_id, e,
        )
        return VerifyResult(ok=False, error="发送失败，请稍后重试")

    # 发送成功才记录（冷却以成功为准，失败可重试）
    try:
        await add_verification_request(user_id, teacher_id, review.get("id"))
    except Exception as e:
        logger.warning("add_verification_request 失败（不影响已送达）: %s", e)

    return VerifyResult(ok=True)
