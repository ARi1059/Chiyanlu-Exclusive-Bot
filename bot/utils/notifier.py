"""F2: 14:00 收藏者开课通知聚合 + 限速推送（v2 §2.2）

核心:
    - 给当天每个有效收藏者发送一条聚合消息（收藏 ∩ 已签到 老师）
    - 限速 25 msg/sec（留 5 余量，Telegram 全局 30/sec）
    - mention HTML + 老师按钮组（跳转 button_url）
    - 失败处理：屏蔽 / chat 不存在 → mark_user_unreachable
    - 不重试（v2 §2.2.5 暂不做，看实际失败率再加）

消息模板:
    @用户昵称 你的收藏老师 2025-05-11 开课共 N 位:
    [夏亦菲]  [林清雪]
    [苏暮晚]
"""

import asyncio
import logging
import time
from html import escape

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import (
    get_notification_targets,
    list_user_favorites_signed_in,
    mark_user_unreachable,
)
from bot.utils.url import normalize_url

logger = logging.getLogger(__name__)

# 限速参数：25 msg/sec，留 5 余量（Telegram 全局 ~30/sec 触发限流）
RATE_LIMIT_MSG_PER_SEC = 25
RATE_LIMIT_INTERVAL = 1.0 / RATE_LIMIT_MSG_PER_SEC


def _build_notification_payload(
    target: dict,
    date_str: str,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """构造单个用户的通知 text + keyboard

    Args:
        target: {user_id, first_name, username, teachers: [...]} 结构
        date_str: YYYY-MM-DD

    Returns:
        (text, keyboard):
            text: HTML 格式，mention + 提示文案
            keyboard: 老师按钮组（每行最多 3 个）；button_url 全部无效时返回 None
    """
    user_id = target["user_id"]
    teachers = target["teachers"]

    # mention: <a href="tg://user?id=...">first_name</a>（v2 §2.2.3）
    raw_name = target.get("first_name") or target.get("username") or "用户"
    mention = f'<a href="tg://user?id={user_id}">{escape(raw_name)}</a>'

    text = f"{mention} 你的收藏老师 {date_str} 开课共 {len(teachers)} 位："

    # 按钮：每行最多 3 个，跳过 button_url 无效的老师
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in teachers:
        url = normalize_url(t["button_url"])
        if not url:
            continue
        btn_text = t["button_text"] or t["display_name"]
        row.append(InlineKeyboardButton(text=btn_text, url=url))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    return text, keyboard


async def _send_one(bot: Bot, target: dict, date_str: str) -> bool:
    """给单个用户发一条通知

    失败处理（v2 §2.2.5）:
        - TelegramForbiddenError（被屏蔽）→ mark_user_unreachable，跳过
        - TelegramBadRequest 含 "chat not found" → 同上
        - 其他异常 → 记日志跳过（不重试）

    Returns:
        True 成功, False 失败
    """
    user_id = target["user_id"]
    text, keyboard = _build_notification_payload(target, date_str)

    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return True
    except TelegramForbiddenError:
        logger.info("用户 %s 屏蔽了 bot，标记为 unreachable", user_id)
        await mark_user_unreachable(user_id)
        return False
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "chat not found" in msg or "user not found" in msg or "user is deactivated" in msg:
            logger.info("用户 %s chat 不可达，标记 unreachable: %s", user_id, e)
            await mark_user_unreachable(user_id)
        else:
            logger.warning("用户 %s 推送 BadRequest（已跳过）: %s", user_id, e)
        return False
    except Exception as e:
        logger.error("用户 %s 推送异常（已跳过）: %s", user_id, e)
        return False


async def send_favorite_notifications(bot: Bot, date_str: str) -> dict:
    """F2 主入口：14:00 收藏通知聚合 + 限速推送

    流程:
        1. 查所有有效收藏者（last_started_bot=1 + notify_enabled=1）的"收藏 ∩ 签到"
        2. 单消费者循环，每发一条 sleep RATE_LIMIT_INTERVAL
        3. 统计成功/失败/耗时

    Args:
        bot: aiogram Bot 实例
        date_str: 推送日期（YYYY-MM-DD）

    Returns:
        {"total": int, "succeeded": int, "failed": int, "duration_seconds": float}
    """
    start = time.monotonic()
    targets = await get_notification_targets(date_str)

    if not targets:
        logger.info("[%s] 无收藏通知目标，跳过", date_str)
        return {"total": 0, "succeeded": 0, "failed": 0, "duration_seconds": 0.0}

    logger.info("[%s] 开始推送收藏通知，目标 %d 位用户", date_str, len(targets))

    succeeded = 0
    failed = 0
    for i, target in enumerate(targets):
        if i > 0:
            await asyncio.sleep(RATE_LIMIT_INTERVAL)
        ok = await _send_one(bot, target, date_str)
        if ok:
            succeeded += 1
        else:
            failed += 1

    duration = time.monotonic() - start
    logger.info(
        "[%s] 收藏通知推送完成: total=%d succeeded=%d failed=%d duration=%.2fs",
        date_str, len(targets), succeeded, failed, duration,
    )
    return {
        "total": len(targets),
        "succeeded": succeeded,
        "failed": failed,
        "duration_seconds": duration,
    }


async def send_notification_to_user(
    bot: Bot,
    user_id: int,
    first_name: str | None,
    username: str | None,
    date_str: str,
) -> tuple[bool, int]:
    """给单个用户发送其"收藏 ∩ 签到"通知

    用途:
        - 管理员后台的 [🧪 测试收藏通知] 按钮（只发给点击者自己）
        - 未来可能的"手动重发"功能

    与 send_favorite_notifications 的区别：不查 users 表的 last_started_bot / notify_enabled
    （测试场景管理员自己一般已私聊 bot，不需要这层过滤）。

    Args:
        bot: aiogram Bot 实例
        user_id: 接收者 user_id
        first_name: 用于 mention 渲染（可空，缺时回退到 username 或"用户"）
        username: 同上
        date_str: 推送日期

    Returns:
        (success, teacher_count):
            success: 推送是否成功（False 表示无内容、推送失败或被屏蔽）
            teacher_count: 命中老师数（0 表示当天该用户的"收藏 ∩ 签到"为空）
    """
    teachers = await list_user_favorites_signed_in(user_id, date_str)
    if not teachers:
        return False, 0

    target = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "teachers": [
            {
                "user_id": t["user_id"],
                "display_name": t["display_name"],
                "button_url": t["button_url"],
                "button_text": t["button_text"],
            }
            for t in teachers
        ],
    }
    ok = await _send_one(bot, target, date_str)
    return ok, len(teachers)
