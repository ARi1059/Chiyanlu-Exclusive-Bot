"""报告审核通知（Phase 9.4）

两类通知：
1. 私聊评价者：审核通过 / 驳回（含原因）
2. 推送超管：新评价提交后（媒体组 2 张证据图 + 概要 + 前往审核按钮）—— Phase 9.4.3

容错：用户屏蔽 bot / chat 不可达 → TelegramForbiddenError / BadRequest 时仅 warning，
不抛错（不阻塞超管审核流程）。

UX-4.3：私聊评价者的通过 / 驳回通知附 CTA keyboard：
    通过 → [📝 个人评价主页] [🔥 找下一个老师] [🏠 返回主菜单]
    驳回 → [📝 个人评价主页] [📩 联系超管 (URL, 仅当 config 配置)] [🏠 返回主菜单]
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from bot.database import (
    REVIEW_RATINGS,
    get_config,
    get_teacher_review,
    get_teacher,
    list_super_admins,
)
from bot.keyboards.admin_kb import rreview_push_action_kb

logger = logging.getLogger(__name__)


def build_user_review_approved_kb() -> InlineKeyboardMarkup:
    """构造"评价通过"通知 CTA keyboard（UX-4.3）。

    布局：
        - [📝 个人评价主页]   callback=user:write_review  查看自己所有评价
        - [🔥 找下一个老师]   callback=user:find          找老师聚合页
        - [🏠 返回主菜单]     callback=user:main          兜底
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 个人评价主页", callback_data="user:write_review")],
        [InlineKeyboardButton(text="🔥 找下一个老师", callback_data="user:find")],
        [InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main")],
    ])


async def build_user_review_rejected_kb() -> InlineKeyboardMarkup:
    """构造"评价驳回"通知 CTA keyboard（UX-4.3）。

    布局：
        - [📝 个人评价主页]   callback=user:write_review  查看驳回详情 + 重新提交入口
        - [📩 联系超管]       url=<contact_url>           仅当 config 配置时显示
        - [🏠 返回主菜单]     callback=user:main          兜底

    联系超管 URL 读取优先级：review_contact_url → lottery_contact_url；
    双空时只有 2 个 callback 按钮，不引入死链。
    """
    contact_url = (await get_config("review_contact_url") or "").strip()
    if not contact_url:
        contact_url = (await get_config("lottery_contact_url") or "").strip()
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text="📝 个人评价主页", callback_data="user:write_review",
        )],
    ]
    if contact_url:
        rows.append([
            InlineKeyboardButton(text="📩 联系超管", url=contact_url),
        ])
    rows.append([
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="user:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    delta: Optional[int] = None,
    new_total: Optional[int] = None,
    package_label: Optional[str] = None,
    reimb_amount: int = 0,
    reimb_pending: bool = False,
) -> None:
    """通知评价者：审核通过（Phase P.1：可选附积分增量 + 当前总积分）

    Args:
        delta: 本次获得积分（None 表示不附积分信息，向后兼容 9.4 调用）
        new_total: 当前总积分（与 delta 配对使用）
        package_label: 套餐标签（如 "包夜"）；若提供则展示"本次获得：+5 积分（包夜）"
        reimb_amount: 报销金额（元）；reimb_pending=True 时显示提交提示
        reimb_pending: 是否已创建 pending reimbursement（评价勾选了报销且满足资格）
    """
    review = await get_teacher_review(review_id)
    if not review:
        return
    name = teacher_name
    if name is None:
        teacher = await get_teacher(review["teacher_id"])
        name = teacher["display_name"] if teacher else f"#{review['teacher_id']}"

    lines = [
        "✅ 你的评价已通过审核。",
        "",
        f"老师：{name}",
        f"评级：{_rating_str(review.get('rating'))} · "
        f"🎯 综合 {review.get('overall_score', '?')}",
    ]
    if delta is not None:
        lines.append("")
        if package_label:
            lines.append(f"本次获得：+{delta} 积分（{package_label}）")
        else:
            lines.append(f"本次获得：+{delta} 积分")
        if new_total is not None:
            lines.append(f"当前总积分：{new_total}")
    if reimb_pending and reimb_amount > 0:
        lines.append("")
        lines.append(f"💰 报销申请已提交：{reimb_amount} 元，正在等待超管审核。")
    lines.append("")
    lines.append("感谢你的反馈！")
    text = "\n".join(lines)
    # UX-4.3：通过通知附 CTA keyboard（个人评价主页 / 找下一个老师 / 主菜单）
    await _safe_send_text(
        bot, review["user_id"], text,
        reply_markup=build_user_review_approved_kb(),
    )


async def notify_teacher_review_approved(
    bot: Bot,
    review_id: int,
    *,
    hidden: bool = False,
) -> bool:
    """评价审核通过后将评价 + 3 按钮一并推送到老师私聊（2026-05 新增）。

    与讨论群评论使用**同一份** render_review_comment 输出，保证：
    - 文本格式一致（含 HTML 转义 + footer config 化）
    - 3 按钮一致（联系 / 评级徽章 / 写报告 deep link）
    - 老师转发该消息到其它对话时，inline keyboard 跟随消息体保留
      （Telegram 行为）；deep link 写报告按钮转发后他人点击仍能进 bot

    隐私边界：与讨论群版本一致，留名半匿名（****1234 / 匿*）
    不暴露评价者真实信息。

    返回：发送成功 True；失败 / skip False（失败仅 logger.warning，
    不抛异常，caller 不应阻塞主流程）。
    """
    from aiogram.enums import ParseMode
    from bot.utils.review_comment import render_review_comment
    from bot.database import (
        get_reimburse_promo_text,
        get_reimburse_promo_url,
    )

    review = await get_teacher_review(review_id)
    if not review:
        logger.warning("notify_teacher_review_approved skip：review %s 不存在", review_id)
        return False
    teacher_id = review.get("teacher_id")
    if not teacher_id:
        logger.warning(
            "notify_teacher_review_approved skip：review %s 缺 teacher_id", review_id,
        )
        return False
    teacher = await get_teacher(teacher_id)
    if not teacher:
        logger.warning(
            "notify_teacher_review_approved skip：teacher %s 不存在", teacher_id,
        )
        return False

    try:
        me = await bot.get_me()
        bot_username = me.username
    except Exception as e:
        logger.warning("notify_teacher_review_approved get_me 失败: %s", e)
        bot_username = "Bot"

    promo_text = await get_reimburse_promo_text()
    promo_url = await get_reimburse_promo_url()
    text, kb = render_review_comment(
        review, teacher,
        bot_username=bot_username,
        promo_text=promo_text,
        promo_url=promo_url,
    )
    if hidden:
        text += (
            "\n\n⚠️ 此评价已被管理员隐藏，不在评论区公开展示"
            "（积分与评分统计照常计入）。"
        )

    return await _safe_send_text(
        bot, teacher_id, text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def notify_teacher_review_visibility(
    bot: Bot, review_id: int, *, hidden: bool,
) -> bool:
    """事后切换评价可见性时通知老师（best-effort 简讯，不重发整条评价）。"""
    review = await get_teacher_review(review_id)
    if not review:
        return False
    teacher_id = review.get("teacher_id")
    if not teacher_id:
        return False
    if hidden:
        text = "⚠️ 你的一条评价已被管理员隐藏，不在评论区公开展示（积分与评分统计照常）。"
    else:
        text = "✅ 你此前被隐藏的一条评价已恢复展示，现已重新发布到评论区。"
    return await _safe_send_text(bot, teacher_id, text)


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
    # UX-4.3：驳回通知附 CTA keyboard（个人评价主页 / 联系超管 / 主菜单）
    kb = await build_user_review_rejected_kb()
    await _safe_send_text(bot, review["user_id"], text, reply_markup=kb)


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
    anon_tag = " · 🕵 匿名提交" if int(review.get("anonymous") or 0) == 1 else ""
    text = (
        "🆕 有新报告待审核\n\n"
        f"老师：{teacher_name}\n"
        f"评价者：{_anonymize_user_id(review['user_id'])} "
        f"(uid: {_anonymize_user_id(review['user_id'])}){anon_tag}\n"
        f"评级：{_rating_str(review.get('rating'))} · "
        f"🎯 {review.get('overall_score', '?')}/10\n"
        f"📝 过程：{summary}"
    )
    # 2026-05-21：req=0 路径 gesture_photo 可能为 NULL；按可用性过滤
    media = [
        InputMediaPhoto(media=review["booking_screenshot_file_id"], caption="📸 约课记录"),
    ]
    if review.get("gesture_photo_file_id"):
        media.append(InputMediaPhoto(
            media=review["gesture_photo_file_id"], caption="✋ 现场手势",
        ))
    supers = await list_super_admins()
    try:
        _me = await bot.get_me()
        _bot_username = _me.username
    except Exception:
        _bot_username = None
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
        # 文字 + 前往审核 / 打开小程序处理 按钮
        await _safe_send_text(
            bot, uid, text,
            reply_markup=rreview_push_action_kb(_bot_username),
        )
