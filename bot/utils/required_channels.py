"""必关频道/群组校验（Phase 9.3）

spec §3：写评价前要求用户已加入 required_subscriptions 中全部 active 频道/群组。
- 列表为空 → 视为无门槛（spec §3.4）
- bot 异常（频道不存在 / bot 没权限）→ 跳过该项 + warning（spec §9）
- 已加入判定：member / administrator / creator 三种 ChatMember status
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot

from bot.database import list_required_subscriptions

logger = logging.getLogger(__name__)

# Telegram ChatMember.status 视为"已加入"的取值
_JOINED_STATUSES: set[str] = {"member", "administrator", "creator"}


async def check_user_subscribed(
    bot: Bot,
    user_id: int,
) -> tuple[bool, list[dict]]:
    """对每个 active required_subscriptions 调 bot.get_chat_member 校验

    Returns:
        (all_joined, missing_items)
        - all_joined: 所有 active 项都校验通过；列表为空时返回 True（无门槛）
        - missing_items: 用户未加入的项列表（含 display_name + invite_link 给 UI 用）
        - bot 调用本身异常的项：跳过 + warning（不计入 missing，按 spec §9 容错）
    """
    items = await list_required_subscriptions(active_only=True)
    if not items:
        return True, []

    missing: list[dict] = []
    for item in items:
        chat_id = item.get("chat_id")
        try:
            cm = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.warning(
                "check_user_subscribed 跳过 chat_id=%s（bot 调用失败）: %s",
                chat_id, e,
            )
            continue
        status = getattr(cm, "status", None)
        if status not in _JOINED_STATUSES:
            missing.append(item)
    return (len(missing) == 0), missing


async def precheck_required_chat(
    bot: Bot,
    chat_id: int,
) -> tuple[bool, str, Optional[dict]]:
    """配置时预校验：chat_id 是否有效 + bot 是否在场

    Returns:
        (ok, reason_or_summary, chat_info)
        - ok=True：bot 已加入；chat_info 含 type / title / username
        - ok=False：reason 给中文原因；chat_info 可能为 None
    """
    # 1. bot.get_chat 拿基础信息
    try:
        chat = await bot.get_chat(chat_id=chat_id)
    except Exception as e:
        return False, f"无法获取该 chat（{type(e).__name__}: {e}）", None

    chat_type = getattr(chat, "type", "unknown")
    title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat_id)

    # 2. 校验 bot 自身能否查成员
    try:
        me = await bot.get_me()
    except Exception as e:
        return False, f"bot.get_me 失败：{e}", None
    try:
        cm = await bot.get_chat_member(chat_id=chat_id, user_id=me.id)
    except Exception as e:
        return False, (
            f"bot 不在该 chat 或无权限查询（{type(e).__name__}: {e}）"
        ), None
    status = getattr(cm, "status", None)
    if status in {"left", "kicked"}:
        return False, f"bot 当前不在该 chat（status={status}）", None

    return True, "OK", {
        "type": str(chat_type),
        "title": title,
        "username": getattr(chat, "username", None),
    }
