"""抽奖必关频道校验（Phase L.2.3）

与评价系统的 required_channels.check_user_subscribed 不同：
- 抽奖每个独立配置 chat_ids（list[int]，无 display_name / invite_link 字段）
- 校验时实时拿 bot.get_chat 的 title / username
- 拒绝用户加入时无邀请链接 → 用 @username 或 chat_id 提示用户手动找

判定规则与 9.3 保持一致：member / administrator / creator 视为已加入；
bot 异常的 chat（不存在 / 没权限）静默跳过（spec §9 容错）。
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Telegram ChatMember.status 视为"已加入"的取值
_JOINED_STATUSES: set[str] = {"member", "administrator", "creator"}


async def check_user_subscribed_to_chats(
    bot: Bot,
    user_id: int,
    chat_ids: list[int],
) -> tuple[bool, list[dict]]:
    """对每个 chat_id 调 bot.get_chat_member 校验

    Returns:
        (all_joined, missing_items)
        - all_joined：列表为空时返回 True
        - missing_items：每项 {chat_id, title, username}
        - bot 调用本身异常 → 静默跳过 + warning（不计入 missing）
    """
    if not chat_ids:
        return True, []

    missing: list[dict] = []
    for cid in chat_ids:
        try:
            cm = await bot.get_chat_member(chat_id=cid, user_id=user_id)
        except Exception as e:
            logger.warning(
                "check_user_subscribed_to_chats 跳过 chat=%s: %s", cid, e,
            )
            continue
        status = getattr(cm, "status", None)
        if status in _JOINED_STATUSES:
            continue
        # 未加入 → 拿 chat title/username 用于提示
        title = f"chat_id={cid}"
        username = None
        try:
            chat = await bot.get_chat(chat_id=cid)
            title = (
                getattr(chat, "title", None)
                or getattr(chat, "username", None)
                or title
            )
            username = getattr(chat, "username", None)
        except Exception as e:
            logger.debug("get_chat 失败 cid=%s: %s", cid, e)
        missing.append({
            "chat_id": cid,
            "title": title,
            "username": username,
        })
    return (len(missing) == 0), missing


def render_lottery_subscribe_links_kb(
    missing: list[dict],
) -> tuple[str, InlineKeyboardMarkup]:
    """渲染必关频道未加入的提示文字 + 链接按钮

    Returns: (text, kb)
    """
    lines = ["⚠️ 参与本次抽奖前请先加入以下频道/群组：\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for it in missing:
        cid = it["chat_id"]
        title = it.get("title") or f"chat_id={cid}"
        username = it.get("username")
        if username:
            lines.append(f"📺 {title} (@{username})")
            rows.append([InlineKeyboardButton(
                text=f"📺 {title}",
                url=f"https://t.me/{username}",
            )])
        else:
            # 无 username → 公开链接拿不到，提示用户手动找
            lines.append(f"📺 {title} (chat_id={cid})")
            rows.append([InlineKeyboardButton(
                text=f"📺 {title} (chat_id={cid})",
                callback_data="noop:lottery_chat_no_link",
            )])
    lines.append("")
    lines.append("加入后请回到抽奖帖重新点 [🎲 参与抽奖]（或在私聊发口令）。")
    rows.append([InlineKeyboardButton(text="🔙 返回主菜单", callback_data="user:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
