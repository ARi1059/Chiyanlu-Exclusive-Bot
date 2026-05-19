"""报销专用必关频道 / 群组校验。

设计：
    - 与全局 required_subscriptions (bot/utils/required_channels.py) 完全独立
    - 配置存于 config 表 key="reimbursement_required_chats" (JSON array)
    - 仅在用户勾选"申请报销"时触发；不影响浏览 / 搜索 / 收藏 / 抽奖 / 评价提交
    - 配置为空 → 视为无门槛，直接放行（与全局 subreq 一致的语义）
    - bot 调用本身异常的项：跳过 + warning（容错），不阻断报销

判定逻辑与 bot/utils/required_channels.py 完全一致：
    ChatMember.status ∈ {"member", "administrator", "creator"} 视为已加入。
"""
from __future__ import annotations

import logging

from aiogram import Bot

from bot.database import get_reimburse_required_chats

logger = logging.getLogger(__name__)

# Telegram ChatMember.status 视为"已加入"的取值（与全局 subreq 同一口径）
_JOINED_STATUSES: set[str] = {"member", "administrator", "creator"}


async def check_user_subscribed_for_reimburse(
    bot: Bot,
    user_id: int,
) -> tuple[bool, list[dict]]:
    """校验用户是否已加入所有"报销专用"必关频道 / 群组。

    Returns:
        (all_joined, missing_items)
        - all_joined: 所有 enabled 项都校验通过；列表为空时返回 True（无门槛 → 放行）
        - missing_items: 用户未加入的项列表（含 display_name + invite_link）
        - bot 调用本身异常的项：跳过 + warning（不计入 missing，与全局 subreq 容错一致）
    """
    items = await get_reimburse_required_chats()
    # 仅校验 enabled=True 的项；禁用项视为暂不强制
    active_items = [it for it in items if it.get("enabled", True)]
    if not active_items:
        return True, []

    missing: list[dict] = []
    for item in active_items:
        chat_id = item.get("chat_id")
        try:
            cm = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.warning(
                "check_user_subscribed_for_reimburse 跳过 chat_id=%s（bot 调用失败）: %s",
                chat_id, e,
            )
            continue
        status = getattr(cm, "status", None)
        if status not in _JOINED_STATUSES:
            missing.append(item)
    return (len(missing) == 0), missing
