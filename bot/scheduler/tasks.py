import logging
from datetime import datetime, timedelta

from typing import Optional, Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytz import timezone

from bot.config import config
from bot.database import (
    get_checked_in_teachers,
    get_config,
    save_sent_message,
    get_sent_messages,
    delete_sent_messages,
)
from bot.utils.url import normalize_url

logger = logging.getLogger(__name__)

_scheduler = None
_bot: Optional[Bot] = None

tz = timezone(config.timezone)


def parse_publish_chat_ids(raw: Optional[str]) -> list[int]:
    """解析发布目标 ID，兼容单个 ID 和逗号分隔的多个 ID"""
    if not raw:
        return []

    chat_ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        chat_ids.append(int(part))
    return chat_ids


async def get_publish_time() -> str:
    """获取当前发布时间配置"""
    return await get_config("publish_time") or config.publish_time


async def schedule_daily_publish(scheduler, bot: Bot) -> str:
    """配置或重载每日签到汇总定时任务，返回生效的发布时间"""
    global _scheduler, _bot
    _scheduler = scheduler
    _bot = bot

    publish_time = await get_publish_time()
    hour, minute = map(int, publish_time.split(":"))
    scheduler.add_job(
        publish_daily_checkin,
        "cron",
        hour=hour,
        minute=minute,
        args=[bot],
        id="daily_publish",
        replace_existing=True,
    )
    return publish_time


async def reload_daily_publish() -> Optional[str]:
    """重载已注册的每日签到汇总定时任务"""
    if _scheduler is None or _bot is None:
        return None
    return await schedule_daily_publish(_scheduler, _bot)


async def build_daily_checkin_payload(date_str: str) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    """构建每日签到发布内容，返回文本和按钮"""
    teachers = await get_checked_in_teachers(date_str)
    if not teachers:
        return None

    buttons = []
    row = []
    for t in teachers:
        button_url = normalize_url(t["button_url"])
        if not button_url:
            logger.warning("跳过无效老师链接: %s (%s)", t["display_name"], t["button_url"])
            continue
        button_text = t["button_text"] or t["display_name"]
        row.append(InlineKeyboardButton(text=button_text, url=button_url))
        # 每行最多 3 个按钮
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if not buttons:
        return None

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📅 {date_str} 开课老师 {len(teachers)}位"
    return text, keyboard


async def send_daily_checkin(bot: Bot, chat_id: int, date_str: str):
    """发送指定日期签到汇总并保存发送记录"""
    payload = await build_daily_checkin_payload(date_str)
    if payload is None:
        logger.info(f"[{date_str}] 无老师签到，跳过发布")
        return None

    text, keyboard = payload
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )
    await save_sent_message(chat_id, msg.message_id, date_str)
    return msg


async def publish_daily_checkin(bot: Bot):
    """每日定时发布签到汇总"""
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # 先删除前一天的消息
    await _delete_previous_messages(bot)

    # 获取发布目标（频道或群组）
    raw_chat_ids = await get_config("publish_channel_id")
    try:
        chat_ids = parse_publish_chat_ids(raw_chat_ids)
    except ValueError:
        logger.error("发布目标配置无效: %s", raw_chat_ids)
        return

    if not chat_ids:
        logger.warning("未设置发布目标，跳过发布")
        return

    for chat_id in chat_ids:
        try:
            msg = await send_daily_checkin(bot, chat_id, today_str)
            if msg:
                logger.info(f"[{today_str}] 已发布签到汇总到 {chat_id}")
        except Exception as e:
            logger.error(f"发布签到汇总失败 chat={chat_id}: {e}")


async def _delete_previous_messages(bot: Bot):
    """删除前一天发送的消息"""
    now = datetime.now(tz)
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    messages = await get_sent_messages(yesterday_str)
    if not messages:
        return

    for msg in messages:
        try:
            await bot.delete_message(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"],
            )
        except Exception as e:
            # 消息可能已被手动删除，捕获异常跳过
            logger.warning(f"删除消息失败 (chat={msg['chat_id']}, msg={msg['message_id']}): {e}")

    # 清除记录
    await delete_sent_messages(yesterday_str)
    logger.info(f"已清理 {yesterday_str} 的 {len(messages)} 条消息记录")
