"""老师档案帖发布工具（Phase 9.2）

封装"发媒体组 / 编辑 caption / 重发 / 删除"四种操作。
admin handler 调用入口；不直接和 DB 表打交道——通过 bot.database 暴露的 CRUD。

设计：
- 所有失败映射到 PublishError(reason=...)，admin handler 据 reason 做友好提示
- 60s debounce 通过 seconds_since_last_caption_edit 判断，避免 Telegram 限流
- 删旧媒体组时部分失败不阻塞（最差结果是频道残留一两条旧帖，admin 可手动清理）
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InputMediaPhoto

from bot.database import (
    delete_teacher_channel_post,
    get_archive_channel_id,
    get_teacher_channel_post,
    get_teacher_full_profile,
    is_teacher_profile_complete,
    seconds_since_last_caption_edit,
    touch_teacher_channel_post,
    upsert_teacher_channel_post,
)
from bot.utils.teacher_profile_render import render_teacher_channel_caption

logger = logging.getLogger(__name__)

# 60s 内同一帖最多 edit 1 次（spec §3.1 风险缓解）
CAPTION_EDIT_DEBOUNCE_SECONDS: float = 60.0


class PublishError(Exception):
    """档案帖发布相关错误，admin handler 据 reason 渲染中文提示

    reason ∈ {
        "incomplete":          必填字段不齐
        "no_channel":          未配置档案频道也无回退
        "no_photos":           相册为空（理论上和 incomplete 重叠，单独分支便于提示）
        "already_published":   首次发布时检测到 teacher_channel_posts 已存在
        "not_published":       update/repost/delete 时 row 不存在
        "api_error":           Telegram API 调用失败
    }
    """
    def __init__(self, reason: str, message: str, *, missing: Optional[list[str]] = None):
        super().__init__(message)
        self.reason = reason
        self.missing = missing or []


def _build_media_group(file_ids: list[str], caption: str) -> list[InputMediaPhoto]:
    """构造 InputMediaPhoto 列表，caption 只挂第一张（Telegram 媒体组规则）"""
    if not file_ids:
        return []
    items: list[InputMediaPhoto] = []
    for idx, fid in enumerate(file_ids[:10]):
        if idx == 0:
            items.append(InputMediaPhoto(media=fid, caption=caption))
        else:
            items.append(InputMediaPhoto(media=fid))
    return items


async def _resolve_channel() -> int:
    """获取档案频道 chat_id；未配置抛 PublishError(no_channel)"""
    chat_id = await get_archive_channel_id()
    if chat_id is None:
        raise PublishError(
            "no_channel",
            "未配置档案频道；请在 [📢 频道设置] → [📦 设置档案频道] 中配置 chat_id。",
        )
    return chat_id


async def _load_publishable_profile(teacher_id: int) -> dict:
    """读取 + 校验老师档案，齐备时返回 full profile，否则抛 incomplete"""
    profile = await get_teacher_full_profile(teacher_id)
    if profile is None:
        raise PublishError("incomplete", f"老师不存在: user_id={teacher_id}")
    ok, missing = await is_teacher_profile_complete(teacher_id)
    if not ok:
        raise PublishError(
            "incomplete",
            "档案缺以下必填字段，请先补全：" + ", ".join(missing),
            missing=missing,
        )
    if not profile.get("photo_album"):
        raise PublishError("no_photos", "相册至少需要 1 张照片。")
    return profile


async def publish_teacher_post(bot: Bot, teacher_id: int) -> dict:
    """首次发布老师档案帖到频道

    Returns:
        {"chat_id": int, "channel_msg_id": int, "media_count": int}

    Raises:
        PublishError: 见 reason 列表
    """
    existing = await get_teacher_channel_post(teacher_id)
    if existing:
        raise PublishError(
            "already_published",
            "该老师已有档案帖；如需重发请用 [🔄 重发档案帖]。",
        )
    profile = await _load_publishable_profile(teacher_id)
    chat_id = await _resolve_channel()

    # 首次发布时 stats 还没记录（teacher_channel_posts 不存在）→ 渲染用占位符
    caption = render_teacher_channel_caption(profile, stats=None)
    media = _build_media_group(profile["photo_album"], caption)
    if not media:
        raise PublishError("no_photos", "相册解析为空。")

    try:
        sent = await bot.send_media_group(chat_id=chat_id, media=media)
    except Exception as e:
        logger.warning("send_media_group 失败 teacher=%s chat=%s: %s", teacher_id, chat_id, e)
        raise PublishError(
            "api_error",
            f"Telegram 发送失败：{type(e).__name__}: {e}",
        ) from e

    msg_ids = [m.message_id for m in sent]
    if not msg_ids:
        raise PublishError("api_error", "Telegram 返回空消息列表。")

    await upsert_teacher_channel_post(
        teacher_id=teacher_id,
        channel_chat_id=chat_id,
        channel_msg_id=msg_ids[0],
        media_group_msg_ids=msg_ids,
    )
    return {
        "chat_id": chat_id,
        "channel_msg_id": msg_ids[0],
        "media_count": len(msg_ids),
    }


async def update_teacher_post_caption(
    bot: Bot,
    teacher_id: int,
    *,
    force: bool = False,
) -> bool:
    """字段编辑后自动 edit_message_caption；命中 debounce 时跳过

    Args:
        force: True 时绕过 60s debounce（admin 显式触发同步）

    Returns:
        True：实际 edit 了 caption
        False：被 debounce 跳过 或 未发布该老师（silent skip）

    Raises:
        PublishError: 仅在 force=True 且 not_published / api_error 时
    """
    post = await get_teacher_channel_post(teacher_id)
    if post is None:
        if force:
            raise PublishError(
                "not_published",
                "该老师尚未发布档案帖，无法更新 caption。",
            )
        return False

    if not force:
        last = await seconds_since_last_caption_edit(teacher_id)
        if last is not None and last < CAPTION_EDIT_DEBOUNCE_SECONDS:
            logger.info(
                "update_teacher_post_caption: debounce 跳过 teacher=%s (上次 %.1fs 前)",
                teacher_id, last,
            )
            return False

    profile = await get_teacher_full_profile(teacher_id)
    if profile is None:
        raise PublishError("incomplete", f"老师不存在: user_id={teacher_id}")

    try:
        caption = render_teacher_channel_caption(profile, stats=post)
    except ValueError as e:
        # 必填字段后来被清空了（理论上不该发生，因为 is_complete 校验过才发的）
        logger.warning("update_caption render 失败 teacher=%s: %s", teacher_id, e)
        if force:
            raise PublishError("incomplete", f"caption 渲染失败：{e}") from e
        return False

    try:
        await bot.edit_message_caption(
            chat_id=post["channel_chat_id"],
            message_id=post["channel_msg_id"],
            caption=caption,
        )
    except Exception as e:
        # 频繁 edit、消息已删除、API 限流等
        msg = str(e)
        if "message is not modified" in msg.lower():
            # caption 内容未变化，Telegram 拒绝；视为成功 + touch
            await touch_teacher_channel_post(teacher_id)
            return True
        logger.warning("edit_message_caption 失败 teacher=%s: %s", teacher_id, e)
        if force:
            raise PublishError(
                "api_error",
                f"Telegram edit_message_caption 失败：{type(e).__name__}: {e}",
            ) from e
        return False

    await touch_teacher_channel_post(teacher_id)
    return True


async def repost_teacher_post(bot: Bot, teacher_id: int) -> dict:
    """删除旧媒体组 + 重新 send_media_group（相册被改后用）

    旧媒体组的 delete_message 失败不阻塞，仅 warning。
    """
    old = await get_teacher_channel_post(teacher_id)
    if old is None:
        raise PublishError(
            "not_published",
            "该老师尚未发布档案帖，请用 [📤 发布档案帖]。",
        )

    # 先删旧帖（best-effort）
    chat_id = old["channel_chat_id"]
    for mid in old.get("media_group_msg_ids") or [old["channel_msg_id"]]:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception as e:
            logger.warning(
                "repost 删旧消息失败 teacher=%s chat=%s msg=%s: %s",
                teacher_id, chat_id, mid, e,
            )

    # 删 DB row，让 publish_teacher_post 走"首次"分支
    await delete_teacher_channel_post(teacher_id)
    return await publish_teacher_post(bot, teacher_id)


async def delete_teacher_post(bot: Bot, teacher_id: int) -> bool:
    """删除频道帖 + DB row（不删老师本身）"""
    post = await get_teacher_channel_post(teacher_id)
    if post is None:
        raise PublishError(
            "not_published",
            "该老师没有档案帖记录，无需删除。",
        )
    chat_id = post["channel_chat_id"]
    for mid in post.get("media_group_msg_ids") or [post["channel_msg_id"]]:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception as e:
            logger.warning(
                "delete_teacher_post 删消息失败 teacher=%s chat=%s msg=%s: %s",
                teacher_id, chat_id, mid, e,
            )
    return await delete_teacher_channel_post(teacher_id)
