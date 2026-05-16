"""抽奖帖渲染 + 发布 + 计数更新（Phase L.2）

spec §4 渲染规则：
- photo + caption（有封面）/ 纯文字消息（无封面）
- 必关频道列表（chat title 从 bot.get_chat 拿）
- inline 键盘：
  - 按键抽奖：[🎲 参与抽奖]（URL deep link）+ [👥 N 人已参与]（noop）
  - 口令抽奖：仅 [👥 N 人已参与]

发布频道：复用 publish_target_chat_ids 第一个（spec §4 注释）
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import (
    count_lottery_entries,
    get_config,
    get_lottery,
    mark_lottery_published,
    seconds_since_lottery_updated,
    touch_lottery,
)

logger = logging.getLogger(__name__)

# Telegram caption 上限
CAPTION_MAX_LEN: int = 1024
# 计数 edit 60s debounce（spec §4.2 说"60s 后台或事件 + 限频"）
COUNT_EDIT_DEBOUNCE_SECONDS: float = 60.0


class LotteryPublishError(Exception):
    """抽奖发布相关错误

    reason ∈ {
        not_found / not_publishable / no_channel / api_error
    }
    """
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


async def _resolve_publish_channel() -> Optional[int]:
    """取 publish_channel_id 第一个 chat_id（与每日 14:00 publish 共用）"""
    raw = await get_config("publish_channel_id")
    if not raw:
        return None
    first = raw.split(",")[0].strip()
    if not first:
        return None
    try:
        return int(first)
    except (TypeError, ValueError):
        return None


async def fetch_chat_info_map(bot: Bot, chat_ids: list[int]) -> dict[int, dict]:
    """批量取 chat 的 title / type / username

    失败的 chat 用 fallback {title: f"chat_id={cid}", username: None}
    """
    result: dict[int, dict] = {}
    for cid in chat_ids:
        try:
            chat = await bot.get_chat(chat_id=cid)
            result[cid] = {
                "title": getattr(chat, "title", None) or getattr(chat, "username", None) or f"chat_id={cid}",
                "type": str(getattr(chat, "type", "unknown")),
                "username": getattr(chat, "username", None),
            }
        except Exception as e:
            logger.warning("fetch_chat_info_map chat_id=%s 失败: %s", cid, e)
            result[cid] = {"title": f"chat_id={cid}", "type": "unknown", "username": None}
    return result


def _truncate(text: str, limit: int) -> str:
    if not text or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def render_lottery_caption(
    lottery: dict,
    bot_username: str,
    chat_info_map: dict[int, dict],
    *,
    n_entries: int = 0,
) -> str:
    """渲染抽奖帖 caption / 文字（spec §4.1）

    超 1024 字符时按 description 优先截断；如仍超长，再按 prize_description 截断。
    n_entries 不渲染到文字（仅按钮显示）。
    """
    name = lottery.get("name", "?")
    description = (lottery.get("description") or "").strip()
    prize = (lottery.get("prize_description") or "").strip()
    prize_count = lottery.get("prize_count", "?")
    draw_at = lottery.get("draw_at", "?")
    entry_method = lottery.get("entry_method") or "?"
    entry_code = lottery.get("entry_code")
    required_chat_ids = lottery.get("required_chat_ids") or []
    cost_points = int(lottery.get("entry_cost_points") or 0)

    def _build(desc_limit: Optional[int] = None, prize_limit: Optional[int] = None) -> str:
        d = _truncate(description, desc_limit) if desc_limit else description
        p = _truncate(prize, prize_limit) if prize_limit else prize
        lines: list[str] = [f"🎉 {name}", ""]
        if d:
            lines.append("📋 活动规则")
            lines.append(d)
            lines.append("")
        lines.append("🎁 奖品")
        lines.append(p or "(未填写)")
        lines.append("")
        lines.append(f"🏆 中奖人数：{prize_count}")
        lines.append(f"⏰ 开奖时间：{draw_at}")
        if cost_points > 0:
            lines.append(f"💰 参与消耗：{cost_points} 积分")
        lines.append("")
        lines.append("📌 参与方式：")
        if entry_method == "button":
            lines.append(f"点击下方 [🎲 参与抽奖] 按钮 → 在私聊完成确认")
        else:
            lines.append(f"在私聊给我发送口令：{entry_code or '???'}")
        if required_chat_ids:
            lines.append("")
            lines.append("📋 参与门槛（请先加入以下频道/群组）：")
            for cid in required_chat_ids:
                info = chat_info_map.get(cid, {})
                title = info.get("title") or f"chat_id={cid}"
                username = info.get("username")
                if username:
                    lines.append(f"  · {title} (@{username})")
                else:
                    lines.append(f"  · {title} (chat_id={cid})")
        lines.append("")
        lines.append("⚠️ 本次抽奖每人仅可参与 1 次")
        lines.append(f"✳ Powered by @{bot_username}")
        return "\n".join(lines)

    # 渐进式截断（spec §4 注：description 优先截断）
    text = _build()
    if len(text) <= CAPTION_MAX_LEN:
        return text
    text = _build(desc_limit=200)
    if len(text) <= CAPTION_MAX_LEN:
        return text
    text = _build(desc_limit=80)
    if len(text) <= CAPTION_MAX_LEN:
        return text
    text = _build(desc_limit=80, prize_limit=60)
    if len(text) > CAPTION_MAX_LEN:
        text = text[: CAPTION_MAX_LEN - 1].rstrip() + "…"
    return text


def build_lottery_keyboard(
    lottery: dict,
    n_entries: int,
    bot_username: str,
) -> InlineKeyboardMarkup:
    """抽奖帖底部 inline 键盘（spec §4.2 / §4.3）"""
    lid = lottery.get("id")
    entry_method = lottery.get("entry_method") or "?"
    rows: list[list[InlineKeyboardButton]] = []
    if entry_method == "button":
        rows.append([InlineKeyboardButton(
            text="🎲 参与抽奖",
            url=f"https://t.me/{bot_username}?start=lottery_{lid}",
        )])
    rows.append([InlineKeyboardButton(
        text=f"👥 {n_entries} 人已参与",
        callback_data="noop:lottery_count",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def publish_lottery_to_channel(bot: Bot, lottery_id: int) -> dict:
    """抽奖发布到频道（被立即发布 / 定时调度 / 重启扫描调用）

    Returns: {chat_id, msg_id}
    Raises LotteryPublishError on hard failure.
    """
    lottery = await get_lottery(lottery_id)
    if lottery is None:
        raise LotteryPublishError("not_found", f"抽奖 {lottery_id} 不存在")
    if lottery.get("status") not in {"draft", "scheduled"}:
        raise LotteryPublishError(
            "not_publishable",
            f"抽奖 {lottery_id} 状态为 {lottery.get('status')}，不可发布",
        )

    chat_id = await _resolve_publish_channel()
    if chat_id is None:
        raise LotteryPublishError(
            "no_channel",
            "未配置 publish_channel_id；请先在 [📢 频道设置] → [📌 设置发布目标] 配置",
        )

    me = await bot.get_me()
    chat_info_map = await fetch_chat_info_map(
        bot, lottery.get("required_chat_ids") or [],
    )
    caption = render_lottery_caption(lottery, me.username, chat_info_map)
    kb = build_lottery_keyboard(lottery, 0, me.username)

    sent = None
    try:
        if lottery.get("cover_file_id"):
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=lottery["cover_file_id"],
                caption=caption,
                reply_markup=kb,
            )
        else:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=kb,
            )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        raise LotteryPublishError(
            "api_error",
            f"频道发送失败：{type(e).__name__}: {e}",
        ) from e
    except Exception as e:
        raise LotteryPublishError(
            "api_error",
            f"频道发送失败：{type(e).__name__}: {e}",
        ) from e

    if sent is None:
        raise LotteryPublishError("api_error", "发送返回 None")

    await mark_lottery_published(
        lottery_id, channel_chat_id=chat_id, channel_msg_id=sent.message_id,
    )
    return {"chat_id": chat_id, "msg_id": sent.message_id}


async def update_lottery_entry_count(
    bot: Bot,
    lottery_id: int,
    *,
    force: bool = False,
) -> bool:
    """编辑频道帖按钮：刷新 [👥 N 人已参与] 计数

    60s debounce（用 lotteries.updated_at）；force=True 绕过。
    返回 True 表示实际 edit；False 表示被 debounce 或未发布跳过。

    所有 Telegram BadRequest / Forbidden 容错（log warning 不抛错）。
    """
    lottery = await get_lottery(lottery_id)
    if lottery is None:
        return False
    chat_id = lottery.get("channel_chat_id")
    msg_id = lottery.get("channel_msg_id")
    if not chat_id or not msg_id:
        return False  # 还没发布到频道

    if not force:
        sec = await seconds_since_lottery_updated(lottery_id)
        if sec is not None and sec < COUNT_EDIT_DEBOUNCE_SECONDS:
            logger.debug(
                "update_lottery_entry_count debounce 跳过 lid=%s (上次 %.1fs 前)",
                lottery_id, sec,
            )
            return False

    me = await bot.get_me()
    n = await count_lottery_entries(lottery_id)
    kb = build_lottery_keyboard(lottery, n, me.username)
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=msg_id, reply_markup=kb,
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        # 同样内容 → 跳过；其它继续 log
        if "not modified" not in msg:
            logger.warning(
                "update_lottery_entry_count edit 失败 lid=%s: %s", lottery_id, e,
            )
    except Exception as e:
        logger.warning(
            "update_lottery_entry_count edit 失败 lid=%s: %s", lottery_id, e,
        )

    await touch_lottery(lottery_id)
    return True


async def refresh_lottery_channel_caption(
    bot: Bot,
    lottery_id: int,
) -> bool:
    """active 编辑后重渲染频道帖 caption / text（Phase L.4.2）

    Admin 改 name / description / prize_description / prize_count /
    required_chat_ids / draw_at 后调用，按当前 DB 状态重新渲染并 edit。
    无 debounce（admin 主动操作即时反馈）。

    返回 True 表示已 edit 或被 'not modified' 跳过；False 表示未发布到频道。
    所有 BadRequest / Forbidden 容错（log warning 不抛错）。
    """
    lottery = await get_lottery(lottery_id)
    if lottery is None:
        return False
    chat_id = lottery.get("channel_chat_id")
    msg_id = lottery.get("channel_msg_id")
    if not chat_id or not msg_id:
        return False  # 还没发布到频道

    try:
        me = await bot.get_me()
    except Exception as e:
        logger.warning("refresh_lottery_channel_caption get_me 失败 lid=%s: %s", lottery_id, e)
        return False

    chat_info_map = await fetch_chat_info_map(
        bot, lottery.get("required_chat_ids") or [],
    )
    caption = render_lottery_caption(lottery, me.username, chat_info_map)
    n = await count_lottery_entries(lottery_id)
    kb = build_lottery_keyboard(lottery, n, me.username)
    has_cover = bool(lottery.get("cover_file_id"))
    try:
        if has_cover:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=caption, reply_markup=kb,
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=caption, reply_markup=kb,
            )
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning(
                "refresh_lottery_channel_caption edit 失败 lid=%s: %s", lottery_id, e,
            )
    except Exception as e:
        logger.warning(
            "refresh_lottery_channel_caption edit 失败 lid=%s: %s", lottery_id, e,
        )
    await touch_lottery(lottery_id)
    return True
