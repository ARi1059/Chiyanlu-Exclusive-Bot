"""讨论群评价评论发布（Phase 9.5.3）

通过审核时调用 publish_review_comment：
- 在讨论群发评论（reply_to_message_id=discussion_anchor_id）
- 文本按 spec §6.3 "【...】" 中括号格式
- 3 个底部按钮：[🔗 联系] / [评级徽章 noop] / [🤖 写评价 deep link]
- 锚消息丢失（Telegram BadRequest "reply message not found"）→
  fallback 发不 reply 的消息 + notify_super_admins_anchor_lost
"""
from __future__ import annotations

import logging
from html import escape as _html_escape
from typing import Optional

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import (
    REVIEW_RATINGS,
    get_reimburse_promo_text,
    get_reimburse_promo_url,
    get_teacher,
    get_teacher_channel_post,
    get_teacher_review,
    update_review_discussion_msg,
)

logger = logging.getLogger(__name__)

MAX_BUTTON_NAME_LEN: int = 10  # spec §6.3：display_name > 20 字符时按"前 10 字…"截断

# 2026-05-20 已 config 化（promo_text + promo_url）；保留默认值常量用作历史
# sync 脚本兼容（scripts/sync_review_promo_footer.py）+ 测试快照。
# render_review_comment 不直接读这两个常量，而由 caller 注入 promo_text /
# promo_url 参数；任一为空字符串则 footer 整行不渲染。
REIMBURSE_PROMO_TEXT: str = "出击报销八折"
REIMBURSE_PROMO_URL: str = "https://t.me/ChiYanDairy/553"


class CommentError(Exception):
    """评论发布错误

    reason ∈ {
        "no_review":     评价不存在
        "no_teacher":    老师不存在
        "no_anchor":     teacher_channel_posts 缺 discussion_chat_id / anchor_id
        "api_error":     Telegram 调用失败（已尝试 fallback 仍失败）
    }
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _trim_name_for_button(name: str) -> str:
    """spec §6.3：display_name > 20 字符 → '前 10 字…'"""
    if not name:
        return ""
    if len(name) > 20:
        return name[:MAX_BUTTON_NAME_LEN] + "…"
    return name


def _format_score(value: float) -> str:
    """6 维分数保留原精度：整数显示 '9'，否则 '8.5'"""
    if value is None:
        return "?"
    f = float(value)
    if f == int(f):
        return str(int(f))
    return f"{f:.1f}"


def _format_overall(value: float) -> str:
    """综合评分固定 2 位小数（spec §6.3）"""
    if value is None:
        return "?.??"
    return f"{float(value):.2f}"


def render_review_comment(
    review: dict,
    teacher: dict,
    bot_username: str = "ChiYanBookBot",
    *,
    promo_text: Optional[str] = None,
    promo_url: Optional[str] = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """渲染评论文字 + 3 按钮键盘

    spec §6.3：
        【老师】：{display_name}
        【留名】：{anonymized_name}   （半匿名 ****6204 风格）
        【人照】：{score_humanphoto}
        【颜值】：{score_appearance}
        【身材】：{score_body}
        【服务】：{score_service}
        【态度】：{score_attitude}
        【环境】：{score_environment}
        【综合】：{overall:.2f}
        【过程】：{summary}            （summary=None 时整行省略）

        ✳ Powered by @{bot_username}

        <a href="{promo_url}">{promo_text}</a>   （任一为空整行不渲染）

    2026-05-20：文本返回 HTML 格式；调用方须以 parse_mode=HTML 发送。
    用户输入字段（display_name / summary）经 html.escape 处理防注入。

    2026-05 续：footer 推广 text / url 由调用方注入（已 config 化）；
    若两参数任一为 None 或空串，footer 整行不渲染。caller 在 publish 阶段
    通过 get_reimburse_promo_text / get_reimburse_promo_url 读 config 后
    传入。**为保持函数纯度（同步 + 易测试）不在本函数内 await**。

    按钮：3 行独占
      [🔗 联系{name前10字…}]       URL = teacher.button_url
      [{rating_emoji} {rating_label}]  callback = noop:rating
      [🤖 给{name前10字…}写报告]   URL = t.me/{bot}?start=write_{teacher_id}
    """
    name = teacher.get("display_name") or f"#{teacher.get('user_id')}"
    short_name = _trim_name_for_button(name)
    teacher_id = teacher.get("user_id")

    # 留名：默认半匿名 ****<last4>；anonymous=1 完全匿名
    if int(review.get("anonymous") or 0) == 1:
        anon = "匿*"
    else:
        uid = review.get("user_id") or 0
        sid = str(uid)
        if len(sid) <= 4:
            anon = "****"
        else:
            anon = "*" * (len(sid) - 4) + sid[-4:]

    summary = review.get("summary")
    safe_name = _html_escape(name)
    lines = [
        f"【老师】：{safe_name}",
        f"【留名】：{anon}",
        f"【人照】：{_format_score(review.get('score_humanphoto'))}",
        f"【颜值】：{_format_score(review.get('score_appearance'))}",
        f"【身材】：{_format_score(review.get('score_body'))}",
        f"【服务】：{_format_score(review.get('score_service'))}",
        f"【态度】：{_format_score(review.get('score_attitude'))}",
        f"【环境】：{_format_score(review.get('score_environment'))}",
        f"【综合】：{_format_overall(review.get('overall_score'))}",
    ]
    if summary:
        lines.append(f"【过程】：{_html_escape(summary)}")
    lines.append("")
    lines.append(f"✳ Powered by @{_html_escape(bot_username)}")
    # footer：仅当 promo_text 与 promo_url 都非空时渲染
    if promo_text and promo_url:
        lines.append("")
        lines.append(
            f'<a href="{_html_escape(promo_url)}">{_html_escape(promo_text)}</a>'
        )

    text = "\n".join(lines)

    # 3 按钮
    rating_meta = {r["key"]: r for r in REVIEW_RATINGS}.get(
        review.get("rating"), {"emoji": "❓", "label": review.get("rating", "?")},
    )
    rating_btn_text = f"{rating_meta['emoji']} {rating_meta['label']}"
    contact_url = teacher.get("button_url") or ""
    write_url = f"https://t.me/{bot_username}?start=write_{teacher_id}"

    rows: list[list[InlineKeyboardButton]] = []
    if contact_url:
        rows.append([InlineKeyboardButton(
            text=f"🔗 联系{short_name}",
            url=contact_url,
        )])
    rows.append([InlineKeyboardButton(
        text=rating_btn_text,
        callback_data="noop:rating",
    )])
    rows.append([InlineKeyboardButton(
        text=f"🤖 给{short_name}写报告",
        url=write_url,
    )])

    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def publish_review_comment(bot: Bot, review_id: int) -> dict:
    """评价通过后发评论到讨论群

    流程：
    1. 取 review + teacher + post（缺锚 → no_anchor）
    2. 渲染 text + kb
    3. send_message(reply_to_message_id=anchor_id)；"reply not found" → fallback：
       不带 reply 重发 + 通知超管锚丢失
    4. 写 teacher_reviews.discussion_chat_id / discussion_msg_id / published_at

    Returns: {"chat_id": int, "msg_id": int, "fallback": bool}
    Raises CommentError on hard failure.
    """
    review = await get_teacher_review(review_id)
    if not review:
        raise CommentError("no_review", f"review {review_id} 不存在")
    teacher_id = review["teacher_id"]
    teacher = await get_teacher(teacher_id)
    if not teacher:
        raise CommentError("no_teacher", f"teacher {teacher_id} 不存在")
    post = await get_teacher_channel_post(teacher_id)
    discussion_chat_id = (post or {}).get("discussion_chat_id")
    anchor_id = (post or {}).get("discussion_anchor_id")
    if not discussion_chat_id or not anchor_id:
        raise CommentError(
            "no_anchor",
            f"teacher {teacher_id} 未捕获到讨论群锚消息（需先在频道发布档案帖 + 等待自动转发）",
        )

    me = await bot.get_me()
    # 2026-05：footer 推广 text / url 已 config 化，由 publish 阶段读取后注入。
    # 任一为空字符串 → render 不渲染整行。
    promo_text = await get_reimburse_promo_text()
    promo_url = await get_reimburse_promo_url()
    text, kb = render_review_comment(
        review, teacher,
        bot_username=me.username,
        promo_text=promo_text,
        promo_url=promo_url,
    )

    fallback = False
    sent_msg = None
    try:
        sent_msg = await bot.send_message(
            chat_id=discussion_chat_id,
            text=text,
            reply_markup=kb,
            reply_to_message_id=anchor_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "reply" in msg and ("not found" in msg or "message to reply" in msg):
            # 锚消息丢失 → fallback 发不 reply + 通知超管
            logger.warning(
                "publish_review_comment 锚丢失 teacher=%s anchor=%s: %s",
                teacher_id, anchor_id, e,
            )
            try:
                sent_msg = await bot.send_message(
                    chat_id=discussion_chat_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                fallback = True
            except Exception as e2:
                raise CommentError(
                    "api_error",
                    f"锚丢失 fallback 仍失败：{type(e2).__name__}: {e2}",
                ) from e2
            # 通知超管（容错）
            try:
                from bot.utils.rreview_notify import notify_super_admins_anchor_lost
                await notify_super_admins_anchor_lost(
                    bot,
                    teacher_id=teacher_id,
                    teacher_name=teacher.get("display_name"),
                )
            except Exception as e3:
                logger.warning("notify_super_admins_anchor_lost 失败: %s", e3)
        else:
            raise CommentError(
                "api_error",
                f"send_message 失败：{type(e).__name__}: {e}",
            ) from e
    except (TelegramForbiddenError, Exception) as e:
        raise CommentError(
            "api_error",
            f"send_message 失败：{type(e).__name__}: {e}",
        ) from e

    if sent_msg is None:
        raise CommentError("api_error", "send_message 返回 None")

    await update_review_discussion_msg(
        review_id=review_id,
        discussion_chat_id=discussion_chat_id,
        discussion_msg_id=sent_msg.message_id,
    )
    return {
        "chat_id": discussion_chat_id,
        "msg_id": sent_msg.message_id,
        "fallback": fallback,
    }
