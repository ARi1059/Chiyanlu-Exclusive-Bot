"""讨论群锚消息自动捕获监听器（Phase 9.5）

工作原理：
频道发档案帖（媒体组）后，Telegram 把第一张图自动转发到绑定的讨论群。
该转发消息的属性：
  - is_automatic_forward == True
  - forward_from_chat.id == 频道 chat_id
  - forward_from_message_id == 频道帖 channel_msg_id

bot 监听这种 message，把当前讨论群 chat_id + msg_id 作为锚记录入库，
供 Phase 9.5.3 评价发布时 reply_to_message_id 使用。

注意：
- 媒体组有 N 张图 → 讨论群会收到 N 条 forward；本监听仅匹配 channel_msg_id
  对应的那一条（即媒体组第一张），其余跳过。
- bot 必须已加入讨论群（admin 在 Telegram 内手动拉入），否则收不到事件。
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, types, F

from bot.database import (
    find_teacher_post_by_channel_msg,
    update_teacher_channel_post_discussion,
)

logger = logging.getLogger(__name__)

router = Router(name="discussion_anchor_listener")


def _extract_forward_channel(msg: types.Message) -> Optional[tuple[int, int]]:
    """从 message 提取 (forward_from_chat_id, forward_from_message_id)

    优先用 forward_origin（aiogram 3.x 新 API）；fallback 用老的
    forward_from_chat / forward_from_message_id 字段。
    """
    # 新 API：forward_origin.type == MessageOriginChannel
    origin = getattr(msg, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        mid = getattr(origin, "message_id", None)
        if chat is not None and getattr(chat, "id", None) is not None and mid is not None:
            try:
                return int(chat.id), int(mid)
            except (TypeError, ValueError):
                pass
    # 老 API：兼容
    chat = getattr(msg, "forward_from_chat", None)
    mid = getattr(msg, "forward_from_message_id", None)
    if chat is not None and getattr(chat, "id", None) is not None and mid is not None:
        try:
            return int(chat.id), int(mid)
        except (TypeError, ValueError):
            pass
    return None


@router.message(F.is_automatic_forward.is_(True))
async def on_automatic_forward(message: types.Message):
    """监听讨论群中"从绑定频道自动转发"的消息

    仅匹配 channel_msg_id 对应的 forward（即媒体组第一张），把当前 message
    在讨论群里的 chat_id + msg_id 作为锚消息写入。
    """
    pair = _extract_forward_channel(message)
    if pair is None:
        logger.debug("automatic_forward 无 forward_from_chat 信息，跳过")
        return
    src_chat_id, src_msg_id = pair

    post = await find_teacher_post_by_channel_msg(src_chat_id, src_msg_id)
    if post is None:
        # 不是我们记录的档案帖（可能是其它频道帖被自动转发）→ 静默跳过
        logger.debug(
            "automatic_forward 不是档案帖：src_chat=%s src_msg=%s",
            src_chat_id, src_msg_id,
        )
        return

    teacher_id = post["teacher_id"]
    discussion_chat_id = message.chat.id
    discussion_anchor_id = message.message_id

    # 如已记录相同锚 → 跳过避免无意义 UPDATE
    if (post.get("discussion_chat_id") == discussion_chat_id
            and post.get("discussion_anchor_id") == discussion_anchor_id):
        return

    ok = await update_teacher_channel_post_discussion(
        teacher_id=teacher_id,
        discussion_chat_id=discussion_chat_id,
        discussion_anchor_id=discussion_anchor_id,
    )
    if ok:
        logger.info(
            "anchor captured teacher=%s channel=(%s,%s) → discussion=(%s,%s)",
            teacher_id, src_chat_id, src_msg_id,
            discussion_chat_id, discussion_anchor_id,
        )
    else:
        logger.warning(
            "anchor 写入失败 teacher=%s discussion=(%s,%s)",
            teacher_id, discussion_chat_id, discussion_anchor_id,
        )
